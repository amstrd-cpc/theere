from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

from db.connection import get_inventory_db


def _row_to_dict(row: Any) -> Dict[str, Any]:
    return dict(row) if row is not None else {}


def get_suppliers() -> List[Dict[str, Any]]:
    with get_inventory_db() as conn:
        cur = conn.execute("SELECT id, name FROM supplier ORDER BY name")
        return [dict(row) for row in cur.fetchall()]


def get_or_create_supplier(name: str) -> int:
    with get_inventory_db() as conn:
        cur = conn.execute("SELECT id FROM supplier WHERE name = ?", (name,))
        row = cur.fetchone()
        if row:
            return int(row["id"])
        cur = conn.execute("INSERT INTO supplier (name) VALUES (?)", (name,))
        conn.commit()
        return int(cur.lastrowid)


def insert_inventory(item: Dict[str, Any]) -> int:
    with get_inventory_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO inventory (
                artist_album, genre, style, label, format, condition, price_gel,
                quantity, supplier_id, created_at, year, description, cover_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.get("artist_album"),
                item.get("genre"),
                item.get("style"),
                item.get("label"),
                item.get("format"),
                item.get("condition"),
                item.get("price_gel"),
                item.get("quantity"),
                item.get("supplier_id"),
                item.get("created_at") or datetime.datetime.utcnow().isoformat(),
                item.get("year"),
                item.get("description"),
                item.get("cover_url"),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def update_inventory_sync(item_id: int, woo_product_id: int, sync_hash: str) -> None:
    with get_inventory_db() as conn:
        conn.execute(
            """
            UPDATE inventory
            SET woo_product_id = ?, woo_synced = 1, woo_last_synced_at = ?, woo_sync_hash = ?
            WHERE id = ?
            """,
            (woo_product_id, datetime.datetime.utcnow().isoformat(), sync_hash, item_id),
        )
        conn.commit()


def get_inventory_by_id(item_id: int) -> Optional[Dict[str, Any]]:
    with get_inventory_db() as conn:
        cur = conn.execute("SELECT * FROM inventory WHERE id = ?", (item_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def search_inventory(query: str) -> List[Dict[str, Any]]:
    with get_inventory_db() as conn:
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='inventory_fts'")
        if cur.fetchone():
            cur = conn.execute(
                """
                SELECT inventory.* FROM inventory
                JOIN inventory_fts ON inventory_fts.rowid = inventory.id
                WHERE inventory_fts MATCH ?
                ORDER BY inventory.created_at DESC
                LIMIT 100
                """,
                (query,),
            )
        else:
            like = f"%{query}%"
            cur = conn.execute(
                """
                SELECT * FROM inventory
                WHERE artist_album LIKE ? OR label LIKE ? OR genre LIKE ? OR style LIKE ?
                ORDER BY created_at DESC
                LIMIT 100
                """,
                (like, like, like, like),
            )
        return [dict(row) for row in cur.fetchall()]


def get_all_inventory() -> List[Dict[str, Any]]:
    with get_inventory_db() as conn:
        cur = conn.execute("SELECT * FROM inventory ORDER BY created_at DESC")
        return [dict(row) for row in cur.fetchall()]


def get_unsynced_inventory(limit: int = 50) -> List[Dict[str, Any]]:
    with get_inventory_db() as conn:
        cur = conn.execute(
            """
            SELECT * FROM inventory
            WHERE woo_product_id IS NULL OR woo_synced = 0
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cur.fetchall()]


def get_low_stock(threshold: int = 1) -> List[Dict[str, Any]]:
    with get_inventory_db() as conn:
        cur = conn.execute(
            "SELECT * FROM inventory WHERE quantity <= ? ORDER BY quantity ASC, created_at DESC",
            (threshold,),
        )
        return [dict(row) for row in cur.fetchall()]


def reduce_inventory_quantity(item_id: int, amount: int) -> bool:
    with get_inventory_db() as conn:
        cur = conn.execute("SELECT quantity FROM inventory WHERE id = ?", (item_id,))
        row = cur.fetchone()
        if not row:
            return False
        current = int(row["quantity"] or 0)
        if current < amount:
            return False
        conn.execute("UPDATE inventory SET quantity = ? WHERE id = ?", (current - amount, item_id))
        conn.commit()
        return True


def update_inventory_fields(item_id: int, fields: Dict[str, Any]) -> None:
    keys = sorted(fields.keys())
    assignments = ", ".join(f"{key} = ?" for key in keys)
    values = [fields[key] for key in keys]
    with get_inventory_db() as conn:
        conn.execute(
            f"UPDATE inventory SET {assignments} WHERE id = ?",
            (*values, item_id),
        )
        conn.commit()
