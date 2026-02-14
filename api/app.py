from __future__ import annotations

import base64
import hashlib
import hmac
import json

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from bootstrap.container import build_container
from core.application.use_cases.process_woo_order import process_woo_order

app = FastAPI(title="Record Store API")


def _verify_wc_signature(raw_body: bytes, header_sig: str, secret: str) -> bool:
    if not header_sig:
        return False
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(expected, header_sig)


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})


@app.post("/webhooks/woo")
async def woo_webhook(
    request: Request,
    store_id: int | None = Query(default=None),
    x_wc_webhook_signature: str | None = Header(default=None, alias="X-WC-Webhook-Signature"),
) -> JSONResponse:
    container = build_container()
    store = container.settings_provider.get_store(store_id) if store_id else container.settings_provider.get_default_store()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    raw_body = await request.body()
    secret = str(store.get("webhook_secret") or "")
    if secret and not _verify_wc_signature(raw_body, x_wc_webhook_signature or "", secret):
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc

    woo_order_id = payload.get("id") if isinstance(payload, dict) else None
    if not woo_order_id:
        raise HTTPException(status_code=400, detail="Missing order id")

    result = process_woo_order(
        store_id=int(store["id"]),
        woo_order_id=int(woo_order_id),
        settings=container.settings_provider,
        orders_repo=container.orders_repo,
        inventory_repo=container.inventory_repo,
        sales_repo=container.sales_repo,
        woo_gateway=container.woo_gateway,
        discogs_gateway=container.discogs_gateway,
        notifier=container.notifier,
    )
    return JSONResponse({"status": "processed", "order_id": result.order_id, "matched": len(result.matched_items), "unmapped": result.unmapped_items})
