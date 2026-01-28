from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
from threading import Thread
from typing import Any, Dict

import requests
from aiohttp import web

from config.settings import load_settings
from services.woo_orders_service import process_woo_order

logger = logging.getLogger(__name__)


def verify_wc_signature(raw_body: bytes, header_sig: str, secret: str) -> bool:
    if not header_sig:
        return False
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(expected, header_sig)


async def woo_webhook(request: web.Request) -> web.Response:
    settings = load_settings()
    secret = settings.webhook_secret
    if not secret:
        logger.warning("Woo webhook secret missing; rejecting request")
        return web.Response(status=500, text="Webhook secret missing")

    raw = await request.read()
    header_sig = request.headers.get("X-WC-Webhook-Signature", "")
    logger.info("Woo webhook received bytes=%s", len(raw))

    if not verify_wc_signature(raw, header_sig, secret):
        logger.warning("Woo webhook signature invalid")
        return web.Response(status=401, text="Invalid signature")

    try:
        order = json.loads(raw.decode("utf-8"))
    except Exception:
        return web.Response(status=400, text="Bad JSON")

    try:
        info = process_woo_order(order)
    except Exception:
        logger.exception("Failed to process Woo webhook")
        return web.Response(status=500, text="Error")

    _send_order_notification(info)

    if info.get("already_processed"):
        return web.json_response({"status": "already_processed"})
    return web.json_response({"status": "ok"})


def run_webhook_server() -> None:
    port = int(os.getenv("PORT", "8080"))
    app = web.Application()
    app.router.add_post("/webhooks/woo/order-paid", woo_webhook)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    runner = web.AppRunner(app)
    loop.run_until_complete(runner.setup())
    site = web.TCPSite(runner, "0.0.0.0", port)
    loop.run_until_complete(site.start())
    logger.info("Woo webhook server running on port %s", port)
    loop.run_forever()


def start_webhook_thread() -> Thread:
    thread = Thread(target=run_webhook_server, daemon=True)
    thread.start()
    return thread


def _send_order_notification(info: Dict[str, Any]) -> None:
    settings = load_settings()
    if not settings.admin_chat_id or not settings.bot_token:
        return

    if info.get("already_processed") or info.get("skipped"):
        return

    order_id = info.get("order_id")
    items = info.get("items", [])

    if not items:
        return

    url = f"https://api.telegram.org/bot{settings.bot_token}/sendMessage"
    for inv, qty, _price, remaining in items:
        text = f"💿 SOLD: ID {inv['id']} — {inv['artist_album']} (qty {qty}). Remaining: {remaining}. Order #{order_id}"
        try:
            requests.post(url, data={"chat_id": settings.admin_chat_id, "text": text}, timeout=10)
        except Exception:
            logger.exception("Failed to send Telegram Woo order notification")
