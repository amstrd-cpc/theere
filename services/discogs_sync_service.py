from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional, Tuple

from services.discogs_service import (
    add_to_collection,
    create_listing,
    fetch_collection_releases,
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


def _normalize_collection_key(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    return " ".join(normalized.split())


def _collection_key_from_release(release: Dict[str, Any]) -> Optional[str]:
    info = release.get("basic_information") or {}
    title = info.get("title") or release.get("title")
    if not title:
        return None
    artists = info.get("artists") or release.get("artists") or []
    artist_names = [artist.get("name") for artist in artists if artist.get("name")]
    artist = ", ".join(artist_names)
    if artist:
        return _normalize_collection_key(f"{artist} - {title}")
    return _normalize_collection_key(str(title))


def _collection_key_from_item(item: Dict[str, Any]) -> Optional[str]:
    artist_album = str(item.get("artist_album") or "").strip()
    if not artist_album:
        return None
    return _normalize_collection_key(artist_album)


def _build_collection_index(store: Dict[str, Any]) -> Tuple[Dict[int, int], Dict[str, int]]:
    release_counts: Dict[int, int] = {}
    name_counts: Dict[str, int] = {}
    try:
        releases = fetch_collection_releases(store)
    except Exception:
        logger.exception("Failed fetching Discogs collection snapshot")
        return release_counts, name_counts
    for release in releases:
        release_id = release.get("id") or (release.get("basic_information") or {}).get("id")
        if release_id:
            release_id = int(release_id)
            release_counts[release_id] = release_counts.get(release_id, 0) + 1
        name_key = _collection_key_from_release(release)
        if name_key:
            name_counts[name_key] = name_counts.get(name_key, 0) + 1
    return release_counts, name_counts


def sync_all_discogs(store_id: int, *, publish_missing: bool) -> Dict[str, int]:
    store = get_store(store_id)
    if not store:
        return {"errors": 1}

    settings = get_store_settings(store_id)
    sync_price = bool(settings.get("discogs_price_sync"))
    listings_enabled = bool(settings.get("discogs_listings_enabled"))
    items = get_all_inventory()
    collection_release_counts, collection_name_counts = _build_collection_index(store)
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
                    source="sync_pull",
                    store_id=store_id,
                    note="Woo snapshot applied during Discogs sync",
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
            name_key = _collection_key_from_item(item)
            current_qty = None
            candidates = []
            release_count = collection_release_counts.get(int(release_id))
            if release_count is not None:
                candidates.append(release_count)
            if name_key:
                name_count = collection_name_counts.get(name_key)
                if name_count is not None:
                    candidates.append(name_count)
            if candidates:
                current_qty = max(candidates)
            else:
                try:
                    instances = fetch_collection_release_instances(store, int(release_id))
                    current_qty = len(instances)
                    collection_release_counts[int(release_id)] = current_qty
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
                        collection_release_counts[int(release_id)] = (
                            collection_release_counts.get(int(release_id), current_qty) + 1
                        )
                        if name_key:
                            collection_name_counts[name_key] = collection_name_counts.get(name_key, current_qty) + 1
                    except Exception:
                        logger.exception("Failed adding release %s to Discogs collection", release_id)
                        results["collection_failed"] += 1
        else:
            results["skipped_no_release"] += 1

        listing_id = mapping.get("discogs_listing_id") if mapping else None
        quantity = int(item.get("quantity") or 0)
        price = float(item.get("price_gel") or 0)
        if listings_enabled and listing_id:
            try:
                update_listing_quantity(store, int(listing_id), quantity)
                if sync_price:
                    update_listing(store, int(listing_id), {"price": f"{price:.2f}"})
                results["listing_updated"] += 1
            except Exception:
                logger.exception("Failed updating Discogs listing %s", listing_id)
                results["listing_failed"] += 1
            continue

        if not publish_missing or not listings_enabled:
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

    if results["listing_updated"] or results["listing_published"] or results["collection_added"]:
        update_discogs_sync_time(store_id)

    return results
