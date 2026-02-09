from __future__ import annotations

import logging

from services.discogs_sync_service import sync_all_discogs, sync_discogs_orders
from services.store_service import get_default_store, get_store_settings
from services.tri_sync_service import poll_discogs_listings, poll_woo_products

logger = logging.getLogger(__name__)


def reconcile_discogs_inventory() -> None:
    store = get_default_store()
    if not store:
        return
    settings = get_store_settings(int(store["id"]))
    if settings.get("discogs_collection_sync_enabled"):
        results = sync_all_discogs(int(store["id"]), publish_missing=False)
        logger.info("Discogs collection sync complete: %s", results)
    try:
        sync_discogs_orders(int(store["id"]))
    except Exception:
        logger.exception("Failed syncing Discogs orders")


def poll_three_way_discogs() -> None:
    store = get_default_store()
    if not store:
        return
    store_id = int(store["id"])
    settings = get_store_settings(store_id)
    if not settings.get("three_way_sync_enabled"):
        return
    poll_discogs_listings(store_id)
    sync_discogs_orders(store_id)


def poll_three_way_woo() -> None:
    store = get_default_store()
    if not store:
        return
    store_id = int(store["id"])
    settings = get_store_settings(store_id)
    if not settings.get("three_way_sync_enabled"):
        return
    poll_woo_products(store_id)
