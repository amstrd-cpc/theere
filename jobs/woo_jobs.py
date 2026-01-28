from __future__ import annotations

import logging
import datetime
from typing import Any, Dict

from telegram import Bot

from config.settings import load_settings
from services.inventory_service import get_unsynced_inventory, update_inventory_sync
from services.runtime import run_blocking
from services.woo_orders_service import process_woo_order
from services.woo_service import WooNotConfigured, fetch_orders, is_configured, upsert_product_from_inventory, compute_sync_hash

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
    settings = load_settings()
    after = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=hours)).isoformat()
    page = 1
    while True:
        try:
            orders = await run_blocking(
                fetch_orders,
                {"status": "processing", "after": after, "page": page, "per_page": 50},
            )
        except WooNotConfigured:
            return
        except Exception:
            logger.exception("Error fetching Woo orders")
            return

        if not orders:
            break

        for order in orders:
            info = await run_blocking(process_woo_order, order)
            if info.get("already_processed"):
                continue
            await _send_order_notification(bot, info, settings.admin_chat_id)

        if len(orders) < 50:
            break
        page += 1


async def _send_order_notification(bot: Bot, info: Dict[str, Any], admin_chat_id: int | None) -> None:
    if not admin_chat_id:
        return
    order_id = info.get("order_id")
    items = info.get("items", [])
    already = info.get("already_processed", False)
    skipped = info.get("skipped", False)
    if already or skipped or not items:
        return

    for inv, qty, _price, remaining in items:
        await bot.send_message(
            chat_id=admin_chat_id,
            text=(
                f"💿 SOLD: ID {inv['id']} — {inv['artist_album']} (qty {qty}). "
                f"Remaining: {remaining}. Order #{order_id}"
            ),
        )
