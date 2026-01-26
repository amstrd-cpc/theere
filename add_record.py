# Rewritten add_record.py with USD to GEL conversion
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler,
    ContextTypes, filters
)
import discogs_client
from dotenv import load_dotenv
import os
import requests
from datetime import datetime
from db import get_db, get_suppliers, get_or_create_supplier
import logging

from woocommerce_sync import WooConfig, WooSync, woo_is_configured, upsert_product_async

load_dotenv()
DISCOGS_TOKEN = os.getenv("DISCOGS_TOKEN")


def _get_discogs_client():
    if not DISCOGS_TOKEN:
        return None
    return discogs_client.Client("RecordStoreApp/1.0", user_token=DISCOGS_TOKEN)


d = _get_discogs_client()

logger = logging.getLogger(__name__)

SEARCH_INPUT, SHOW_RESULTS, ASK_CONDITION, ASK_PRICE, ASK_QUANTITY, ASK_SUPPLIER = range(6)
CONDITION_OPTIONS = ["m", "nm", "vg+", "vg", "g+", "g", "f", "p"]


def fetch_usd_to_gel():
    try:
        today = datetime.now().strftime("%d.%m.%Y")
        url = f"https://nbg.gov.ge/gw/api/ct/monetarypolicy/currencies/en/json/?date={today}"
        response = requests.get(url)
        data = response.json()
        for item in data[0]['currencies']:
            if item['code'] == 'USD':
                return float(item['rate'])
    except Exception as e:
        print(f"Error fetching GEL rate: {e}")
    return 1.0


def save_to_inventory(row) -> int:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
        INSERT INTO inventory (artist_album, genre, style, label, format, condition, price_gel, quantity, supplier_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            row,
        )
        conn.commit()
        return int(cursor.lastrowid)


