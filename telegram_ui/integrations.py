from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from db.connection import get_inventory_db
from services.runtime import run_blocking
from services.store_service import get_default_store, get_store_settings, update_store_settings
from services.sync_engine import SyncEngine
from services.woo_service import is_configured
from telegram_ui.auth import require_admin, require_auth


def _bool_label(value: bool, on: str = "ON", off: str = "OFF") -> str:
    return on if value else off


def _woo_keyboard(settings: dict) -> InlineKeyboardMarkup:
    strategy = (settings.get("woo_sync_strategy") or "lww").lower()
    def _strategy_label(value: str, label: str) -> str:
        return f"✅ {label}" if strategy == value else label

    buttons = [
        [
            InlineKeyboardButton(
                f"Periodic Sync: {_bool_label(settings.get('woo_sync_enabled'))}",
                callback_data="integrations:woo:toggle:woo_sync_enabled",
            )
        ],
        [
            InlineKeyboardButton(
                f"Instant Sync: {_bool_label(settings.get('woo_instant_sync_enabled'))}",
                callback_data="integrations:woo:toggle:woo_instant_sync_enabled",
            )
        ],
        [
            InlineKeyboardButton(
                f"Orders Auto-Decrement: {_bool_label(settings.get('auto_decrement_enabled'))}",
                callback_data="integrations:woo:toggle:auto_decrement_enabled",
            )
        ],
        [
            InlineKeyboardButton(
                f"Orders Notifications: {_bool_label(settings.get('orders_admin_notifications'))}",
                callback_data="integrations:woo:toggle:orders_admin_notifications",
            )
        ],
        [
            InlineKeyboardButton(_strategy_label("lww", "Last-write-wins"), callback_data="integrations:woo:strategy:lww"),
            InlineKeyboardButton(_strategy_label("woo", "Woo wins"), callback_data="integrations:woo:strategy:woo"),
        ],
        [
            InlineKeyboardButton(_strategy_label("local", "Local wins"), callback_data="integrations:woo:strategy:local"),
        ],
        [
            InlineKeyboardButton("Run sync now", callback_data="integrations:woo:run_sync"),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


def _discogs_keyboard(settings: dict, connected: bool) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                f"Collection Sync: {_bool_label(settings.get('discogs_collection_sync_enabled'))}",
                callback_data="integrations:discogs:toggle:discogs_collection_sync_enabled",
            )
        ],
        [
            InlineKeyboardButton(
                "Update Discogs Token" if connected else "Connect Discogs",
                callback_data="integrations:discogs:connect",
            )
        ],
        [
            InlineKeyboardButton(
                "Listings Sync (coming soon)",
                callback_data="integrations:discogs:coming_soon",
            )
        ],
    ]
    return InlineKeyboardMarkup(buttons)


def _format_woo_status(store_id: int, settings: dict) -> str:
    connected = is_configured(store_id)
    return (
        "🛒 WooCommerce\n"
        f"Status: {'Connected' if connected else 'Not connected'}\n"
        f"• Periodic Sync: {_bool_label(settings.get('woo_sync_enabled'))}\n"
        f"• Instant Sync: {_bool_label(settings.get('woo_instant_sync_enabled'))}\n"
        f"• Orders Auto-Decrement: {_bool_label(settings.get('auto_decrement_enabled'))}\n"
        f"• Orders Notifications: {_bool_label(settings.get('orders_admin_notifications'))}\n"
        f"• Strategy: {(settings.get('woo_sync_strategy') or 'lww').upper()}\n"
    )


def _format_discogs_status(store: dict, settings: dict) -> str:
    connected = bool(store.get("discogs_token"))
    return (
        "💿 Discogs\n"
        f"Status: {'Connected' if connected else 'Not connected'}\n"
        f"• Collection Sync: {_bool_label(settings.get('discogs_collection_sync_enabled'))}\n"
        "• Listings Sync: coming soon\n"
    )


@require_auth
@require_admin
async def integrations_woo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    store = get_default_store()
    if not store:
        await update.message.reply_text("❌ No store configured. Run /setup_woo first.")
        return
    settings = get_store_settings(int(store["id"]))
    await update.message.reply_text(_format_woo_status(int(store["id"]), settings), reply_markup=_woo_keyboard(settings))


@require_auth
@require_admin
async def integrations_discogs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    store = get_default_store()
    if not store:
        await update.message.reply_text("❌ No store configured. Run /setup_woo first.")
        return
    settings = get_store_settings(int(store["id"]))
    connected = bool(store.get("discogs_token"))
    await update.message.reply_text(
        _format_discogs_status(store, settings),
        reply_markup=_discogs_keyboard(settings, connected),
    )


