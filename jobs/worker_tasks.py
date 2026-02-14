from __future__ import annotations

from bootstrap.container import build_container
from core.application.use_cases.process_woo_order import process_woo_order


def process_woo_order_job(*, store_id: int, woo_order_id: int) -> dict:
    container = build_container()
    result = process_woo_order(
        store_id=store_id,
        woo_order_id=woo_order_id,
        settings=container.settings_provider,
        orders_repo=container.orders_repo,
        inventory_repo=container.inventory_repo,
        sales_repo=container.sales_repo,
        woo_gateway=container.woo_gateway,
        discogs_gateway=container.discogs_gateway,
        notifier=container.notifier,
    )
    return {"order_id": result.order_id, "matched": len(result.matched_items), "unmapped": result.unmapped_items}
