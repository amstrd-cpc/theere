from __future__ import annotations

import datetime
import logging

from services.channel_sync_service import reconcile_channel_stock
from services.product_map_service import get_latest_seen_at
from services.store_service import get_default_store, get_store_settings
from services.tri_sync_service import poll_discogs_listings

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


def poll_three_way_discogs() -> None:
    store = get_default_store()
    if not store:
        return
    settings = get_store_settings(int(store["id"]))
    if not settings.get("three_way_sync_enabled"):
        return
    interval_minutes = int(settings.get("three_way_discogs_interval_minutes") or 15)
    last_seen = get_latest_seen_at(int(store["id"]), channel="discogs")
    if last_seen:
        try:
            last_dt = datetime.datetime.fromisoformat(last_seen)
            if datetime.datetime.utcnow() - last_dt < datetime.timedelta(minutes=interval_minutes):
                return
        except ValueError:
            pass
    poll_discogs_listings(int(store["id"]))
