from __future__ import annotations

import datetime
import json

from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from config.settings import load_settings
from services.runtime import run_blocking
from services.store_service import get_default_store
from telegram_ui.callback_contract import NavigationCallback, parse_navigation_callback
from telegram_ui.session_guard import validate_callback_or_reject
from telegram_ui.menus.main import build_inline_menu, get_command_target, get_menu


async def _is_navigation_router_enabled() -> bool:
    global_default = load_settings().nav_router_enabled
    if not global_default:
        return False

    store = await run_blocking(get_default_store)
    if not store:
        return True

    raw_settings = store.get("settings_json")
    if not raw_settings:
        return True

    try:
        parsed_settings = json.loads(raw_settings)
    except (TypeError, json.JSONDecodeError):
        return True

    if "nav_router_enabled" not in parsed_settings:
        return True

    return bool(parsed_settings.get("nav_router_enabled"))


def _build_command_update_from_callback(update: Update, command: str, bot) -> Update:
    query = update.callback_query
    message = query.message.to_dict() if query and query.message else {}
    if query and query.from_user:
        message["from"] = query.from_user.to_dict()

    if query and query.message and query.message.chat:
        message["chat"] = query.message.chat.to_dict()

    message.setdefault("message_id", query.message.message_id if query and query.message else 0)
    message["date"] = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    message["text"] = command
    message["entities"] = [{"type": "bot_command", "offset": 0, "length": len(command)}]
    payload = {"update_id": update.update_id, "message": message}
    return Update.de_json(payload, bot)


async def _dispatch_callback_target(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    callback: NavigationCallback,
) -> None:
    try:
        if callback.action in {"menu", "back"}:
            menu = get_menu(callback.target)
            target_menu = menu
            if callback.action == "back":
                target_menu = get_menu(menu.parent_id) if menu.parent_id else get_menu("main")
            user_id = update.callback_query.from_user.id if update.callback_query and update.callback_query.from_user else None
            text, markup = build_inline_menu(target_menu.menu_id, user_id=user_id)
            context.user_data["active_menu_id"] = target_menu.menu_id
            await update.callback_query.edit_message_text(text=text, reply_markup=markup)
            await update.callback_query.answer()
            return

        if callback.action == "command":
            command = get_command_target(callback.target)
            if not command:
                await update.callback_query.answer("Unknown command", show_alert=False)
                return
            synthetic_update = _build_command_update_from_callback(update, command, context.bot)
            await context.application.process_update(synthetic_update)
            await update.callback_query.answer()
            return
    except KeyError:
        await update.callback_query.answer("Unknown menu target", show_alert=False)
        return

    await update.callback_query.answer("Unsupported callback action", show_alert=False)


async def handle_navigation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return

    ok, normalized_data = await validate_callback_or_reject(
        update,
        context,
        expected_node=f"nav:{context.user_data.get('active_menu_id', 'main')}",
        expected_state="menu",
    )
    if not ok:
        return
    callback = parse_navigation_callback(normalized_data)
    if not callback:
        await query.answer("Unsupported navigation callback", show_alert=False)
        return

    if not await _is_navigation_router_enabled():
        await query.answer("New menu router is disabled", show_alert=False)
        return

    await _dispatch_callback_target(update, context, callback)


def create_navigation_callback_handler() -> CallbackQueryHandler:
    return CallbackQueryHandler(handle_navigation_callback, pattern=r"^nav:")
