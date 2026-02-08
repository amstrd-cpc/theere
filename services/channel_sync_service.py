from __future__ import annotations

import logging
from typing import List

from services.inventory_service import get_inventory_by_id
from services.product_map_service import find_mapping_by_internal_id, list_product_mappings
from services.store_service import get_store, get_store_settings, update_discogs_sync_time
from services.woo_service import update_product_by_id, update_stock
from services.discogs_service import update_listing, update_listing_quantity

logger = logging.getLogger(__name__)


def sync_inventory_item(
    store_id: int,
    internal_product_id: int,
    *,
    sync_price: bool = False,
) -> None:
    store = get_store(store_id)
    if not store:
        logger.warning("Store %s not found for sync", store_id)
        return
    item = get_inventory_by_id(internal_product_id)
    if not item:
        return
    mapping = find_mapping_by_internal_id(store_id, internal_product_id)
    if not mapping:
        return

    qty = int(item.get("quantity") or 0)
    price = float(item.get("price_gel") or 0)

    if mapping.get("woo_product_id"):
        try:
            update_stock(int(mapping["woo_product_id"]), qty, store=store)
            if sync_price:
                update_product_by_id(int(mapping["woo_product_id"]), {"regular_price": f"{price:.2f}"}, store=store)
        except Exception:
            logger.exception("Failed syncing Woo for inventory %s", internal_product_id)

    if mapping.get("discogs_listing_id"):
        try:
            update_listing_quantity(store, int(mapping["discogs_listing_id"]), qty)
            if sync_price:
                update_listing(store, int(mapping["discogs_listing_id"]), {"price": f"{price:.2f}"})
            update_discogs_sync_time(store_id)
        except Exception:
            logger.exception("Failed syncing Discogs for inventory %s", internal_product_id)


def reconcile_channel_stock(store_id: int, *, channel: str) -> List[int]:
    store = get_store(store_id)
    if not store:
        return []
    settings = get_store_settings(store_id)
    sync_price = bool(settings.get("discogs_price_sync"))
    mappings = list_product_mappings(store_id)
    synced: List[int] = []
    for mapping in mappings:
        internal_id = mapping.get("internal_product_id")
        if not internal_id:
            continue
        item = get_inventory_by_id(int(internal_id))
        if not item:
            continue
        qty = int(item.get("quantity") or 0)
        price = float(item.get("price_gel") or 0)

        if channel == "woo" and mapping.get("woo_product_id"):
            try:
                update_stock(int(mapping["woo_product_id"]), qty, store=store)
                if sync_price:
                    update_product_by_id(int(mapping["woo_product_id"]), {"regular_price": f"{price:.2f}"}, store=store)
                synced.append(int(internal_id))
            except Exception:
                logger.exception("Woo reconcile failed for %s", internal_id)

        if channel == "discogs" and mapping.get("discogs_listing_id"):
            try:
                update_listing_quantity(store, int(mapping["discogs_listing_id"]), qty)
                if sync_price:
                    update_listing(store, int(mapping["discogs_listing_id"]), {"price": f"{price:.2f}"})
                synced.append(int(internal_id))
            except Exception:
                logger.exception("Discogs reconcile failed for %s", internal_id)
    if channel == "discogs" and synced:
        update_discogs_sync_time(store_id)
    return synced
