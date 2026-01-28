from __future__ import annotations

from config.settings import load_settings

settings = load_settings()

BOT_TOKEN = settings.bot_token
ADMIN_CHAT_ID = settings.admin_chat_id
ADMIN_IDS = settings.admin_ids
