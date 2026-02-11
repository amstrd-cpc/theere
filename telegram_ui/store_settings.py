from __future__ import annotations

import json

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from services.store_service import get_default_store, get_store_settings, update_store_settings
from telegram_ui.auth import require_admin, require_auth


@require_auth
@require_admin
async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store = get_default_store()
    if not store:
        await update.message.reply_text("❌ No store configured. Run /setup_woo first.")
        return

    if context.args:
        await _apply_settings(update, context, int(store["id"]))
        return

    settings = get_store_settings(int(store["id"]))
    webhook_ids = {}
    if store.get("webhook_ids"):
        try:
            webhook_ids = json.loads(store["webhook_ids"])
        except json.JSONDecodeError:
            webhook_ids = {}
    webhook_count = len([value for value in webhook_ids.values() if value])
    woo_connected = bool(store.get("woo_consumer_key") and store.get("woo_consumer_secret"))
    discogs_connected = bool(store.get("discogs_token"))
    text = (
        "⚙️ Store Settings\n\n"
        "🏪 Store\n"
        f"• Store ID: {store.get('id')}\n"
        f"• Name: {store.get('store_name') or 'unnamed'}\n"
        f"• URL: {store.get('store_url')}\n"
        f"• Enabled: {bool(store.get('is_enabled'))}\n"
        f"• Created: {store.get('created_at')}\n"
        f"• Updated: {store.get('updated_at')}\n\n"
        "🔌 Integrations & Status\n"
        f"• Woo connected: {woo_connected}\n"
        f"• Woo webhooks configured: {webhook_count} active\n"
        f"• Discogs connected: {discogs_connected}\n"
        f"• Discogs user: {store.get('discogs_username') or 'not set'}\n"
        f"• Discogs last sync: {store.get('discogs_last_sync_at') or 'never'}\n\n"
        "🔄 Sync Settings\n"
        f"• Auto decrement: {settings.get('auto_decrement_enabled')}\n"
        f"• Trigger status: {settings.get('auto_decrement_status')}\n"
        f"• Discogs sync on sale: {settings.get('discogs_sync_on_sale')}\n"
        f"• Discogs price sync: {settings.get('discogs_price_sync')}\n"
        f"• Discogs polling: {settings.get('discogs_polling_enabled')}\n"
        f"• Discogs interval: {settings.get('discogs_polling_interval_minutes')} min\n"
        f"• Discogs listings enabled: {settings.get('discogs_listings_enabled')}\n"
        f"• Three-way sync: {settings.get('three_way_sync_enabled')}\n"
        f"• 3-way Discogs interval: {settings.get('three_way_discogs_interval_minutes')} min\n"
        f"• 3-way Woo interval: {settings.get('three_way_woo_interval_minutes')} min\n"
        f"• Woo incoming allowed: {settings.get('woo_allow_incoming')}\n"
        f"• Discogs incoming allowed: {settings.get('discogs_allow_incoming')}\n"
        f"• Woo incoming fields: {settings.get('woo_incoming_fields')}\n"
        f"• Discogs incoming fields: {settings.get('discogs_incoming_fields')}\n"
        f"• Bootstrap completed: {settings.get('bootstrap_completed')}\n"
        f"• Notification chat: {settings.get('notification_chat_id') or 'default'}\n"
        f"• Verify SSL: {settings.get('verify_ssl')}\n"
        f"• Nav router enabled: {settings.get('nav_router_enabled')}\n\n"
        "Update with: /settings auto_decrement on|off, /settings status <status>, "
        "/settings discogs on|off, /settings discogs_price on|off, "
        "/settings discogs_poll on|off, /settings discogs_interval <minutes>, /settings discogs_listings on|off, "
        "/settings three_way on|off, /settings three_way_discogs_interval <minutes>, "
        "/settings three_way_woo_interval <minutes>, /settings woo_incoming on|off, "
        "/settings discogs_incoming on|off, /settings nav_router on|off, /settings notify <chat_id>"
    )
    await update.message.reply_text(text)


async def _apply_settings(update: Update, context: ContextTypes.DEFAULT_TYPE, store_id: int) -> None:
    key = context.args[0].lower()
    value = context.args[1] if len(context.args) > 1 else ""

    updates = {}
    if key in {"auto_decrement", "auto"}:
        updates["auto_decrement_enabled"] = value.lower() in {"on", "true", "1", "yes"}
    elif key in {"status", "trigger"}:
        updates["auto_decrement_status"] = value.lower()
    elif key in {"discogs", "discogs_sync"}:
        updates["discogs_sync_on_sale"] = value.lower() in {"on", "true", "1", "yes"}
    elif key in {"discogs_price", "discogs_price_sync"}:
        updates["discogs_price_sync"] = value.lower() in {"on", "true", "1", "yes"}
    elif key in {"discogs_poll", "discogs_polling"}:
        updates["discogs_polling_enabled"] = value.lower() in {"on", "true", "1", "yes"}
    elif key in {"discogs_listings", "discogs_listings_enabled"}:
        updates["discogs_listings_enabled"] = value.lower() in {"on", "true", "1", "yes"}
    elif key in {"discogs_interval", "discogs_polling_interval"}:
        try:
            updates["discogs_polling_interval_minutes"] = int(value)
        except ValueError:
            await update.message.reply_text("Interval must be numeric minutes.")
            return
    elif key in {"three_way", "three_way_sync"}:
        updates["three_way_sync_enabled"] = value.lower() in {"on", "true", "1", "yes"}
    elif key in {"three_way_discogs_interval", "three_way_discogs_polling_interval"}:
        try:
            updates["three_way_discogs_interval_minutes"] = int(value)
        except ValueError:
            await update.message.reply_text("Interval must be numeric minutes.")
            return
    elif key in {"three_way_woo_interval", "three_way_woo_polling_interval"}:
        try:
            updates["three_way_woo_interval_minutes"] = int(value)
        except ValueError:
            await update.message.reply_text("Interval must be numeric minutes.")
            return
    elif key in {"woo_incoming", "woo_allow_incoming"}:
        updates["woo_allow_incoming"] = value.lower() in {"on", "true", "1", "yes"}
    elif key in {"discogs_incoming", "discogs_allow_incoming"}:
        updates["discogs_allow_incoming"] = value.lower() in {"on", "true", "1", "yes"}
    elif key in {"nav_router", "navigation_router", "new_menu_router"}:
        updates["nav_router_enabled"] = value.lower() in {"on", "true", "1", "yes"}
    elif key in {"notify", "notification"}:
        try:
            updates["notification_chat_id"] = int(value) if value else None
        except ValueError:
            await update.message.reply_text("Chat ID must be numeric.")
            return
    else:
        await update.message.reply_text("Unknown setting. Use /settings for help.")
        return

    new_settings = update_store_settings(store_id, updates)
    await update.message.reply_text(f"✅ Settings updated: {new_settings}")


def create_settings_handler() -> CommandHandler:
    return CommandHandler("settings", settings_command)
