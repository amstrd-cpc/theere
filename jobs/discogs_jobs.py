from __future__ import annotations

import datetime
import logging

from services.channel_sync_service import reconcile_channel_stock
from services.store_service import get_default_store, get_store_settings

logger = logging.getLogger(__name__)


def reconcile_discogs_inventory() -> None:
    store = get_default_store()
    if not store:
        return
    settings = get_store_settings(int(store["id"]))
    if not settings.get("discogs_polling_enabled"):
        return
    interval_minutes = int(settings.get("discogs_polling_interval_minutes") or 30)
    last_sync = store.get("discogs_last_sync_at")
    if last_sync:
        try:
            last_dt = datetime.datetime.fromisoformat(last_sync)
            if datetime.datetime.utcnow() - last_dt < datetime.timedelta(minutes=interval_minutes):
                return
        except ValueError:
            pass
    synced = reconcile_channel_stock(int(store["id"]), channel="discogs")
    if synced:
        logger.info("Discogs reconcile updated %s items", len(synced))
