from __future__ import annotations

import datetime
import logging
import math
from typing import Optional

import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ConversationHandler, ContextTypes, MessageHandler, filters

from services.inventory_service import (
    get_inventory_by_id,
    get_inventory_page,
    get_low_stock,
    update_inventory_fields,
    update_inventory_supplier,
)
from services.runtime import run_blocking
from services.woo_service import is_configured
from woocommerce_client import payload_for_update_from_inventory, update_product_by_id
from telegram_ui import messages
from telegram_ui.auth import require_auth

logger = logging.getLogger(__name__)

LISTING, EDITING = range(2)
PAGE_SIZE = 8

EDIT_FIELD_PROMPTS = {
    "name": messages.INVENTORY_EDIT_PROMPT_NAME,
    "price": messages.INVENTORY_EDIT_PROMPT_PRICE,
    "quantity": messages.INVENTORY_EDIT_PROMPT_QUANTITY,
    "condition": messages.INVENTORY_EDIT_PROMPT_CONDITION,
    "genre": messages.INVENTORY_EDIT_PROMPT_GENRE,
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


def _build_inventory_keyboard(items: list[dict], page: int, total: int) -> InlineKeyboardMarkup:
    buttons = []
    for item in items:
        text = f"{item.get('artist_album', 'Item')} (Qty: {item.get('quantity', 0)})"
        if len(text) > 60:
            text = text[:57] + "..."
        buttons.append([InlineKeyboardButton(text, callback_data=f"inventory_item:{item['id']}")])

    total_pages = max(1, math.ceil(total / PAGE_SIZE))
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"inventory_page:{page - 1}"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"inventory_page:{page + 1}"))
    if nav_buttons:
        buttons.append(nav_buttons)
    return InlineKeyboardMarkup(buttons)


def _build_edit_menu(item_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("Edit Name", callback_data=f"inventory_edit:name:{item_id}")],
        [InlineKeyboardButton("Edit Price", callback_data=f"inventory_edit:price:{item_id}")],
        [InlineKeyboardButton("Edit Quantity", callback_data=f"inventory_edit:quantity:{item_id}")],
        [InlineKeyboardButton("Edit Condition", callback_data=f"inventory_edit:condition:{item_id}")],
        [InlineKeyboardButton("Edit Category/Genre", callback_data=f"inventory_edit:genre:{item_id}")],
        [InlineKeyboardButton("Edit Supplier", callback_data=f"inventory_edit:supplier:{item_id}")],
        [InlineKeyboardButton("Sync to Woo", callback_data=f"inventory_sync:{item_id}")],
        [InlineKeyboardButton("Back", callback_data="inventory_back")],
    ]
    return InlineKeyboardMarkup(buttons)


def _normalize_optional_value(value: str) -> Optional[str]:
    cleaned = value.strip()
    if cleaned.lower() in {"", "none", "n/a", "na"}:
        return None
    return cleaned


async def _show_inventory_page(target, context: ContextTypes.DEFAULT_TYPE, page: int) -> None:
    items, total = await run_blocking(get_inventory_page, page, PAGE_SIZE)
    if total == 0:
        if hasattr(target, "edit_message_text"):
            await target.edit_message_text(messages.INVENTORY_PAGE_EMPTY)
        else:
            await target.message.reply_text(messages.INVENTORY_PAGE_EMPTY)
        return

    total_pages = max(1, math.ceil(total / PAGE_SIZE))
    normalized_page = max(1, min(page, total_pages))
    if normalized_page != page:
        page = normalized_page
        items, total = await run_blocking(get_inventory_page, page, PAGE_SIZE)
    context.user_data["inventory_page"] = page
    message = f"{messages.INVENTORY_PAGE_TITLE.format(page=page, total_pages=total_pages)}\n"
    message += messages.INVENTORY_FOUND.format(count=total)
    for i, item in enumerate(items, 1 + (page - 1) * PAGE_SIZE):
        message += _format_inventory_item(item, i)

    keyboard = _build_inventory_keyboard(items, page, total)
    if hasattr(target, "edit_message_text"):
        await target.edit_message_text(message, reply_markup=keyboard)
    else:
        await target.message.reply_text(message, reply_markup=keyboard)


async def _show_edit_menu(query, context: ContextTypes.DEFAULT_TYPE, item_id: int) -> None:
    item = await run_blocking(get_inventory_by_id, item_id)
    if not item:
        await query.edit_message_text(messages.INVENTORY_USE_AGAIN)
        return
    context.user_data["inventory_item_id"] = item_id
    await query.edit_message_text(_format_detail(item), reply_markup=_build_edit_menu(item_id))


@require_auth
async def start_inventory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _show_inventory_page(update, context, 1)
    return LISTING


@require_auth
async def handle_inventory_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""

    if data.startswith("inventory_page:"):
        page = int(data.split(":")[1])
        await _show_inventory_page(query, context, page)
        return LISTING

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
        page = context.user_data.get("inventory_page", 1)
        await _show_inventory_page(query, context, page)
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

        woo_product_id = item.get("woo_product_id")
        if not woo_product_id:
            await query.edit_message_text(messages.INVENTORY_SYNC_MISSING_WOO)
            return LISTING

        payload = payload_for_update_from_inventory(item)
        logger.info(
            "Woo sync inventory id=%s woo_product_id=%s fields=%s",
            item.get("id"),
            woo_product_id,
            sorted(payload.keys()),
        )

        try:
            await run_blocking(update_product_by_id, int(woo_product_id), payload)
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

        await run_blocking(
            update_inventory_fields,
            item_id,
            {
                "woo_synced": 1,
                "woo_last_synced_at": datetime.datetime.utcnow().isoformat(),
            },
        )
        await query.edit_message_text(messages.INVENTORY_SYNC_SUCCESS, reply_markup=_build_edit_menu(item_id))
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
