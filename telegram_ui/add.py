from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Dict

import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import CallbackQueryHandler, CommandHandler, ConversationHandler, ContextTypes, MessageHandler, filters

from services import discogs_service
from services.discogs_sync_service import sync_discogs_item
from services.add_session_service import create_add_session, validate_add_callback
from services.store_service import get_default_store, get_store_settings
from services.inventory_service import (
    get_or_create_supplier,
    get_suppliers,
    insert_inventory,
    get_inventory_by_id,
    update_inventory_fields,
)
from services.product_map_service import find_mapping_by_internal_id, upsert_product_map
from services.runtime import run_blocking
from services.sync_engine import SyncEngine
from services.tri_sync_service import poll_discogs_listings, poll_woo_products
from services.woo_service import (
    WooNotConfigured,
    category_names_from_inventory,
    upload_media,
    fetch_next_sku,
)
from telegram_ui import messages

logger = logging.getLogger(__name__)

(
    CHOOSE_TYPE,
    SEARCH_INPUT,
    SHOW_RESULTS,
    ASK_CONDITION,
    ASK_PRICE,
    ASK_QUANTITY,
    ASK_SUPPLIER,
    OTHER_CATEGORY,
    OTHER_NAME,
    OTHER_PRICE,
    OTHER_QUANTITY,
    OTHER_DESCRIPTION,
    OTHER_PHOTOS,
    CONFIRM,
) = range(14)
CONDITION_OPTIONS = ["m", "nm", "vg+", "vg", "g+", "g", "f", "p"]


def _format_release_button(item: Dict[str, Any]) -> str:
    title = item.get("title") or "Unknown"
    formats = item.get("format") or []
    format_text = ", ".join(formats) if isinstance(formats, list) else str(formats)
    text = f"{title} [{format_text}]"
    return text[:60]


def _condition_label(code: str) -> str:
    return {
        "m": "Mint (M)",
        "nm": "Near Mint (NM or M-)",
        "vg+": "Very Good Plus (VG+)",
        "vg": "Very Good (VG)",
        "g+": "Good Plus (G+)",
        "g": "Good (G)",
        "f": "Fair (F)",
        "p": "Poor (P)",
    }.get(code, code)


def _fetch_usd_to_gel() -> float:
    today = datetime.now().strftime("%d.%m.%Y")
    url = f"https://nbg.gov.ge/gw/api/ct/monetarypolicy/currencies/en/json/?date={today}"
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    data = response.json()
    for item in data[0]["currencies"]:
        if item["code"] == "USD":
            return float(item["rate"])
    return 1.0


def _start_add_session(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> str:
    session = create_add_session()
    token = str(session["session_id"])
    context.user_data["add_session"] = session
    logger.info("Started /add session %s", session["session_id"])
    return token


def _set_expected_step(context: ContextTypes.DEFAULT_TYPE, expected_step: str) -> None:
    session = context.user_data.get("add_session")
    if isinstance(session, dict):
        session["expected_step"] = expected_step


def _current_add_session_id(context: ContextTypes.DEFAULT_TYPE) -> str:
    session = context.user_data.get("add_session")
    if isinstance(session, dict):
        return str(session.get("session_id") or "")
    return ""


async def _ack_callback(update: Update) -> None:
    if update.callback_query:
        try:
            await update.callback_query.answer()
        except BadRequest:
            pass


def _parse_add_callback(data: str) -> tuple[str, str, list[str]] | None:
    parts = data.split(":")
    if len(parts) < 3 or parts[0] != "add":
        return None
    action = parts[1]
    session_id = parts[2]
    rest = parts[3:]
    return action, session_id, rest


async def _validate_add_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.callback_query:
        return True
    parsed = _parse_add_callback(update.callback_query.data)
    session_id = parsed[1] if parsed else None
    action = parsed[0] if parsed else None
    ok, reason = validate_add_callback(
        session=context.user_data.get("add_session"),
        callback_session_id=session_id,
        callback_action=action,
    )
    if not ok:
        correlation_id = f"cbq:{update.callback_query.id}" if update.callback_query.id else f"upd:{update.update_id}"
        logger.info("Rejected add callback reason=%s menu=add correlation_id=%s", reason, correlation_id)
        await update.effective_message.reply_text(messages.ADD_SUPPLIER_STALE)
        return False
    return True


async def start_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    store = await run_blocking(get_default_store)
    context.user_data["store"] = store
    session_id = _start_add_session(context, update.effective_user.id)
    try:
        next_id = await run_blocking(fetch_next_sku)
        next_id_hint = messages.ADD_NEXT_ID_HINT.format(next_id=next_id)
    except WooNotConfigured:
        next_id_hint = messages.ADD_NEXT_ID_UNAVAILABLE
    except Exception:
        logger.exception("Failed to fetch next Woo SKU")
        next_id_hint = messages.ADD_NEXT_ID_UNAVAILABLE
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(messages.ADD_TYPE_RECORD, callback_data=f"add:type:{session_id}:record"),
                InlineKeyboardButton(messages.ADD_TYPE_OTHER, callback_data=f"add:type:{session_id}:other"),
            ]
        ]
    )
    await update.message.reply_text(
        f"{next_id_hint}\n\n{messages.ADD_TYPE_PROMPT}",
        reply_markup=keyboard,
    )
    _set_expected_step(context, "choose_type")
    return CHOOSE_TYPE


