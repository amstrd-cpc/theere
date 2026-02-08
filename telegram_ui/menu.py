from __future__ import annotations

import re

from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters

from services.runtime import run_blocking
from telegram_ui import messages
from telegram_ui.auth import auth_manager
from telegram_ui.keyboards import (
    BACK_BUTTON,
    DISCOGS_MENU_CONNECT,
    DISCOGS_MENU_LINK,
    DISCOGS_MENU_PUBLISH,
    DISCOGS_MENU_RECONCILE,
    DISCOGS_MENU_REFRESH,
    DISCOGS_MENU_STATUS,
    DISCOGS_MENU_UNLINK,
    MAIN_MENU_DISCOGS,
    MAIN_MENU_SETTINGS,
    MAIN_MENU_SHOP,
    MAIN_MENU_WOO,
    SETTINGS_MENU_HELP,
    SETTINGS_MENU_LOGOUT,
    SETTINGS_MENU_STATUS,
    SETTINGS_MENU_USERS,
    SHOP_MENU_ADD,
    SHOP_MENU_DAILY,
    SHOP_MENU_INVENTORY,
    SHOP_MENU_LOW_STOCK,
    SHOP_MENU_MONTHLY,
    SHOP_MENU_RECENT_SALES,
    SHOP_MENU_REPORTS,
    SHOP_MENU_SELL,
    SHOP_MENU_WEEKLY,
    WOO_MENU_MAP,
    WOO_MENU_ORDERS,
    WOO_MENU_RECONCILE,
    WOO_MENU_REPAIR_WEBHOOKS,
    WOO_MENU_SETTINGS,
    WOO_MENU_SETUP,
    build_discogs_menu,
    build_main_menu,
    build_settings_menu,
    build_shop_menu,
    build_woo_menu,
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
    WOO_MENU_SETTINGS: "/settings",
    WOO_MENU_MAP: "/map_woo",
    WOO_MENU_REPAIR_WEBHOOKS: "/repair_webhooks",
    WOO_MENU_RECONCILE: "/reconcile_woo",
    DISCOGS_MENU_CONNECT: "/connect_discogs",
    DISCOGS_MENU_STATUS: "/discogs_status",
    DISCOGS_MENU_PUBLISH: "/publish_discogs",
    DISCOGS_MENU_LINK: "/link_discogs",
    DISCOGS_MENU_UNLINK: "/unlink_discogs",
    DISCOGS_MENU_RECONCILE: "/reconcile_discogs",
    DISCOGS_MENU_REFRESH: "/discogs_refresh",
    SETTINGS_MENU_STATUS: "/status",
    SETTINGS_MENU_USERS: "/users",
    SETTINGS_MENU_HELP: "/help",
    SETTINGS_MENU_LOGOUT: "/logout",
}

SUBMENUS = {
    MAIN_MENU_SHOP: (build_shop_menu, messages.SHOP_MENU_PROMPT),
    MAIN_MENU_WOO: (build_woo_menu, messages.WOO_MENU_PROMPT),
    MAIN_MENU_DISCOGS: (build_discogs_menu, messages.DISCOGS_MENU_PROMPT),
    MAIN_MENU_SETTINGS: (build_settings_menu, messages.SETTINGS_MENU_PROMPT),
}

PUBLIC_COMMANDS = {"/login", "/help", "/start"}


async def handle_menu_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    user_id = update.effective_user.id
    is_authed = await run_blocking(auth_manager.is_authenticated, user_id)

    if text == BACK_BUTTON:
        await update.message.reply_text(
            messages.MAIN_MENU_PROMPT,
            reply_markup=build_main_menu(is_authed),
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

    update.message.text = command
    await context.application.process_update(update)


def create_menu_handler() -> MessageHandler:
    options = set(SUBMENUS.keys()) | set(MENU_COMMANDS.keys()) | {BACK_BUTTON}
    pattern = r"^(?:%s)$" % "|".join(re.escape(option) for option in sorted(options))
    return MessageHandler(filters.Regex(re.compile(pattern)), handle_menu_selection)
