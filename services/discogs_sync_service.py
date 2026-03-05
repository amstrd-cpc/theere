from __future__ import annotations

import datetime
import logging
import re
from typing import Any, Dict, Optional, Tuple

from db.connection import get_inventory_db
from services.discogs_service import (
    add_to_collection,
    create_listing,
    delete_listing,
    fetch_collection_releases,
    fetch_collection_release_instances,
    fetch_marketplace_orders,
    update_listing,
    update_listing_quantity,
    update_listing_status,
)
from services.inventory_service import (
    find_inventory_by_discogs_release_id,
    get_all_inventory,
    insert_inventory,
    update_inventory_fields,
)
from services.product_map_service import (
    find_mapping_by_discogs_listing_id,
    find_mapping_by_internal_id,
    upsert_product_map,
)
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


def _listing_payload_from_item(item: Dict[str, Any]) -> Dict[str, Any]:
    price = float(item.get("price_gel") or 0)
    quantity = int(item.get("quantity") or 0)
    return {
        "release_id": int(item.get("discogs_release_id")),
        "condition": item.get("condition") or "Mint (M)",
        "sleeve_condition": item.get("sleeve_condition") or "Generic",
        "price": f"{price:.2f}",
        "quantity": quantity,
        "status": "For Sale",
        "comments": item.get("description") or "",
    }


def update_listing_from_item(store: Dict[str, Any], listing_id: int, item: Dict[str, Any]) -> Dict[str, Any]:
    payload = _listing_payload_from_item(item)
    payload.pop("release_id", None)
    return update_listing(store, listing_id, payload)


def unlist_listing(store: Dict[str, Any], listing_id: int) -> Dict[str, Any]:
    return update_listing_status(store, listing_id, "Draft")


def relist_listing(store: Dict[str, Any], listing_id: int) -> Dict[str, Any]:
    return update_listing_status(store, listing_id, "For Sale")


def remove_listing(store: Dict[str, Any], listing_id: int) -> Dict[str, Any]:
    return delete_listing(store, listing_id)


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

        payload = _listing_payload_from_item(item)
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


def sync_discogs_item(store_id: int, internal_product_id: int) -> Dict[str, int]:
    store = get_store(store_id)
    if not store:
        return {"errors": 1}

    item = next((row for row in get_all_inventory() if int(row.get("id") or 0) == internal_product_id), None)
    if not item:
        return {"errors": 1}

    settings = get_store_settings(store_id)
    sync_price = bool(settings.get("discogs_price_sync"))
    listings_enabled = bool(settings.get("discogs_listings_enabled"))
    collection_enabled = bool(settings.get("discogs_collection_sync_enabled"))
    mapping = find_mapping_by_internal_id(store_id, internal_product_id)

    results = {
        "collection_added": 0,
        "collection_skipped": 0,
        "collection_failed": 0,
        "listing_updated": 0,
        "listing_published": 0,
        "listing_failed": 0,
        "skipped_missing": 0,
        "skipped_no_release": 0,
        "errors": 0,
    }

    release_id = item.get("discogs_release_id")
    if collection_enabled:
        if release_id:
            try:
                instances = fetch_collection_release_instances(store, int(release_id))
                current_count = len(instances.get("releases") or [])
                desired_count = max(1, int(item.get("quantity") or 0))
                missing = max(0, desired_count - current_count)
                for _ in range(missing):
                    add_to_collection(store, int(release_id))
                    results["collection_added"] += 1
                if missing == 0:
                    results["collection_skipped"] += 1
            except Exception:
                logger.exception("Failed syncing Discogs collection for inventory %s", internal_product_id)
                results["collection_failed"] += 1
                results["errors"] += 1
        else:
            results["skipped_no_release"] += 1

    if listings_enabled:
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
                results["errors"] += 1
        else:
            if not _has_listing_fields(item):
                results["skipped_missing"] += 1
            else:
                payload = _listing_payload_from_item(item)
                try:
                    listing = create_listing(store, payload)
                    listing_id = listing.get("id")
                    if listing_id:
                        upsert_product_map(
                            store_id=store_id,
                            internal_product_id=internal_product_id,
                            discogs_listing_id=int(listing_id),
                            discogs_release_id=int(item.get("discogs_release_id")),
                        )
                        results["listing_published"] += 1
                    else:
                        results["listing_failed"] += 1
                        results["errors"] += 1
                except Exception:
                    logger.exception("Failed publishing Discogs listing for inventory %s", internal_product_id)
                    results["listing_failed"] += 1
                    results["errors"] += 1

    if results["collection_added"] or results["listing_updated"] or results["listing_published"]:
        update_discogs_sync_time(store_id)

    return results


def _discogs_orders_processed(order_id: int) -> bool:
    with get_inventory_db() as conn:
        cur = conn.execute("SELECT 1 FROM discogs_orders WHERE order_id = ?", (order_id,))
        return cur.fetchone() is not None


