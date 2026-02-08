from __future__ import annotations

import logging
from typing import Any, Dict

from services.discogs_service import (
    add_to_collection,
    create_listing,
    fetch_collection_release_instances,
    update_listing,
    update_listing_quantity,
)
from services.inventory_service import get_all_inventory, update_inventory_fields
from services.product_map_service import find_mapping_by_internal_id, upsert_product_map
from services.store_service import get_store, get_store_settings, update_discogs_sync_time
from services.woo_service import fetch_product_by_id

logger = logging.getLogger(__name__)


def _parse_woo_snapshot(product: Dict[str, Any]) -> tuple[int, float]:
    quantity = int(product.get("stock_quantity") or 0)
    try:
        price = float(product.get("regular_price") or product.get("price") or 0)
    except (TypeError, ValueError):
        price = 0.0
    return quantity, price


def _has_listing_fields(item: Dict[str, Any]) -> bool:
    if not item.get("discogs_release_id"):
        return False
    if not (item.get("condition") or "").strip():
        return False
    if not (item.get("sleeve_condition") or "").strip():
        return False
    if float(item.get("price_gel") or 0) <= 0:
        return False
    if not (item.get("description") or "").strip():
        return False
    return True


def sync_all_discogs(store_id: int, *, publish_missing: bool) -> Dict[str, int]:
    store = get_store(store_id)
    if not store:
        return {"errors": 1}

    settings = get_store_settings(store_id)
    sync_price = bool(settings.get("discogs_price_sync"))
    items = get_all_inventory()
    results = {
        "total_items": len(items),
        "woo_synced": 0,
        "woo_failed": 0,
        "collection_added": 0,
        "collection_failed": 0,
        "collection_skipped": 0,
        "listing_updated": 0,
        "listing_published": 0,
        "listing_failed": 0,
        "skipped_missing": 0,
        "skipped_no_release": 0,
    }

    for item in items:
        item_id = int(item.get("id") or 0)
        mapping = find_mapping_by_internal_id(store_id, item_id)
        if mapping and mapping.get("woo_product_id"):
            try:
                product = fetch_product_by_id(int(mapping["woo_product_id"]), store=store)
                quantity, price = _parse_woo_snapshot(product)
                update_inventory_fields(
                    item_id,
                    {"quantity": quantity, "price_gel": price},
                    sync_channels=False,
                )
                item["quantity"] = quantity
                item["price_gel"] = price
                results["woo_synced"] += 1
            except Exception:
                logger.exception("Failed syncing Woo data for inventory %s", item_id)
                results["woo_failed"] += 1

        release_id = item.get("discogs_release_id")
        if release_id:
            target_qty = max(0, int(item.get("quantity") or 0))
            try:
                instances = fetch_collection_release_instances(store, int(release_id))
                current_qty = len(instances)
            except Exception:
                logger.exception("Failed checking Discogs collection for release %s", release_id)
                results["collection_failed"] += 1
                current_qty = None

            if current_qty is None:
                pass
            elif current_qty >= target_qty:
                results["collection_skipped"] += 1
            else:
                to_add = target_qty - current_qty
                for _ in range(to_add):
                    try:
                        add_to_collection(store, int(release_id))
                        results["collection_added"] += 1
                    except Exception:
                        logger.exception("Failed adding release %s to Discogs collection", release_id)
                        results["collection_failed"] += 1
        else:
            results["skipped_no_release"] += 1

        listing_id = mapping.get("discogs_listing_id") if mapping else None
        quantity = int(item.get("quantity") or 0)
        price = float(item.get("price_gel") or 0)
        if listing_id:
            try:
                update_listing_quantity(store, int(listing_id), quantity)
                if sync_price:
                    update_listing(store, int(listing_id), {"price": f"{price:.2f}"})
                results["listing_updated"] += 1
            except Exception:
                logger.exception("Failed updating Discogs listing %s", listing_id)
                results["listing_failed"] += 1
            continue

        if not publish_missing:
            continue

        if not _has_listing_fields(item):
            results["skipped_missing"] += 1
            continue

        payload = {
            "release_id": int(item.get("discogs_release_id")),
            "condition": item.get("condition") or "Mint (M)",
            "sleeve_condition": item.get("sleeve_condition") or "Generic",
            "price": f"{price:.2f}",
            "quantity": quantity,
            "status": "For Sale",
            "comments": item.get("description") or "",
        }
        try:
            listing = create_listing(store, payload)
            listing_id = listing.get("id")
            if listing_id:
                upsert_product_map(
                    store_id=store_id,
                    internal_product_id=item_id,
                    discogs_listing_id=int(listing_id),
                    discogs_release_id=int(item.get("discogs_release_id")),
                )
                results["listing_published"] += 1
            else:
                results["listing_failed"] += 1
        except Exception:
            logger.exception("Failed publishing Discogs listing for inventory %s", item_id)
            results["listing_failed"] += 1

    if results["listing_updated"] or results["listing_published"]:
        update_discogs_sync_time(store_id)

    return results
