from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from services.runtime import ServiceTimeoutError, run_blocking
from services.store_service import get_default_store
from services.woo_import_service import get_latest_import_summary, import_woo_products
from telegram_ui.auth import require_admin, require_auth


@require_auth
@require_admin
async def trigger_woo_import(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    store = get_default_store()
    if not store:
        await update.message.reply_text("❌ No store configured. Run /setup_woo first.")
        return
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("I understand", callback_data="woo_import:ack")],
            [InlineKeyboardButton("Cancel", callback_data="woo_import:cancel")],
        ]
    )
    await update.message.reply_text(
        "⚠️ This will import Woo products and update local inventory based on mapping rules.\n"
        "Step 1/2: Acknowledge to continue.",
        reply_markup=keyboard,
    )


@require_auth
@require_admin
async def handle_woo_import_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data or ""

    if data == "woo_import:cancel":
        await query.edit_message_text("❌ Woo import cancelled.")
        return

    if data == "woo_import:ack":
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("✅ Confirm import now", callback_data="woo_import:run")],
                [InlineKeyboardButton("Cancel", callback_data="woo_import:cancel")],
            ]
        )
        await query.edit_message_text(
            "Step 2/2: Confirm to run Woo import now.",
            reply_markup=keyboard,
        )
        return

    if data != "woo_import:run":
        return

    store = get_default_store()
    if not store:
        await query.edit_message_text("❌ No store configured. Run /setup_woo first.")
        return

    await query.edit_message_text("🔄 Running Woo import...")
    try:
        summary = await run_blocking(import_woo_products, store_id=int(store["id"]), notify=True, timeout=300.0)
    except ServiceTimeoutError:
        await query.edit_message_text("⚠️ Woo import is taking too long. Please retry or reduce catalog size.")
        return
    await query.edit_message_text(
        "✅ Woo import complete.\n"
        f"• created: {summary.get('created', 0)}\n"
        f"• updated: {summary.get('updated', 0)}\n"
        f"• skipped: {summary.get('skipped', 0)}\n"
        f"• conflicts: {summary.get('conflicts', 0)}\n"
        f"• manual_needed: {summary.get('manual_needed', 0)}"
    )


@require_auth
@require_admin
async def woo_import_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    store = get_default_store()
    if not store:
        await update.message.reply_text("❌ No store configured. Run /setup_woo first.")
        return
    summary = await run_blocking(get_latest_import_summary, int(store["id"]))
    if not summary:
        await update.message.reply_text("ℹ️ No Woo import runs yet.")
        return
    await update.message.reply_text(
        "📦 Last Woo Import\n"
        f"• at: {summary.get('ts_finished') or summary.get('ts_started')}\n"
        f"• created: {summary.get('created_count', 0)}\n"
        f"• updated: {summary.get('updated_count', 0)}\n"
        f"• skipped: {summary.get('skipped_count', 0)}\n"
        f"• conflicts: {summary.get('conflict_count', 0)}\n"
        f"• manual_needed: {summary.get('manual_needed_count', 0)}"
    )


def create_woo_import_handlers() -> list:
    return [
        CommandHandler("import_woo", trigger_woo_import),
        CommandHandler("woo_import_summary", woo_import_summary),
        CallbackQueryHandler(handle_woo_import_callback, pattern=r"^woo_import:"),
    ]
