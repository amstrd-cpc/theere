from __future__ import annotations

import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters

from services.inventory_service import get_inventory_by_id, search_inventory
from services.product_map_service import upsert_product_map
from services.runtime import run_blocking
from services.store_service import get_default_store
from services.woo_mapping_service import auto_map_woo_products
from services.woo_service import WooNotConfigured
from telegram_ui.auth import require_admin, require_auth

SEARCHING, SELECTING, EXTRA_INPUT, CONFIRMING = range(4)


def _build_search_keyboard(items: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for item in items:
        text = f"{item.get('artist_album', 'Item')} (Qty: {item.get('quantity', 0)})"
        if len(text) > 60:
            text = text[:57] + "..."
        buttons.append([InlineKeyboardButton(text, callback_data=f"woo_map_select:{item['id']}")])
    return InlineKeyboardMarkup(buttons)


def _build_confirm_keyboard(item_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton("✅ Confirm", callback_data=f"woo_map_confirm:{item_id}:yes"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"woo_map_confirm:{item_id}:no"),
        ]
    ]
    return InlineKeyboardMarkup(buttons)


def _extract_product_id(value: str) -> int | None:
    match = re.search(r"(\d+)", value)
    if not match:
        return None
    return int(match.group(1))


def _format_item_summary(item: dict) -> str:
    artist_album = item.get("artist_album", "Unknown")
    condition = item.get("condition", "N/A")
    price = float(item.get("price_gel") or 0)
    quantity = item.get("quantity", 0)
    return (
        f"🎵 {artist_album}\n"
        f"🎚 Condition: {condition}\n"
        f"💰 Price: ₾{price:.2f}\n"
        f"📦 Stock: {quantity}"
    )


@require_auth
@require_admin
async def map_woo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store = get_default_store()
    if not store:
        await update.message.reply_text("❌ No store configured. Run /setup_woo first.")
        return ConversationHandler.END
    await update.message.reply_text("Tell me the artist or album name you want to map to WooCommerce:")
    return SEARCHING


@require_auth
@require_admin
async def handle_map_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = (update.message.text or "").strip()
    if not query:
        await update.message.reply_text("Please enter a valid name to search.")
        return SEARCHING

    items = await run_blocking(search_inventory, query)
    if not items:
        await update.message.reply_text(f"❌ No matches found for '{query}'. Try another name.")
        return SEARCHING

    message = f"Found {len(items)} match(es). Tap the correct item:"
    await update.message.reply_text(message, reply_markup=_build_search_keyboard(items))
    return SELECTING


@require_auth
@require_admin
async def handle_map_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    _, item_id = data.split(":", 1)
    item = await run_blocking(get_inventory_by_id, int(item_id))
    if not item:
        await query.edit_message_text("Item not found. Please try again.")
        return ConversationHandler.END

    context.user_data["woo_map_item_id"] = int(item_id)
    await query.edit_message_text(
        f"{_format_item_summary(item)}\n\nPaste the Woo product URL or ID to link:",
    )
    return EXTRA_INPUT


@require_auth
@require_admin
async def handle_map_extra(update: Update, context: ContextTypes.DEFAULT_TYPE):
    item_id = context.user_data.get("woo_map_item_id")
    if not item_id:
        await update.message.reply_text("Please start again with /map_woo.")
        return ConversationHandler.END

    woo_product_id = _extract_product_id(update.message.text or "")
    if not woo_product_id:
        await update.message.reply_text("Please paste a valid Woo product URL or ID.")
        return EXTRA_INPUT

    context.user_data["woo_map_product_id"] = woo_product_id
    item = await run_blocking(get_inventory_by_id, int(item_id))
    if not item:
        await update.message.reply_text("Item not found. Please start again.")
        return ConversationHandler.END

    confirm_text = (
        f"{_format_item_summary(item)}\n"
        f"🔗 Woo product ID: {woo_product_id}\n\n"
        "Confirm mapping this item?"
    )
    await update.message.reply_text(confirm_text, reply_markup=_build_confirm_keyboard(int(item_id)))
    return CONFIRMING


@require_auth
@require_admin
async def handle_map_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    _, item_id, decision = data.split(":", 2)
    if decision != "yes":
        await query.edit_message_text("❌ Cancelled.")
        return ConversationHandler.END

    store = get_default_store()
    if not store:
        await query.edit_message_text("❌ No store configured. Run /setup_woo first.")
        return ConversationHandler.END

    woo_product_id = context.user_data.get("woo_map_product_id")
    if not woo_product_id:
        await query.edit_message_text("Missing Woo product ID. Please start again.")
        return ConversationHandler.END

    upsert_product_map(
        store_id=int(store["id"]),
        internal_product_id=int(item_id),
        woo_product_id=int(woo_product_id),
        sku=None,
    )
    await query.edit_message_text("✅ Mapping saved.")
    return ConversationHandler.END


async def cancel_map(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text("❌ Mapping cancelled.")
    return ConversationHandler.END


@require_auth
@require_admin
async def auto_map_woo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store = get_default_store()
    if not store:
        await update.message.reply_text("❌ No store configured. Run /setup_woo first.")
        return

    await update.message.reply_text("🔎 Auto-mapping WooCommerce products to inventory...")
    try:
        result = await run_blocking(auto_map_woo_products, store_id=int(store["id"]))
    except WooNotConfigured:
        await update.message.reply_text("❌ WooCommerce not configured. Run /setup_woo first.")
        return

    await update.message.reply_text(
        "✅ Auto-mapping complete.\n"
        f"🔗 Linked: {result.get('linked', 0)}\n"
        f"⚠️ Ambiguous: {result.get('ambiguous', 0)}\n"
        f"⏭️ Skipped: {result.get('skipped', 0)}"
    )


def create_map_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("map_woo", map_woo)],
        states={
            SEARCHING: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_map_search)],
            SELECTING: [CallbackQueryHandler(handle_map_select, pattern=r"^woo_map_select:")],
            EXTRA_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_map_extra)],
            CONFIRMING: [CallbackQueryHandler(handle_map_confirm, pattern=r"^woo_map_confirm:")],
        },
        fallbacks=[CommandHandler("cancel", cancel_map)],
        name="map_woo",
        persistent=False,
    )


def create_auto_map_handler() -> CommandHandler:
    return CommandHandler("auto_map_woo", auto_map_woo)
