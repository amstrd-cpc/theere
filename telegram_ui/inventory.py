from __future__ import annotations

import logging
from typing import Optional

import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import CallbackQueryHandler, CommandHandler, ConversationHandler, ContextTypes, MessageHandler, filters

from services.inventory_service import (
    get_inventory_by_id,
    get_low_stock,
    search_inventory,
    update_inventory_fields,
    update_inventory_supplier,
)
from services.runtime import run_blocking
from services.store_service import get_default_store
from services.ui_session_service import create_callback_session, inject_session
from services.woo_service import is_configured
from telegram_ui import messages
from telegram_ui.auth import require_auth
from telegram_ui.session_guard import validate_callback_or_reject

logger = logging.getLogger(__name__)

SEARCHING, LISTING, EDITING = range(3)

EDIT_FIELD_PROMPTS = {
    "name": messages.INVENTORY_EDIT_PROMPT_NAME,
    "price": messages.INVENTORY_EDIT_PROMPT_PRICE,
    "quantity": messages.INVENTORY_EDIT_PROMPT_QUANTITY,
    "condition": messages.INVENTORY_EDIT_PROMPT_CONDITION,
    "genre": messages.INVENTORY_EDIT_PROMPT_GENRE,
    "style": "Enter the new style (or 'none' to clear):",
    "label": "Enter the new label (or 'none' to clear):",
    "format": "Enter the new format (or 'none' to clear):",
    "year": "Enter the new year (or 'none' to clear):",
    "description": "Enter the new description (or 'none' to clear):",
    "supplier": messages.INVENTORY_EDIT_PROMPT_SUPPLIER,
}


def _format_inventory_item(item: dict, index: int) -> str:
    price = item.get("price_gel", 0)
    quantity = item.get("quantity", 0)
    artist_album = item.get("artist_album", "Unknown")
    condition = item.get("condition", "N/A")
    supplier = item.get("supplier_name") or "N/A"
    return (
        f"{index}. [ID {item.get('id')}] {artist_album}\n"
        f"   Price: ₾{float(price):.2f} | Qty: {quantity} | Cond: {condition} | Supplier: {supplier}\n\n"
    )


def _format_detail(item: dict) -> str:
    lines = [
        f"🎵 {item.get('artist_album', 'Unknown')}",
        f"💰 Price: ₾{float(item.get('price_gel') or 0):.2f}",
        f"📦 Stock: {item.get('quantity', 0)}",
        f"🎚 Condition: {item.get('condition', 'N/A')}",
        f"🏷 Label: {item.get('label', 'N/A')}",
        f"🎼 Genre: {item.get('genre', 'N/A')}",
        f"🎛 Style: {item.get('style', 'N/A')}",
        f"📀 Format: {item.get('format', 'N/A')}",
        f"🏢 Supplier: {item.get('supplier_name') or 'N/A'}",
    ]
    if item.get("year"):
        lines.append(f"📅 Year: {item.get('year')}")
    if item.get("woo_product_id"):
        lines.append(f"🛒 Woo ID: {item.get('woo_product_id')}")
    if item.get("woo_last_synced_at"):
        lines.append(f"🔄 Woo Synced: {item.get('woo_last_synced_at')}")
    if item.get("description"):
        lines.append("\nDescription:\n" + item.get("description"))
    return "\n".join(lines)


def _build_search_keyboard(items: list[dict], session_token: str) -> InlineKeyboardMarkup:
    buttons = []
    for item in items:
        text = f"{item.get('artist_album', 'Item')} (Qty: {item.get('quantity', 0)})"
        if len(text) > 60:
            text = text[:57] + "..."
        buttons.append([InlineKeyboardButton(text, callback_data=inject_session(f"inventory_item:{item['id']}", session_token))])
    return InlineKeyboardMarkup(buttons)


def _build_edit_menu(item_id: int, session_token: str) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("Edit Name", callback_data=inject_session(f"inventory_edit:name:{item_id}", session_token))],
        [InlineKeyboardButton("Edit Price", callback_data=inject_session(f"inventory_edit:price:{item_id}", session_token))],
        [InlineKeyboardButton("Edit Quantity", callback_data=inject_session(f"inventory_edit:quantity:{item_id}", session_token))],
        [InlineKeyboardButton("Edit Condition", callback_data=inject_session(f"inventory_edit:condition:{item_id}", session_token))],
        [InlineKeyboardButton("Edit Genre", callback_data=inject_session(f"inventory_edit:genre:{item_id}", session_token))],
        [InlineKeyboardButton("Edit Style", callback_data=inject_session(f"inventory_edit:style:{item_id}", session_token))],
        [InlineKeyboardButton("Edit Label", callback_data=inject_session(f"inventory_edit:label:{item_id}", session_token))],
        [InlineKeyboardButton("Edit Format", callback_data=inject_session(f"inventory_edit:format:{item_id}", session_token))],
        [InlineKeyboardButton("Edit Year", callback_data=inject_session(f"inventory_edit:year:{item_id}", session_token))],
        [InlineKeyboardButton("Edit Description", callback_data=inject_session(f"inventory_edit:description:{item_id}", session_token))],
        [InlineKeyboardButton("Edit Supplier", callback_data=inject_session(f"inventory_edit:supplier:{item_id}", session_token))],
        [InlineKeyboardButton("Sync to Woo", callback_data=inject_session(f"inventory_sync:{item_id}", session_token))],
        [InlineKeyboardButton("Back", callback_data=inject_session("inventory_back", session_token))],
    ]
    return InlineKeyboardMarkup(buttons)


