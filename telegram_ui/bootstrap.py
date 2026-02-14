from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from services.discogs_sync_service import bootstrap_collection_import
from services.runtime import run_blocking
from services.store_service import (
    complete_bootstrap_transition,
    get_default_store,
    get_store_settings,
    transition_bootstrap_to_running,
)
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

    started, reason = await run_blocking(transition_bootstrap_to_running, store_id)
    if not started:
        message = "ℹ️ Bootstrap skipped."
        if reason == "already_bootstrapping":
            message = "⏳ Bootstrap already in progress."
        elif reason == "already_completed":
            message = "✅ Bootstrap already completed."
        elif reason == "inventory_non_empty_requires_reset":
            message = "🛑 Inventory is non-empty. Admin reset flow is required before re-bootstrap."
        elif reason == "store_missing":
            message = "❌ Store not found."
        await query.edit_message_text(message)
        return

    action = (query.data or "").split(":", 1)[1] if ":" in (query.data or "") else ""
    await query.edit_message_text("🔄 Bootstrapping inventory. This may take a few minutes...")
    results = {"woo": None, "discogs": None}
    success = False
    try:
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
        success = True
    finally:
        await run_blocking(complete_bootstrap_transition, store_id, success=success)

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
