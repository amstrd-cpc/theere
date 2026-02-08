from __future__ import annotations

import logging

from telegram import Bot

from services.runtime import run_blocking
from services.store_service import get_default_store
from services.sync_engine import SyncEngine
from services.woo_service import WooNotConfigured, is_configured

logger = logging.getLogger(__name__)


async def sync_inventory_to_woo() -> None:
    if not is_configured():
        return
    store = get_default_store()
    if not store:
        return
    await run_blocking(SyncEngine().run_periodic_sync, int(store["id"]))


async def poll_recent_woo_orders(bot: Bot, hours: int = 6) -> None:
    if not is_configured():
        return
    store = get_default_store()
    if not store:
        return
    try:
        await run_blocking(SyncEngine().sync_orders, int(store["id"]))
    except WooNotConfigured:
        return
    except Exception:
        logger.exception("Error fetching Woo orders")
        return


def poll_three_way_woo() -> None:
    logger.info("Three-way Woo sync disabled in favor of SyncEngine.")
