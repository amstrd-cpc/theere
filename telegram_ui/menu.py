from __future__ import annotations

import re

from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters

from services.runtime import run_blocking
from telegram_ui import messages
from telegram_ui.auth import auth_manager
from telegram_ui.keyboards import (
    BACK_TO_DISCOGS,
    BACK_TO_MAIN,
    BACK_TO_SETTINGS,
    BACK_TO_SHOP,
    BACK_TO_WOO,
    DISCOGS_MENU_CONNECTION_ACTIONS,
    DISCOGS_MENU_CONNECT,
    DISCOGS_MENU_LINK,
    DISCOGS_MENU_PUBLISH,
    DISCOGS_MENU_PUBLISH_ACTIONS,
    DISCOGS_MENU_PUBLISH_ALL,
    DISCOGS_MENU_PUBLISH_SELECTION,
    DISCOGS_MENU_COLLECTION,
    DISCOGS_MENU_COLLECTION_SELECTION,
    DISCOGS_MENU_RECONCILE,
    DISCOGS_MENU_REFRESH,
    DISCOGS_MENU_STATUS,
    DISCOGS_MENU_SYNC_ACTIONS,
    DISCOGS_MENU_SYNC_ALL,
    DISCOGS_MENU_UNLINK,
    MAIN_MENU_DISCOGS,
    MAIN_MENU_SETTINGS,
    MAIN_MENU_SHOP,
    MAIN_MENU_WOO,
    SETTINGS_MENU_ACCOUNT_ACTIONS,
    SETTINGS_MENU_HELP,
    SETTINGS_MENU_LOGOUT,
    SETTINGS_MENU_CANCEL,
    SETTINGS_MENU_STATUS,
    SETTINGS_MENU_START,
    SETTINGS_MENU_SUPPORT_ACTIONS,
    SETTINGS_MENU_USERS,
    SHOP_MENU_INVENTORY_ACTIONS,
    SHOP_MENU_REPORTS_ACTIONS,
    SHOP_MENU_SALES_ACTIONS,
    SHOP_MENU_ADD,
    SHOP_MENU_DAILY,
    SHOP_MENU_INVENTORY,
    SHOP_MENU_LOW_STOCK,
    SHOP_MENU_MONTHLY,
    SHOP_MENU_RECENT_SALES,
    SHOP_MENU_REPORTS,
    SHOP_MENU_SELL,
    SHOP_MENU_WEEKLY,
    WOO_MENU_AUTO_MAP,
    WOO_MENU_CONNECT,
    WOO_MENU_MAPPING_ACTIONS,
    WOO_MENU_MAP,
    WOO_MENU_ORDERS_ACTIONS,
    WOO_MENU_ORDERS,
    WOO_MENU_SETUP_ACTIONS,
    WOO_MENU_RECONCILE,
    WOO_MENU_REPAIR_WEBHOOKS,
    WOO_MENU_SETTINGS,
    WOO_MENU_SETUP,
    build_discogs_connection_menu,
    build_discogs_menu,
    build_discogs_publish_menu,
    build_discogs_sync_menu,
    build_main_menu,
    build_settings_account_menu,
    build_settings_menu,
    build_settings_support_menu,
    build_shop_inventory_menu,
    build_shop_menu,
    build_shop_reports_menu,
    build_shop_sales_menu,
    build_woo_mapping_menu,
    build_woo_menu,
    build_woo_orders_menu,
    build_woo_setup_menu,
)

MENU_COMMANDS = {
    SHOP_MENU_ADD: "/add",
    SHOP_MENU_SELL: "/sell",
    SHOP_MENU_INVENTORY: "/inventory",
    SHOP_MENU_LOW_STOCK: "/stock",
    SHOP_MENU_RECENT_SALES: "/sales",
    SHOP_MENU_REPORTS: "/reports",
    SHOP_MENU_DAILY: "/daily",
    SHOP_MENU_WEEKLY: "/weekly",
    SHOP_MENU_MONTHLY: "/monthly",
    WOO_MENU_ORDERS: "/orders",
    WOO_MENU_SETUP: "/setup_woo",
    WOO_MENU_CONNECT: "/connect",
    WOO_MENU_SETTINGS: "/settings",
    WOO_MENU_MAP: "/map_woo",
    WOO_MENU_AUTO_MAP: "/auto_map_woo",
    WOO_MENU_REPAIR_WEBHOOKS: "/repair_webhooks",
    WOO_MENU_RECONCILE: "/reconcile_woo",
    DISCOGS_MENU_CONNECT: "/connect_discogs",
    DISCOGS_MENU_STATUS: "/discogs_status",
    DISCOGS_MENU_PUBLISH: "/publish_discogs",
    DISCOGS_MENU_PUBLISH_ALL: "/publish_discogs_all",
    DISCOGS_MENU_PUBLISH_SELECTION: "/publish_discogs_selection",
    DISCOGS_MENU_COLLECTION: "/collect_discogs",
    DISCOGS_MENU_COLLECTION_SELECTION: "/collect_discogs_selection",
    DISCOGS_MENU_LINK: "/link_discogs",
    DISCOGS_MENU_UNLINK: "/unlink_discogs",
    DISCOGS_MENU_RECONCILE: "/reconcile_discogs",
    DISCOGS_MENU_REFRESH: "/discogs_refresh",
    DISCOGS_MENU_SYNC_ALL: "/sync_discogs_all",
    SETTINGS_MENU_STATUS: "/status",
    SETTINGS_MENU_USERS: "/users",
    SETTINGS_MENU_HELP: "/help",
    SETTINGS_MENU_START: "/start",
    SETTINGS_MENU_CANCEL: "/cancel",
    SETTINGS_MENU_LOGOUT: "/logout",
}