async def handle_add_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return CHOOSE_TYPE
    await _ack_callback(update)
    if not await _validate_add_session(update, context):
        return ConversationHandler.END
    parsed = _parse_add_callback(update.callback_query.data)
    if not parsed:
        return ConversationHandler.END
    _, _, rest = parsed
    choice = rest[0] if rest else ""
    if choice == "record":
        store = context.user_data.get("store")
        if not store or not store.get("discogs_token"):
            await update.callback_query.edit_message_text(messages.ADD_DISCOGS_MISSING)
            return ConversationHandler.END
        context.user_data["product_type"] = "record"
        await update.callback_query.edit_message_text(messages.ADD_PROMPT_QUERY)
        return SEARCH_INPUT
    if choice == "other":
        context.user_data["product_type"] = "other"
        await update.callback_query.edit_message_text(messages.ADD_OTHER_CATEGORY_PROMPT)
        return OTHER_CATEGORY
    return CHOOSE_TYPE


async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    context.user_data["query"] = query
    context.user_data["page"] = 1
    return await show_results(update, context)


async def show_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    page = context.user_data["page"]
    query = context.user_data["query"]
    session_id = _current_add_session_id(context)
    try:
        store = context.user_data.get("store")
        results = await run_blocking(discogs_service.search_releases, store, query, page, 50)
    except discogs_service.DiscogsNotConfigured:
        await update.effective_message.reply_text(messages.ADD_DISCOGS_MISSING)
        return ConversationHandler.END
    context.user_data["results"] = results

    buttons = [
        [InlineKeyboardButton(_format_release_button(release), callback_data=f"add:select:{session_id}:{i}")]
        for i, release in enumerate(results)
    ]

    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"add:page:{session_id}:prev"))
    if len(results) == 50:
        nav_buttons.append(InlineKeyboardButton("➡️ Next", callback_data=f"add:page:{session_id}:next"))
    if nav_buttons:
        buttons.append(nav_buttons)

    if update.callback_query:
        await update.callback_query.edit_message_text(
            messages.ADD_SELECT_RELEASE, reply_markup=InlineKeyboardMarkup(buttons)
        )
    else:
        await update.message.reply_text(
            messages.ADD_SELECT_RELEASE, reply_markup=InlineKeyboardMarkup(buttons)
        )
    _set_expected_step(context, "show_results")
    return SHOW_RESULTS


async def handle_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _ack_callback(update)
    if not await _validate_add_session(update, context):
        return ConversationHandler.END
    parsed = _parse_add_callback(update.callback_query.data)
    if not parsed:
        return ConversationHandler.END
    _, _, rest = parsed
    direction = rest[0] if rest else ""
    if direction == "next":
        context.user_data["page"] += 1
    elif direction == "prev":
        context.user_data["page"] = max(1, context.user_data["page"] - 1)
    return await show_results(update, context)


async def handle_release_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _ack_callback(update)
    if not await _validate_add_session(update, context):
        return ConversationHandler.END
    parsed = _parse_add_callback(update.callback_query.data)
    if not parsed:
        return ConversationHandler.END
    _, _, rest = parsed
    idx = int(rest[0])
    selected = context.user_data["results"][idx]
    release_id = selected.get("id")
    store = context.user_data.get("store")
    release = await run_blocking(discogs_service.fetch_release, store, int(release_id))
    context.user_data["release"] = release
    session_id = _current_add_session_id(context)

    await update.callback_query.edit_message_text(
        messages.ADD_SELECT_CONDITION.format(title=release.get("title", "")),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(c, callback_data=f"add:cond:{session_id}:{c}")
                    for c in CONDITION_OPTIONS[i:i + 4]
                ]
                for i in range(0, len(CONDITION_OPTIONS), 4)
            ]
        ),
    )
    _set_expected_step(context, "ask_condition")
    return ASK_CONDITION


