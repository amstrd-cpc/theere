from __future__ import annotations

import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import CallbackQueryHandler, CommandHandler, ConversationHandler, ContextTypes, MessageHandler, filters

from services.inventory_service import get_inventory_by_id, reduce_inventory_quantity, search_inventory, update_inventory_fields
from services.sales_service import record_sale
from services.runtime import run_blocking
from services.woo_service import WooNotConfigured, is_configured, update_stock
from telegram_ui import messages

SELL_QUERY, SELL_SELECT, SELL_PRICE, SELL_MORE, SELL_PAYMENT = range(5)


def _escape_html(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def sell_flow_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(messages.SELL_WELCOME)
    context.user_data.clear()
    context.user_data["cart"] = []
    return SELL_QUERY


async def sell_flow_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    context.user_data["query"] = query
    found_items = await run_blocking(search_inventory, query)

    if not found_items:
        await update.message.reply_text(messages.SELL_NOT_FOUND.format(query=_escape_html(query)), parse_mode="HTML")
        return ConversationHandler.END

    context.user_data["found_items"] = found_items
    buttons = []
    for i, item in enumerate(found_items):
        button_text = f"{item['artist_album']} - {item['condition']} (Qty: {item['quantity']}) - ₾{item['price_gel']:.2f}"
        if len(button_text) > 60:
            button_text = button_text[:57] + "..."
        buttons.append([InlineKeyboardButton(button_text, callback_data=f"select_{i}")])

    reply_markup = InlineKeyboardMarkup(buttons)
    await update.message.reply_text(messages.SELL_SELECT_PROMPT, reply_markup=reply_markup)
    return SELL_SELECT


async def sell_flow_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except BadRequest:
        pass

    selected_index = int(query.data.split("_")[1])
    selected_item = context.user_data["found_items"][selected_index]
    context.user_data["selected_item"] = selected_item

    message_text = messages.SELL_SELECTED.format(
        artist_album=_escape_html(selected_item["artist_album"]),
        condition=_escape_html(selected_item["condition"]),
        quantity=selected_item["quantity"],
        price=float(selected_item["price_gel"]),
    )

    await query.edit_message_text(message_text, parse_mode="HTML")
    return SELL_PRICE


async def sell_flow_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text.strip()
    selected_item = context.user_data["selected_item"]

    if msg.lower() == "ok":
        final_price = selected_item["price_gel"]
    else:
        try:
            final_price = float(msg)
            if final_price < 0:
                await update.message.reply_text(messages.SELL_PRICE_NEGATIVE)
                return SELL_PRICE
        except ValueError:
            await update.message.reply_text(messages.SELL_PRICE_INVALID)
            return SELL_PRICE

    cart = context.user_data.get("cart", [])
    cart.append({"item": selected_item, "price": final_price})
    context.user_data["cart"] = cart

    buttons = [
        [InlineKeyboardButton("➕ Add More", callback_data="more")],
        [InlineKeyboardButton("✅ Checkout", callback_data="checkout")],
    ]
    await update.message.reply_text(
        messages.SELL_ADDED.format(artist_album=selected_item["artist_album"], price=final_price),
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return SELL_MORE


async def sell_flow_more(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except BadRequest:
        pass

    if query.data == "more":
        await query.edit_message_text(messages.SELL_NEXT_PROMPT)
        return SELL_QUERY

    payment_buttons = [
        [InlineKeyboardButton("💵 Cash", callback_data="payment_cash")],
        [InlineKeyboardButton("💳 POS/Card", callback_data="payment_pos")],
    ]
    await query.edit_message_text(messages.SELL_PAYMENT_PROMPT, reply_markup=InlineKeyboardMarkup(payment_buttons))
    return SELL_PAYMENT


async def sell_flow_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except BadRequest:
        pass

    payment_method = query.data.split("_")[1]
    cart = context.user_data.get("cart", [])
    if not cart:
        await query.edit_message_text(messages.SELL_CART_EMPTY)
        return ConversationHandler.END

    total = 0
    summary_lines = []

    try:
        for entry in cart:
            item = entry["item"]
            price = entry["price"]
            total += price

            success = await run_blocking(reduce_inventory_quantity, item["id"], 1)
            if not success:
                summary_lines.append(messages.SELL_FAILED_ITEM.format(artist_album=item["artist_album"]))
                continue

            await run_blocking(record_sale, item, price, payment_method)

            updated = await run_blocking(get_inventory_by_id, item["id"])
            remaining = updated["quantity"] if updated else 0
            try:
                if updated and is_configured():
                    woo_id = updated.get("woo_product_id")
                    if woo_id:
                        await run_blocking(update_stock, int(woo_id), int(remaining))
                        await run_blocking(
                            update_inventory_fields,
                            updated["id"],
                            {
                                "woo_synced": 1,
                                "woo_last_synced_at": datetime.datetime.utcnow().isoformat(),
                            },
                        )
            except WooNotConfigured:
                pass
            summary_lines.append(f"{item['artist_album']} - ₾{price:.2f} (left: {remaining})")

        summary_lines.append(messages.SELL_PAYMENT_LINE.format(method=payment_method.upper()))
        summary_lines.append(messages.SELL_TOTAL_LINE.format(total=total))

        await query.edit_message_text("\n".join(summary_lines), parse_mode="HTML")
    except Exception as exc:
        await query.edit_message_text(messages.SELL_ERROR_PROCESSING.format(error=exc))
    return ConversationHandler.END


async def cancel_sale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(messages.SELL_CANCEL)
    return ConversationHandler.END


def start_sell_flow() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("sell", sell_flow_start)],
        states={
            SELL_QUERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, sell_flow_query)],
            SELL_SELECT: [CallbackQueryHandler(sell_flow_select, pattern=r"^select_\d+")],
            SELL_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, sell_flow_price)],
            SELL_MORE: [CallbackQueryHandler(sell_flow_more, pattern=r"^(more|checkout)$")],
            SELL_PAYMENT: [CallbackQueryHandler(sell_flow_payment, pattern=r"^payment_(cash|pos)$")],
        },
        fallbacks=[CommandHandler("cancel", cancel_sale)],
        name="sell_vinyls",
        persistent=False,
    )
