from __future__ import annotations

from typing import Any, Dict, List

from core.application.ports.gateways import DiscogsGateway, WooGateway
from core.application.ports.notifier import Notifier
from core.application.ports.repositories import InventoryRepo, OrdersRepo, SalesRepo, SettingsProvider
from core.domain.models import ProcessingResult


def _extract_theere_id(line: Dict[str, Any]) -> int | None:
    for item in line.get("meta_data") or []:
        if str(item.get("key") or "").lower() == "theere_id":
            try:
                return int(item.get("value"))
            except (TypeError, ValueError):
                return None
    return None


def _line_item_price(line: Dict[str, Any], qty: int) -> float:
    try:
        if line.get("price") is not None:
            return float(line["price"])
        return float(line.get("total") or 0) / max(qty, 1)
    except Exception:
        return 0.0


def process_woo_order(
    *,
    store_id: int,
    woo_order_id: int,
    settings: SettingsProvider,
    orders_repo: OrdersRepo,
    inventory_repo: InventoryRepo,
    sales_repo: SalesRepo,
    woo_gateway: WooGateway,
    discogs_gateway: DiscogsGateway,
    notifier: Notifier,
) -> ProcessingResult:
    store = settings.get_store(store_id)
    if not store:
        raise ValueError(f"Store {store_id} not found")
    order = woo_gateway.fetch_order_by_id(store, woo_order_id)
    if not order:
        raise ValueError(f"Woo order {woo_order_id} not found")

    order_id = orders_repo.upsert_order_snapshot(store_id, order)
    existing = orders_repo.get_order_by_woo_id(store_id, woo_order_id)
    if existing and existing.get("inventory_applied_at"):
        return ProcessingResult(order_id=order_id)

    matched_items: List[Dict[str, Any]] = []
    unmapped_items: List[str] = []
    discogs_updates: List[tuple[int, int, float]] = []

    for line in order.get("line_items", []):
        internal_id = _extract_theere_id(line)
        mapping = None
        if internal_id:
            mapping = orders_repo.find_mapping(store_id, internal_id=internal_id)
        else:
            sku = (line.get("sku") or "").strip()
            if sku:
                mapping = orders_repo.find_mapping(store_id, sku=sku)
            if not mapping and line.get("variation_id"):
                mapping = orders_repo.find_mapping(store_id, variation_id=int(line["variation_id"]))
            if not mapping and line.get("product_id"):
                mapping = orders_repo.find_mapping(store_id, woo_product_id=int(line["product_id"]))
            if mapping:
                internal_id = int(mapping["internal_product_id"])

        qty = int(line.get("quantity") or 1)
        per_price = _line_item_price(line, qty)

        if not internal_id:
            unmapped_items.append(line.get("name") or "unknown")
            continue

        inserted = orders_repo.insert_order_line_item(
            order_id=order_id,
            woo_line_item_id=line.get("id"),
            internal_product_id=internal_id,
            sku=(line.get("sku") or None),
            quantity=qty,
            price=per_price,
        )
        if not inserted:
            continue

        inv = inventory_repo.get_by_id(internal_id)
        if not inv:
            unmapped_items.append(line.get("name") or "unknown")
            continue

        current_qty = int(inv.get("quantity") or 0)
        new_qty = max(0, current_qty - qty)
        inventory_repo.update_quantity(internal_id, new_qty, source="order_decrement", correlation_id=str(woo_order_id))

        for _ in range(qty):
            sales_repo.record_sale(inv, per_price, order.get("payment_method") or "woo")

        matched_items.append({"theere_id": internal_id, "name": line.get("name") or inv.get("artist_album") or "Unknown", "qty": qty, "remaining": new_qty})

        if mapping and mapping.get("discogs_listing_id"):
            discogs_updates.append((int(mapping["discogs_listing_id"]), new_qty, float(inv.get("price_gel") or 0)))

    store_settings = settings.get_store_settings(store_id)
    notify_admin_enabled = bool(store_settings.get("orders_admin_notifications"))

    if unmapped_items:
        orders_repo.mark_needs_review(order_id, True)
        if notify_admin_enabled:
            notifier.notify_admin(store, f"⚠️ Order {woo_order_id} has unmapped items: {', '.join(unmapped_items)}")
    else:
        orders_repo.mark_needs_review(order_id, False)
        orders_repo.mark_inventory_applied(order_id)

    if store_settings.get("discogs_sync_on_sale"):
        for listing_id, remaining, price in discogs_updates:
            discogs_gateway.update_listing_quantity(store, listing_id, remaining)
            if store_settings.get("discogs_price_sync"):
                discogs_gateway.update_listing(store, listing_id, {"price": f"{price:.2f}"})

    if matched_items and notify_admin_enabled:
        item_lines = "\n".join(f"• ID {item['theere_id']} — {item['name']} × {item['qty']}" for item in matched_items)
        notifier.notify_admin(store, f"💿 Woo order {woo_order_id} applied\n{item_lines}")

    return ProcessingResult(order_id=order_id, matched_items=matched_items, unmapped_items=unmapped_items)
