from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
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
    wc_verify_ssl: bool
    db_path: str
    sales_db_path: Optional[str]
    redis_url: str
    api_base_url: Optional[str]
    webhook_port: int
    default_store_id: Optional[int]


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


def _parse_optional_int(raw: Optional[str]) -> Optional[int]:
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def load_settings() -> Settings:
    bot_token = os.getenv("BOT_TOKEN", "").strip()
    admin_chat_id = os.getenv("ADMIN_CHAT_ID")
    admin_ids = _parse_int_list(os.getenv("ADMIN_IDS"))
    bot_password = os.getenv("BOT_PASSWORD", "your_default_password_here")
    session_timeout_hours = int(os.getenv("SESSION_TIMEOUT_HOURS", "24"))
    wc_verify_ssl = os.getenv("WC_VERIFY_SSL", "true").lower() not in {"0", "false", "no"}
    db_path = os.getenv("RECORDSTORE_DB_FILE") or os.getenv("DB_PATH")
    if not db_path:
        data_dir = Path("/data")
        if data_dir.exists():
            db_path = str(data_dir / "clime_db.db")
        else:
            db_path = "clime_db.db"
    sales_db_path = os.getenv("SALES_DB_PATH")
    if not sales_db_path and Path(db_path).parent == Path("/data"):
        sales_db_path = str(Path("/data") / "sales.db")
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    api_base_url = os.getenv("API_BASE_URL")
    webhook_port = int(os.getenv("WEBHOOK_PORT", "8080"))
    default_store_id = _parse_optional_int(os.getenv("DEFAULT_STORE_ID"))

    return Settings(
        bot_token=bot_token,
        admin_chat_id=int(admin_chat_id) if admin_chat_id else None,
        admin_ids=admin_ids,
        bot_password=bot_password,
        session_timeout_hours=session_timeout_hours,
        wc_verify_ssl=wc_verify_ssl,
        db_path=db_path,
        sales_db_path=sales_db_path,
        redis_url=redis_url,
        api_base_url=api_base_url,
        webhook_port=webhook_port,
        default_store_id=default_store_id,
    )


def health_check(settings: Settings) -> str:
    lines = ["✅ Configuration Health Check"]
    lines.append(f"BOT_TOKEN: {'set' if settings.bot_token else 'missing'}")
    lines.append(f"ADMIN_CHAT_ID: {settings.admin_chat_id or 'not set'}")
    lines.append(f"ADMIN_IDS: {settings.admin_ids or 'not set'}")
    lines.append(f"REDIS_URL: {settings.redis_url}")
    lines.append(f"API_BASE_URL: {settings.api_base_url or 'not set'}")
    lines.append(f"WEBHOOK_PORT: {settings.webhook_port}")
    lines.append(f"DEFAULT_STORE_ID: {settings.default_store_id or 'not set'}")
    lines.append(f"DB_PATH: {settings.db_path}")
    lines.append(f"SALES_DB_PATH: {settings.sales_db_path or settings.db_path}")
    return "\n".join(lines)
