from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from db.connection import get_inventory_db
from services.channel_sync_service import reconcile_channel_stock
from services.discogs_sync_service import sync_all_discogs
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
                f"Listings Sync: {_bool_label(settings.get('discogs_listings_enabled'))}",
                callback_data="integrations:discogs:toggle:discogs_listings_enabled",
            )
        ],
        [
            InlineKeyboardButton(
                f"Three-way Sync: {_bool_label(settings.get('three_way_sync_enabled'))}",
                callback_data="integrations:discogs:toggle:three_way_sync_enabled",
            )
        ],
        [
            InlineKeyboardButton(
                "Update Discogs Token" if connected else "Connect Discogs",
                callback_data="integrations:discogs:connect",
            )
        ],
    ]
    return InlineKeyboardMarkup(buttons)


def _sync_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Run Woo sync now", callback_data="integrations:sync:woo_run")],
            [
                InlineKeyboardButton("Reconcile Woo", callback_data="integrations:sync:woo_reconcile"),
                InlineKeyboardButton("Reconcile Discogs", callback_data="integrations:sync:discogs_reconcile"),
            ],
            [InlineKeyboardButton("Sync all Discogs", callback_data="integrations:sync:discogs_all")],
            [
                InlineKeyboardButton("Woo settings", callback_data="integrations:sync:open_woo"),
                InlineKeyboardButton("Discogs settings", callback_data="integrations:sync:open_discogs"),
            ],
            [InlineKeyboardButton("Refresh sync status", callback_data="integrations:sync:status")],
        ]
    )


def _format_sync_menu(store: dict, settings: dict) -> str:
    return (
        "🔄 Sync Menu\n"
        f"• Woo periodic: {_bool_label(settings.get('woo_sync_enabled'))}\n"
        f"• Woo instant: {_bool_label(settings.get('woo_instant_sync_enabled'))}\n"
        f"• Discogs collection: {_bool_label(settings.get('discogs_collection_sync_enabled'))}\n"
        f"• Discogs listings: {_bool_label(settings.get('discogs_listings_enabled'))}\n"
        f"• Three-way sync: {_bool_label(settings.get('three_way_sync_enabled'))}\n"
        f"• Discogs connected: {_bool_label(bool(store.get('discogs_token')), on='YES', off='NO')}"
    )


@require_auth
@require_admin
async def sync_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    store = get_default_store()
    if not store:
        await update.message.reply_text("❌ No store configured. Run /setup_woo first.")
        return
    settings = get_store_settings(int(store["id"]))
    await update.message.reply_text(_format_sync_menu(store, settings), reply_markup=_sync_keyboard())


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
        f"• Listings Sync: {_bool_label(settings.get('discogs_listings_enabled'))}\n"
        f"• Three-way Sync: {_bool_label(settings.get('three_way_sync_enabled'))}\n"
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


def _latest_tri_sync_run(store_id: int, run_type: str) -> dict | None:
    with get_inventory_db() as conn:
        cur = conn.execute(
            """
            SELECT * FROM tri_sync_runs
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
    tri_discogs = _latest_tri_sync_run(store_id, "discogs")
    tri_woo = _latest_tri_sync_run(store_id, "woo")
    counts = (
        f"Pushed: {periodic.get('pushed_count', 0)}, "
        f"Pulled: {periodic.get('pulled_count', 0)}, "
        f"Created: {periodic.get('created_local_count', 0)}, "
        f"Mapping fixed: {periodic.get('mapping_fixed_count', 0)}, "
        f"Incoming: {periodic.get('incoming_count', 0)}, "
        f"Drifted: {periodic.get('drifted_count', 0)}, "
        f"Conflicts: {periodic.get('conflict_count', 0)}"
        if periodic
        else "No periodic sync data yet."
    )
    tri_discogs_counts = (
        f"Incoming: {tri_discogs.get('incoming_count', 0)}, "
        f"Applied: {tri_discogs.get('applied_count', 0)}, "
        f"Drifted: {tri_discogs.get('drifted_count', 0)}, "
        f"Conflicts: {tri_discogs.get('conflict_count', 0)}"
        if tri_discogs
        else "no runs"
    )
    tri_woo_counts = (
        f"Incoming: {tri_woo.get('incoming_count', 0)}, "
        f"Applied: {tri_woo.get('applied_count', 0)}, "
        f"Drifted: {tri_woo.get('drifted_count', 0)}, "
        f"Conflicts: {tri_woo.get('conflict_count', 0)}"
        if tri_woo
        else "no runs"
    )
    last_error = periodic.get("last_error") if periodic and periodic.get("last_error") else "none"
    text = (
        "📊 Sync Status\n"
        f"• Last periodic sync: {periodic_line}\n"
        f"• Last instant sync: {instant_line}\n"
        f"• Last order processed: {last_order_line}\n"
        f"• Webhook last received: {webhook_received}\n"
        f"• Webhook last processed: {webhook_processed}\n"
        f"• Three-way Discogs: {tri_discogs.get('ts_finished') if tri_discogs else 'never'} ({tri_discogs_counts})\n"
        f"• Three-way Woo: {tri_woo.get('ts_finished') if tri_woo else 'never'} ({tri_woo_counts})\n"
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

    if section == "sync":
        if action == "woo_run":
            await run_blocking(SyncEngine().run_manual_sync, store_id)
        elif action == "woo_reconcile":
            await run_blocking(reconcile_channel_stock, store_id, channel="woo")
        elif action == "discogs_reconcile":
            await run_blocking(reconcile_channel_stock, store_id, channel="discogs")
        elif action == "discogs_all":
            await run_blocking(sync_all_discogs, store_id, publish_missing=True)
        elif action == "open_woo":
            try:
                await query.edit_message_text(_format_woo_status(store_id, settings), reply_markup=_woo_keyboard(settings))
            except BadRequest as exc:
                if "Message is not modified" not in str(exc):
                    raise
            return
        elif action == "open_discogs":
            connected = bool(store.get("discogs_token"))
            try:
                await query.edit_message_text(
                    _format_discogs_status(store, settings),
                    reply_markup=_discogs_keyboard(settings, connected),
                )
            except BadRequest as exc:
                if "Message is not modified" not in str(exc):
                    raise
            return

        settings = get_store_settings(store_id)
        refreshed_store = get_default_store() or store
        try:
            await query.edit_message_text(
                _format_sync_menu(refreshed_store, settings),
                reply_markup=_sync_keyboard(),
            )
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
        return


def create_integrations_handlers() -> list:
    return [
        CommandHandler("integrations_woo", integrations_woo),
        CommandHandler("integrations_discogs", integrations_discogs),
        CommandHandler("sync", sync_menu),
        CommandHandler("sync_status", sync_status),
        CommandHandler("backups", backups_status),
        CallbackQueryHandler(handle_integrations_callback, pattern=r"^integrations:"),
    ]
