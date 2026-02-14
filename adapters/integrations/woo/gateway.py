from __future__ import annotations

from typing import Any, Dict, List

from services.woo_service import fetch_order_by_id, fetch_products_page


class WooServiceGateway:
    def fetch_order_by_id(self, store: Dict[str, Any], woo_order_id: int) -> Dict[str, Any] | None:
        return fetch_order_by_id(store, woo_order_id)

    def fetch_products_page(self, store: Dict[str, Any], page: int, per_page: int) -> List[Dict[str, Any]]:
        return fetch_products_page(page=page, per_page=per_page, store=store)
