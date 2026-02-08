from __future__ import annotations

import datetime
import hashlib
import logging
from typing import Any, Dict, Optional, Tuple

from services.discogs_service import fetch_listing, update_listing, update_listing_quantity
from services.inventory_service import get_inventory_by_id, update_inventory_fields
from services.product_map_service import list_product_mappings, update_product_map_fields
from services.store_service import get_store, get_store_settings
from services.woo_service import fetch_product_by_id, update_product_by_id, update_stock

logger = logging.getLogger(__name__)


def _hash_state(quantity: int, price: float) -> str:
    payload = f"{int(quantity)}|{float(price):.2f}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _parse_timestamp(value: Optional[str]) -> Optional[datetime.datetime]:
    if not value:
        return None
    try:
        cleaned = value.replace("Z", "+00:00")
        return datetime.datetime.fromisoformat(cleaned)
    except ValueError:
        return None


def _discogs_snapshot(listing: Dict[str, Any]) -> Tuple[int, float, Optional[datetime.datetime]]:
    quantity = int(listing.get("quantity") or 0)
    try:
        price = float(listing.get("price") or 0)
    except (TypeError, ValueError):
        price = 0.0
    timestamp = _parse_timestamp(listing.get("updated") or listing.get("posted"))
    return quantity, price, timestamp


def _woo_snapshot(product: Dict[str, Any]) -> Tuple[int, float, Optional[datetime.datetime]]:
    quantity = int(product.get("stock_quantity") or 0)
    try:
        price = float(product.get("regular_price") or product.get("price") or 0)
    except (TypeError, ValueError):
        price = 0.0
    timestamp = _parse_timestamp(product.get("date_modified_gmt") or product.get("date_modified"))
    return quantity, price, timestamp


def _local_snapshot(item: Dict[str, Any]) -> Tuple[int, float]:
    quantity = int(item.get("quantity") or 0)
    price = float(item.get("price_gel") or 0)
    return quantity, price


def _should_pull_remote(
    *,
    remote_hash: str,
    local_hash: str,
    remote_changed: bool,
    local_changed: bool,
    last_sync_direction: str,
    last_sync_hash: Optional[str],
    last_sync_at: Optional[datetime.datetime],
    remote_timestamp: Optional[datetime.datetime],
) -> bool:
    if remote_hash == local_hash:
        return False
    if last_sync_hash is None:
        return True
    if remote_changed and not local_changed:
        return True
    if remote_changed and local_changed and remote_timestamp and last_sync_at:
        return remote_timestamp > last_sync_at
    if local_hash == last_sync_hash and last_sync_direction.startswith("from_"):
        return False
    return False


def _should_push_local(
    *,
    remote_hash: str,
    local_hash: str,
    remote_changed: bool,
    local_changed: bool,
    last_sync_direction: str,
    last_sync_hash: Optional[str],
) -> bool:
    if remote_hash == local_hash:
        return False
    if last_sync_hash is None:
        return False
    if local_changed:
        return True
    if not remote_changed and local_hash == last_sync_hash and last_sync_direction.startswith("from_"):
        return True
    return False


