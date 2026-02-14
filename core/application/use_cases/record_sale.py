from __future__ import annotations

from core.application.ports.repositories import InventoryRepo, SalesRepo


def record_sale(inventory_repo: InventoryRepo, sales_repo: SalesRepo, item_id: int, *, price: float, payment_method: str) -> dict:
    item = inventory_repo.get_by_id(item_id)
    if not item:
        raise ValueError("Item not found")
    current_qty = int(item.get("quantity") or 0)
    if current_qty <= 0:
        raise ValueError("Out of stock")
    inventory_repo.update_quantity(item_id, current_qty - 1, source="sale", correlation_id=f"sale:{item_id}")
    return sales_repo.record_sale(item, price, payment_method)
