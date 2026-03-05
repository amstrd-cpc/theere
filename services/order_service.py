from __future__ import annotations

import datetime
import hashlib
import json
from typing import Any, Dict, List, Optional

from db.connection import get_inventory_db


def _hash_payload(payload: Dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def upsert_order_snapshot(store_id: int, order: Dict[str, Any]) -> int:
    now = datetime.datetime.now(datetime.UTC).isoformat()
    woo_order_id = int(order.get("id"))
    status = (order.get("status") or "").lower()
    billing = order.get("billing") or {}
    shipping = order.get("shipping") or {}
    billing_name = f"{billing.get('first_name', '')} {billing.get('last_name', '')}".strip()
    shipping_name = f"{shipping.get('first_name', '')} {shipping.get('last_name', '')}".strip()
    payload_hash = _hash_payload(order)

    with get_inventory_db() as conn:
        cur = conn.execute(
            """
            SELECT id, last_seen_hash
            FROM orders
            WHERE store_id = ? AND woo_order_id = ?
            """,
            (store_id, woo_order_id),
        )
        existing = cur.fetchone()
        if existing:
            order_id = int(existing[0])
            conn.execute(
                """
                UPDATE orders
                SET status = ?, total = ?, currency = ?, billing_name = ?, billing_email = ?,
                    billing_phone = ?, shipping_name = ?, updated_at = ?, last_seen_hash = ?
                WHERE id = ?
                """,
                (
                    status,
                    order.get("total"),
                    order.get("currency"),
                    billing_name,
                    billing.get("email"),
                    billing.get("phone"),
                    shipping_name,
                    now,
                    payload_hash,
                    order_id,
                ),
            )
            conn.commit()
            return order_id

        cur = conn.execute(
            """
            INSERT INTO orders (
                store_id,
                woo_order_id,
                status,
                total,
                currency,
                billing_name,
                billing_email,
                billing_phone,
                shipping_name,
                created_at,
                updated_at,
                last_seen_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                store_id,
                woo_order_id,
                status,
                order.get("total"),
                order.get("currency"),
                billing_name,
                billing.get("email"),
                billing.get("phone"),
                shipping_name,
                order.get("date_created") or now,
                now,
                payload_hash,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def mark_inventory_applied(order_id: int) -> None:
    now = datetime.datetime.now(datetime.UTC).isoformat()
    with get_inventory_db() as conn:
        conn.execute(
            "UPDATE orders SET inventory_applied_at = ? WHERE id = ?",
            (now, order_id),
        )
        conn.commit()


def mark_needs_review(order_id: int, needs_review: bool) -> None:
    with get_inventory_db() as conn:
        conn.execute(
            "UPDATE orders SET needs_review = ? WHERE id = ?",
            (1 if needs_review else 0, order_id),
        )
        conn.commit()


def get_order_by_woo_id(store_id: int, woo_order_id: int) -> Optional[Dict[str, Any]]:
    with get_inventory_db() as conn:
        cur = conn.execute(
            "SELECT * FROM orders WHERE store_id = ? AND woo_order_id = ?",
            (store_id, woo_order_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def list_recent_orders(store_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    with get_inventory_db() as conn:
        cur = conn.execute(
            """
            SELECT * FROM orders
            WHERE store_id = ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (store_id, limit),
        )
        return [dict(row) for row in cur.fetchall()]


def insert_order_line_item(
    *,
    order_id: int,
    woo_line_item_id: Optional[int],
    internal_product_id: Optional[int],
    sku: Optional[str],
    quantity: int,
    price: float,
) -> bool:
    with get_inventory_db() as conn:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO order_line_items (
                order_id,
                woo_line_item_id,
                internal_product_id,
                sku,
                quantity,
                price
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (order_id, woo_line_item_id, internal_product_id, sku, quantity, price),
        )
        conn.commit()
        return cur.rowcount > 0
