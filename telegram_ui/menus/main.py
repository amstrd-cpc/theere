from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from services.ui_session_service import create_callback_session, inject_session
from telegram_ui.menus.admin import MENU as ADMIN_MENU
from telegram_ui.menus.common import MenuDefinition, MenuButton, back_button, home_button, menu_button
from telegram_ui.menus.discogs import MENU as DISCOGS_MENU
from telegram_ui.menus.inventory import MENU as INVENTORY_MENU
from telegram_ui.menus.misc import MENU as MISC_MENU
from telegram_ui.menus.reports import MENU as REPORTS_MENU
from telegram_ui.menus.sales import MENU as SALES_MENU
from telegram_ui.menus.settings import MENU as SETTINGS_MENU
from telegram_ui.menus.sync import MENU as SYNC_MENU
from telegram_ui.menus.woo import MENU as WOO_MENU

MAIN_MENU = MenuDefinition(
    menu_id="main",
    title="Main",
    parent_id=None,
    buttons=(
        menu_button("📦 Inventory", "inventory"),
        menu_button("💸 Sales", "sales"),
        menu_button("🔄 Sync", "sync"),
        menu_button("🎧 Discogs", "discogs"),
        menu_button("🛒 WooCommerce", "woo"),
        menu_button("📊 Reports", "reports"),
        menu_button("⚙️ Settings", "settings"),
        menu_button("🧩 Misc", "misc"),
        menu_button("🛡️ Admin", "admin"),
    ),
)

MENUS: dict[str, MenuDefinition] = {
    menu.menu_id: menu
    for menu in (
        MAIN_MENU,
        INVENTORY_MENU,
        SALES_MENU,
        SYNC_MENU,
        DISCOGS_MENU,
        WOO_MENU,
        REPORTS_MENU,
        SETTINGS_MENU,
        MISC_MENU,
        ADMIN_MENU,
    )
}

# Complete command mapping from docs/COMMAND_CATALOG.md.
CATALOG_COMMANDS: set[str] = {
    "/add",
    "/auto_map_woo",
    "/backups",
    "/cancel",
    "/collect_discogs",
    "/collect_discogs_selection",
    "/connect",
    "/connect_discogs",
    "/daily",
    "/discogs_refresh",
    "/discogs_status",
    "/help",
    "/integrations_discogs",
    "/integrations_woo",
    "/inventory",
    "/link_discogs",
    "/login",
    "/logout",
    "/map_woo",
    "/monthly",
    "/orders",
    "/publish_discogs",
    "/publish_discogs_all",
    "/publish_discogs_selection",
    "/reconcile_discogs",
    "/reconcile_woo",
    "/relist_discogs",
    "/remove_discogs_listing",
    "/repair_webhooks",
    "/reports",
    "/sales",
    "/sell",
    "/settings",
    "/setup_woo",
    "/start",
    "/status",
    "/stock",
    "/sync_discogs_all",
    "/sync_status",
    "/unlink_discogs",
    "/unlist_discogs",
    "/update_discogs_listing",
    "/users",
    "/weekly",
}


def build_command_button_map() -> dict[str, tuple[str, ...]]:
    mapping: dict[str, list[str]] = {}
    for menu in MENUS.values():
        for button in menu.buttons:
            if not button.command:
                continue
            mapping.setdefault(button.command, []).append(f"{menu.menu_id}:{button.label}")

    return {command: tuple(button_refs) for command, button_refs in mapping.items()}


COMMAND_TO_MENU_BUTTONS = build_command_button_map()


missing = CATALOG_COMMANDS - set(COMMAND_TO_MENU_BUTTONS)
if missing:
    raise RuntimeError(f"Missing menu mappings for commands: {sorted(missing)}")


def get_menu(menu_id: str) -> MenuDefinition:
    return MENUS[menu_id]


def get_command_target(target: str) -> str | None:
    key = "/" + target.strip().lstrip("/")
    return key if key in COMMAND_TO_MENU_BUTTONS else None


def _build_breadcrumb(menu_id: str) -> str:
    trail: list[str] = []
    current = MENUS[menu_id]
    while current:
        trail.append(current.title)
        if not current.parent_id:
            break
        current = MENUS[current.parent_id]
    return " › ".join(reversed(trail))


def build_inline_menu(menu_id: str, *, user_id: int | None = None) -> tuple[str, InlineKeyboardMarkup]:
    definition = MENUS[menu_id]
    session_token = None
    if user_id is not None:
        session = create_callback_session(user_id=user_id, expected_node=f"nav:{menu_id}", expected_state="menu")
        session_token = str(session["session_token"])

    rows = [
        [InlineKeyboardButton(text=button.label, callback_data=inject_session(button.callback_data, session_token) if session_token else button.callback_data)]
        for button in definition.buttons
    ]

    if menu_id != "main":
        nav_buttons: tuple[MenuButton, MenuButton] = (
            back_button(menu_id, session_token=session_token),
            home_button(session_token=session_token),
        )
        rows.append([InlineKeyboardButton(text=btn.label, callback_data=btn.callback_data) for btn in nav_buttons])

    text = f"📍 { _build_breadcrumb(menu_id) }\nChoose an action:"
    return text, InlineKeyboardMarkup(rows)