def poll_discogs_listings(store_id: int) -> None:
    store = get_store(store_id)
    if not store:
        return
    settings = get_store_settings(store_id)
    sync_price = bool(settings.get("discogs_price_sync"))
    mappings = list_product_mappings(store_id)
    for mapping in mappings:
        listing_id = mapping.get("discogs_listing_id")
        internal_id = mapping.get("internal_product_id")
        if not listing_id or not internal_id:
            continue
        item = get_inventory_by_id(int(internal_id))
        if not item:
            continue
        try:
            listing = fetch_listing(store, int(listing_id))
        except Exception:
            logger.exception("Failed fetching Discogs listing %s", listing_id)
            continue

        remote_qty, remote_price, remote_timestamp = _discogs_snapshot(listing)
        local_qty, local_price = _local_snapshot(item)
        remote_hash = _hash_state(remote_qty, remote_price)
        local_hash = _hash_state(local_qty, local_price)
        remote_changed = remote_hash != mapping.get("discogs_last_seen_hash")
        last_sync_hash = mapping.get("last_sync_hash")
        last_sync_direction = mapping.get("last_sync_direction") or ""
        last_sync_at = _parse_timestamp(mapping.get("last_sync_at"))
        local_changed = bool(last_sync_hash) and local_hash != last_sync_hash

        if _should_pull_remote(
            remote_hash=remote_hash,
            local_hash=local_hash,
            remote_changed=remote_changed,
            local_changed=local_changed,
            last_sync_direction=last_sync_direction,
            last_sync_hash=last_sync_hash,
            last_sync_at=last_sync_at,
            remote_timestamp=remote_timestamp,
        ):
            update_inventory_fields(
                int(internal_id),
                {"quantity": remote_qty, "price_gel": remote_price},
                sync_channels=False,
            )
            update_product_map_fields(
                store_id,
                int(internal_id),
                {
                    "last_sync_direction": "from_discogs",
                    "last_sync_hash": remote_hash,
                    "last_sync_at": datetime.datetime.utcnow().isoformat(),
                },
            )
            local_qty, local_price = remote_qty, remote_price
            local_hash = remote_hash
        elif _should_push_local(
            remote_hash=remote_hash,
            local_hash=local_hash,
            remote_changed=remote_changed,
            local_changed=local_changed,
            last_sync_direction=last_sync_direction,
            last_sync_hash=last_sync_hash,
        ):
            try:
                update_listing_quantity(store, int(listing_id), local_qty)
                if sync_price:
                    update_listing(store, int(listing_id), {"price": f"{local_price:.2f}"})
            except Exception:
                logger.exception("Failed updating Discogs listing %s", listing_id)
            update_product_map_fields(
                store_id,
                int(internal_id),
                {
                    "last_sync_direction": "to_discogs",
                    "last_sync_hash": local_hash,
                    "last_sync_at": datetime.datetime.utcnow().isoformat(),
                },
            )

        update_product_map_fields(
            store_id,
            int(internal_id),
            {
                "discogs_last_seen_quantity": remote_qty,
                "discogs_last_seen_price": remote_price,
                "discogs_last_seen_at": datetime.datetime.utcnow().isoformat(),
                "discogs_last_seen_hash": remote_hash,
            },
        )


def poll_woo_products(store_id: int) -> None:
    store = get_store(store_id)
    if not store:
        return
    mappings = list_product_mappings(store_id)
    for mapping in mappings:
        product_id = mapping.get("woo_product_id")
        internal_id = mapping.get("internal_product_id")
        if not product_id or not internal_id:
            continue
        item = get_inventory_by_id(int(internal_id))
        if not item:
            continue
        try:
            product = fetch_product_by_id(int(product_id), store=store)
        except Exception:
            logger.exception("Failed fetching Woo product %s", product_id)
            continue

        remote_qty, remote_price, remote_timestamp = _woo_snapshot(product)
        local_qty, local_price = _local_snapshot(item)
        remote_hash = _hash_state(remote_qty, remote_price)
        local_hash = _hash_state(local_qty, local_price)
        remote_changed = remote_hash != mapping.get("woo_last_seen_hash")
        last_sync_hash = mapping.get("last_sync_hash")
        last_sync_direction = mapping.get("last_sync_direction") or ""
        last_sync_at = _parse_timestamp(mapping.get("last_sync_at"))
        local_changed = bool(last_sync_hash) and local_hash != last_sync_hash

        if _should_pull_remote(
            remote_hash=remote_hash,
            local_hash=local_hash,
            remote_changed=remote_changed,
            local_changed=local_changed,
            last_sync_direction=last_sync_direction,
            last_sync_hash=last_sync_hash,
            last_sync_at=last_sync_at,
            remote_timestamp=remote_timestamp,
        ):
            update_inventory_fields(
                int(internal_id),
                {"quantity": remote_qty, "price_gel": remote_price},
                sync_channels=False,
            )
            update_product_map_fields(
                store_id,
                int(internal_id),
                {
                    "last_sync_direction": "from_woo",
                    "last_sync_hash": remote_hash,
                    "last_sync_at": datetime.datetime.utcnow().isoformat(),
                },
            )
            local_qty, local_price = remote_qty, remote_price
            local_hash = remote_hash
        elif _should_push_local(
            remote_hash=remote_hash,
            local_hash=local_hash,
            remote_changed=remote_changed,
            local_changed=local_changed,
            last_sync_direction=last_sync_direction,
            last_sync_hash=last_sync_hash,
        ):
            try:
                update_stock(int(product_id), local_qty, store=store)
                update_product_by_id(int(product_id), {"regular_price": f"{local_price:.2f}"}, store=store)
            except Exception:
                logger.exception("Failed updating Woo product %s", product_id)
            update_product_map_fields(
                store_id,
                int(internal_id),
                {
                    "last_sync_direction": "to_woo",
                    "last_sync_hash": local_hash,
                    "last_sync_at": datetime.datetime.utcnow().isoformat(),
                },
            )

        update_product_map_fields(
            store_id,
            int(internal_id),
            {
                "woo_last_seen_quantity": remote_qty,
                "woo_last_seen_price": remote_price,
                "woo_last_seen_at": datetime.datetime.utcnow().isoformat(),
                "woo_last_seen_hash": remote_hash,
            },
        )
