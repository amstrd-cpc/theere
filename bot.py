#!/usr/bin/env python3
"""
Protected Record Store Telegram Bot
All functions require authentication with password
"""

import asyncio
import base64
import datetime
import hashlib
import hmac
import json
import logging
import re
from threading import Thread
import os
import requests
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes, JobQueue
from dotenv import load_dotenv

load_dotenv()

# Import your existing modules
from auth import auth_manager, require_auth, create_auth_handlers, check_auth_middleware
from add_record import start_add_flow, orphan_supplier_callback
from sales import start_sell_flow
from inventory import create_inventory_conversation, create_inventory_edit_conversation, register_inventory_callbacks
from db import get_db, init_db
import inventory as inventory_utils
import reports
from woocommerce_client import WooNotConfigured, fetch_orders, is_configured
from woocommerce_sync import sync_inventory_to_woo
from config import ADMIN_CHAT_ID, BOT_TOKEN


ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def escape_markdown_v2(text: str) -> str:
    """
    Escape MarkdownV2 special characters
    """
    if not isinstance(text, str):
        text = str(text)
    escape_chars = r"_*[]()~`>#+-=|{}.!\\"
    return re.sub(f"([{re.escape(escape_chars)}])", r"\\\1", text)

# === Protected Command Handlers ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command - always accessible"""
    user = update.effective_user
    welcome_message = (
        f"🎵 *Welcome to the Record Store Bot\\!* 🎵\n\n"
        f"Hello {escape_markdown_v2(user.first_name)}\\!\n\n"
        f"🔒 *This bot is password protected\\.*\n"
        f"You must authenticate before using any commands\\.\n\n"
        f"*Commands:*\n"
        f"• /login \\- Enter password to authenticate\n"
        f"• /help \\- Show this help message\n\n"
        f"After authentication, you'll have access to:\n"
        f"• /add \\- Add new records to inventory\n"
        f"• /sell \\- Process record sales\n"
        f"• /inventory \\- Search and view inventory\n"
        f"• /reports \\- Generate sales reports\n"
        f"• /status \\- Check authentication status\n"
        f"• /logout \\- Sign out\n\n"
        f"🔐 *Use /login to get started\\!*"
    )
    
    await update.message.reply_text(welcome_message, parse_mode="MarkdownV2")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command - always accessible"""
    user_id = update.effective_user.id
    
    if auth_manager.is_authenticated(user_id):
        help_text = (
            "🎵 *Record Store Bot \\- Commands* 🎵\n\n"
            "*Inventory Management:*\n"
            "• /add \\- Add new records from Discogs\n"
            "• /inventory \\- Interactive inventory search\n"
            "• /stock \\- View low stock items\n\n"
            "*Sales:*\n"
            "• /sell \\- Process a sale\n"
            "• /sales \\- View recent sales\n\n"
            "*Reports:*\n"
            "• /reports \\- Generate sales reports\n"
            "• /daily \\- Today's sales summary\n"
            "• /weekly \\- Weekly sales report\n"
            "• /monthly \\- Monthly sales report\n\n"
            "*Account:*\n"
            "• /status \\- Check authentication status\n"
            "• /logout \\- Sign out\n"
            "• /users \\- View active users \\(admin\\)\n\n"
            "*General:*\n"
            "• /help \\- Show this help\n"
            "• /cancel \\- Cancel current operation"
        )
    else:
        help_text = (
            "🔒 *Authentication Required* 🔒\n\n"
            "*Available Commands:*\n"
            "• /login \\- Enter password to authenticate\n"
            "• /help \\- Show this help\n"
            "• /start \\- Welcome message\n\n"
            "*After authentication, you'll have access to:*\n"
            "• Inventory management\n"
            "• Sales processing\n"
            "• Report generation\n"
            "• And much more\\!\n\n"
            "🔐 *Use /login to get started\\!*"
        )
    
    await update.message.reply_text(help_text, parse_mode="MarkdownV2")

@require_auth
async def recent_sales(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show recent sales - requires authentication"""
    sales = reports.get_recent_sales(limit=10)
    
    if not sales:
        await update.message.reply_text("📊 No recent sales found\\.", parse_mode="MarkdownV2")
        return
    
    message = "💰 *Recent Sales*\n\n"
    for sale in sales:
        # Escape the artist_album field for MarkdownV2
        safe_artist_album = escape_markdown_v2(str(sale['artist_album']))
        safe_payment_method = escape_markdown_v2(str(sale['payment_method']))
        safe_date = escape_markdown_v2(str(sale['date']))
        price = sale['price_gel']
        
        message += (
            f"🎵 {safe_artist_album}\n"
            f"💰 ₾{price:.2f} \\({safe_payment_method}\\)\n"
            f"📅 {safe_date}\n\n"
        )
    
    await update.message.reply_text(message, parse_mode="MarkdownV2")

