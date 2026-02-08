from __future__ import annotations

import logging
from typing import Dict, Optional

import requests

from config.settings import load_settings

logger = logging.getLogger(__name__)


def notify_admin(store: Dict[str, object], message: str) -> None:
    settings = load_settings()
    chat_id = _notification_chat_id(store, settings)
    if not chat_id or not settings.bot_token:
        return
    url = f"https://api.telegram.org/bot{settings.bot_token}/sendMessage"
    try:
        requests.post(url, data={"chat_id": chat_id, "text": message}, timeout=10)
    except Exception:
        logger.exception("Failed to send Telegram notification")


def _notification_chat_id(store: Dict[str, object], settings) -> Optional[int]:
    store_settings = store.get("settings") if isinstance(store, dict) else None
    if isinstance(store_settings, dict):
        value = store_settings.get("notification_chat_id")
        if value:
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
    return settings.admin_chat_id
