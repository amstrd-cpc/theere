from __future__ import annotations

from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from config.settings import load_settings
from services.runtime import run_blocking
from services.store_service import get_default_store, get_store_settings
from telegram_ui.callback_contract import NavigationCallback, parse_navigation_callback
from telegram_ui.menu_registry import ROOT_MENU_ID, get_menu_definition


async def _is_navigation_router_enabled() -> bool:
    global_default = load_settings().nav_router_enabled
    store = await run_blocking(get_default_store)
    if not store:
        return global_default
    store_settings = await run_blocking(get_store_settings, int(store["id"]))
    return bool(store_settings.get("nav_router_enabled", global_default))


def _build_command_update_from_callback(update: Update, command: str, bot) -> Update:
    query = update.callback_query
    message = query.message.to_dict() if query and query.message else {}
    message["text"] = command
    message["entities"] = [{"type": "bot_command", "offset": 0, "length": len(command)}]
    payload = {"update_id": update.update_id, "message": message}
    return Update.de_json(payload, bot)


async def _dispatch_callback_target(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    callback: NavigationCallback,
) -> None:
    definition = get_menu_definition(callback.target)
    if not definition:
        await update.callback_query.answer("Unknown menu target", show_alert=False)
        return

    if callback.action == "back" and definition.parent_id:
        parent = get_menu_definition(definition.parent_id)
        definition = parent or definition
    elif callback.action == "back":
        definition = get_menu_definition(ROOT_MENU_ID) or definition

    if not definition.command_target:
        await update.callback_query.answer("Menu container selected", show_alert=False)
        return

    synthetic_update = _build_command_update_from_callback(update, definition.command_target, context.bot)
    await context.application.process_update(synthetic_update)
    await update.callback_query.answer()


async def handle_navigation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return

    callback = parse_navigation_callback(query.data)
    if not callback:
        await query.answer("Unsupported navigation callback", show_alert=False)
        return

    if not await _is_navigation_router_enabled():
        await query.answer("New menu router is disabled", show_alert=False)
        return

    await _dispatch_callback_target(update, context, callback)


def create_navigation_callback_handler() -> CallbackQueryHandler:
    return CallbackQueryHandler(handle_navigation_callback, pattern=r"^nav:")
