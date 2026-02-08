from __future__ import annotations

import datetime
import logging
import os
from typing import Any, Dict

from db.connection import get_inventory_db
from services.inventory_service import (
    get_inventory_by_id,
    get_inventory_by_woo_product_id,
    update_inventory_fields,
)
from services.sales_service import record_sale

logger = logging.getLogger(__name__)


def _auto_sell_enabled() -> bool:
    value = (os.getenv("AUTO_SELL_WOO", "1") or "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def is_order_processed(order_id: int) -> bool:
    with get_inventory_db(row_factory=None) as conn:
        cur = conn.execute("SELECT 1 FROM woo_orders WHERE order_id = ?", (order_id,))
        return cur.fetchone() is not None


def mark_order_processed(order_id: int) -> None:
    now = datetime.datetime.now(datetime.UTC).isoformat()
    with get_inventory_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO woo_orders (order_id, processed_at) VALUES (?, ?)",
            (order_id, now),
        )
        conn.commit()


def process_woo_order(order: Dict[str, Any]) -> Dict[str, Any]:
    order_id = order.get("id")
    if not order_id:
        return {"order_id": None, "already_processed": False, "items": [], "unmatched": []}

    status = (order.get("status") or "").lower().strip()
    eligible_statuses = {"processing", "completed"}
    logger.info("Woo order received id=%s status=%s", order_id, status or "unknown")

    if is_order_processed(order_id):
        logger.info("Woo order %s already processed (dedupe hit)", order_id)
        return {
            "order_id": order_id,
            "status": status,
            "payment_method": order.get("payment_method"),
            "billing_name": f"{order.get('billing', {}).get('first_name', '')} {order.get('billing', {}).get('last_name', '')}".strip(),
            "items": [],
            "unmatched": [],
            "currency": order.get("currency"),
            "order_total": order.get("total"),
            "already_processed": True,
            "skipped": False,
        }

    if status and status not in eligible_statuses:
        logger.info("Woo order %s skipped due to status=%s", order_id, status)
        return {
            "order_id": order_id,
            "status": status,
            "payment_method": order.get("payment_method"),
            "billing_name": f"{order.get('billing', {}).get('first_name', '')} {order.get('billing', {}).get('last_name', '')}".strip(),
            "items": [],
            "unmatched": [],
            "currency": order.get("currency"),
            "order_total": order.get("total"),
            "already_processed": False,
            "skipped": True,
            "skip_reason": f"Order status '{status}' is not eligible for auto-sell.",
        }

    if not _auto_sell_enabled():
        mark_order_processed(order_id)
        logger.info("Woo auto-sell disabled; order %s recorded without inventory changes", order_id)
        return {
            "order_id": order_id,
            "status": status,
            "payment_method": order.get("payment_method"),
            "billing_name": f"{order.get('billing', {}).get('first_name', '')} {order.get('billing', {}).get('last_name', '')}".strip(),
            "items": [],
            "unmatched": [],
            "currency": order.get("currency"),
            "order_total": order.get("total"),
            "already_processed": False,
            "skipped": True,
            "skip_reason": "AUTO_SELL_WOO is disabled; notification only.",
        }

    items = []
    unmatched = []

    payment_method = order.get("payment_method") or "woo"

    for line in order.get("line_items", []):
        sku = line.get("sku")
        qty = int(line.get("quantity", 1))
        item_id = None
        inv = None
        if sku and str(sku).strip().isdigit():
            item_id = int(sku)
            inv = get_inventory_by_id(item_id)
        if not inv:
            product_id = line.get("product_id")
            if product_id:
                inv = get_inventory_by_woo_product_id(int(product_id))
                if inv:
                    item_id = int(inv["id"])

        if not inv or not item_id:
            logger.warning(
                "Woo line item unmatched (sku=%s product_id=%s name=%s)",
                sku,
                line.get("product_id"),
                line.get("name"),
            )
            unmatched.append(line)
            continue

        try:
            if line.get("price") is not None:
                per_price = float(line["price"])
            else:
                per_price = float(line.get("total", 0)) / max(qty, 1)
        except Exception:
            per_price = 0.0

        current_qty = int(inv.get("quantity") or 0)
        new_qty = max(0, current_qty - qty)
        update_inventory_fields(
            item_id,
            {
                "quantity": new_qty,
                "woo_synced": 1,
                "woo_last_synced_at": datetime.datetime.utcnow().isoformat(),
            },
            sync_channels=False,
            source="order_decrement",
            correlation_id=str(order_id),
            note=f"Woo order {order_id} decrement",
        )
        logger.info("Woo stock decrement id=%s: %s -> %s", item_id, current_qty, new_qty)

        for _ in range(qty):
            record_sale(inv, per_price, payment_method)
        logger.info("Woo mapped item sku=%s product_id=%s -> inventory=%s qty=%s", sku, line.get("product_id"), item_id, qty)
        items.append((inv, qty, per_price, new_qty))

    mark_order_processed(order_id)
    logger.info("Woo order %s marked processed", order_id)

    return {
        "order_id": order_id,
        "status": status,
        "payment_method": payment_method,
        "billing_name": f"{order.get('billing', {}).get('first_name', '')} {order.get('billing', {}).get('last_name', '')}".strip(),
        "items": items,
        "unmatched": unmatched,
        "currency": order.get("currency"),
        "order_total": order.get("total"),
        "already_processed": False,
        "skipped": False,
    }