@require_auth
async def daily_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate daily sales report with Excel - requires authentication"""
    try:
        file_path, summary = reports.generate_daily_excel_report()
        await update.message.reply_text(summary, parse_mode="Markdown")
        with open(file_path, "rb") as f:
            await update.message.reply_document(document=f, filename=os.path.basename(file_path), caption="📊 Daily Sales Report")
    except FileNotFoundError:
        await update.message.reply_text("📭 No sales recorded for today yet.")
    except Exception as e:
        await update.message.reply_text(
            f"❌ Error generating daily report: {escape_markdown_v2(str(e))}",
            parse_mode="MarkdownV2",
        )

@require_auth
async def weekly_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate weekly sales report with Excel - requires authentication"""
    try:
        file_path, summary = reports.generate_weekly_excel_report()
        await update.message.reply_text(summary, parse_mode="Markdown")
        with open(file_path, "rb") as f:
            await update.message.reply_document(document=f, filename=os.path.basename(file_path), caption="📊 Weekly Sales Report")
    except FileNotFoundError:
        await update.message.reply_text("📭 No sales recorded for this week yet.")
    except Exception as e:
        await update.message.reply_text(
            f"❌ Error generating weekly report: {escape_markdown_v2(str(e))}",
            parse_mode="MarkdownV2",
        )

@require_auth
async def monthly_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate monthly sales report with Excel - requires authentication"""
    try:
        file_path, summary = reports.generate_monthly_excel_report()
        await update.message.reply_text(summary, parse_mode="Markdown")
        with open(file_path, "rb") as f:
            await update.message.reply_document(document=f, filename=os.path.basename(file_path), caption="📊 Monthly Sales Report")
    except FileNotFoundError:
        await update.message.reply_text("📭 No sales recorded for this month yet.")
    except Exception as e:
        await update.message.reply_text(
            f"❌ Error generating monthly report: {escape_markdown_v2(str(e))}",
            parse_mode="MarkdownV2",
        )

async def unauthorized_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle messages from unauthorized users"""
    if not await check_auth_middleware(update, context):
        return  # Auth check already sent the denial message

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error("Exception while handling an update:", exc_info=context.error)


