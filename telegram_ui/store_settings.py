from __future__ import annotations

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
    text = (
        "⚙️ Store Settings\n"
        f"• Auto decrement: {settings.get('auto_decrement_enabled')}\n"
        f"• Trigger status: {settings.get('auto_decrement_status')}\n"
        f"• Discogs sync: {settings.get('discogs_sync_on_sale')}\n"
        f"• Discogs price sync: {settings.get('discogs_price_sync')}\n"
        f"• Discogs polling: {settings.get('discogs_polling_enabled')}\n"
        f"• Discogs interval: {settings.get('discogs_polling_interval_minutes')} min\n"
        f"• Notification chat: {settings.get('notification_chat_id') or 'default'}\n\n"
        "Update with: /settings auto_decrement on|off, /settings status <status>, "
        "/settings discogs on|off, /settings discogs_price on|off, "
        "/settings discogs_poll on|off, /settings discogs_interval <minutes>, "
        "/settings notify <chat_id>"
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
    elif key in {"discogs_interval", "discogs_polling_interval"}:
        try:
            updates["discogs_polling_interval_minutes"] = int(value)
        except ValueError:
            await update.message.reply_text("Interval must be numeric minutes.")
            return
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
