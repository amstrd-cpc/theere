from __future__ import annotations

import json
import secrets
from typing import Dict

from telegram import Update
from telegram.ext import CommandHandler, ConversationHandler, ContextTypes, MessageHandler, filters

from config.settings import load_settings
from services.store_service import create_store, get_default_store, update_store_webhook_ids
from services.woo_service import create_webhook, list_webhooks, validate_credentials
from telegram_ui.auth import require_admin, require_auth

ASK_STORE_NAME, ASK_STORE_URL, ASK_CONSUMER_KEY, ASK_CONSUMER_SECRET = range(4)


def _normalize_store_url(value: str) -> str:
    return value.strip().rstrip("/")


@require_auth
@require_admin
async def start_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Enter store name (e.g., My Record Store):")
    return ASK_STORE_NAME


@require_auth
@require_admin
async def store_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["store_name"] = update.message.text.strip()
    await update.message.reply_text("Enter store URL (e.g., https://example.com):")
    return ASK_STORE_URL


@require_auth
@require_admin
async def store_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["store_url"] = _normalize_store_url(update.message.text)
    await update.message.reply_text("Enter WooCommerce consumer key:")
    return ASK_CONSUMER_KEY


@require_auth
@require_admin
async def consumer_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["consumer_key"] = update.message.text.strip()
    await update.message.reply_text("Enter WooCommerce consumer secret:")
    return ASK_CONSUMER_SECRET


@require_auth
@require_admin
async def consumer_secret(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store_name = context.user_data.get("store_name", "")
    store_url = context.user_data.get("store_url", "")
    consumer_key = context.user_data.get("consumer_key", "")
    consumer_secret = update.message.text.strip()

    temp_store = {
        "store_url": store_url,
        "woo_consumer_key": consumer_key,
        "woo_consumer_secret": consumer_secret,
    }

    if not validate_credentials(temp_store):
        await update.message.reply_text("❌ WooCommerce credentials invalid. Please /setup_woo again.")
        return ConversationHandler.END

    settings = load_settings()
    if not settings.api_base_url:
        await update.message.reply_text("⚠️ API_BASE_URL missing. Set it before creating webhooks.")
        return ConversationHandler.END

    webhook_secret = secrets.token_hex(32)
    store_id = create_store(
        store_name=store_name,
        store_url=store_url,
        consumer_key=consumer_key,
        consumer_secret=consumer_secret,
        webhook_secret=webhook_secret,
    )

    delivery_url = f"{settings.api_base_url.rstrip('/')}/webhooks/woo/{store_id}"
    webhook_ids: Dict[str, int] = {}
    for topic in ["order.created", "order.updated"]:
        name = f"Record Store Bot {topic}"
        webhook = create_webhook(temp_store, name=name, topic=topic, delivery_url=delivery_url, secret=webhook_secret)
        if webhook and webhook.get("id"):
            webhook_ids[topic] = int(webhook["id"])

    update_store_webhook_ids(store_id, webhook_ids)

    await update.message.reply_text(
        "✅ WooCommerce connected. Webhooks created. Use /settings to review triggers.")
    return ConversationHandler.END


async def cancel_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚫 Setup cancelled.")
    return ConversationHandler.END


@require_auth
@require_admin
async def repair_webhooks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store = get_default_store()
    if not store:
        await update.message.reply_text("❌ No store configured. Run /setup_woo first.")
        return

    webhook_ids = {}
    if store.get("webhook_ids"):
        try:
            webhook_ids = json.loads(store["webhook_ids"])
        except json.JSONDecodeError:
            webhook_ids = {}

    existing = {str(item.get("id")): item for item in list_webhooks(store)}
    settings = load_settings()
    if not settings.api_base_url:
        await update.message.reply_text("⚠️ API_BASE_URL missing. Set it before creating webhooks.")
        return

    delivery_url = f"{settings.api_base_url.rstrip('/')}/webhooks/woo/{store['id']}"
    updated = False
    for topic in ["order.created", "order.updated"]:
        webhook_id = webhook_ids.get(topic)
        if webhook_id and str(webhook_id) in existing:
            continue
        name = f"Record Store Bot {topic}"
        webhook = create_webhook(store, name=name, topic=topic, delivery_url=delivery_url, secret=store["webhook_secret"])
        if webhook and webhook.get("id"):
            webhook_ids[topic] = int(webhook["id"])
            updated = True

    if updated:
        update_store_webhook_ids(int(store["id"]), webhook_ids)
        await update.message.reply_text("✅ Webhooks repaired.")
    else:
        await update.message.reply_text("✅ Webhooks healthy. No changes needed.")


def create_setup_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("setup_woo", start_setup), CommandHandler("connect", start_setup)],
        states={
            ASK_STORE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, store_name)],
            ASK_STORE_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, store_url)],
            ASK_CONSUMER_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, consumer_key)],
            ASK_CONSUMER_SECRET: [MessageHandler(filters.TEXT & ~filters.COMMAND, consumer_secret)],
        },
        fallbacks=[CommandHandler("cancel", cancel_setup)],
        name="setup_woo",
        persistent=False,
    )


def create_repair_handler() -> CommandHandler:
    return CommandHandler("repair_webhooks", repair_webhooks)
