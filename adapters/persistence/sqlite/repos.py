from __future__ import annotations

import datetime
import hashlib
import json
from typing import Any, Dict, Optional

from db.connection import get_inventory_db, get_sales_db
from core.domain.models import InventoryItem


class SqliteInventoryRepo:
    def create_supplier_if_missing(self, name: str) -> int:
        with get_inventory_db() as conn:
            cur = conn.execute("SELECT id FROM supplier WHERE name = ?", (name,))
            row = cur.fetchone()
            if row:
                return int(row["id"])
            cur = conn.execute("INSERT INTO supplier (name) VALUES (?)", (name,))
            conn.commit()
            return int(cur.lastrowid)

    def add_item(self, item: InventoryItem) -> int:
        now = datetime.datetime.utcnow().isoformat()
        with get_inventory_db() as conn:
            cur = conn.execute(
                """
                INSERT INTO inventory (
                    artist_album, genre, style, label, format, condition, sleeve_condition, price_gel,
                    quantity, supplier_id, created_at, updated_at, year, description, cover_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.artist_album,
                    item.genre,
                    item.style,
                    item.label,
                    item.format,
                    item.condition,
                    item.sleeve_condition,
                    item.price_gel,
                    item.quantity,
                    item.supplier_id,
                    now,
                    now,
                    item.year,
                    item.description,
                    item.cover_url,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def get_by_id(self, item_id: int) -> Optional[Dict[str, Any]]:
        with get_inventory_db() as conn:
            cur = conn.execute("SELECT * FROM inventory WHERE id = ?", (item_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def update_quantity(self, item_id: int, new_quantity: int, *, source: str, correlation_id: str) -> None:
        now = datetime.datetime.utcnow().isoformat()
        with get_inventory_db() as conn:
            conn.execute(
                """
                UPDATE inventory SET quantity = ?, updated_at = ?, woo_synced = 1, woo_last_synced_at = ?
                WHERE id = ?
                """,
                (new_quantity, now, now, item_id),
            )
            conn.execute(
                """
                INSERT INTO inventory_events (inventory_id, event_type, source, correlation_id, notes, created_at)
                VALUES (?, 'quantity_update', ?, ?, ?, ?)
                """,
                (item_id, source, correlation_id, f"quantity={new_quantity}", now),
            )
            conn.commit()


class SqliteSalesRepo:
    def record_sale(self, item: Dict[str, Any], price: float, payment_method: str) -> Dict[str, Any]:
        today = datetime.date.today().isoformat()
        with get_sales_db() as conn:
            conn.execute(
                """
                INSERT INTO sales (
                    date, artist_album, genre, style, label, format, condition, price_gel, supplier_id, payment_method, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    today,
                    item.get("artist_album"),
                    item.get("genre"),
                    item.get("style"),
                    item.get("label"),
                    item.get("format"),
                    item.get("condition"),
                    price,
                    item.get("supplier_id"),
                    payment_method,
                    datetime.datetime.utcnow().isoformat(),
                ),
            )
            conn.commit()
        return {"date": today, "artist_album": item.get("artist_album"), "price_gel": price, "payment_method": payment_method}


class SqliteOrdersRepo:
    def upsert_order_snapshot(self, store_id: int, order: Dict[str, Any]) -> int:
        woo_order_id = int(order.get("id") or 0)
        payload_hash = hashlib.sha256(json.dumps(order, sort_keys=True).encode("utf-8")).hexdigest()
        status = order.get("status")
        billing = order.get("billing") or {}
        shipping = order.get("shipping") or {}
        billing_name = " ".join(part for part in [billing.get("first_name"), billing.get("last_name")] if part).strip()
        shipping_name = " ".join(part for part in [shipping.get("first_name"), shipping.get("last_name")] if part).strip()
        now = datetime.datetime.utcnow().isoformat()
        with get_inventory_db() as conn:
            cur = conn.execute("SELECT id FROM orders WHERE store_id = ? AND woo_order_id = ?", (store_id, woo_order_id))
            row = cur.fetchone()
            if row:
                order_id = int(row["id"])
                conn.execute(
                    """UPDATE orders SET status=?, total=?, currency=?, billing_name=?, billing_email=?, billing_phone=?, shipping_name=?, updated_at=?, last_seen_hash=? WHERE id=?""",
                    (status, order.get("total"), order.get("currency"), billing_name, billing.get("email"), billing.get("phone"), shipping_name, now, payload_hash, order_id),
                )
                conn.commit()
                return order_id
            cur = conn.execute(
                """
                INSERT INTO orders (store_id, woo_order_id, status, total, currency, billing_name, billing_email, billing_phone, shipping_name, created_at, updated_at, last_seen_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (store_id, woo_order_id, status, order.get("total"), order.get("currency"), billing_name, billing.get("email"), billing.get("phone"), shipping_name, order.get("date_created") or now, now, payload_hash),
            )
            conn.commit()
            return int(cur.lastrowid)

    def get_order_by_woo_id(self, store_id: int, woo_order_id: int) -> Optional[Dict[str, Any]]:
        with get_inventory_db() as conn:
            cur = conn.execute("SELECT * FROM orders WHERE store_id=? AND woo_order_id=?", (store_id, woo_order_id))
            row = cur.fetchone()
            return dict(row) if row else None

    def insert_order_line_item(self, *, order_id: int, woo_line_item_id: Optional[int], internal_product_id: Optional[int], sku: Optional[str], quantity: int, price: float) -> bool:
        with get_inventory_db() as conn:
            cur = conn.execute(
                """INSERT OR IGNORE INTO order_line_items (order_id, woo_line_item_id, internal_product_id, sku, quantity, price) VALUES (?, ?, ?, ?, ?, ?)""",
                (order_id, woo_line_item_id, internal_product_id, sku, quantity, price),
            )
            conn.commit()
            return cur.rowcount > 0

    def mark_inventory_applied(self, order_id: int) -> None:
        with get_inventory_db() as conn:
            conn.execute("UPDATE orders SET inventory_applied_at=? WHERE id=?", (datetime.datetime.utcnow().isoformat(), order_id))
            conn.commit()

    def mark_needs_review(self, order_id: int, needs_review: bool) -> None:
        with get_inventory_db() as conn:
            conn.execute("UPDATE orders SET needs_review=? WHERE id=?", (1 if needs_review else 0, order_id))
            conn.commit()

    def find_mapping(self, store_id: int, *, internal_id: Optional[int] = None, sku: Optional[str] = None, variation_id: Optional[int] = None, woo_product_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        clauses = ["store_id = ?"]
        params: list[Any] = [store_id]
        if internal_id is not None:
            clauses.append("internal_product_id = ?")
            params.append(internal_id)
        if sku is not None:
            clauses.append("sku = ?")
            params.append(sku)
        if variation_id is not None:
            clauses.append("woo_variation_id = ?")
            params.append(variation_id)
        if woo_product_id is not None:
            clauses.append("woo_product_id = ?")
            params.append(woo_product_id)
        query = f"SELECT * FROM product_map WHERE {' AND '.join(clauses)} LIMIT 1"
        with get_inventory_db() as conn:
            cur = conn.execute(query, tuple(params))
            row = cur.fetchone()
            return dict(row) if row else None
