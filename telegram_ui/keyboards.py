from __future__ import annotations

from telegram import KeyboardButton, ReplyKeyboardMarkup

MAIN_MENU_SHOP = "Shop"
MAIN_MENU_WOO = "Woo"
MAIN_MENU_DISCOGS = "Discogs"
MAIN_MENU_SETTINGS = "Settings"

BACK_TO_MAIN = "⬅️ Back to Main"
BACK_TO_SHOP = "⬅️ Back to Shop"
BACK_TO_WOO = "⬅️ Back to Woo"
BACK_TO_DISCOGS = "⬅️ Back to Discogs"
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

WOO_MENU_SETUP_ACTIONS = "Setup & Sync"
WOO_MENU_ORDERS_ACTIONS = "Orders & Fulfillment"
WOO_MENU_MAPPING_ACTIONS = "Product Mapping"
WOO_MENU_ORDERS = "Orders"
WOO_MENU_SETUP = "Setup Woo"
WOO_MENU_CONNECT = "Connect Woo (Alt)"
WOO_MENU_SETTINGS = "Sync Settings"
WOO_MENU_MAP = "Map Product"
WOO_MENU_AUTO_MAP = "Auto Map Products"
WOO_MENU_REPAIR_WEBHOOKS = "Repair Webhooks"
WOO_MENU_RECONCILE = "Reconcile Woo Stock"

DISCOGS_MENU_CONNECTION_ACTIONS = "Discogs Connection"
DISCOGS_MENU_PUBLISH_ACTIONS = "Publish / Add to Discogs"
DISCOGS_MENU_SYNC_ACTIONS = "Inventory Sync"
DISCOGS_MENU_CONNECT = "Connect Discogs"
DISCOGS_MENU_STATUS = "Discogs Status"
DISCOGS_MENU_PUBLISH = "Publish Listing"
DISCOGS_MENU_PUBLISH_ALL = "Publish All Listings"
DISCOGS_MENU_PUBLISH_SELECTION = "Publish Selection"
DISCOGS_MENU_COLLECTION = "Add to Collection"
DISCOGS_MENU_COLLECTION_ALL = "Add All to Collection"
DISCOGS_MENU_COLLECTION_SELECTION = "Add Selection to Collection"
DISCOGS_MENU_LINK = "Link Listing"
DISCOGS_MENU_UNLINK = "Unlink Listing"
DISCOGS_MENU_RECONCILE = "Reconcile Discogs Stock"
DISCOGS_MENU_REFRESH = "Refresh Quantities"

SETTINGS_MENU_ACCOUNT_ACTIONS = "Account"
SETTINGS_MENU_SUPPORT_ACTIONS = "Support & Help"
SETTINGS_MENU_STATUS = "Status"
SETTINGS_MENU_LOGOUT = "Logout"
SETTINGS_MENU_HELP = "Help"
SETTINGS_MENU_USERS = "Users"
SETTINGS_MENU_START = "Start"
SETTINGS_MENU_CANCEL = "Cancel Operation"


def build_main_menu(authenticated: bool) -> ReplyKeyboardMarkup:
    if not authenticated:
        buttons = [
            [KeyboardButton("/login"), KeyboardButton("/help")],
            [KeyboardButton("/start"), KeyboardButton("/cancel")],
        ]
        return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

    buttons = [
        [KeyboardButton(MAIN_MENU_SHOP), KeyboardButton(MAIN_MENU_WOO)],
        [KeyboardButton(MAIN_MENU_DISCOGS), KeyboardButton(MAIN_MENU_SETTINGS)],
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


def build_woo_menu() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(WOO_MENU_SETUP_ACTIONS), KeyboardButton(WOO_MENU_ORDERS_ACTIONS)],
        [KeyboardButton(WOO_MENU_MAPPING_ACTIONS)],
        [KeyboardButton(SETTINGS_MENU_CANCEL)],
        [KeyboardButton(BACK_TO_MAIN)],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def build_woo_setup_menu() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(WOO_MENU_SETUP), KeyboardButton(WOO_MENU_CONNECT)],
        [KeyboardButton(WOO_MENU_SETTINGS)],
        [KeyboardButton(WOO_MENU_REPAIR_WEBHOOKS)],
        [KeyboardButton(WOO_MENU_RECONCILE)],
        [KeyboardButton(SETTINGS_MENU_CANCEL)],
        [KeyboardButton(BACK_TO_WOO)],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def build_woo_orders_menu() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(WOO_MENU_ORDERS)],
        [KeyboardButton(SETTINGS_MENU_CANCEL)],
        [KeyboardButton(BACK_TO_WOO)],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def build_woo_mapping_menu() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(WOO_MENU_MAP), KeyboardButton(WOO_MENU_AUTO_MAP)],
        [KeyboardButton(SETTINGS_MENU_CANCEL)],
        [KeyboardButton(BACK_TO_WOO)],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def build_discogs_menu() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(DISCOGS_MENU_PUBLISH)],
        [KeyboardButton(DISCOGS_MENU_COLLECTION)],
        [KeyboardButton(DISCOGS_MENU_CONNECTION_ACTIONS), KeyboardButton(DISCOGS_MENU_PUBLISH_ACTIONS)],
        [KeyboardButton(DISCOGS_MENU_SYNC_ACTIONS)],
        [KeyboardButton(SETTINGS_MENU_CANCEL)],
        [KeyboardButton(BACK_TO_MAIN)],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def build_discogs_connection_menu() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(DISCOGS_MENU_CONNECT), KeyboardButton(DISCOGS_MENU_STATUS)],
        [KeyboardButton(SETTINGS_MENU_CANCEL)],
        [KeyboardButton(BACK_TO_DISCOGS)],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def build_discogs_publish_menu() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(DISCOGS_MENU_PUBLISH)],
        [KeyboardButton(DISCOGS_MENU_PUBLISH_ALL), KeyboardButton(DISCOGS_MENU_PUBLISH_SELECTION)],
        [KeyboardButton(DISCOGS_MENU_COLLECTION)],
        [KeyboardButton(DISCOGS_MENU_COLLECTION_ALL), KeyboardButton(DISCOGS_MENU_COLLECTION_SELECTION)],
        [KeyboardButton(SETTINGS_MENU_CANCEL)],
        [KeyboardButton(BACK_TO_DISCOGS)],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def build_discogs_sync_menu() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(DISCOGS_MENU_LINK), KeyboardButton(DISCOGS_MENU_UNLINK)],
        [KeyboardButton(DISCOGS_MENU_REFRESH)],
        [KeyboardButton(DISCOGS_MENU_RECONCILE), KeyboardButton(WOO_MENU_RECONCILE)],
        [KeyboardButton(SETTINGS_MENU_CANCEL)],
        [KeyboardButton(BACK_TO_DISCOGS)],
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