def _mark_discogs_order_processed(order_id: int) -> None:
    now = datetime.datetime.now(datetime.UTC).isoformat()
    with get_inventory_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO discogs_orders (order_id, processed_at) VALUES (?, ?)",
            (order_id, now),
        )
        conn.commit()


def sync_discogs_orders(store_id: int) -> Dict[str, int]:
    store = get_store(store_id)
    if not store:
        return {"orders": 0, "applied": 0, "unmatched": 0}
    page = 1
    applied = 0
    unmatched = 0
    orders_seen = 0
    while True:
        payload = fetch_marketplace_orders(store, status="Payment Received", page=page)
        orders = payload.get("orders") or []
        if not orders:
            break
        for order in orders:
            order_id = order.get("id")
            if not order_id or _discogs_orders_processed(int(order_id)):
                continue
            orders_seen += 1
            for item in order.get("items", []):
                listing_id = item.get("listing_id")
                release_id = item.get("release_id")
                quantity = int(item.get("quantity") or 1)
                mapping = None
                if listing_id:
                    mapping = find_mapping_by_discogs_listing_id(store_id, int(listing_id))
                inventory_item = None
                if mapping and mapping.get("internal_product_id"):
                    from services.inventory_service import get_inventory_by_id

                    inventory_item = get_inventory_by_id(int(mapping["internal_product_id"]))
                if not inventory_item and release_id:
                    inventory_item = find_inventory_by_discogs_release_id(int(release_id))
                if not inventory_item:
                    unmatched += 1
                    continue
                current_qty = int(inventory_item.get("quantity") or 0)
                new_qty = max(0, current_qty - quantity)
                update_inventory_fields(
                    int(inventory_item["id"]),
                    {"quantity": new_qty},
                    sync_channels=False,
                    source="order_decrement",
                    correlation_id=str(order_id),
                    note="Discogs order decrement",
                )
                applied += 1
            _mark_discogs_order_processed(int(order_id))
        pagination = payload.get("pagination") or {}
        total_pages = int(pagination.get("pages") or page)
        if page >= total_pages:
            break
        page += 1
    return {"orders": orders_seen, "applied": applied, "unmatched": unmatched}


def bootstrap_collection_import(store_id: int) -> Dict[str, int]:
    store = get_store(store_id)
    if not store:
        return {"imported": 0, "updated": 0}
    now = datetime.datetime.now(datetime.UTC).isoformat()
    releases = fetch_collection_releases(store)
    release_counts: Dict[int, int] = {}
    for release in releases:
        release_id = release.get("id") or (release.get("basic_information") or {}).get("id")
        if not release_id:
            continue
        release_counts[int(release_id)] = release_counts.get(int(release_id), 0) + 1

    imported = 0
    updated = 0
    for release in releases:
        info = release.get("basic_information") or {}
        release_id = info.get("id") or release.get("id")
        if not release_id:
            continue
        release_id = int(release_id)
        count = release_counts.get(release_id, 1)
        existing = find_inventory_by_discogs_release_id(release_id)
        cover = None
        images = info.get("images") or []
        if images:
            cover = images[0].get("uri")
        if existing:
            updates: Dict[str, Any] = {}
            if int(existing.get("quantity") or 0) < count:
                updates["quantity"] = count
            if cover and not existing.get("cover_url"):
                updates["cover_url"] = cover
            if updates:
                update_inventory_fields(
                    int(existing["id"]),
                    updates,
                    sync_channels=False,
                    source="import_restore",
                    note="Discogs bootstrap import update",
                )
                updated += 1
            continue
        title = info.get("title") or release.get("title") or "Discogs Release"
        artists = info.get("artists") or []
        artist_names = [artist.get("name") for artist in artists if artist.get("name")]
        artist = ", ".join(artist_names)
        artist_album = f"{artist} - {title}" if artist else title
        labels = ", ".join(
            label.get("name") for label in (info.get("labels") or []) if isinstance(label, dict) and label.get("name")
        )
        formats = []
        for fmt in info.get("formats") or []:
            if not isinstance(fmt, dict):
                continue
            name = fmt.get("name")
            descriptions = fmt.get("descriptions") or []
            parts = [str(name)] if name else []
            parts.extend(str(desc) for desc in descriptions if desc)
            if parts:
                formats.append(" ".join(parts))
        item = {
            "artist_album": artist_album,
            "price_gel": 0.0,
            "quantity": count,
            "created_at": now,
            "updated_at": now,
            "local_rev": 1,
            "last_change_source": "import_restore",
            "label": labels,
            "format": ", ".join(formats),
            "year": info.get("year"),
            "cover_url": cover,
            "discogs_release_id": release_id,
            "discogs_uri": info.get("resource_url") or release.get("resource_url"),
        }
        insert_inventory(item)
        imported += 1
    return {"imported": imported, "updated": updated}