def set_inventory_woo_link(item_id: int, woo_product_id: int) -> None:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE inventory
            SET woo_product_id = ?, woo_synced = 1, woo_last_synced_at = ?
            WHERE id = ?
            """,
            (str(woo_product_id), datetime.utcnow().isoformat(), item_id),
        )
        conn.commit()


def fetch_price_suggestions(release_id):
    if not d:
        return {}
    try:
        return d._get(f"https://api.discogs.com/marketplace/price_suggestions/{release_id}")
    except Exception:
        return {}


def safe_join_list(data, default="N/A"):
    if not data:
        return default
    try:
        if isinstance(data, list):
            return ", ".join(str(item) for item in data if item)
        else:
            return str(data)
    except Exception:
        return default


def safe_get_labels(release):
    try:
        if hasattr(release, 'labels') and release.labels:
            labels = [str(label.name) if hasattr(label, 'name') else str(label) for label in release.labels]
            return ", ".join(labels) if labels else "N/A"
        return "N/A"
    except Exception:
        return "N/A"


def safe_get_format(release):
    try:
        format_data = release.data.get("formats", [])
        format_parts = []
        for fmt in format_data:
            parts = []
            if fmt.get("name"):
                parts.append(str(fmt.get("name")))
            if fmt.get("descriptions"):
                parts.extend([str(desc) for desc in fmt.get("descriptions", [])])
            if parts:
                format_parts.append(" ".join(parts))
        return ", ".join(format_parts) if format_parts else "Unknown Format"
    except Exception:
        return "Unknown Format"


async def start_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not d:
        await update.message.reply_text(
            "⚠️ Discogs is not configured. Set DISCOGS_TOKEN to enable /add."
        )
        return ConversationHandler.END
    await update.message.reply_text("Enter album name (Artist - Title):")
    context.user_data.clear()
    return SEARCH_INPUT


async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    context.user_data["query"] = query
    context.user_data["page"] = 1
    return await show_results(update, context)


async def show_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not d:
        await update.message.reply_text(
            "⚠️ Discogs is not configured. Set DISCOGS_TOKEN to enable /add."
        )
        return ConversationHandler.END
    page = context.user_data["page"]
    query = context.user_data["query"]
    results = list(d.search(query, type='release').page(page))
    context.user_data["results"] = results

    buttons = [[InlineKeyboardButton(f"{release.title} [{safe_get_format(release)}]"[:60], callback_data=f"select_{i}")] for i, release in enumerate(results)]

    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data="prev"))
    if len(results) == 50:
        nav_buttons.append(InlineKeyboardButton("➡️ Next", callback_data="next"))
    if nav_buttons:
        buttons.append(nav_buttons)

    if update.callback_query:
        await update.callback_query.edit_message_text("Select a release:", reply_markup=InlineKeyboardMarkup(buttons))
    else:
        await update.message.reply_text("Select a release:", reply_markup=InlineKeyboardMarkup(buttons))

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
    context.user_data["release"] = selected
    await update.callback_query.edit_message_text(
        f"Selected: {selected.title}\n\nNow choose vinyl condition:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(c, callback_data=f"cond_{c}") for c in CONDITION_OPTIONS[i:i+4]]
            for i in range(0, len(CONDITION_OPTIONS), 4)
        ])
    )
    return ASK_CONDITION


async def handle_condition_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cond = update.callback_query.data.split("_")[1]
    context.user_data["condition"] = cond
    release = context.user_data["release"]
    suggestions = fetch_price_suggestions(release.id)
    full_condition = {
        "m": "Mint (M)", "nm": "Near Mint (NM or M-)", "vg+": "Very Good Plus (VG+)",
        "vg": "Very Good (VG)", "g+": "Good Plus (G+)", "g": "Good (G)",
        "f": "Fair (F)", "p": "Poor (P)"
    }.get(cond)

    price_usd = suggestions.get(full_condition, {}).get("value", None)
    if price_usd:
        rate = fetch_usd_to_gel()
        price_gel = round(price_usd * rate, 2)
        context.user_data["suggested_price_usd"] = round(price_usd, 2)
        context.user_data["suggested_price_gel"] = price_gel
        msg = f"Suggested price for {full_condition}: ${price_usd:.2f} ≈ {price_gel:.2f} GEL"
    else:
        context.user_data["suggested_price_usd"] = None
        context.user_data["suggested_price_gel"] = None
        msg = "No price suggestion found."

    await update.callback_query.edit_message_text(
        msg + "\n\nSend your own price in GEL or type 'ok' to accept the suggested price."
    )
    return ASK_PRICE


async def handle_price_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text.strip()

    if msg.lower() == "ok" and context.user_data.get("suggested_price_gel") is not None:
        final_price = context.user_data["suggested_price_gel"]
    else:
        try:
            final_price = float(msg)
        except ValueError:
            await update.message.reply_text("❌ Invalid price. Please enter a valid number or 'ok' to accept suggested price:")
            return ASK_PRICE

    context.user_data["final_price"] = round(final_price, 2)
    await update.message.reply_text("How many copies do you want to add?")
    return ASK_QUANTITY


async def handle_quantity_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        qty = int(update.message.text.strip())
        if qty < 1:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Invalid quantity. Enter a whole number ≥ 1:")
        return ASK_QUANTITY

    context.user_data["quantity"] = qty

    suppliers = get_suppliers()
    if suppliers:
        buttons = [[InlineKeyboardButton(name, callback_data=f"sup_{sid}")]
                   for sid, name in suppliers]
        await update.message.reply_text(
            "Select supplier:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    else:
        await update.message.reply_text("Enter supplier name:")

    return ASK_SUPPLIER


async def handle_supplier_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.callback_query:
            query = update.callback_query
            await query.answer()
            if not context.user_data or "release" not in context.user_data:
                await update.effective_message.reply_text(
                    "⚠️ This supplier button is from an old /add session. Run /add again."
                )
                return ConversationHandler.END
            supplier_id = int(query.data.split("_")[1])
            supplier_name = None
            logger.info("Supplier callback received: supplier_id=%s", supplier_id)
        else:
            supplier_name = update.message.text.strip()
            supplier_id = get_or_create_supplier(supplier_name)
            logger.info("Supplier text received: supplier_name=%s", supplier_name)

        release = context.user_data["release"]
        cond = context.user_data["condition"]
        price = context.user_data["final_price"]
        qty = context.user_data["quantity"]

        row = [
            str(release.title),
            safe_join_list(release.genres),
            safe_join_list(release.styles),
            safe_get_labels(release),
            safe_get_format(release),
            str(cond),
            float(price),
            int(qty),
            supplier_id,
        ]

        try:
            inventory_id = save_to_inventory(row)
            logger.info("Inventory saved: inventory_id=%s supplier_id=%s", inventory_id, supplier_id)
            name_display = supplier_name if supplier_name else next(
                (n for i, n in get_suppliers() if i == supplier_id),
                "",
            )
            await update.effective_message.reply_text(
                f"✅ {qty} copy(ies) of '{release.title}' added from {name_display} at {price:.2f} GEL each."
            )

            # --- Woo sync in background (non-blocking) ---
            if woo_is_configured():
                logger.info(
                    "Woo sync starting: inventory_id=%s supplier_id=%s",
                    inventory_id,
                    supplier_id,
                )
                chat_id = update.effective_chat.id if update.effective_chat else None
                app = context.application

                try:
                    product_payload = WooSync(WooConfig.from_env()).build_product_payload(
                        inventory_id=inventory_id,
                        release_id=int(getattr(release, "id", 0) or 0),
                        title=str(release.title),
                        price_gel=float(price),
                        quantity=int(qty),
                        condition=str(cond),
                        supplier_name=name_display or "Unknown",
                        genres=safe_join_list(release.genres),
                        styles=safe_join_list(release.styles),
                        labels=safe_get_labels(release),
                        vinyl_format=safe_get_format(release),
                    )
                except Exception as e:
                    logger.exception("Failed to build Woo payload")
                    await update.effective_message.reply_text(f"🛒 Woo sync FAILED: {e}")
                    return ConversationHandler.END

                async def _run_woo_sync() -> None:
                    try:
                        res = await upsert_product_async(product_payload)
                        pid = res.get("id")
                        if pid:
                            set_inventory_woo_link(inventory_id, int(pid))
                        logger.info("Woo sync OK: inventory_id=%s product_id=%s", inventory_id, pid)
                        if chat_id is not None:
                            await app.bot.send_message(
                                chat_id=chat_id,
                                text=f"🛒 Woo sync OK. Product id: {pid}",
                            )
                    except Exception as e:
                        logger.exception("Woo sync failed")
                        if chat_id is not None:
                            await app.bot.send_message(
                                chat_id=chat_id,
                                text=f"🛒 Woo sync FAILED: {e}",
                            )

                app.create_task(_run_woo_sync())
            else:
                logger.info("Woo env vars not set; skipping Woo sync")
                await update.effective_message.reply_text("🛒 Woo sync skipped (not configured).")
        except Exception as e:
            await update.effective_message.reply_text(f"❌ Error saving to inventory: {str(e)}")
            logger.exception("Error saving inventory row")
            print(f"Error details: {e}")
            print(f"Row data: {row}")
    except Exception:
        logger.exception("Unhandled error in supplier handler")

    return ConversationHandler.END

# Backwards-compatibility: older bot.py versions import this name.
async def orphan_supplier_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle stale supplier callbacks without relying on user_data."""
    if update.callback_query:
        await update.callback_query.answer()
    await update.effective_message.reply_text(
        "⚠️ This supplier button is from an old /add session. Run /add again."
    )
    return ConversationHandler.END

async def cancel_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the add flow from any state."""
    context.user_data.clear()
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("🚫 Add flow cancelled.")
    else:
        await update.message.reply_text("🚫 Add flow cancelled.")
    return ConversationHandler.END

def start_add_flow():
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
        fallbacks=[CommandHandler("cancel", cancel_add)],  # ← crucial
        name="add_record",
        persistent=False,
    )