async def handle_condition_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _ack_callback(update)
    if not await _validate_add_session(update, context):
        return ConversationHandler.END
    parsed = _parse_add_callback(update.callback_query.data)
    if not parsed:
        return ConversationHandler.END
    _, _, rest = parsed
    cond = rest[0]
    context.user_data["condition"] = cond
    release = context.user_data["release"]

    store = context.user_data.get("store")
    suggestions = await run_blocking(discogs_service.fetch_price_suggestions, store, int(release.get("id")))
    full_condition = _condition_label(cond)

    price_usd = suggestions.get(full_condition, {}).get("value") if suggestions else None
    if price_usd:
        rate = await run_blocking(_fetch_usd_to_gel)
        price_gel = round(float(price_usd) * rate, 2)
        context.user_data["suggested_price_usd"] = round(float(price_usd), 2)
        context.user_data["suggested_price_gel"] = price_gel
        msg = messages.ADD_SUGGESTED_PRICE.format(
            full_condition=full_condition, price_usd=float(price_usd), price_gel=price_gel
        )
    else:
        context.user_data["suggested_price_usd"] = None
        context.user_data["suggested_price_gel"] = None
        msg = messages.ADD_NO_SUGGESTION

    await update.callback_query.edit_message_text(msg + messages.ADD_PRICE_PROMPT)
    return ASK_PRICE


async def handle_price_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text.strip()

    if msg.lower() == "ok" and context.user_data.get("suggested_price_gel") is not None:
        final_price = context.user_data["suggested_price_gel"]
    else:
        try:
            final_price = float(msg)
        except ValueError:
            await update.message.reply_text(messages.ADD_PRICE_INVALID)
            return ASK_PRICE

    context.user_data["final_price"] = round(float(final_price), 2)
    await update.message.reply_text(messages.ADD_QUANTITY_PROMPT)
    return ASK_QUANTITY


async def handle_quantity_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        qty = int(update.message.text.strip())
        if qty < 1:
            raise ValueError
    except ValueError:
        await update.message.reply_text(messages.ADD_QUANTITY_INVALID)
        return ASK_QUANTITY

    context.user_data["quantity"] = qty
    await _prompt_supplier(update, context)
    return ASK_SUPPLIER


