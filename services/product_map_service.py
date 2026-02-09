from __future__ import annotations

import datetime
from typing import Any, Dict, Optional

from db.connection import get_inventory_db


def upsert_product_map(
    *,
    store_id: int,
    internal_product_id: int,
    woo_product_id: Optional[int] = None,
    woo_variation_id: Optional[int] = None,
    sku: Optional[str] = None,
    discogs_listing_id: Optional[int] = None,
    discogs_release_id: Optional[int] = None,
) -> None:
    now = datetime.datetime.utcnow().isoformat()
    with get_inventory_db() as conn:
        conn.execute(
            """
            INSERT INTO product_map (
                store_id,
                internal_product_id,
                woo_product_id,
                woo_variation_id,
                sku,
                discogs_listing_id,
                discogs_release_id,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(store_id, internal_product_id)
            DO UPDATE SET
                woo_product_id = COALESCE(excluded.woo_product_id, product_map.woo_product_id),
                woo_variation_id = COALESCE(excluded.woo_variation_id, product_map.woo_variation_id),
                sku = COALESCE(excluded.sku, product_map.sku),
                discogs_listing_id = COALESCE(excluded.discogs_listing_id, product_map.discogs_listing_id),
                discogs_release_id = COALESCE(excluded.discogs_release_id, product_map.discogs_release_id),
                updated_at = excluded.updated_at
            """,
            (
                store_id,
                internal_product_id,
                woo_product_id,
                woo_variation_id,
                sku,
                discogs_listing_id,
                discogs_release_id,
                now,
                now,
            ),
        )
        conn.commit()


def find_mapping_by_sku(store_id: int, sku: str) -> Optional[Dict[str, Any]]:
    with get_inventory_db() as conn:
        cur = conn.execute(
            "SELECT * FROM product_map WHERE store_id = ? AND sku = ?",
            (store_id, sku),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def find_mapping_by_woo_product_id(store_id: int, woo_product_id: int) -> Optional[Dict[str, Any]]:
    with get_inventory_db() as conn:
        cur = conn.execute(
            "SELECT * FROM product_map WHERE store_id = ? AND woo_product_id = ?",
            (store_id, woo_product_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def find_mapping_by_variation_id(store_id: int, variation_id: int) -> Optional[Dict[str, Any]]:
    with get_inventory_db() as conn:
        cur = conn.execute(
            "SELECT * FROM product_map WHERE store_id = ? AND woo_variation_id = ?",
            (store_id, variation_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def find_mapping_by_discogs_listing_id(store_id: int, listing_id: int) -> Optional[Dict[str, Any]]:
    with get_inventory_db() as conn:
        cur = conn.execute(
            "SELECT * FROM product_map WHERE store_id = ? AND discogs_listing_id = ?",
            (store_id, listing_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def find_mapping_by_internal_id(store_id: int, internal_product_id: int) -> Optional[Dict[str, Any]]:
    with get_inventory_db() as conn:
        cur = conn.execute(
            "SELECT * FROM product_map WHERE store_id = ? AND internal_product_id = ?",
            (store_id, internal_product_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def list_product_mappings(store_id: int) -> list[Dict[str, Any]]:
    with get_inventory_db() as conn:
        cur = conn.execute("SELECT * FROM product_map WHERE store_id = ?", (store_id,))
        return [dict(row) for row in cur.fetchall()]


def clear_discogs_listing(store_id: int, internal_product_id: int) -> None:
    now = datetime.datetime.utcnow().isoformat()
    with get_inventory_db() as conn:
        conn.execute(
            """
            UPDATE product_map
            SET discogs_listing_id = NULL, updated_at = ?
            WHERE store_id = ? AND internal_product_id = ?
            """,
            (now, store_id, internal_product_id),
        )
        conn.commit()


def update_product_map_fields(store_id: int, internal_product_id: int, fields: Dict[str, Any]) -> None:
    if not fields:
        return
    now = datetime.datetime.utcnow().isoformat()
    fields = dict(fields)
    fields.setdefault("updated_at", now)
    keys = sorted(fields.keys())
    assignments = ", ".join(f"{key} = ?" for key in keys)
    values = [fields[key] for key in keys]
    values.extend([store_id, internal_product_id])
    with get_inventory_db() as conn:
        conn.execute(
            f"UPDATE product_map SET {assignments} WHERE store_id = ? AND internal_product_id = ?",
            values,
        )
        conn.commit()


def get_latest_seen_at(store_id: int, *, channel: str) -> Optional[str]:
    column = "discogs_last_seen_at" if channel == "discogs" else "woo_last_seen_at"
    with get_inventory_db() as conn:
        cur = conn.execute(
            f"SELECT MAX({column}) AS last_seen FROM product_map WHERE store_id = ?",
            (store_id,),
        )
        row = cur.fetchone()
        return row["last_seen"] if row else None