SUBMENUS = {
    MAIN_MENU_SHOP: (build_shop_menu, messages.SHOP_MENU_PROMPT),
    SHOP_MENU_INVENTORY_ACTIONS: (build_shop_inventory_menu, messages.SHOP_INVENTORY_MENU_PROMPT),
    SHOP_MENU_SALES_ACTIONS: (build_shop_sales_menu, messages.SHOP_SALES_MENU_PROMPT),
    SHOP_MENU_REPORTS_ACTIONS: (build_shop_reports_menu, messages.SHOP_REPORTS_MENU_PROMPT),
    MAIN_MENU_WOO: (build_woo_menu, messages.WOO_MENU_PROMPT),
    WOO_MENU_SETUP_ACTIONS: (build_woo_setup_menu, messages.WOO_SETUP_MENU_PROMPT),
    WOO_MENU_ORDERS_ACTIONS: (build_woo_orders_menu, messages.WOO_ORDERS_MENU_PROMPT),
    WOO_MENU_MAPPING_ACTIONS: (build_woo_mapping_menu, messages.WOO_MAPPING_MENU_PROMPT),
    MAIN_MENU_DISCOGS: (build_discogs_menu, messages.DISCOGS_MENU_PROMPT),
    DISCOGS_MENU_CONNECTION_ACTIONS: (build_discogs_connection_menu, messages.DISCOGS_CONNECTION_MENU_PROMPT),
    DISCOGS_MENU_PUBLISH_ACTIONS: (build_discogs_publish_menu, messages.DISCOGS_PUBLISH_MENU_PROMPT),
    DISCOGS_MENU_SYNC_ACTIONS: (build_discogs_sync_menu, messages.DISCOGS_SYNC_MENU_PROMPT),
    MAIN_MENU_SETTINGS: (build_settings_menu, messages.SETTINGS_MENU_PROMPT),
    SETTINGS_MENU_ACCOUNT_ACTIONS: (build_settings_account_menu, messages.SETTINGS_ACCOUNT_MENU_PROMPT),
    SETTINGS_MENU_SUPPORT_ACTIONS: (build_settings_support_menu, messages.SETTINGS_SUPPORT_MENU_PROMPT),
}

PUBLIC_COMMANDS = {"/login", "/help", "/start", "/cancel"}
BACK_TARGETS = {
    BACK_TO_MAIN: (build_main_menu, messages.MAIN_MENU_PROMPT, False),
    BACK_TO_SHOP: (build_shop_menu, messages.SHOP_MENU_PROMPT, True),
    BACK_TO_WOO: (build_woo_menu, messages.WOO_MENU_PROMPT, True),
    BACK_TO_DISCOGS: (build_discogs_menu, messages.DISCOGS_MENU_PROMPT, True),
    BACK_TO_SETTINGS: (build_settings_menu, messages.SETTINGS_MENU_PROMPT, True),
}


def _build_command_update(update: Update, command: str, bot) -> Update:
    payload = update.to_dict()
    message = payload.get("message") or {}
    message["text"] = command
    message["entities"] = [{"type": "bot_command", "offset": 0, "length": len(command)}]
    payload["message"] = message
    return Update.de_json(payload, bot)


async def handle_menu_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    user_id = update.effective_user.id
    is_authed = await run_blocking(auth_manager.is_authenticated, user_id)

    if text in BACK_TARGETS:
        builder, prompt, requires_auth = BACK_TARGETS[text]
        if requires_auth and not is_authed:
            await update.message.reply_text(
                messages.AUTH_REQUIRED_MARKDOWN,
                parse_mode="Markdown",
                reply_markup=build_main_menu(False),
            )
            return
        await update.message.reply_text(
            prompt,
            reply_markup=builder(is_authed) if builder is build_main_menu else builder(),
        )
        return

    submenu = SUBMENUS.get(text)
    if submenu:
        if not is_authed:
            await update.message.reply_text(
                messages.AUTH_REQUIRED_MARKDOWN,
                parse_mode="Markdown",
                reply_markup=build_main_menu(False),
            )
            return
        builder, prompt = submenu
        await update.message.reply_text(prompt, reply_markup=builder())
        return

    command = MENU_COMMANDS.get(text)
    if not command:
        return

    if command not in PUBLIC_COMMANDS and not is_authed:
        await update.message.reply_text(
            messages.AUTH_REQUIRED_MARKDOWN,
            parse_mode="Markdown",
            reply_markup=build_main_menu(False),
        )
        return

    command_update = _build_command_update(update, command, context.bot)
    await context.application.process_update(command_update)


def create_menu_handler() -> MessageHandler:
    options = set(SUBMENUS.keys()) | set(MENU_COMMANDS.keys()) | set(BACK_TARGETS.keys())
    pattern = r"^(?:%s)$" % "|".join(re.escape(option) for option in sorted(options))
    return MessageHandler(filters.Regex(re.compile(pattern)), handle_menu_selection)