async def handle_supplier_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await _ack_callback(update)
        if not await _validate_add_session(update, context):
            return ConversationHandler.END
    try:
        if update.callback_query:
            query = update.callback_query
            parsed = _parse_add_callback(query.data)
            if not parsed:
                return ConversationHandler.END
            _, _, rest = parsed
            supplier_token = rest[0] if rest else ""
            if supplier_token == "other":
                await update.effective_message.reply_text(messages.ADD_SUPPLIER_PROMPT)
                return ASK_SUPPLIER
            supplier_id = int(supplier_token)
            supplier_name = (context.user_data.get("suppliers_by_id") or {}).get(supplier_id)
        else:
            supplier_name = update.message.text.strip()
            supplier_id = await run_blocking(get_or_create_supplier, supplier_name)

        context.user_data["supplier_id"] = supplier_id
        context.user_data["supplier_name"] = supplier_name
        product_type = context.user_data.get("product_type", "record")
        if product_type == "other":
            await update.effective_message.reply_text(messages.ADD_OTHER_DESCRIPTION_PROMPT)
            return OTHER_DESCRIPTION

        if not context.user_data or "release" not in context.user_data:
            await update.effective_message.reply_text(messages.ADD_SUPPLIER_STALE)
            return ConversationHandler.END

        release = context.user_data["release"]
        cond = context.user_data["condition"]
        price = context.user_data["final_price"]
        qty = context.user_data["quantity"]

        artist_name = discogs_service.extract_artists(release)
        release_title = str(release.get("title") or "Unknown")
        artist_album = f"{artist_name} - {release_title}" if artist_name != "Unknown" else release_title

        item = {
            "artist_album": artist_album,
            "genre": discogs_service.safe_join_list(release.get("genres"), default=""),
            "style": discogs_service.safe_join_list(release.get("styles"), default=""),
            "label": discogs_service.extract_labels(release),
            "format": discogs_service.extract_formats(release),
            "condition": str(cond),
            "price_gel": float(price),
            "quantity": int(qty),
            "supplier_id": supplier_id,
            "product_type": "record",
            "year": release.get("year"),
            "description": release.get("notes"),
            "tracklist": release.get("tracklist") or [],
            "cover_url": discogs_service.extract_cover_url(release),
            "discogs_release_id": release.get("id"),
            "discogs_master_id": release.get("master_id"),
            "discogs_uri": release.get("uri"),
            "supplier_name": supplier_name,
        }

        inventory_id = await run_blocking(insert_inventory, item)
        logger.info("Inserted inventory row id=%s (type=%s)", inventory_id, product_type)
        await update.effective_message.reply_text(
            messages.ADD_SAVED_LOCAL.format(inventory_id=inventory_id)
        )
        store = context.user_data.get("store")
        if store:
            await run_blocking(
                upsert_product_map,
                store_id=int(store["id"]),
                internal_product_id=int(inventory_id),
                discogs_release_id=item.get("discogs_release_id"),
                sku=str(inventory_id),
            )

        inventory_row = await run_blocking(get_inventory_by_id, inventory_id)
        if not inventory_row:
            raise RuntimeError("Inventory insert failed")

        inventory_row.update({
            "product_type": product_type,
            "tracklist": item.get("tracklist"),
            "cover_url": item.get("cover_url"),
            "discogs_release_id": item.get("discogs_release_id"),
            "discogs_master_id": item.get("discogs_master_id"),
            "discogs_uri": item.get("discogs_uri"),
            "supplier_name": supplier_name,
        })

        await _run_post_add_sync(
            update,
            store=context.user_data.get("store"),
            inventory_id=int(inventory_id),
            inventory_row=inventory_row,
        )
    except Exception as exc:
        logger.exception("Error saving inventory row")
        await update.effective_message.reply_text(messages.ADD_SAVE_ERROR.format(error=str(exc)))

    return ConversationHandler.END


async def _run_post_add_sync(
    update: Update,
    *,
    store: dict | None,
    inventory_id: int,
    inventory_row: dict[str, Any],
) -> None:
    if not store:
        return

    store_id = int(store["id"])
    mapping = None
    try:
        await run_blocking(SyncEngine().run_instant_sync_for_item, store_id, int(inventory_id))
        mapping = await run_blocking(find_mapping_by_internal_id, store_id, int(inventory_id))
    except WooNotConfigured:
        await update.effective_message.reply_text(messages.ADD_WOO_NOT_CONFIGURED)
    except Exception as exc:
        logger.exception("Woo sync failed")
        await update.effective_message.reply_text(
            messages.ADD_WOO_FAILED.format(error=f"{type(exc).__name__}: {exc}")
        )
    else:
        woo_id = mapping.get("woo_product_id") if mapping else None
        category_names = ", ".join(category_names_from_inventory(inventory_row))
        if woo_id:
            await update.effective_message.reply_text(
                messages.ADD_WOO_OK_DETAILS.format(
                    inventory_id=inventory_id,
                    woo_id=woo_id,
                    categories=category_names or "N/A",
                )
            )

    try:
        results = await run_blocking(sync_discogs_item, store_id, int(inventory_id))
        if results.get("errors"):
            logger.warning("Discogs immediate sync completed with errors for inventory %s", inventory_id)
    except Exception:
        logger.exception("Discogs immediate sync failed for inventory %s", inventory_id)

    settings = await run_blocking(get_store_settings, store_id)
    if settings.get("three_way_sync_enabled"):
        try:
            await run_blocking(poll_woo_products, store_id)
            if store.get("discogs_token"):
                await run_blocking(poll_discogs_listings, store_id)
        except Exception:
            logger.exception("Three-way sync poll failed after add for inventory %s", inventory_id)


async def handle_other_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["manual_category"] = update.message.text.strip()
    await update.message.reply_text(messages.ADD_OTHER_NAME_PROMPT)
    return OTHER_NAME


async def handle_other_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["manual_name"] = update.message.text.strip()
    await update.message.reply_text(messages.ADD_OTHER_PRICE_PROMPT)
    return OTHER_PRICE


