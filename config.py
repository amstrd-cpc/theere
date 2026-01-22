import os
from dotenv import load_dotenv

load_dotenv()


def _parse_admin_ids(raw_ids: str | None) -> list[int]:
    if not raw_ids:
        return []

    ids: list[int] = []
    for part in raw_ids.split(","):
        cleaned = part.strip()
        if not cleaned:
            continue
        try:
            ids.append(int(cleaned))
        except ValueError as exc:  # pragma: no cover - config parsing
            raise ValueError(
                "ADMIN_IDS must be a comma-separated list of Telegram user IDs"
            ) from exc
    return ids


BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN must be set in environment variables")

ADMIN_IDS = _parse_admin_ids(os.getenv("ADMIN_IDS"))
if not ADMIN_IDS:
    raise ValueError("ADMIN_IDS must be set in the .env file (comma-separated Telegram user IDs)")

# ADMIN_CHAT_ID is used for outbound notifications; default to the first admin ID
# for one-on-one chats, but allow overriding (e.g., to a group or channel).
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID") or str(ADMIN_IDS[0])
