from __future__ import annotations

import logging

from services.discogs_sync_service import sync_all_discogs
from services.store_service import get_default_store, get_store_settings

logger = logging.getLogger(__name__)


def reconcile_discogs_inventory() -> None:
    store = get_default_store()
    if not store:
        return
    settings = get_store_settings(int(store["id"]))
    if not settings.get("discogs_collection_sync_enabled"):
        return
    results = sync_all_discogs(int(store["id"]), publish_missing=False)
    logger.info("Discogs collection sync complete: %s", results)


def poll_three_way_discogs() -> None:
    logger.info("Three-way Discogs sync disabled in favor of collection-only sync.")