async def handle_other_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text(messages.ADD_OTHER_PRICE_INVALID)
        return OTHER_PRICE
    context.user_data["manual_price"] = round(price, 2)
    await update.message.reply_text(messages.ADD_QUANTITY_PROMPT)
    return OTHER_QUANTITY


async def handle_other_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        qty = int(update.message.text.strip())
        if qty < 1:
            raise ValueError
    except ValueError:
        await update.message.reply_text(messages.ADD_QUANTITY_INVALID)
        return OTHER_QUANTITY
    context.user_data["manual_quantity"] = qty
    await _prompt_supplier(update, context)
    return ASK_SUPPLIER


async def handle_other_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["manual_description"] = update.message.text.strip()
    context.user_data["other_photos"] = []
    session_id = _current_add_session_id(context)
    buttons = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(messages.ADD_OTHER_PHOTOS_DONE, callback_data=f"add:photos:{session_id}:done"),
                InlineKeyboardButton(messages.ADD_OTHER_PHOTOS_CANCEL, callback_data=f"add:photos:{session_id}:cancel"),
            ]
        ]
    )
    await update.message.reply_text(messages.ADD_OTHER_PHOTOS_PROMPT, reply_markup=buttons)
    _set_expected_step(context, "other_photos")
    return OTHER_PHOTOS


async def handle_other_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photos = context.user_data.setdefault("other_photos", [])
    if not update.message.photo:
        return OTHER_PHOTOS
    file_id = update.message.photo[-1].file_id
    photos.append(file_id)
    session_id = _current_add_session_id(context)
    buttons = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(messages.ADD_OTHER_PHOTOS_DONE, callback_data=f"add:photos:{session_id}:done"),
                InlineKeyboardButton(messages.ADD_OTHER_PHOTOS_CANCEL, callback_data=f"add:photos:{session_id}:cancel"),
            ]
        ]
    )
    await update.message.reply_text(messages.ADD_OTHER_PHOTOS_REMINDER, reply_markup=buttons)
    _set_expected_step(context, "other_photos")
    return OTHER_PHOTOS


async def handle_other_photo_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _ack_callback(update)
    if not await _validate_add_session(update, context):
        return ConversationHandler.END
    parsed = _parse_add_callback(update.callback_query.data)
    if not parsed:
        return ConversationHandler.END
    _, _, rest = parsed
    action = rest[0] if rest else ""
    if action == "cancel":
        return await cancel_add(update, context)
    if action != "done":
        return OTHER_PHOTOS
    if not context.user_data.get("other_photos"):
        await update.effective_message.reply_text(messages.ADD_OTHER_PHOTOS_REQUIRED)
        return OTHER_PHOTOS
    session_id = _current_add_session_id(context)
    confirm_buttons = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(messages.ADD_OTHER_CONFIRM_TITLE, callback_data=f"add:confirm:{session_id}:yes"),
                InlineKeyboardButton(messages.ADD_OTHER_CANCEL_TITLE, callback_data=f"add:confirm:{session_id}:cancel"),
            ]
        ]
    )
    await update.effective_message.reply_text(messages.ADD_OTHER_CONFIRM_PROMPT, reply_markup=confirm_buttons)
    _set_expected_step(context, "confirm")
    return CONFIRM


async def handle_other_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _ack_callback(update)
    if not await _validate_add_session(update, context):
        return ConversationHandler.END
    parsed = _parse_add_callback(update.callback_query.data)
    if not parsed:
        return ConversationHandler.END
    _, _, rest = parsed
    action = rest[0] if rest else ""
    if action == "cancel":
        return await cancel_add(update, context)
    if action != "yes":
        return CONFIRM
    await _finalize_other_item(update, context)
    return ConversationHandler.END


