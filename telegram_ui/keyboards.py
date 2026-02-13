from __future__ import annotations

from telegram import KeyboardButton, ReplyKeyboardMarkup

MAIN_MENU_SHOP = "Shop"
MAIN_MENU_INTEGRATIONS = "Integrations"
MAIN_MENU_SYNC = "Sync"
MAIN_MENU_SYNC_STATUS = "Sync Status"
MAIN_MENU_BACKUPS = "Backups"
MAIN_MENU_SETTINGS = "Settings"

BACK_TO_MAIN = "⬅️ Back to Main"
BACK_TO_SHOP = "⬅️ Back to Shop"
BACK_TO_INTEGRATIONS = "⬅️ Back to Integrations"
BACK_TO_SYNC = "⬅️ Back to Sync"
BACK_TO_SETTINGS = "⬅️ Back to Settings"

SHOP_MENU_INVENTORY_ACTIONS = "Inventory Actions"
SHOP_MENU_SALES_ACTIONS = "Sales Actions"
SHOP_MENU_REPORTS_ACTIONS = "Reports & Summaries"

SHOP_MENU_ADD = "Add Item"
SHOP_MENU_SELL = "Sell Item"
SHOP_MENU_INVENTORY = "Inventory"
SHOP_MENU_LOW_STOCK = "Low Stock"
SHOP_MENU_RECENT_SALES = "Recent Sales"
SHOP_MENU_REPORTS = "Reports"
SHOP_MENU_DAILY = "Daily Report"
SHOP_MENU_WEEKLY = "Weekly Report"
SHOP_MENU_MONTHLY = "Monthly Report"

INTEGRATIONS_MENU_WOO = "WooCommerce"
INTEGRATIONS_MENU_DISCOGS = "Discogs"
SYNC_MENU_OPEN = "Sync Controls"

DISCOGS_MENU_CONNECT = "Connect Discogs"
DISCOGS_MENU_STATUS = "Discogs Status"
DISCOGS_MENU_COLLECTION = "Collection Sync"

SETTINGS_MENU_ACCOUNT_ACTIONS = "Account"
SETTINGS_MENU_SUPPORT_ACTIONS = "Support & Help"
SETTINGS_MENU_STATUS = "Status"
SETTINGS_MENU_LOGOUT = "Logout"
SETTINGS_MENU_HELP = "Help"
SETTINGS_MENU_USERS = "Users"
SETTINGS_MENU_START = "Start"
SETTINGS_MENU_CANCEL = "/cancel"


def build_main_menu(authenticated: bool) -> ReplyKeyboardMarkup:
    if not authenticated:
        buttons = [
            [KeyboardButton("/login"), KeyboardButton("/help")],
            [KeyboardButton("/start"), KeyboardButton("/cancel")],
        ]
        return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

    buttons = [
        [KeyboardButton(MAIN_MENU_SHOP), KeyboardButton(MAIN_MENU_INTEGRATIONS)],
        [KeyboardButton(MAIN_MENU_SYNC), KeyboardButton(MAIN_MENU_SYNC_STATUS)],
        [KeyboardButton(MAIN_MENU_BACKUPS)],
        [KeyboardButton(MAIN_MENU_SETTINGS)],
        [KeyboardButton(SETTINGS_MENU_CANCEL)],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def build_shop_menu() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(SHOP_MENU_INVENTORY_ACTIONS), KeyboardButton(SHOP_MENU_SALES_ACTIONS)],
        [KeyboardButton(SHOP_MENU_REPORTS_ACTIONS)],
        [KeyboardButton(SETTINGS_MENU_CANCEL)],
        [KeyboardButton(BACK_TO_MAIN)],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def build_shop_inventory_menu() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(SHOP_MENU_ADD), KeyboardButton(SHOP_MENU_INVENTORY)],
        [KeyboardButton(SHOP_MENU_LOW_STOCK)],
        [KeyboardButton(SETTINGS_MENU_CANCEL)],
        [KeyboardButton(BACK_TO_SHOP)],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def build_shop_sales_menu() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(SHOP_MENU_SELL), KeyboardButton(SHOP_MENU_RECENT_SALES)],
        [KeyboardButton(SETTINGS_MENU_CANCEL)],
        [KeyboardButton(BACK_TO_SHOP)],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def build_shop_reports_menu() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(SHOP_MENU_REPORTS)],
        [KeyboardButton(SHOP_MENU_DAILY), KeyboardButton(SHOP_MENU_WEEKLY)],
        [KeyboardButton(SHOP_MENU_MONTHLY)],
        [KeyboardButton(SETTINGS_MENU_CANCEL)],
        [KeyboardButton(BACK_TO_SHOP)],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def build_integrations_menu() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(INTEGRATIONS_MENU_WOO), KeyboardButton(INTEGRATIONS_MENU_DISCOGS)],
        [KeyboardButton(SETTINGS_MENU_CANCEL)],
        [KeyboardButton(BACK_TO_MAIN)],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def build_discogs_menu() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(DISCOGS_MENU_CONNECT), KeyboardButton(DISCOGS_MENU_STATUS)],
        [KeyboardButton(DISCOGS_MENU_COLLECTION)],
        [KeyboardButton(SETTINGS_MENU_CANCEL)],
        [KeyboardButton(BACK_TO_INTEGRATIONS)],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def build_discogs_connection_menu() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(DISCOGS_MENU_CONNECT), KeyboardButton(DISCOGS_MENU_STATUS)],
        [KeyboardButton(SETTINGS_MENU_CANCEL)],
        [KeyboardButton(BACK_TO_INTEGRATIONS)],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def build_settings_menu() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(SETTINGS_MENU_ACCOUNT_ACTIONS), KeyboardButton(SETTINGS_MENU_SUPPORT_ACTIONS)],
        [KeyboardButton(SETTINGS_MENU_CANCEL)],
        [KeyboardButton(BACK_TO_MAIN)],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def build_settings_account_menu() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(SETTINGS_MENU_STATUS), KeyboardButton(SETTINGS_MENU_USERS)],
        [KeyboardButton(SETTINGS_MENU_LOGOUT)],
        [KeyboardButton(SETTINGS_MENU_CANCEL)],
        [KeyboardButton(BACK_TO_SETTINGS)],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def build_settings_support_menu() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(SETTINGS_MENU_HELP), KeyboardButton(SETTINGS_MENU_START)],
        [KeyboardButton(SETTINGS_MENU_CANCEL)],
        [KeyboardButton(BACK_TO_SETTINGS)],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def build_sync_menu() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(SYNC_MENU_OPEN), KeyboardButton(MAIN_MENU_SYNC_STATUS)],
        [KeyboardButton(MAIN_MENU_BACKUPS)],
        [KeyboardButton(SETTINGS_MENU_CANCEL)],
        [KeyboardButton(BACK_TO_MAIN)],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)
