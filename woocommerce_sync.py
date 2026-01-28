from __future__ import annotations

import asyncio
import inspect

from telegram_ui import messages
from services.woo_service import is_configured
from jobs.woo_jobs import sync_inventory_to_woo as sync_inventory_job


async def _reply(update, context, text: str) -> None:
    if update and getattr(update, "message", None):
        await update.message.reply_text(text)


def sync_inventory_to_woo_handler():
    return sync_inventory_to_woo


def sync_inventory_to_woo(update=None, context=None):
    if not is_configured():
        if update:
            return asyncio.get_event_loop().run_until_complete(
                _reply(update, context, messages.WOO_NOT_CONFIGURED_MESSAGE)
            )
        return

    if update:
        asyncio.get_event_loop().run_until_complete(_reply(update, context, messages.WOO_SYNC_NOTE))

    coro = sync_inventory_job()
    if inspect.iscoroutine(coro):
        asyncio.get_event_loop().run_until_complete(coro)