def _latest_sync_run(store_id: int, run_type: str) -> dict | None:
    with get_inventory_db() as conn:
        cur = conn.execute(
            """
            SELECT * FROM sync_runs
            WHERE store_id = ? AND run_type = ?
            ORDER BY ts_started DESC
            LIMIT 1
            """,
            (store_id, run_type),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def _latest_backup(backup_type: str) -> dict | None:
    with get_inventory_db() as conn:
        cur = conn.execute(
            """
            SELECT * FROM backup_runs
            WHERE backup_type = ?
            ORDER BY ts_started DESC
            LIMIT 1
            """,
            (backup_type,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


@require_auth
@require_admin
async def sync_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    store = get_default_store()
    if not store:
        await update.message.reply_text("❌ No store configured. Run /setup_woo first.")
        return
    store_id = int(store["id"])
    periodic = _latest_sync_run(store_id, "periodic")
    instant = _latest_sync_run(store_id, "instant")
    with get_inventory_db() as conn:
        cur = conn.execute("SELECT MAX(inventory_applied_at) AS last_applied FROM orders WHERE store_id = ?", (store_id,))
        last_order = cur.fetchone()
        cur = conn.execute("SELECT MAX(received_at) AS last_received, MAX(processed_at) AS last_processed FROM webhook_events WHERE store_id = ?", (store_id,))
        webhook = cur.fetchone()

    periodic_line = f"{periodic.get('ts_finished') if periodic else 'never'}"
    instant_line = f"{instant.get('ts_finished') if instant else 'never'}"
    last_order_line = last_order["last_applied"] if last_order and last_order["last_applied"] else "never"
    webhook_received = webhook["last_received"] if webhook and webhook["last_received"] else "never"
    webhook_processed = webhook["last_processed"] if webhook and webhook["last_processed"] else "never"
    counts = (
        f"Pushed: {periodic.get('pushed_count', 0)}, "
        f"Pulled: {periodic.get('pulled_count', 0)}, "
        f"Created: {periodic.get('created_local_count', 0)}, "
        f"Mapping fixed: {periodic.get('mapping_fixed_count', 0)}"
        if periodic
        else "No periodic sync data yet."
    )
    last_error = periodic.get("last_error") if periodic and periodic.get("last_error") else "none"
    text = (
        "📊 Sync Status\n"
        f"• Last periodic sync: {periodic_line}\n"
        f"• Last instant sync: {instant_line}\n"
        f"• Last order processed: {last_order_line}\n"
        f"• Webhook last received: {webhook_received}\n"
        f"• Webhook last processed: {webhook_processed}\n"
        "• Queue length: 0\n"
        f"• Last periodic counts: {counts}\n"
        f"• Last error: {last_error}\n"
    )
    await update.message.reply_text(text)


@require_auth
@require_admin
async def backups_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rolling = _latest_backup("rolling")
    daily = _latest_backup("daily")
    rolling_line = f"{rolling.get('ts_finished')} ({rolling.get('status')})" if rolling else "never"
    daily_line = f"{daily.get('ts_finished')} ({daily.get('status')})" if daily else "never"
    next_rolling = "within 15 minutes"
    next_daily = "within 24 hours"
    text = (
        "🗄️ Backups\n"
        f"• Last rolling backup: {rolling_line}\n"
        f"• Last daily backup: {daily_line}\n"
        f"• Next rolling backup: {next_rolling}\n"
        f"• Next daily backup: {next_daily}\n"
        "• Retention: rolling 24 hours, daily 30 days\n"
        "• Location: ./backups\n"
    )
    await update.message.reply_text(text)


@require_auth
@require_admin
async def handle_integrations_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data.split(":")
    if len(data) < 3:
        return
    store = get_default_store()
    if not store:
        await query.edit_message_text("❌ No store configured. Run /setup_woo first.")
        return
    store_id = int(store["id"])
    settings = get_store_settings(store_id)
    section = data[1]
    action = data[2]

    if section == "woo":
        if action == "toggle" and len(data) == 4:
            key = data[3]
            current = bool(settings.get(key))
            settings = update_store_settings(store_id, {key: not current})
        elif action == "strategy" and len(data) == 4:
            settings = update_store_settings(store_id, {"woo_sync_strategy": data[3]})
        elif action == "run_sync":
            await run_blocking(SyncEngine().run_manual_sync, store_id)
            settings = get_store_settings(store_id)
        try:
            await query.edit_message_text(_format_woo_status(store_id, settings), reply_markup=_woo_keyboard(settings))
        except BadRequest as exc:
            if "Message is not modified" not in str(exc):
                raise
        return

    if section == "discogs":
        if action == "toggle" and len(data) == 4:
            key = data[3]
            current = bool(settings.get(key))
            settings = update_store_settings(store_id, {key: not current})
            connected = bool(store.get("discogs_token"))
            try:
                await query.edit_message_text(
                    _format_discogs_status(store, settings),
                    reply_markup=_discogs_keyboard(settings, connected),
                )
            except BadRequest as exc:
                if "Message is not modified" not in str(exc):
                    raise
        elif action == "coming_soon":
            await query.answer("Listings sync is coming soon.", show_alert=True)
        return


def create_integrations_handlers() -> list:
    return [
        CommandHandler("integrations_woo", integrations_woo),
        CommandHandler("integrations_discogs", integrations_discogs),
        CommandHandler("sync_status", sync_status),
        CommandHandler("backups", backups_status),
        CallbackQueryHandler(handle_integrations_callback, pattern=r"^integrations:"),
    ]
