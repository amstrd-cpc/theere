from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from services.discogs_sync_service import bootstrap_collection_import
from services.inventory_service import inventory_is_empty
from services.runtime import run_blocking
from services.store_service import get_default_store, get_store_settings, update_store_settings
from services.sync_engine import SyncEngine
from telegram_ui.auth import require_admin, require_auth


def bootstrap_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🛒 WooCommerce", callback_data="bootstrap:woo"),
                InlineKeyboardButton("💿 Discogs", callback_data="bootstrap:discogs"),
            ],
            [InlineKeyboardButton("🔀 Merge both", callback_data="bootstrap:merge")],
        ]
    )


@require_auth
@require_admin
async def handle_bootstrap_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    store = get_default_store()
    if not store:
        await query.edit_message_text("❌ No store configured. Run /setup_woo first.")
        return
    store_id = int(store["id"])
    settings = get_store_settings(store_id)
    if settings.get("bootstrap_completed"):
        await query.edit_message_text("✅ Bootstrap already completed.")
        return
    if not await run_blocking(inventory_is_empty):
        await query.edit_message_text("ℹ️ Inventory already has data; bootstrap skipped.")
        await run_blocking(update_store_settings, store_id, {"bootstrap_completed": True})
        return

    action = (query.data or "").split(":", 1)[1] if ":" in (query.data or "") else ""
    await query.edit_message_text("🔄 Bootstrapping inventory. This may take a few minutes...")
    results = {"woo": None, "discogs": None}
    if action in {"woo", "merge"}:
        results["woo"] = await run_blocking(
            SyncEngine().reconcile_catalog,
            store_id,
            initial_load=True,
            timeout=300.0,
        )
    if action in {"discogs", "merge"}:
        results["discogs"] = await run_blocking(
            bootstrap_collection_import,
            store_id,
            timeout=300.0,
        )
    await run_blocking(update_store_settings, store_id, {"bootstrap_completed": True})

    summary = ["✅ Bootstrap completed."]
    if results["woo"] is not None:
        summary.append(
            "🛒 WooCommerce import: "
            f"created={results['woo'].get('created_local_count', 0)} "
            f"pulled={results['woo'].get('pulled_count', 0)}"
        )
    if results["discogs"] is not None:
        summary.append(
            "💿 Discogs import: "
            f"imported={results['discogs'].get('imported', 0)} "
            f"updated={results['discogs'].get('updated', 0)}"
        )
    await query.edit_message_text("\n".join(summary))


def create_bootstrap_handlers() -> list:
    return [
        CallbackQueryHandler(handle_bootstrap_choice, pattern=r"^bootstrap:"),
    ]
