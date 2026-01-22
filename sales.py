# sales.py — Fully updated with quantity tracking and dual DB logging
import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler,
    ContextTypes, filters
)
from db import get_db
import inventory as inventory_utils
from woocommerce_client import (
    WooNotConfigured,
    is_configured,
    update_product_stock,
)

SELL_QUERY, SELL_SELECT, SELL_PRICE, SELL_MORE, SELL_PAYMENT = range(5)

def escape_markdown_v2(text):
    """Escape special characters for MarkdownV2"""
    special_chars = r'_*[]()~`>#+-=|{}.!'
    return ''.join(f'\\{char}' if char in special_chars else char for char in str(text))

def escape_markdown_v1(text):
    """Escape special characters for Markdown (legacy)"""
    special_chars = r'_*`['
    return ''.join(f'\\{char}' if char in special_chars else char for char in str(text))

# === Start Sell Flow ===
async def sell_flow_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💰 Welcome to the Sell Vinyls flow!\n"
        "Please enter the artist or album name you want to sell:"
    )
    context.user_data.clear()
    context.user_data["cart"] = []
    return SELL_QUERY

async def sell_flow_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    context.user_data["query"] = query
    found_items = inventory_utils.search_inventory(query)

    if not found_items:
        # Use HTML parsing instead of Markdown to avoid conflicts
        await update.message.reply_text(f"❌ No matching records found for: <b>{query}</b>", parse_mode="HTML")
        return ConversationHandler.END

    context.user_data["found_items"] = found_items
    
    # Create buttons with proper item information including quantity
    buttons = []
    for i, item in enumerate(found_items):
        button_text = f"{item['artist_album']} - {item['condition']} (Qty: {item['quantity']}) - ₾{item['price_gel']:.2f}"
        # Truncate if too long for button
        if len(button_text) > 60:
            button_text = button_text[:57] + "..."
        buttons.append([InlineKeyboardButton(button_text, callback_data=f"select_{i}")])

    reply_markup = InlineKeyboardMarkup(buttons)
    await update.message.reply_text("Please select the record you want to sell:", reply_markup=reply_markup)
    return SELL_SELECT

async def sell_flow_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    selected_index = int(query.data.split("_")[1])
    selected_item = context.user_data["found_items"][selected_index]
    context.user_data["selected_item"] = selected_item

    message_text = (
        f"Selected: <b>{selected_item['artist_album']}</b>\n"
        f"Condition: {selected_item['condition']}\n"
        f"Available: {selected_item['quantity']} copies\n"
        f"Listed price: ₾{selected_item['price_gel']:.2f}\n\n"
        f"Enter the selling price or type 'ok' to use the listed price:"
    )

    await query.edit_message_text(
        message_text,
        parse_mode="HTML",
    )
    return SELL_PRICE

async def sell_flow_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    payment_method = query.data.split("_")[1]
    cart = context.user_data.get("cart", [])
    if not cart:
        await query.edit_message_text("Cart is empty.")
        return ConversationHandler.END

    today = datetime.date.today().isoformat()
    total = 0
    summary_lines = []

    try:
        for entry in cart:
            item = entry["item"]
            price = entry["price"]
            total += price

            success = inventory_utils.reduce_inventory_quantity(item["id"], 1)
            if not success:
                summary_lines.append(f"Failed to sell {item['artist_album']} (out of stock)")
                continue

            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO sales (
                        date, artist_album, genre, style, label, format,
                        condition, price_gel, supplier_id, payment_method
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        today,
                        item["artist_album"],
                        item["genre"],
                        item["style"],
                        item["label"],
                        item["format"],
                        item["condition"],
                        price,
                        item.get("supplier_id"),
                        payment_method,
                    ),
                )
                conn.commit()

            # Sales are recorded in the unified DB (sales table). Reports read from the same DB.

            updated = inventory_utils.get_inventory_by_id(item["id"])
            remaining = updated["quantity"] if updated else 0
            try:
                if updated and is_configured():
                    woo_id = updated.get("woo_product_id")
                    if woo_id:
                        update_product_stock(int(woo_id), int(remaining))
                        with get_db() as conn:
                            cur = conn.cursor()
                            cur.execute(
                                """
                                UPDATE inventory
                                SET woo_synced = 1, woo_last_synced_at = ?
                                WHERE id = ?
                                """,
                                (datetime.datetime.utcnow().isoformat(), updated["id"]),
                            )
                            conn.commit()
            except WooNotConfigured:
                pass
            except Exception as e:
                print(f"WooCommerce stock update failed for inventory {item['id']}: {e}")
            summary_lines.append(
                f"{item['artist_album']} - ₾{price:.2f} (left: {remaining})"
            )

        summary_lines.append(f"Payment: {payment_method.upper()}")
        summary_lines.append(f"Total: ₾{total:.2f}")

        await query.edit_message_text(
            "\n".join(summary_lines),
            parse_mode="HTML",
        )

    except Exception as e:
        await query.edit_message_text(f"❌ Error processing sale: {str(e)}")
    return ConversationHandler.END

async def sell_flow_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text.strip()
    selected_item = context.user_data["selected_item"]

    # Handle price input
    if msg.lower() == "ok":
        final_price = selected_item['price_gel']
    else:
        try:
            final_price = float(msg)
            if final_price < 0:
                await update.message.reply_text("❌ Price cannot be negative. Please enter a valid price or 'ok':")
                return SELL_PRICE
        except ValueError:
            await update.message.reply_text("❌ Invalid price format. Please enter a valid number or 'ok':")
            return SELL_PRICE

    cart = context.user_data.get("cart", [])
    cart.append({"item": selected_item, "price": final_price})
    context.user_data["cart"] = cart

    buttons = [
        [InlineKeyboardButton("➕ Add More", callback_data="more")],
        [InlineKeyboardButton("✅ Checkout", callback_data="checkout")],
    ]
    await update.message.reply_text(
        f"Added {selected_item['artist_album']} - ₾{final_price:.2f} to cart.\n"
        "Add another item or proceed to checkout?",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return SELL_MORE


async def sell_flow_more(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "more":
        await query.edit_message_text(
            "Enter the artist or album name of the next record:"
        )
        return SELL_QUERY

    # Checkout selected
    payment_buttons = [
        [InlineKeyboardButton("💵 Cash", callback_data="payment_cash")],
        [InlineKeyboardButton("💳 POS/Card", callback_data="payment_pos")],
    ]
    await query.edit_message_text(
        "Choose payment method:",
        reply_markup=InlineKeyboardMarkup(payment_buttons),
    )
    return SELL_PAYMENT

async def cancel_sale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle cancellation of sale process"""
    await update.message.reply_text("❌ Sale cancelled.")
    return ConversationHandler.END

# === Entry Point ===
def start_sell_flow():
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
        persistent=False
    )