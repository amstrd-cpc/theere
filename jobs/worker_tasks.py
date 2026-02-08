from __future__ import annotations

import datetime
import logging
from typing import Any, Dict, List

from services import order_service
from services.inventory_service import get_inventory_by_id, update_inventory_fields
from services.notification_service import notify_admin
from services.product_map_service import (
    find_mapping_by_internal_id,
    find_mapping_by_sku,
    find_mapping_by_woo_product_id,
    find_mapping_by_variation_id,
)
from services.sales_service import record_sale
from services.store_service import get_store, get_store_settings
from services.webhook_event_service import get_webhook_event, mark_webhook_failed, mark_webhook_processed
from services.woo_service import fetch_order_by_id
from services.discogs_service import update_listing, update_listing_quantity

logger = logging.getLogger(__name__)


def process_woo_webhook_event(event_id: int) -> None:
    event = get_webhook_event(event_id)
    if not event:
        logger.warning("Webhook event %s not found", event_id)
        return

    store = get_store(int(event["store_id"]))
    if not store:
        logger.warning("Store %s not found for webhook event %s", event.get("store_id"), event_id)
        return

    try:
        if event.get("woo_order_id"):
            sync_order_state(int(event["store_id"]), int(event["woo_order_id"]))
        mark_webhook_processed(event_id)
    except Exception as exc:
        logger.exception("Failed processing webhook event %s", event_id)
        mark_webhook_failed(event_id, str(exc))
        notify_admin(store, f"⚠️ Webhook event {event_id} failed: {exc}")
        raise


def sync_order_state(store_id: int, woo_order_id: int) -> None:
    store = get_store(store_id)
    if not store:
        logger.warning("Store %s not found for order sync", store_id)
        return
    order = fetch_order_by_id(store, woo_order_id)
    if not order:
        logger.warning("Woo order %s not found for store %s", woo_order_id, store_id)
        return
    order_id = order_service.upsert_order_snapshot(store_id, order)
    settings = get_store_settings(store_id)
    trigger_status = (settings.get("auto_decrement_status") or "processing").lower()
    if settings.get("auto_decrement_enabled") and (order.get("status") or "").lower() == trigger_status:
        apply_inventory_decrement_for_order(store_id, woo_order_id, order=order, order_id=order_id)


def apply_inventory_decrement_for_order(
    store_id: int,
    woo_order_id: int,
    *,
    order: Dict[str, Any] | None = None,
    order_id: int | None = None,
) -> None:
    store = get_store(store_id)
    if not store:
        logger.warning("Store %s not found for inventory apply", store_id)
        return

    if order is None:
        order = fetch_order_by_id(store, woo_order_id)
        if not order:
            return

    if order_id is None:
        existing = order_service.get_order_by_woo_id(store_id, woo_order_id)
        order_id = int(existing["id"]) if existing else order_service.upsert_order_snapshot(store_id, order)

    existing = order_service.get_order_by_woo_id(store_id, woo_order_id)
    if existing and existing.get("inventory_applied_at"):
        logger.info("Inventory already applied for order %s", woo_order_id)
        return

    matched_items: List[Dict[str, Any]] = []
    unmapped_items: List[str] = []
    discogs_updates: List[tuple[int, int, float]] = []

    for line in order.get("line_items", []):
        theere_id = _extract_theere_id(line)
        mapping = None
        internal_id = None
        if theere_id:
            internal_id = theere_id
            mapping = find_mapping_by_internal_id(store_id, internal_id)
        else:
            sku = (line.get("sku") or "").strip()
            if sku:
                mapping = find_mapping_by_sku(store_id, sku)
            if not mapping and line.get("variation_id"):
                mapping = find_mapping_by_variation_id(store_id, int(line["variation_id"]))
            if not mapping and line.get("product_id"):
                mapping = find_mapping_by_woo_product_id(store_id, int(line["product_id"]))
            if mapping:
                internal_id = int(mapping["internal_product_id"])

        qty = int(line.get("quantity") or 1)
        per_price = _line_item_price(line, qty)

        if not internal_id:
            unmapped_items.append(line.get("name") or "unknown")
            continue

        inserted = order_service.insert_order_line_item(
            order_id=order_id,
            woo_line_item_id=line.get("id"),
            internal_product_id=internal_id,
            sku=(line.get("sku") or None),
            quantity=qty,
            price=per_price,
        )

        if not inserted:
            continue

        inv = get_inventory_by_id(internal_id)
        if not inv:
            unmapped_items.append(line.get("name") or "unknown")
            continue

        current_qty = int(inv.get("quantity") or 0)
        new_qty = max(0, current_qty - qty)
        update_inventory_fields(
            internal_id,
            {
                "quantity": new_qty,
                "woo_synced": 1,
                "woo_last_synced_at": datetime.datetime.utcnow().isoformat(),
            },
            sync_channels=False,
            source="order_decrement",
            store_id=store_id,
            correlation_id=str(woo_order_id),
            note=f"Woo order {woo_order_id} decrement",
        )
        for _ in range(qty):
            record_sale(inv, per_price, order.get("payment_method") or "woo")

        matched_items.append(
            {
                "theere_id": internal_id,
                "name": line.get("name") or inv.get("artist_album") or "Unknown",
                "qty": qty,
                "remaining": new_qty,
            }
        )

        if mapping and mapping.get("discogs_listing_id"):
            discogs_updates.append((int(mapping["discogs_listing_id"]), new_qty, float(inv.get("price_gel") or 0)))

    settings = get_store_settings(store_id)
    notify_admin_enabled = bool(settings.get("orders_admin_notifications"))

    if unmapped_items:
        order_service.mark_needs_review(order_id, True)
        if notify_admin_enabled:
            notify_admin(
                store,
                f"⚠️ Order {woo_order_id} has unmapped items: {', '.join(unmapped_items)}",
            )
    else:
        order_service.mark_needs_review(order_id, False)
        order_service.mark_inventory_applied(order_id)

    if settings.get("discogs_sync_on_sale"):
        for listing_id, remaining, price in discogs_updates:
            try:
                update_listing_quantity(store, listing_id, remaining)
                if settings.get("discogs_price_sync"):
                    update_listing(store, listing_id, {"price": f"{price:.2f}"})
            except Exception as exc:
                logger.exception("Failed updating Discogs listing %s", listing_id)
                if notify_admin_enabled:
                    notify_admin(store, f"⚠️ Discogs update failed for listing {listing_id}: {exc}")

    if matched_items and notify_admin_enabled:
        item_lines = "\n".join(
            f"• ID {item['theere_id']} — {item['name']} × {item['qty']}"
            for item in matched_items
        )
        notes = (order.get("customer_note") or "").strip()
        note_line = f"\n📝 Notes: {notes}" if notes else ""
        total = order.get("total")
        currency = order.get("currency") or "GEL"
        notify_admin(
            store,
            f"💿 Woo order {woo_order_id} applied\n"
            f"{item_lines}\n"
            f"💰 Total: {total} {currency}{note_line}",
        )


def _extract_theere_id(line: Dict[str, Any]) -> int | None:
    meta = line.get("meta_data") or []
    for item in meta:
        key = (item.get("key") or "").lower()
        if key == "theere_id":
            try:
                return int(item.get("value"))
            except (TypeError, ValueError):
                return None
    return None


def _line_item_price(line: Dict[str, Any], qty: int) -> float:
    try:
        if line.get("price") is not None:
            return float(line["price"])
        total = float(line.get("total") or 0)
        return total / max(qty, 1)
    except Exception:
        return 0.0
