from __future__ import annotations

from typing import Dict

from core.application.ports.gateways import WooGateway
from core.application.ports.repositories import SettingsProvider


def sync_catalog(*, store_id: int, settings: SettingsProvider, woo_gateway: WooGateway) -> Dict[str, int]:
    store = settings.get_store(store_id)
    if not store:
        raise ValueError(f"Store {store_id} not found")
    total_products = 0
    page = 1
    per_page = 100
    while True:
        products = woo_gateway.fetch_products_page(store, page=page, per_page=per_page)
        if not products:
            break
        total_products += len(products)
        if len(products) < per_page:
            break
        page += 1
    return {"store_id": store_id, "woo_products_seen": total_products}
