from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict

import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ConversationHandler, ContextTypes, MessageHandler, filters

from services import discogs_service
from config.settings import load_settings
from services.inventory_service import get_or_create_supplier, get_suppliers, insert_inventory, get_inventory_by_id, update_inventory_sync
from services.runtime import run_blocking
from services.woo_service import WooNotConfigured, upsert_product_from_inventory, compute_sync_hash
from telegram_ui import messages

logger = logging.getLogger(__name__)

SEARCH_INPUT, SHOW_RESULTS, ASK_CONDITION, ASK_PRICE, ASK_QUANTITY, ASK_SUPPLIER = range(6)
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


async def start_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings = load_settings()
    if not settings.discogs_token:
        await update.message.reply_text(messages.ADD_DISCOGS_MISSING)
        return ConversationHandler.END

    await update.message.reply_text(messages.ADD_PROMPT_QUERY)
    context.user_data.clear()
    return SEARCH_INPUT


async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    context.user_data["query"] = query
    context.user_data["page"] = 1
    return await show_results(update, context)


async def show_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    page = context.user_data["page"]
    query = context.user_data["query"]
    try:
        results = await run_blocking(discogs_service.search_releases, query, page, 50)
    except discogs_service.DiscogsNotConfigured:
        await update.effective_message.reply_text(messages.ADD_DISCOGS_MISSING)
        return ConversationHandler.END
    context.user_data["results"] = results

    buttons = [
        [InlineKeyboardButton(_format_release_button(release), callback_data=f"select_{i}")]
        for i, release in enumerate(results)
    ]

    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data="prev"))
    if len(results) == 50:
        nav_buttons.append(InlineKeyboardButton("➡️ Next", callback_data="next"))
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
    return SHOW_RESULTS


async def handle_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query.data == "next":
        context.user_data["page"] += 1
    elif update.callback_query.data == "prev":
        context.user_data["page"] = max(1, context.user_data["page"] - 1)
    return await show_results(update, context)


async def handle_release_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    idx = int(update.callback_query.data.split("_")[1])
    selected = context.user_data["results"][idx]
    release_id = selected.get("id")
    release = await run_blocking(discogs_service.fetch_release, int(release_id))
    context.user_data["release"] = release

    await update.callback_query.edit_message_text(
        messages.ADD_SELECT_CONDITION.format(title=release.get("title", "")),
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton(c, callback_data=f"cond_{c}") for c in CONDITION_OPTIONS[i:i + 4]]
                for i in range(0, len(CONDITION_OPTIONS), 4)
            ]
        ),
    )
    return ASK_CONDITION


async def handle_condition_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cond = update.callback_query.data.split("_")[1]
    context.user_data["condition"] = cond
    release = context.user_data["release"]

    suggestions = await run_blocking(discogs_service.fetch_price_suggestions, int(release.get("id")))
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
    suppliers = await run_blocking(get_suppliers)
    if suppliers:
        buttons = [
            [InlineKeyboardButton(row["name"], callback_data=f"sup_{row['id']}")]
            for row in suppliers
        ]
        await update.message.reply_text(
            messages.ADD_SELECT_SUPPLIER, reply_markup=InlineKeyboardMarkup(buttons)
        )
    else:
        await update.message.reply_text(messages.ADD_SUPPLIER_PROMPT)
    return ASK_SUPPLIER


async def handle_supplier_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.callback_query:
            query = update.callback_query
            await query.answer()
            if not context.user_data or "release" not in context.user_data:
                await update.effective_message.reply_text(messages.ADD_SUPPLIER_STALE)
                return ConversationHandler.END
            supplier_id = int(query.data.split("_")[1])
            supplier_name = None
        else:
            supplier_name = update.message.text.strip()
            supplier_id = await run_blocking(get_or_create_supplier, supplier_name)

        release = context.user_data["release"]
        cond = context.user_data["condition"]
        price = context.user_data["final_price"]
        qty = context.user_data["quantity"]

        artist_name = discogs_service.extract_artists(release)
        release_title = str(release.get("title") or "Unknown")
        artist_album = f"{artist_name} - {release_title}" if artist_name != "Unknown" else release_title

        item = {
            "artist_album": artist_album,
            "genre": discogs_service.safe_join_list(release.get("genres")),
            "style": discogs_service.safe_join_list(release.get("styles")),
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
        }

        inventory_id = await run_blocking(insert_inventory, item)
        await update.effective_message.reply_text(
            messages.ADD_SAVED_LOCAL.format(inventory_id=inventory_id)
        )

        inventory_row = await run_blocking(get_inventory_by_id, inventory_id)
        if not inventory_row:
            raise RuntimeError("Inventory insert failed")

        inventory_row.update({
            "product_type": "record",
            "tracklist": item.get("tracklist"),
            "cover_url": item.get("cover_url"),
        })

        try:
            woo_product = await run_blocking(upsert_product_from_inventory, inventory_row)
        except WooNotConfigured:
            await update.effective_message.reply_text(messages.ADD_WOO_NOT_CONFIGURED)
        except Exception as exc:
            logger.exception("Woo sync failed")
            await update.effective_message.reply_text(
                messages.ADD_WOO_FAILED.format(error=f"{type(exc).__name__}: {exc}")
            )
        else:
            woo_id = woo_product.get("id")
            if woo_id:
                sync_hash = compute_sync_hash(woo_product)
                await run_blocking(update_inventory_sync, inventory_id, int(woo_id), sync_hash)
            await update.effective_message.reply_text(
                messages.ADD_WOO_OK.format(woo_id=woo_id)
            )
    except Exception as exc:
        logger.exception("Error saving inventory row")
        await update.effective_message.reply_text(messages.ADD_SAVE_ERROR.format(error=str(exc)))

    return ConversationHandler.END


async def orphan_supplier_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    await update.effective_message.reply_text(messages.ADD_SUPPLIER_STALE)
    return ConversationHandler.END


async def cancel_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(messages.ADD_CANCEL)
    else:
        await update.message.reply_text(messages.ADD_CANCEL)
    return ConversationHandler.END


def start_add_flow() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("add", start_add)],
        states={
            SEARCH_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search)],
            SHOW_RESULTS: [
                CallbackQueryHandler(handle_release_select, pattern=r"^select_"),
                CallbackQueryHandler(handle_pagination, pattern="^(next|prev)$"),
            ],
            ASK_CONDITION: [CallbackQueryHandler(handle_condition_select, pattern=r"^cond_")],
            ASK_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_price_input)],
            ASK_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_quantity_input)],
            ASK_SUPPLIER: [
                CallbackQueryHandler(handle_supplier_input, pattern=r"^sup_\d+"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_supplier_input),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_add)],
        name="add_record",
        persistent=False,
    )