# === WooCommerce Webhook Helpers ===
def init_woo_orders_table():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
                CREATE TABLE IF NOT EXISTS woo_orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER UNIQUE,
                    processed_at TEXT
                )
            """
        )
        conn.commit()


def is_order_processed(order_id: int) -> bool:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM woo_orders WHERE order_id = ?", (order_id,))
        return cursor.fetchone() is not None


def mark_order_processed(order_id: int):
    now = datetime.datetime.now(datetime.UTC).isoformat()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO woo_orders (order_id, processed_at) VALUES (?, ?)",
            (order_id, now),
        )
        conn.commit()


def process_woo_order(order: dict) -> dict:
    """
    Process a WooCommerce order payload.

    Behavior:
    - Idempotent: uses woo_orders table to avoid double-processing.
    - Matches Woo line_items to local inventory rows by SKU == inventory.id.
    - Automatically records the sale in the local DB (sales table) and decrements local stock.

    Returns a dict with processed information for notification.
    """
    order_id = order.get("id")
    if not order_id:
        return {"order_id": None, "already_processed": False, "items": [], "unmatched": []}

    status = (order.get("status") or "").lower().strip()
    # Only treat these as "real" sales. Webhooks/polling can fire for other statuses.
    eligible_statuses = {"processing", "completed"}

    if is_order_processed(order_id):
        return {
            "order_id": order_id,
            "status": status,
            "payment_method": order.get("payment_method"),
            "billing_name": f"{order.get('billing', {}).get('first_name', '')} {order.get('billing', {}).get('last_name', '')}".strip(),
            "items": [],
            "unmatched": [],
            "currency": order.get("currency"),
            "order_total": order.get("total"),
            "already_processed": True,
            "skipped": False,
        }

    if status and status not in eligible_statuses:
        # Not a status we want to auto-sell on. Don't mark as processed so it can be processed later
        # when it transitions to processing/completed.
        return {
            "order_id": order_id,
            "status": status,
            "payment_method": order.get("payment_method"),
            "billing_name": f"{order.get('billing', {}).get('first_name', '')} {order.get('billing', {}).get('last_name', '')}".strip(),
            "items": [],
            "unmatched": [],
            "currency": order.get("currency"),
            "order_total": order.get("total"),
            "already_processed": False,
            "skipped": True,
            "skip_reason": f"Order status '{status}' is not eligible for auto-sell.",
        }

    items = []
    unmatched = []

    order_date = order.get("date_created", "").split("T")[0] or datetime.date.today().isoformat()
    payment_method = order.get("payment_method") or "woo"

    now_iso = datetime.datetime.now(datetime.UTC).isoformat()

    for li in order.get("line_items", []):
        sku = li.get("sku")
        qty = li.get("quantity", 1)

        if not sku:
            unmatched.append(li)
            continue

        try:
            item_id = int(sku)
        except (TypeError, ValueError):
            unmatched.append(li)
            continue

        inv = inventory_utils.get_inventory_by_id(item_id)
        if not inv:
            unmatched.append(li)
            continue

        # Calculate unit price
        try:
            if li.get("price") is not None:
                per_price = float(li["price"])
            else:
                per_price = float(li.get("total", 0)) / max(int(qty or 1), 1)
        except Exception:
            per_price = 0.0

        # Decrement local inventory atomically.
        if not inventory_utils.reduce_inventory_quantity(item_id, int(qty or 1)):
            # Keep it in unmatched so you see it immediately in Telegram.
            unmatched.append(li)
            continue

        # Insert ONE ROW PER UNIT SOLD (current schema doesn't store quantity in sales).
        # This keeps totals and item counts correct in your reports.
        with get_db() as conn:
            c = conn.cursor()
            for _ in range(int(qty or 1)):
                c.execute(
                    """
                    INSERT INTO sales (
                        date, artist_album, genre, style, label, format,
                        condition, price_gel, supplier_id, payment_method
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        order_date,
                        inv.get("artist_album"),
                        inv.get("genre"),
                        inv.get("style"),
                        inv.get("label"),
                        inv.get("format"),
                        inv.get("condition"),
                        per_price,
                        inv.get("supplier_id"),
                        payment_method,
                    ),
                )

            # Mark the inventory row as "synced" since Woo is the source of truth for this sale.
            try:
                c.execute(
                    """
                    UPDATE inventory
                    SET woo_synced = 1, woo_last_synced_at = ?
                    WHERE id = ?
                    """,
                    (now_iso, item_id),
                )
            except Exception:
                # If inventory table isn't present (old schema), ignore.
                pass

            conn.commit()

        # Optional: legacy report hook (kept for compatibility; in optimized version it's a no-op)
        try:
            log_sale_to_report_db({
                "date": order_date,
                "artist_album": inv.get("artist_album"),
                "genre": inv.get("genre"),
                "style": inv.get("style"),
                "label": inv.get("label"),
                "format": inv.get("format"),
                "condition": inv.get("condition"),
                "price_gel": per_price,
                "supplier": inv.get("supplier"),
                "payment_method": payment_method,
            })
        except Exception:
            pass

        items.append((inv, int(qty or 1), per_price))

    # Mark order processed only after we attempted to apply it.
    # Even if some line items were unmatched, we still mark it to avoid repeated decrements for matched items.
    mark_order_processed(order_id)

    return {
        "order_id": order_id,
        "status": status,
        "payment_method": payment_method,
        "billing_name": f"{order.get('billing', {}).get('first_name', '')} {order.get('billing', {}).get('last_name', '')}".strip(),
        "items": items,
        "unmatched": unmatched,
        "currency": order.get("currency"),
        "order_total": order.get("total"),
        "already_processed": False,
        "skipped": False,
    }


