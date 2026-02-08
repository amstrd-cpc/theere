from __future__ import annotations

import logging
import datetime

from telegram import Bot

from services.inventory_service import get_unsynced_inventory, update_inventory_sync
from services.runtime import run_blocking
from services.product_map_service import get_latest_seen_at
from services.store_service import get_default_store, get_store_settings
from services.tri_sync_service import poll_woo_products
from services.woo_service import WooNotConfigured, fetch_orders, is_configured, upsert_product_from_inventory, compute_sync_hash
from jobs.worker_tasks import sync_order_state

logger = logging.getLogger(__name__)


async def sync_inventory_to_woo() -> None:
    if not is_configured():
        return
    items = await run_blocking(get_unsynced_inventory)
    for item in items:
        try:
            product = await run_blocking(upsert_product_from_inventory, item)
            woo_id = product.get("id")
            if woo_id:
                sync_hash = compute_sync_hash(product)
                await run_blocking(update_inventory_sync, item["id"], int(woo_id), sync_hash)
        except Exception:
            logger.exception("Woo sync failed for inventory %s", item.get("id"))
            continue


async def poll_recent_woo_orders(bot: Bot, hours: int = 6) -> None:
    if not is_configured():
        return
    store = get_default_store()
    if not store:
        return
    after = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=hours)).isoformat()
    page = 1
    while True:
        try:
            orders = await run_blocking(
                fetch_orders,
                {"status": "processing", "after": after, "page": page, "per_page": 50},
                store,
            )
        except WooNotConfigured:
            return
        except Exception:
            logger.exception("Error fetching Woo orders")
            return

        if not orders:
            break

        for order in orders:
            if not order.get("id"):
                continue
            await run_blocking(sync_order_state, int(store["id"]), int(order["id"]))

        if len(orders) < 50:
            break
        page += 1


def poll_three_way_woo() -> None:
    store = get_default_store()
    if not store:
        return
    settings = get_store_settings(int(store["id"]))
    if not settings.get("three_way_sync_enabled"):
        return
    interval_minutes = int(settings.get("three_way_woo_interval_minutes") or 15)
    last_seen = get_latest_seen_at(int(store["id"]), channel="woo")
    if last_seen:
        try:
            last_dt = datetime.datetime.fromisoformat(last_seen)
            if datetime.datetime.utcnow() - last_dt < datetime.timedelta(minutes=interval_minutes):
                return
        except ValueError:
            pass
    poll_woo_products(int(store["id"]))
