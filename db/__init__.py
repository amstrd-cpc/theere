from db.connection import get_db, get_inventory_db, get_sales_db
from db.migrations import migrate


def init_db() -> None:
    migrate()


__all__ = ["get_db", "get_inventory_db", "get_sales_db", "init_db"]
