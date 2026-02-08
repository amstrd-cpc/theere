from __future__ import annotations

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from services.product_map_service import upsert_product_map
from services.store_service import get_default_store
from telegram_ui.auth import require_admin, require_auth


@require_auth
@require_admin
async def map_woo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store = get_default_store()
    if not store:
        await update.message.reply_text("❌ No store configured. Run /setup_woo first.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /map_woo <woo_product_id> <internal_id> [sku]")
        return

    try:
        woo_product_id = int(context.args[0])
        internal_id = int(context.args[1])
    except ValueError:
        await update.message.reply_text("IDs must be numeric.")
        return

    sku = context.args[2] if len(context.args) > 2 else None
    upsert_product_map(
        store_id=int(store["id"]),
        internal_product_id=internal_id,
        woo_product_id=woo_product_id,
        sku=sku,
    )
    await update.message.reply_text("✅ Mapping saved.")


def create_map_handler() -> CommandHandler:
    return CommandHandler("map_woo", map_woo)
