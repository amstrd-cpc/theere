from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from config.settings import load_settings
from jobs.worker_tasks import sync_order_state
from services.order_service import get_order_by_woo_id, list_recent_orders, upsert_order_snapshot
from services.runtime import run_blocking
from services.store_service import get_default_store
from services.ui_session_service import create_callback_session, inject_session
from services.woo_service import fetch_order_by_id, update_order_status
from telegram_ui.auth import auth_manager, require_admin, require_auth
from telegram_ui.session_guard import validate_callback_or_reject


@require_auth
@require_admin
async def list_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store = get_default_store()
    if not store:
        await update.message.reply_text("❌ No store configured. Run /setup_woo first.")
        return

    orders = list_recent_orders(int(store["id"]), limit=10)
    if not orders:
        await update.message.reply_text("No recent orders found.")
        return

    session = create_callback_session(user_id=update.effective_user.id, expected_node="orders", expected_state="listing")
    session_token = str(session["session_token"])
    context.user_data["orders_session_token"] = session_token

    buttons = []
    lines = ["🧾 Recent Orders:"]
    for order in orders:
        woo_id = order.get("woo_order_id")
        status = order.get("status") or "unknown"
        total = order.get("total") or ""
        lines.append(f"• #{woo_id} ({status}) {total}")
        buttons.append([InlineKeyboardButton(f"View #{woo_id}", callback_data=inject_session(f"order:view:{woo_id}", session_token))])

    await update.message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons))


async def order_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()

    ok, data = await validate_callback_or_reject(update, context, expected_node="orders")
    if not ok:
        return

    user_id = query.from_user.id if query.from_user else None
    if user_id is None:
        return
    if not await run_blocking(auth_manager.is_authenticated, user_id):
        await query.edit_message_text("🔒 Authentication required.")
        return
    settings = load_settings()
    if settings.admin_ids and user_id not in settings.admin_ids:
        await query.edit_message_text("🚫 Admin access required for this action.")
        return

    parts = data.split(":")
    if len(parts) < 3:
        return

    action = parts[1]
    woo_order_id = int(parts[2])

    store = get_default_store()
    if not store:
        await query.edit_message_text("❌ No store configured.")
        return

    if action == "view":
        await _show_order(query, store, woo_order_id, context.user_data.get("orders_session_token", ""))
    elif action == "status":
        new_status = parts[3] if len(parts) > 3 else ""
        await _update_status(query, store, woo_order_id, new_status)


async def _show_order(query, store: dict, woo_order_id: int, session_token: str) -> None:
    order = get_order_by_woo_id(int(store["id"]), woo_order_id)
    if not order:
        fresh = fetch_order_by_id(store, woo_order_id)
        if fresh:
            upsert_order_snapshot(int(store["id"]), fresh)
            order = get_order_by_woo_id(int(store["id"]), woo_order_id)

    if not order:
        await query.edit_message_text("Order not found.")
        return

    status = order.get("status") or "unknown"
    text = (
        f"Order #{woo_order_id}\n"
        f"Status: {status}\n"
        f"Total: {order.get('total') or ''} {order.get('currency') or ''}\n"
        f"Customer: {order.get('billing_name') or ''}\n"
    )

    buttons = [
        [InlineKeyboardButton("Pending → Processing", callback_data=inject_session(f"order:status:{woo_order_id}:processing", session_token))],
        [InlineKeyboardButton("Processing → Completed", callback_data=inject_session(f"order:status:{woo_order_id}:completed", session_token))],
        [InlineKeyboardButton("Processing → On-hold", callback_data=inject_session(f"order:status:{woo_order_id}:on-hold", session_token))],
        [InlineKeyboardButton("Cancel", callback_data=inject_session(f"order:status:{woo_order_id}:cancelled", session_token))],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))


async def _update_status(query, store: dict, woo_order_id: int, new_status: str) -> None:
    if not new_status:
        await query.edit_message_text("Invalid status.")
        return
    updated = update_order_status(store, woo_order_id, new_status)
    if not updated:
        await query.edit_message_text("Failed to update status.")
        return
    upsert_order_snapshot(int(store["id"]), updated)
    await run_blocking(sync_order_state, int(store["id"]), woo_order_id)
    await query.edit_message_text(f"✅ Order #{woo_order_id} updated to {new_status}.")


def create_orders_handler() -> CommandHandler:
    return CommandHandler("orders", list_orders)


def create_orders_callback_handler() -> CallbackQueryHandler:
    return CallbackQueryHandler(order_callback, pattern=r"^order:")
