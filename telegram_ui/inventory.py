from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ConversationHandler, ContextTypes, MessageHandler, filters

from services.inventory_service import get_all_inventory, get_inventory_by_id, get_low_stock, search_inventory
from services.runtime import run_blocking
from telegram_ui import messages
from telegram_ui.auth import require_auth

WAITING_FOR_QUERY = 0
VIEWING_DETAIL = 1


def _format_inventory_item(item: dict, index: int) -> str:
    price = item.get("price_gel", 0)
    quantity = item.get("quantity", 0)
    artist_album = item.get("artist_album", "Unknown")
    return (
        f"{index}. {artist_album}\n"
        f"   Price: ₾{float(price):.2f}\n"
        f"   Qty: {quantity}\n\n"
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


@require_auth
async def start_inventory_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(messages.INVENTORY_SEARCH_PROMPT)
    return WAITING_FOR_QUERY


async def handle_inventory_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    if not query:
        await update.message.reply_text(messages.INVENTORY_QUERY_INVALID)
        return WAITING_FOR_QUERY

    searching_message = await update.message.reply_text(messages.INVENTORY_SEARCHING)
    try:
        if query.lower() == "all":
            results = await run_blocking(get_all_inventory)
            title = messages.INVENTORY_ALL_TITLE
        else:
            results = await run_blocking(search_inventory, query)
            title = messages.INVENTORY_SEARCH_TITLE.format(query=query)
        await searching_message.delete()

        if not results:
            await update.message.reply_text(messages.INVENTORY_NO_RESULTS.format(query=query))
            return ConversationHandler.END

        total_results = len(results)
        message = f"{title}\n{messages.INVENTORY_FOUND.format(count=total_results)}"
        for i, item in enumerate(results[:8]):
            message += _format_inventory_item(item, i + 1)
        if total_results > 8:
            message += f"\n{messages.INVENTORY_SHOWING.format(total=total_results)}"
        await update.message.reply_text(message)

        buttons = []
        for item in results[:25]:
            text = f"{item.get('artist_album', 'Item')} (Qty: {item.get('quantity', 0)})"
            if len(text) > 60:
                text = text[:57] + "..."
            buttons.append([InlineKeyboardButton(text, callback_data=f"inventory_detail:{item['id']}")])
        await update.message.reply_text(
            messages.INVENTORY_SELECT_PROMPT,
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        context.user_data["inventory_results"] = {item["id"]: item for item in results}
    except Exception as exc:
        try:
            await searching_message.delete()
        except Exception:
            pass
        await update.message.reply_text(messages.INVENTORY_SEARCH_ERROR.format(error=str(exc)))

    return ConversationHandler.END


async def view_inventory_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    item_id = int(query.data.split(":")[1])
    item = await run_blocking(get_inventory_by_id, item_id)
    if not item:
        await query.edit_message_text(messages.INVENTORY_USE_AGAIN)
        return ConversationHandler.END
    await query.edit_message_text(_format_detail(item))
    return VIEWING_DETAIL


async def cancel_inventory_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(messages.INVENTORY_CANCEL)
    return ConversationHandler.END


def create_inventory_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("inventory", start_inventory_search)],
        states={
            WAITING_FOR_QUERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_inventory_query)],
            VIEWING_DETAIL: [CallbackQueryHandler(view_inventory_detail, pattern=r"^inventory_detail:")],
        },
        fallbacks=[CommandHandler("cancel", cancel_inventory_search)],
        name="inventory_search",
        persistent=False,
    )


def register_inventory_callbacks(application) -> None:
    application.add_handler(CallbackQueryHandler(view_inventory_detail, pattern=r"^inventory_detail:"))


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
