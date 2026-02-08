from __future__ import annotations

from telegram import KeyboardButton, ReplyKeyboardMarkup

MAIN_MENU_SHOP = "Shop"
MAIN_MENU_WOO = "Woo"
MAIN_MENU_DISCOGS = "Discogs"
MAIN_MENU_SETTINGS = "Settings"
BACK_BUTTON = "Back"

SHOP_MENU_ADD = "Add Item"
SHOP_MENU_SELL = "Sell Item"
SHOP_MENU_INVENTORY = "Inventory"
SHOP_MENU_LOW_STOCK = "Low Stock"
SHOP_MENU_RECENT_SALES = "Recent Sales"
SHOP_MENU_REPORTS = "Reports"
SHOP_MENU_DAILY = "Daily Report"
SHOP_MENU_WEEKLY = "Weekly Report"
SHOP_MENU_MONTHLY = "Monthly Report"

WOO_MENU_ORDERS = "Orders"
WOO_MENU_SETUP = "Setup Woo"
WOO_MENU_SETTINGS = "Sync Settings"
WOO_MENU_MAP = "Map Product"
WOO_MENU_REPAIR_WEBHOOKS = "Repair Webhooks"
WOO_MENU_RECONCILE = "Reconcile Woo Stock"

DISCOGS_MENU_CONNECT = "Connect Discogs"
DISCOGS_MENU_STATUS = "Discogs Status"
DISCOGS_MENU_PUBLISH = "Publish Listing"
DISCOGS_MENU_LINK = "Link Listing"
DISCOGS_MENU_UNLINK = "Unlink Listing"
DISCOGS_MENU_RECONCILE = "Reconcile Discogs Stock"
DISCOGS_MENU_REFRESH = "Refresh Quantities"

SETTINGS_MENU_STATUS = "Status"
SETTINGS_MENU_LOGOUT = "Logout"
SETTINGS_MENU_HELP = "Help"
SETTINGS_MENU_USERS = "Users"


def build_main_menu(authenticated: bool) -> ReplyKeyboardMarkup:
    if not authenticated:
        buttons = [
            [KeyboardButton("/login"), KeyboardButton("/help"), KeyboardButton("/start")],
        ]
        return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

    buttons = [
        [KeyboardButton(MAIN_MENU_SHOP), KeyboardButton(MAIN_MENU_WOO)],
        [KeyboardButton(MAIN_MENU_DISCOGS), KeyboardButton(MAIN_MENU_SETTINGS)],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def build_shop_menu() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(SHOP_MENU_ADD), KeyboardButton(SHOP_MENU_SELL)],
        [KeyboardButton(SHOP_MENU_INVENTORY), KeyboardButton(SHOP_MENU_LOW_STOCK)],
        [KeyboardButton(SHOP_MENU_RECENT_SALES), KeyboardButton(SHOP_MENU_REPORTS)],
        [KeyboardButton(SHOP_MENU_DAILY), KeyboardButton(SHOP_MENU_WEEKLY)],
        [KeyboardButton(SHOP_MENU_MONTHLY)],
        [KeyboardButton(BACK_BUTTON)],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def build_woo_menu() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(WOO_MENU_ORDERS), KeyboardButton(WOO_MENU_SETUP)],
        [KeyboardButton(WOO_MENU_SETTINGS), KeyboardButton(WOO_MENU_MAP)],
        [KeyboardButton(WOO_MENU_REPAIR_WEBHOOKS)],
        [KeyboardButton(WOO_MENU_RECONCILE)],
        [KeyboardButton(BACK_BUTTON)],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def build_discogs_menu() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(DISCOGS_MENU_CONNECT), KeyboardButton(DISCOGS_MENU_STATUS)],
        [KeyboardButton(DISCOGS_MENU_PUBLISH), KeyboardButton(DISCOGS_MENU_LINK)],
        [KeyboardButton(DISCOGS_MENU_UNLINK), KeyboardButton(DISCOGS_MENU_REFRESH)],
        [KeyboardButton(DISCOGS_MENU_RECONCILE)],
        [KeyboardButton(BACK_BUTTON)],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def build_settings_menu() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(SETTINGS_MENU_STATUS), KeyboardButton(SETTINGS_MENU_USERS)],
        [KeyboardButton(SETTINGS_MENU_HELP), KeyboardButton(SETTINGS_MENU_LOGOUT)],
        [KeyboardButton(BACK_BUTTON)],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)