def _normalize_optional_value(value: str) -> Optional[str]:
    cleaned = value.strip()
    if cleaned.lower() in {"", "none", "n/a", "na"}:
        return None
    return cleaned


async def _send_message(target, text: str, reply_markup: Optional[InlineKeyboardMarkup] = None) -> None:
    if hasattr(target, "edit_message_text"):
        await target.edit_message_text(text, reply_markup=reply_markup)
        return
    await target.message.reply_text(text, reply_markup=reply_markup)


async def _show_search_results(target, context: ContextTypes.DEFAULT_TYPE, query: str) -> None:
    items = await run_blocking(search_inventory, query)
    context.user_data["inventory_search_query"] = query
    if not items:
        await _send_message(target, messages.INVENTORY_NO_RESULTS.format(query=query))
        return

    message = f"{messages.INVENTORY_SEARCH_TITLE.format(query=query)}\n"
    message += messages.INVENTORY_FOUND.format(count=len(items))
    message += messages.INVENTORY_SELECT_PROMPT + "\n\n"
    for i, item in enumerate(items, 1):
        message += _format_inventory_item(item, i)

    session = create_callback_session(user_id=context._user_id if hasattr(context, "_user_id") else 0, expected_node="inventory", expected_state="listing")
    context.user_data["inventory_session_token"] = str(session["session_token"])
    keyboard = _build_search_keyboard(items, context.user_data["inventory_session_token"])
    await _send_message(target, message, reply_markup=keyboard)


async def _show_edit_menu(query, context: ContextTypes.DEFAULT_TYPE, item_id: int) -> None:
    item = await run_blocking(get_inventory_by_id, item_id)
    if not item:
        await query.edit_message_text(messages.INVENTORY_USE_AGAIN)
        return
    context.user_data["inventory_item_id"] = item_id
    token = context.user_data.get("inventory_session_token", "")
    await query.edit_message_text(_format_detail(item), reply_markup=_build_edit_menu(item_id, token))


@require_auth
async def start_inventory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context._user_id = update.effective_user.id
    await update.message.reply_text(messages.INVENTORY_SEARCH_PROMPT)
    return SEARCHING


@require_auth
async def handle_inventory_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context._user_id = update.effective_user.id
    query = (update.message.text or "").strip()
    if not query:
        await update.message.reply_text(messages.INVENTORY_QUERY_INVALID)
        return SEARCHING

    await update.message.reply_text(messages.INVENTORY_SEARCHING)
    await _show_search_results(update, context, query)
    return LISTING


@require_auth
async def handle_inventory_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except BadRequest:
        pass
    ok, data = await validate_callback_or_reject(update, context, expected_node="inventory")
    if not ok:
        return ConversationHandler.END

    if data.startswith("inventory_item:"):
        item_id = int(data.split(":")[1])
        await _show_edit_menu(query, context, item_id)
        return LISTING

    if data.startswith("inventory_edit:"):
        _, field, item_id = data.split(":")
        context.user_data["inventory_edit_field"] = field
        context.user_data["inventory_item_id"] = int(item_id)
        prompt = EDIT_FIELD_PROMPTS.get(field, messages.INVENTORY_EDIT_PROMPT_NAME)
        await query.edit_message_text(prompt)
        return EDITING

    if data == "inventory_back":
        search_query = context.user_data.get("inventory_search_query")
        if not search_query:
            await query.edit_message_text(messages.INVENTORY_USE_AGAIN)
            return ConversationHandler.END
        await _show_search_results(query, context, search_query)
        return LISTING

    if data.startswith("inventory_sync:"):
        item_id = int(data.split(":")[1])
        item = await run_blocking(get_inventory_by_id, item_id)
        if not item:
            await query.edit_message_text(messages.INVENTORY_USE_AGAIN)
            return ConversationHandler.END

        if not is_configured():
            await query.edit_message_text(messages.WOO_NOT_CONFIGURED_MESSAGE)
            return LISTING

        logger.info("Manual Woo sync requested for inventory id=%s", item.get("id"))

        from services import sync_engine

        try:
            store = await run_blocking(get_default_store)
            if not store:
                await query.edit_message_text(messages.WOO_NOT_CONFIGURED_MESSAGE)
                return LISTING
            await run_blocking(sync_engine.SyncEngine().run_instant_sync_for_item, int(store["id"]), item_id)
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response else None
            if status == 404:
                await query.edit_message_text(messages.INVENTORY_SYNC_NOT_FOUND)
                return LISTING
            await query.edit_message_text(messages.INVENTORY_SYNC_ERROR.format(error=str(exc)))
            return LISTING
        except Exception as exc:
            await query.edit_message_text(messages.INVENTORY_SYNC_ERROR.format(error=str(exc)))
            return LISTING
        token = context.user_data.get("inventory_session_token", "")
        await query.edit_message_text(messages.INVENTORY_SYNC_SUCCESS, reply_markup=_build_edit_menu(item_id, token))
        return LISTING

    return LISTING


