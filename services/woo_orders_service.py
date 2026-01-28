from __future__ import annotations

import datetime
import os
from typing import Any, Dict

from db.connection import get_inventory_db
from services.inventory_service import get_inventory_by_id, reduce_inventory_quantity, update_inventory_fields
from services.sales_service import record_sale


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

    if is_order_processed(order_id):
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
        if not sku:
            unmatched.append(line)
            continue
        try:
            item_id = int(sku)
        except (TypeError, ValueError):
            unmatched.append(line)
            continue

        inv = get_inventory_by_id(item_id)
        if not inv:
            unmatched.append(line)
            continue

        try:
            if line.get("price") is not None:
                per_price = float(line["price"])
            else:
                per_price = float(line.get("total", 0)) / max(qty, 1)
        except Exception:
            per_price = 0.0

        if not reduce_inventory_quantity(item_id, qty):
            unmatched.append(line)
            continue

        for _ in range(qty):
            record_sale(inv, per_price, payment_method)

        update_inventory_fields(
            item_id,
            {
                "woo_synced": 1,
                "woo_last_synced_at": datetime.datetime.utcnow().isoformat(),
            },
        )

        items.append((inv, qty, per_price))

    mark_order_processed(order_id)

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
