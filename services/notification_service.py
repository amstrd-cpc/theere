from __future__ import annotations

import logging
from typing import Dict

logger = logging.getLogger(__name__)


def notify_admin(store: Dict[str, object], message: str) -> None:
    store_name = store.get("store_name") if isinstance(store, dict) else "unknown"
    logger.info("[NOTIFY:%s] %s", store_name, message)