@require_auth
async def handle_inventory_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    field = context.user_data.get("inventory_edit_field")
    item_id = context.user_data.get("inventory_item_id")
    if not field or not item_id:
        await update.message.reply_text(messages.INVENTORY_USE_AGAIN)
        return ConversationHandler.END

    value = update.message.text.strip()

    if field == "name":
        if not value:
            await update.message.reply_text(messages.INVENTORY_EDIT_NAME_REQUIRED)
            return EDITING
        await run_blocking(update_inventory_fields, item_id, {"artist_album": value})
    elif field == "price":
        try:
            price = float(value)
            if price < 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text(messages.INVENTORY_EDIT_INVALID_NUMBER)
            return EDITING
        await run_blocking(update_inventory_fields, item_id, {"price_gel": price})
    elif field == "quantity":
        try:
            quantity = int(value)
            if quantity < 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text(messages.INVENTORY_EDIT_INVALID_INTEGER)
            return EDITING
        await run_blocking(update_inventory_fields, item_id, {"quantity": quantity})
    elif field == "condition":
        await run_blocking(update_inventory_fields, item_id, {"condition": value})
    elif field == "genre":
        genre = _normalize_optional_value(value)
        await run_blocking(update_inventory_fields, item_id, {"genre": genre})
    elif field == "style":
        style = _normalize_optional_value(value)
        await run_blocking(update_inventory_fields, item_id, {"style": style})
    elif field == "label":
        label = _normalize_optional_value(value)
        await run_blocking(update_inventory_fields, item_id, {"label": label})
    elif field == "format":
        fmt = _normalize_optional_value(value)
        await run_blocking(update_inventory_fields, item_id, {"format": fmt})
    elif field == "year":
        normalized = _normalize_optional_value(value)
        if normalized is None:
            await run_blocking(update_inventory_fields, item_id, {"year": None})
        else:
            try:
                year = int(normalized)
                if year < 0:
                    raise ValueError
            except ValueError:
                await update.message.reply_text(messages.INVENTORY_EDIT_INVALID_INTEGER)
                return EDITING
            await run_blocking(update_inventory_fields, item_id, {"year": year})
    elif field == "description":
        description = _normalize_optional_value(value)
        await run_blocking(update_inventory_fields, item_id, {"description": description})
    elif field == "supplier":
        supplier = _normalize_optional_value(value)
        await run_blocking(update_inventory_supplier, item_id, supplier)
    else:
        await update.message.reply_text(messages.INVENTORY_USE_AGAIN)
        return ConversationHandler.END

    context.user_data.pop("inventory_edit_field", None)
    updated_item = await run_blocking(get_inventory_by_id, item_id)
    await update.message.reply_text(messages.INVENTORY_EDIT_SAVED)
    if updated_item:
        await update.message.reply_text(
            _format_detail(updated_item),
            reply_markup=_build_edit_menu(item_id),
        )
    return LISTING


async def cancel_inventory_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(messages.INVENTORY_CANCEL)
    return ConversationHandler.END


def create_inventory_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("inventory", start_inventory)],
        states={
            SEARCHING: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_inventory_search)],
            LISTING: [CallbackQueryHandler(handle_inventory_callback, pattern=r"^inventory_")],
            EDITING: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_inventory_edit)],
        },
        fallbacks=[CommandHandler("cancel", cancel_inventory_search)],
        name="inventory_list",
        persistent=False,
    )


def register_inventory_callbacks(application) -> None:
    application.add_handler(CallbackQueryHandler(handle_inventory_callback, pattern=r"^inventory_"))


@require_auth
async def low_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    items = await run_blocking(get_low_stock)
    if not items:
        await update.message.reply_text(messages.STOCK_EMPTY)
        return
    message = messages.STOCK_HEADER
    for i, item in enumerate(items, 1):
        message += _format_inventory_item(item, i)
    await update.message.reply_text(message)