async def _finalize_other_item(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    supplier_id = context.user_data.get("supplier_id")
    supplier_name = context.user_data.get("supplier_name")
    item = {
        "artist_album": context.user_data["manual_name"],
        "genre": context.user_data["manual_category"],
        "style": "",
        "label": "N/A",
        "format": "N/A",
        "condition": "N/A",
        "price_gel": float(context.user_data["manual_price"]),
        "quantity": int(context.user_data["manual_quantity"]),
        "supplier_id": supplier_id,
        "product_type": "other",
        "description": context.user_data.get("manual_description"),
        "supplier_name": supplier_name,
    }
    try:
        inventory_id = await run_blocking(insert_inventory, item)
        logger.info("Inserted inventory row id=%s (type=other)", inventory_id)
        await update.effective_message.reply_text(messages.ADD_SAVED_LOCAL.format(inventory_id=inventory_id))

        inventory_row = await run_blocking(get_inventory_by_id, inventory_id)
        if not inventory_row:
            raise RuntimeError("Inventory insert failed")

        photos = context.user_data.get("other_photos") or []
        woo_images: list[dict[str, Any]] = []
        cover_url = None
        for idx, file_id in enumerate(photos):
            file = await context.bot.get_file(file_id)
            file_bytes = await file.download_as_bytearray()
            ext = os.path.splitext(file.file_path or "")[1] or ".jpg"
            filename = f"inventory_{inventory_id}_{idx + 1}{ext}"
            logger.info("Uploading photo %s for inventory %s", filename, inventory_id)
            media = await run_blocking(upload_media, bytes(file_bytes), filename)
            media_id = media.get("id")
            if media_id:
                woo_images.append({"id": int(media_id)})
            if not cover_url:
                cover_url = media.get("source_url")

        inventory_row.update({
            "product_type": "other",
            "supplier_name": supplier_name,
            "woo_images": woo_images,
            "cover_url": cover_url,
        })

        if cover_url:
            await run_blocking(update_inventory_fields, inventory_id, {"cover_url": cover_url})

        await _run_post_add_sync(
            update,
            store=context.user_data.get("store"),
            inventory_id=int(inventory_id),
            inventory_row=inventory_row,
        )
    except Exception as exc:
        logger.exception("Error saving other inventory row")
        await update.effective_message.reply_text(messages.ADD_SAVE_ERROR.format(error=str(exc)))


async def orphan_supplier_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _ack_callback(update)
    if not await _validate_add_session(update, context):
        return ConversationHandler.END
    return ConversationHandler.END


async def cancel_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    if update.callback_query:
        await update.callback_query.edit_message_text(messages.ADD_CANCEL)
    else:
        await update.message.reply_text(messages.ADD_CANCEL)
    return ConversationHandler.END


async def _prompt_supplier(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    suppliers = await run_blocking(get_suppliers)
    session_id = _current_add_session_id(context)
    if suppliers:
        context.user_data["suppliers_by_id"] = {row["id"]: row["name"] for row in suppliers}
        buttons = [
            [InlineKeyboardButton(row["name"], callback_data=f"add:supplier:{session_id}:{row['id']}")]
            for row in suppliers
        ]
        buttons.append([InlineKeyboardButton("Other", callback_data=f"add:supplier:{session_id}:other")])
        await update.effective_message.reply_text(
            messages.ADD_SELECT_SUPPLIER, reply_markup=InlineKeyboardMarkup(buttons)
        )
    else:
        await update.effective_message.reply_text(messages.ADD_SUPPLIER_PROMPT)
    _set_expected_step(context, "ask_supplier")


def start_add_flow() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("add", start_add)],
        states={
            CHOOSE_TYPE: [CallbackQueryHandler(handle_add_type, pattern=r"^add:type:")],
            SEARCH_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search)],
            SHOW_RESULTS: [
                CallbackQueryHandler(handle_release_select, pattern=r"^add:select:"),
                CallbackQueryHandler(handle_pagination, pattern=r"^add:page:"),
            ],
            ASK_CONDITION: [CallbackQueryHandler(handle_condition_select, pattern=r"^add:cond:")],
            ASK_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_price_input)],
            ASK_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_quantity_input)],
            ASK_SUPPLIER: [
                CallbackQueryHandler(handle_supplier_input, pattern=r"^add:supplier:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_supplier_input),
            ],
            OTHER_CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_other_category)],
            OTHER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_other_name)],
            OTHER_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_other_price)],
            OTHER_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_other_quantity)],
            OTHER_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_other_description)],
            OTHER_PHOTOS: [
                MessageHandler(filters.PHOTO, handle_other_photo),
                CallbackQueryHandler(handle_other_photo_action, pattern=r"^add:photos:"),
            ],
            CONFIRM: [CallbackQueryHandler(handle_other_confirm, pattern=r"^add:confirm:")],
        },
        fallbacks=[CommandHandler("cancel", cancel_add)],
        name="add_record",
        persistent=False,
    )
