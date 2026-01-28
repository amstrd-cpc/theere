from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import requests
import os
from threading import Thread
from typing import Any, Dict

from flask import Flask, request

from config.settings import load_settings
from services.woo_orders_service import process_woo_order

logger = logging.getLogger(__name__)

app = Flask(__name__)


def verify_wc_signature(raw_body: bytes, header_sig: str, secret: str) -> bool:
    if not header_sig:
        return True
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(expected, header_sig)


@app.route("/wc-webhook/<secret>", methods=["POST"])
def woo_webhook(secret: str):
    settings = load_settings()
    expected_secret = settings.webhook_secret
    if not expected_secret or secret != expected_secret:
        return ("Forbidden", 403)

    raw = request.get_data()
    header_sig = request.headers.get("X-WC-Webhook-Signature", "")

    if header_sig and not verify_wc_signature(raw, header_sig, expected_secret):
        return ("Invalid signature", 401)

    try:
        order = json.loads(raw.decode("utf-8"))
    except Exception:
        return ("Bad JSON", 400)

    try:
        info = process_woo_order(order)
    except Exception:
        logger.exception("Failed to process Woo webhook")
        return ("Error", 500)

    _send_order_notification(info)

    if info.get("already_processed"):
        return (json.dumps({"status": "already_processed"}), 200, {"Content-Type": "application/json"})
    return (json.dumps({"status": "ok"}), 200, {"Content-Type": "application/json"})


def run_webhook_server() -> None:
    port = int(os.getenv("WEBHOOK_PORT", "32412"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


def start_webhook_thread() -> Thread:
    thread = Thread(target=run_webhook_server, daemon=True)
    thread.start()
    return thread


def _send_order_notification(info: Dict[str, Any]) -> None:
    settings = load_settings()
    if not settings.admin_chat_id or not settings.bot_token:
        return

    order_id = info.get("order_id")
    status = info.get("status") or "unknown"
    payment = info.get("payment_method") or "unknown"
    billing_name = info.get("billing_name") or "N/A"
    currency = info.get("currency") or ""
    total = info.get("order_total") or "0"
    items = info.get("items", [])
    unmatched = info.get("unmatched", [])
    already = info.get("already_processed", False)
    skipped = info.get("skipped", False)
    skip_reason = info.get("skip_reason")

    lines: list[str] = []
    if already:
        lines.append("(Already processed)")
    if skipped:
        lines.append("(Auto-sell skipped)")
        if skip_reason:
            lines.append(f"Reason: {skip_reason}")

    lines.append(f"New Woo order #{order_id}")
    lines.append(f"Status: {status}")
    lines.append(f"Payment: {payment}")
    lines.append(f"Customer: {billing_name}")
    lines.append("")
    lines.append("Items:")

    if not items:
        lines.append("- (none)")
    else:
        for inv, qty, price in items:
            lines.append(f"- {inv['artist_album']} x{qty} – {price} {currency} (id {inv['id']})")

    if unmatched:
        lines.append("")
        lines.append("Unmatched items:")
        for entry in unmatched:
            lines.append(f"- {entry.get('name', 'Unknown')} x{entry.get('quantity')} (SKU {entry.get('sku')})")

    lines.append("")
    if (not already) and (not skipped) and items:
        lines.append("✅ Sale recorded locally (inventory + sales updated).")
    elif (not already) and (not skipped) and (not items):
        lines.append("⚠️ No items were recorded locally.")

    lines.append(f"Order total: {total} {currency}")

    url = f"https://api.telegram.org/bot{settings.bot_token}/sendMessage"
    try:
        requests.post(url, data={"chat_id": settings.admin_chat_id, "text": "\n".join(lines)}, timeout=10)
    except Exception:
        logger.exception("Failed to send Telegram Woo order notification")
