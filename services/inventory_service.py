from __future__ import annotations

import datetime
import logging
from typing import Any, Dict, List, Optional, Tuple

from db.connection import get_inventory_db

logger = logging.getLogger(__name__)
_inventory_sequence_checked = False


def _row_to_dict(row: Any) -> Dict[str, Any]:
    return dict(row) if row is not None else {}


def get_suppliers() -> List[Dict[str, Any]]:
    with get_inventory_db() as conn:
        cur = conn.execute("SELECT id, name FROM supplier ORDER BY name")
        return [dict(row) for row in cur.fetchall()]


def get_next_inventory_id() -> int:
    ensure_inventory_sequence()
    with get_inventory_db() as conn:
        cur = conn.execute(
            """
            SELECT
                COALESCE(MAX(inventory.id), 0) AS max_id,
                COALESCE(seq, 0) AS seq
            FROM inventory
            LEFT JOIN sqlite_sequence ON sqlite_sequence.name = 'inventory'
            """
        )
        row = cur.fetchone()
        if not row:
            return 1
        max_id = int(row["max_id"] or 0)
        seq = int(row["seq"] or 0)
        return max(max_id, seq) + 1


def get_next_local_inventory_id() -> int:
    with get_inventory_db() as conn:
        cur = conn.execute("SELECT id FROM inventory ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        last_id = int(row["id"]) if row and row["id"] is not None else 0
        return last_id + 1


def ensure_inventory_sequence() -> None:
    global _inventory_sequence_checked
    if _inventory_sequence_checked:
        return

    with get_inventory_db() as conn:
        cur = conn.execute("SELECT COALESCE(MAX(id), 0) FROM inventory")
        row = cur.fetchone()
        local_max_id = int(row[0] or 0) if row else 0

        max_woo_sku = 0
        max_woo_id = 0
        from services import woo_service

        if woo_service.is_configured():
            page = 1
            per_page = 100
            while True:
                products = woo_service.fetch_products_page(page=page, per_page=per_page)
                if not products:
                    break
                for product in products:
                    if product.get("id"):
                        try:
                            max_woo_id = max(max_woo_id, int(product["id"]))
                        except (TypeError, ValueError):
                            pass
                    sku = str(product.get("sku") or "").strip()
                    if sku.isdigit():
                        max_woo_sku = max(max_woo_sku, int(sku))
                if len(products) < per_page:
                    break
                page += 1

        target_seq = max(local_max_id, max_woo_sku, max_woo_id)
        conn.execute(
            "INSERT OR IGNORE INTO sqlite_sequence(name, seq) VALUES ('inventory', ?)",
            (target_seq,),
        )
        conn.execute(
            "UPDATE sqlite_sequence SET seq = MAX(seq, ?) WHERE name = 'inventory'",
            (target_seq,),
        )
        conn.commit()
        _inventory_sequence_checked = True
        logger.info(
            "Ensured inventory sequence at %s (local max=%s, Woo max=%s)",
            target_seq,
            local_max_id,
            max(max_woo_sku, max_woo_id),
        )


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
    ensure_inventory_sequence()
    with get_inventory_db() as conn:
        now = item.get("created_at") or datetime.datetime.now(datetime.UTC).isoformat()
        cur = conn.execute(
            """
            INSERT INTO inventory (
                artist_album, genre, style, label, format, condition, sleeve_condition, price_gel,
                quantity, supplier_id, created_at, updated_at, local_rev, last_change_source, year, description, cover_url,
                discogs_release_id, discogs_master_id, discogs_uri
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.get("artist_album"),
                item.get("genre"),
                item.get("style"),
                item.get("label"),
                item.get("format"),
                item.get("condition"),
                item.get("sleeve_condition"),
                item.get("price_gel"),
                item.get("quantity"),
                item.get("supplier_id"),
                now,
                item.get("updated_at") or now,
                item.get("local_rev") or 0,
                item.get("last_change_source"),
                item.get("year"),
                item.get("description"),
                item.get("cover_url"),
                item.get("discogs_release_id"),
                item.get("discogs_master_id"),
                item.get("discogs_uri"),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def insert_inventory_with_id(item_id: int, item: Dict[str, Any]) -> int:
    ensure_inventory_sequence()
    with get_inventory_db() as conn:
        now = item.get("created_at") or datetime.datetime.now(datetime.UTC).isoformat()
        conn.execute(
            """
            INSERT INTO inventory (
                id, artist_album, genre, style, label, format, condition, sleeve_condition, price_gel,
                quantity, supplier_id, created_at, updated_at, local_rev, last_change_source, year, description, cover_url,
                discogs_release_id, discogs_master_id, discogs_uri
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id,
                item.get("artist_album"),
                item.get("genre"),
                item.get("style"),
                item.get("label"),
                item.get("format"),
                item.get("condition"),
                item.get("sleeve_condition"),
                item.get("price_gel"),
                item.get("quantity"),
                item.get("supplier_id"),
                now,
                item.get("updated_at") or now,
                item.get("local_rev") or 0,
                item.get("last_change_source"),
                item.get("year"),
                item.get("description"),
                item.get("cover_url"),
                item.get("discogs_release_id"),
                item.get("discogs_master_id"),
                item.get("discogs_uri"),
            ),
        )
        conn.execute(
            "UPDATE sqlite_sequence SET seq = MAX(seq, ?) WHERE name = 'inventory'",
            (item_id,),
        )
        conn.commit()
        return item_id


def update_inventory_sync(item_id: int, woo_product_id: int, sync_hash: str) -> None:
    with get_inventory_db() as conn:
        conn.execute(
            """
            UPDATE inventory
            SET woo_product_id = ?, woo_synced = 1, woo_last_synced_at = ?, woo_sync_hash = ?
            WHERE id = ?
            """,
            (woo_product_id, datetime.datetime.now(datetime.UTC).isoformat(), sync_hash, item_id),
        )
        conn.commit()


def get_inventory_by_id(item_id: int) -> Optional[Dict[str, Any]]:
    with get_inventory_db() as conn:
        cur = conn.execute(
            """
            SELECT inventory.*, supplier.name AS supplier_name
            FROM inventory
            LEFT JOIN supplier ON supplier.id = inventory.supplier_id
            WHERE inventory.id = ?
            """,
            (item_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def get_inventory_by_woo_product_id(woo_product_id: int) -> Optional[Dict[str, Any]]:
    with get_inventory_db() as conn:
        cur = conn.execute(
            """
            SELECT inventory.*, supplier.name AS supplier_name
            FROM inventory
            LEFT JOIN supplier ON supplier.id = inventory.supplier_id
            WHERE inventory.woo_product_id = ?
            """,
            (woo_product_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def get_inventory_page(page: int, page_size: int = 8) -> Tuple[List[Dict[str, Any]], int]:
    offset = max(page - 1, 0) * page_size
    with get_inventory_db() as conn:
        cur = conn.execute("SELECT COUNT(1) AS total FROM inventory")
        total_row = cur.fetchone()
        total = int(total_row["total"] or 0) if total_row else 0
        cur = conn.execute(
            """
            SELECT inventory.*, supplier.name AS supplier_name
            FROM inventory
            LEFT JOIN supplier ON supplier.id = inventory.supplier_id
            ORDER BY inventory.created_at DESC
            LIMIT ? OFFSET ?
            """,
            (page_size, offset),
        )
        items = [dict(row) for row in cur.fetchall()]
        return items, total


def inventory_is_empty() -> bool:
    with get_inventory_db() as conn:
        cur = conn.execute("SELECT 1 FROM inventory LIMIT 1")
        return cur.fetchone() is None


def find_inventory_by_discogs_release_id(release_id: int) -> Optional[Dict[str, Any]]:
    with get_inventory_db() as conn:
        cur = conn.execute(
            """
            SELECT inventory.*, supplier.name AS supplier_name
            FROM inventory
            LEFT JOIN supplier ON supplier.id = inventory.supplier_id
            WHERE inventory.discogs_release_id = ?
            """,
            (int(release_id),),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def search_inventory(query: str, limit: int = 15) -> List[Dict[str, Any]]:
    with get_inventory_db() as conn:
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='inventory_fts'")
        if cur.fetchone():
            cur = conn.execute(
                """
                SELECT inventory.*, supplier.name AS supplier_name, bm25(inventory_fts) AS rank
                FROM inventory
                JOIN inventory_fts ON inventory_fts.rowid = inventory.id
                LEFT JOIN supplier ON supplier.id = inventory.supplier_id
                WHERE inventory_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (query, limit),
            )
        else:
            like = f"%{query}%"
            cur = conn.execute(
                """
                SELECT inventory.*, supplier.name AS supplier_name
                FROM inventory
                LEFT JOIN supplier ON supplier.id = inventory.supplier_id
                WHERE artist_album LIKE ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (like, limit),
            )
        return [dict(row) for row in cur.fetchall()]


def get_all_inventory() -> List[Dict[str, Any]]:
    with get_inventory_db() as conn:
        cur = conn.execute(
            """
            SELECT inventory.*, supplier.name AS supplier_name
            FROM inventory
            LEFT JOIN supplier ON supplier.id = inventory.supplier_id
            ORDER BY inventory.created_at DESC
            """
        )
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
    update_inventory_fields(
        item_id,
        {"quantity": current - amount},
        sync_channels=True,
        source="manual_bot",
    )
    return True


def log_inventory_event(
    *,
    store_id: Optional[int],
    internal_product_id: int,
    theere_id: Optional[str],
    field: str,
    old_value: Any,
    new_value: Any,
    source: str,
    correlation_id: Optional[str] = None,
    note: Optional[str] = None,
) -> None:
    ts = datetime.datetime.now(datetime.UTC).isoformat()
    with get_inventory_db() as conn:
        conn.execute(
            """
            INSERT INTO inventory_events (
                ts,
                store_id,
                internal_product_id,
                theere_id,
                field,
                old_value,
                new_value,
                source,
                correlation_id,
                note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ts,
                store_id,
                internal_product_id,
                theere_id,
                field,
                str(old_value) if old_value is not None else None,
                str(new_value) if new_value is not None else None,
                source,
                correlation_id,
                note,
            ),
        )
        conn.commit()


def update_inventory_fields(
    item_id: int,
    fields: Dict[str, Any],
    *,
    sync_channels: bool = True,
    source: str = "manual_bot",
    store_id: Optional[int] = None,
    correlation_id: Optional[str] = None,
    note: Optional[str] = None,
) -> None:
    if not fields:
        return
    track_fields = {"quantity", "price_gel"}
    tracked = track_fields & set(fields.keys())
    old_qty = None
    old_price = None
    local_rev = None
    with get_inventory_db() as conn:
        if tracked:
            cur = conn.execute(
                "SELECT quantity, price_gel, local_rev FROM inventory WHERE id = ?",
                (item_id,),
            )
            row = cur.fetchone()
            if not row:
                return
            old_qty = int(row["quantity"] or 0)
            old_price = float(row["price_gel"] or 0)
            local_rev = int(row["local_rev"] or 0)
    now = datetime.datetime.now(datetime.UTC).isoformat()
    keys = sorted(fields.keys())
    assignments = ", ".join(f"{key} = ?" for key in keys)
    values = [fields[key] for key in keys]
    extra_assignments: List[str] = []
    extra_values: List[Any] = []
    if tracked:
        extra_assignments.extend(["updated_at = ?", "local_rev = ?", "last_change_source = ?"])
        extra_values.extend([now, (local_rev or 0) + 1, source])
    assignment_block = ", ".join([assignments, *extra_assignments]) if extra_assignments else assignments
    with get_inventory_db() as conn:
        conn.execute(
            f"UPDATE inventory SET {assignment_block} WHERE id = ?",
            (*values, *extra_values, item_id),
        )
        conn.commit()
    if tracked:
        from services.store_service import get_default_store

        if store_id is None:
            store = get_default_store()
            store_id = int(store["id"]) if store else None
        if "quantity" in fields:
            new_qty = int(fields["quantity"] or 0)
            if old_qty is None or new_qty != old_qty:
                log_inventory_event(
                    store_id=store_id,
                    internal_product_id=item_id,
                    theere_id=str(item_id),
                    field="quantity",
                    old_value=old_qty,
                    new_value=new_qty,
                    source=source,
                    correlation_id=correlation_id,
                    note=note,
                )
        if "price_gel" in fields:
            new_price = float(fields["price_gel"] or 0)
            if old_price is None or new_price != old_price:
                log_inventory_event(
                    store_id=store_id,
                    internal_product_id=item_id,
                    theere_id=str(item_id),
                    field="regular_price",
                    old_value=old_price,
                    new_value=new_price,
                    source=source,
                    correlation_id=correlation_id,
                    note=note,
                )
    if sync_channels and tracked:
        from services import sync_engine
        from services.store_service import get_default_store, get_store_settings

        try:
            store = get_default_store()
            if not store:
                return
            settings = get_store_settings(int(store["id"]))
            if settings.get("woo_instant_sync_enabled"):
                sync_engine.SyncEngine().run_instant_sync_for_item(int(store["id"]), item_id)
        except Exception:
            logger.exception("Instant sync failed for item %s", item_id)


def update_inventory_supplier(item_id: int, supplier_name: Optional[str]) -> None:
    supplier_id: Optional[int] = None
    if supplier_name:
        supplier_id = get_or_create_supplier(supplier_name)
    update_inventory_fields(item_id, {"supplier_id": supplier_id})