def send_woo_order_notification(info: dict):
    """Send a Telegram message to admin chat about Woo order."""
    if not ADMIN_CHAT_ID:
        return

    order_id = info.get("order_id")
    status = info.get("status") or "unknown"
    payment = info.get("payment_method") or "unknown"
    billing_name = info.get("billing_name") or "N/A"
    currency = info.get("currency") or ""
    total = info.get("order_total") or "0"
    items = info.get("items", [])
    unmatched = info.get("unmatched", [])
    already = info.get("already_processed", False)

    lines = []

    skipped = info.get("skipped", False)
    skip_reason = info.get("skip_reason")

    if already:
        lines.append("(Already processed)")

    if skipped:
        lines.append("(Auto-sell skipped)")
        if skip_reason:
            lines.append(f"Reason: {skip_reason}")

    lines.append(f"New Woo order #{order_id}")
    lines.append(f"Status: {status}")
    lines.append(f"Payment: {payment}")
    lines.append(f"Customer: {billing_name}")
    lines.append("")
    lines.append("Items:")

    if not items:
        lines.append("- (none)")
    else:
        for inv, qty, price in items:
            lines.append(f"- {inv['artist_album']} x{qty} – {price} {currency} (id {inv['id']})")

    if unmatched:
        lines.append("")
        lines.append("Unmatched items:")
        for u in unmatched:
            lines.append(f"- {u.get('name', 'Unknown')} x{u.get('quantity')} (SKU {u.get('sku')})")

    lines.append("")
    if (not already) and (not skipped) and items:
        lines.append("✅ Sale recorded locally (inventory + sales updated).")
    elif (not already) and (not skipped) and (not items):
        lines.append("⚠️ No items were recorded locally.")

    lines.append(f"Order total: {total} {currency}")

    text = "\n".join(lines)

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": ADMIN_CHAT_ID, "text": text})


def backfill_recent_woo_orders(hours: int = 24):
    """Poll WooCommerce for recent orders to ensure we didn't miss any webhooks."""
    if not is_configured():
        return

    after = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=hours)).isoformat()

    page = 1

    try:
        while True:
            orders = fetch_orders(
                statuses=["processing", "completed"],
                after=after,
                page=page,
                per_page=50,
            )
            if not orders:
                break

            for order in orders:
                info = process_woo_order(order)
                if info.get("already_processed"):
                    continue
                send_woo_order_notification(info)

            if len(orders) < 50:
                break
            page += 1
    except WooNotConfigured:
        print("WooCommerce not configured; skipping Woo order backfill.")
    except Exception as e:
        print(f"Error while backfilling Woo orders: {e}")


async def poll_recent_woo_orders_job(context: ContextTypes.DEFAULT_TYPE):
    """Periodic job to backfill/poll Woo orders without requiring webhooks."""

    # Offload to a thread so we don't block the event loop if Woo is slow
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, backfill_recent_woo_orders, 6)


