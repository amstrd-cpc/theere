from __future__ import annotations

from telegram import KeyboardButton, ReplyKeyboardMarkup


def build_main_menu(authenticated: bool) -> ReplyKeyboardMarkup:
    if not authenticated:
        buttons = [
            [KeyboardButton("/login"), KeyboardButton("/help"), KeyboardButton("/start")],
        ]
        return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

    buttons = [
        [KeyboardButton("/add"), KeyboardButton("/sell"), KeyboardButton("/inventory")],
        [KeyboardButton("/reports"), KeyboardButton("/sales"), KeyboardButton("/stock")],
        [KeyboardButton("/daily"), KeyboardButton("/weekly"), KeyboardButton("/monthly")],
        [KeyboardButton("/orders"), KeyboardButton("/settings"), KeyboardButton("/setup_woo")],
        [KeyboardButton("/repair_webhooks"), KeyboardButton("/map_woo")],
        [KeyboardButton("/connect_discogs"), KeyboardButton("/discogs_status")],
        [KeyboardButton("/publish_discogs"), KeyboardButton("/link_discogs"), KeyboardButton("/unlink_discogs")],
        [KeyboardButton("/reconcile_discogs"), KeyboardButton("/reconcile_woo"), KeyboardButton("/discogs_refresh")],
        [KeyboardButton("/status"), KeyboardButton("/logout"), KeyboardButton("/help")],
        [KeyboardButton("/cancel")],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)
