from __future__ import annotations

from db.connection import get_db, get_inventory_db, get_sales_db
from db.migrations import migrate


def init_db() -> None:
    migrate()
    ensure_inventory_woo_product_id()


def ensure_inventory_woo_product_id() -> None:
    with get_inventory_db() as conn:
        cur = conn.execute("PRAGMA table_info(inventory)")
        columns = {row[1] for row in cur.fetchall()}
        if "woo_product_id" not in columns:
            conn.execute("ALTER TABLE inventory ADD COLUMN woo_product_id INTEGER")
            conn.commit()


__all__ = [
    "get_db",
    "get_inventory_db",
    "get_sales_db",
    "init_db",
    "ensure_inventory_woo_product_id",
]