# === Flask Webhook App ===
app = Flask(__name__)


def verify_wc_signature(raw_body: bytes, header_sig: str, secret: str) -> bool:
    """
    Verify WooCommerce HMAC-SHA256 signature if header is present.
    Header is base64 encoded.
    """
    if not header_sig:
        return True
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(expected, header_sig)


@app.route("/wc-webhook/<secret>", methods=["POST"])
def woo_webhook(secret):
    expected_secret = os.getenv("WOO_WEBHOOK_SECRET")
    if not expected_secret or secret != expected_secret:
        return ("Forbidden", 403)

    raw = request.get_data()
    header_sig = request.headers.get("X-WC-Webhook-Signature", "")

    if header_sig and not verify_wc_signature(raw, header_sig, expected_secret):
        return ("Invalid signature", 401)

    try:
        order = json.loads(raw.decode("utf-8"))
    except Exception:
        return ("Bad JSON", 400)

    info = process_woo_order(order)
    send_woo_order_notification(info)
    if info.get("already_processed"):
        return (json.dumps({"status": "already_processed"}), 200, {"Content-Type": "application/json"})
    else:
        return (json.dumps({"status": "ok"}), 200, {"Content-Type": "application/json"})


def run_webhook_server():
    port = int(os.getenv("WEBHOOK_PORT", "32412"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

def main():
    """Main function to run the bot"""
    # Ensure required tables exist
    init_db()
    reports.init_report_db()
    init_woo_orders_table()
    # Idempotent diff-based Woo sync (safe across restarts; avoids duplicates)
    sync_inventory_to_woo()
    # Ensure any recent Woo orders are reflected locally in case a webhook was missed
    backfill_recent_woo_orders(hours=24)
    # Create application with JobQueue enabled for scheduled tasks
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .job_queue(JobQueue())
        .build()
    )

    # Periodically poll WooCommerce for orders in case webhooks are not firing
    # Check the last ~6 hours every 5 minutes to catch missed sales
    if application.job_queue:
        application.job_queue.run_repeating(
            poll_recent_woo_orders_job,
            interval=datetime.timedelta(minutes=5),
            first=datetime.timedelta(minutes=2),
            name="woo-order-poll",
        )
    else:
        logger.warning(
            "JobQueue unavailable; install python-telegram-bot[job-queue] to enable Woo polling."
        )
    
    # Add authentication handlers (these don't require auth)
    auth_handlers = create_auth_handlers()
    for handler in auth_handlers:
        application.add_handler(handler)
    
    # Add always-accessible commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(reports.report_handler())
    
    # Add protected command handlers
    application.add_handler(CommandHandler("sales", recent_sales))
    application.add_handler(CommandHandler("daily", daily_report))
    application.add_handler(CommandHandler("weekly", weekly_report))
    application.add_handler(CommandHandler("monthly", monthly_report))
    
    # Add conversation handlers (these have their own auth checks)
    application.add_handler(start_add_flow())
    # Fallback: catch stale supplier inline buttons (e.g., clicked after /add ended or bot restart)
    application.add_handler(
        CallbackQueryHandler(orphan_supplier_callback, pattern=r"^sup_\d+$"),
        group=1,
    )
    application.add_handler(start_sell_flow())
    application.add_handler(create_inventory_conversation())
    register_inventory_callbacks(application)
    
    # Add fallback handler for unauthorized access
    application.add_handler(MessageHandler(filters.ALL, unauthorized_handler))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Cleanup expired sessions on startup
    auth_manager.cleanup_expired_sessions()

    # Start webhook HTTP server in background
    webhook_thread = Thread(target=run_webhook_server, daemon=True)
    webhook_thread.start()

    # Start the bot
    logger.info("🤖 Starting protected record store bot...")
    logger.info(f"🔒 Session timeout: {os.getenv('SESSION_TIMEOUT_HOURS', '24')} hours")

    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
