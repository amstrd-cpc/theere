from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from api.rate_limit import SimpleRateLimiter
from jobs.queue import enqueue_job, get_queue
from jobs.worker_tasks import process_woo_webhook_event
from services.store_service import get_store
from services.webhook_event_service import (
    create_webhook_event,
    get_last_webhook_processed_at,
    get_last_webhook_received_at,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="Record Store Webhook API")
rate_limiter = SimpleRateLimiter(max_requests=120, window_seconds=60)


def _verify_wc_signature(raw_body: bytes, header_sig: str, secret: str) -> bool:
    if not header_sig:
        return False
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(expected, header_sig)


def _hash_payload(raw_body: bytes) -> str:
    return hashlib.sha256(raw_body).hexdigest()


@app.post("/webhooks/woo/{store_id}")
async def woo_webhook(
    store_id: int,
    request: Request,
    x_wc_webhook_signature: str | None = Header(default=None, alias="X-WC-Webhook-Signature"),
    x_wc_webhook_delivery: str | None = Header(default=None, alias="X-WC-Webhook-Delivery"),
    x_wc_webhook_topic: str | None = Header(default=None, alias="X-WC-Webhook-Topic"),
) -> JSONResponse:
    client_ip = request.client.host if request.client else "unknown"
    if not rate_limiter.allow(client_ip):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    store = get_store(store_id)
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    raw_body = await request.body()
    if not _verify_wc_signature(raw_body, x_wc_webhook_signature or "", store["webhook_secret"]):
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    woo_order_id = payload.get("id") if isinstance(payload, dict) else None
    payload_hash = _hash_payload(raw_body)
    topic = x_wc_webhook_topic or "order.updated"
    if x_wc_webhook_delivery:
        event_key = x_wc_webhook_delivery
    else:
        event_key = f"{topic}:{woo_order_id}:{payload_hash}"

    event_id = create_webhook_event(
        store_id=store_id,
        event_key=event_key,
        woo_order_id=woo_order_id,
        topic=topic,
        payload_hash=payload_hash,
    )

    if event_id is None:
        return JSONResponse({"status": "duplicate"})

    enqueue_job(process_woo_webhook_event, event_id)
    return JSONResponse({"status": "queued", "event_id": event_id})


@app.get("/health")
async def health() -> JSONResponse:
    queue = get_queue()
    return JSONResponse(
        {
            "status": "ok",
            "queue_length": queue.count,
            "last_webhook_received_at": get_last_webhook_received_at(),
            "last_webhook_processed_at": get_last_webhook_processed_at(),
        }
    )
