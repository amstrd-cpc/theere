from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_chat_id: Optional[int]
    admin_ids: List[int]
    bot_password: str
    session_timeout_hours: int
    discogs_token: Optional[str]
    wc_api_url: Optional[str]
    wc_consumer_key: Optional[str]
    wc_consumer_secret: Optional[str]
    wc_verify_ssl: bool
    db_path: str
    sales_db_path: Optional[str]
    webhook_secret: Optional[str]


def _parse_int_list(raw: Optional[str]) -> List[int]:
    if not raw:
        return []
    values: List[int] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            values.append(int(item))
        except ValueError:
            continue
    return values


def load_settings() -> Settings:
    bot_token = os.getenv("BOT_TOKEN", "").strip()
    admin_chat_id = os.getenv("ADMIN_CHAT_ID")
    admin_ids = _parse_int_list(os.getenv("ADMIN_IDS"))
    bot_password = os.getenv("BOT_PASSWORD", "your_default_password_here")
    session_timeout_hours = int(os.getenv("SESSION_TIMEOUT_HOURS", "24"))
    discogs_token = os.getenv("DISCOGS_TOKEN")
    wc_api_url = os.getenv("WC_API_URL")
    wc_consumer_key = os.getenv("WC_CONSUMER_KEY")
    wc_consumer_secret = os.getenv("WC_CONSUMER_SECRET")
    wc_verify_ssl = os.getenv("WC_VERIFY_SSL", "true").lower() not in {"0", "false", "no"}
    db_path = os.getenv("RECORDSTORE_DB_FILE") or os.getenv("DB_PATH") or "clime_db.db"
    sales_db_path = os.getenv("SALES_DB_PATH")
    webhook_secret = (
        os.getenv("WOO_WEBHOOK_SECRET")
        or os.getenv("WC_WEBHOOK_SECRET")
        or os.getenv("WEBHOOK_SECRET")
    )

    return Settings(
        bot_token=bot_token,
        admin_chat_id=int(admin_chat_id) if admin_chat_id else None,
        admin_ids=admin_ids,
        bot_password=bot_password,
        session_timeout_hours=session_timeout_hours,
        discogs_token=discogs_token,
        wc_api_url=wc_api_url,
        wc_consumer_key=wc_consumer_key,
        wc_consumer_secret=wc_consumer_secret,
        wc_verify_ssl=wc_verify_ssl,
        db_path=db_path,
        sales_db_path=sales_db_path,
        webhook_secret=webhook_secret,
    )


def health_check(settings: Settings) -> str:
    lines = ["✅ Configuration Health Check"]
    lines.append(f"BOT_TOKEN: {'set' if settings.bot_token else 'missing'}")
    lines.append(f"ADMIN_CHAT_ID: {settings.admin_chat_id or 'not set'}")
    lines.append(f"ADMIN_IDS: {settings.admin_ids or 'not set'}")
    lines.append(f"DISCOGS_TOKEN: {'set' if settings.discogs_token else 'missing'}")
    lines.append(
        "WooCommerce: "
        + ("configured" if settings.wc_api_url and settings.wc_consumer_key and settings.wc_consumer_secret else "missing")
    )
    lines.append(f"DB_PATH: {settings.db_path}")
    lines.append(f"SALES_DB_PATH: {settings.sales_db_path or settings.db_path}")
    return "\n".join(lines)
