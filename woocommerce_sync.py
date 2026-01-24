"""woocommerce_sync.py

WooCommerce REST API helpers for inventory sync.

Required environment variables:
- WOO_URL
- WOO_CONSUMER_KEY
- WOO_CONSUMER_SECRET

Optional:
- WOO_DRAFT_ONLY=true (create products as draft)
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import os
from typing import Any, Dict, Optional

import requests
from dotenv import load_dotenv

from db import get_db

load_dotenv()

logger = logging.getLogger(__name__)


API_BASE = "/wp-json/wc/v3"
DEFAULT_TIMEOUT_S = float(os.getenv("WOO_TIMEOUT", "25"))


def woo_is_configured() -> bool:
    return bool((os.getenv("WOO_URL") or "").strip()) and bool(
        (os.getenv("WOO_CONSUMER_KEY") or "").strip()
    ) and bool((os.getenv("WOO_CONSUMER_SECRET") or "").strip())


def _get_woo_base_url() -> str:
    return (os.getenv("WOO_URL") or "").strip().rstrip("/")


def _get_woo_auth() -> tuple[str, str]:
    return (
        (os.getenv("WOO_CONSUMER_KEY") or "").strip(),
        (os.getenv("WOO_CONSUMER_SECRET") or "").strip(),
    )


def _endpoint(path: str) -> str:
    path = path if path.startswith("/") else f"/{path}"
    return f"{_get_woo_base_url()}{API_BASE}{path}"


def _build_title(item: Dict[str, Any]) -> str:
    artist_album = (item.get("artist_album") or "").strip()
    year = item.get("year")
    if year:
        return f"{artist_album} ({year})".strip()
    return artist_album


def _build_sku(item: Dict[str, Any]) -> str:
    discogs_id = item.get("discogs_id")
    if discogs_id:
        return f"discogs-{discogs_id}"
    inventory_id = item.get("inventory_id")
    if inventory_id:
        return f"inv-{inventory_id}"
    return f"record-{int(datetime.datetime.utcnow().timestamp())}"


def _build_meta(item: Dict[str, Any]) -> list[dict[str, str]]:
    meta: dict[str, str] = {}
    if item.get("discogs_id"):
        meta["discogs_id"] = str(item.get("discogs_id"))
    if item.get("condition"):
        meta["condition"] = str(item.get("condition"))
    if item.get("genre"):
        meta["genre"] = str(item.get("genre"))
    if item.get("style"):
        meta["style"] = str(item.get("style"))
    if item.get("label"):
        meta["label"] = str(item.get("label"))
    if item.get("format"):
        meta["format"] = str(item.get("format"))
    return [{"key": k, "value": v} for k, v in meta.items()]


def _build_payload(item: Dict[str, Any]) -> Dict[str, Any]:
    price_gel = float(item.get("price_gel") or 0)
    quantity = int(item.get("quantity") or 0)
    status = "draft" if os.getenv("WOO_DRAFT_ONLY", "false").lower() == "true" else "publish"

    return {
        "name": _build_title(item),
        "type": "simple",
        "sku": _build_sku(item),
        "regular_price": f"{price_gel:.2f}",
        "manage_stock": True,
        "stock_quantity": quantity,
        "status": status,
        "description": (item.get("description") or "").strip(),
        "meta_data": _build_meta(item),
    }


def _request(
    method: str,
    url: str,
    *,
    json: Optional[dict] = None,
    params: Optional[dict[str, Any]] = None,
) -> requests.Response:
    ck, cs = _get_woo_auth()
    response = requests.request(
        method,
        url,
        auth=(ck, cs),
        params=params,
        json=json,
        timeout=DEFAULT_TIMEOUT_S,
    )
    response.raise_for_status()
    return response


def _find_product_by_sku(sku: str) -> Optional[int]:
    if not sku:
        return None
    response = _request("GET", _endpoint("/products"), params={"sku": sku, "per_page": 100})
    products = response.json() or []
    for product in products:
        if str(product.get("sku") or "").strip() == sku:
            return int(product.get("id"))
    return None


def _upsert_product_sync(item: Dict[str, Any]) -> Dict[str, Any]:
    payload = _build_payload(item)
    sku = payload.get("sku")
    if not sku:
        raise ValueError("WooCommerce payload missing sku")

    product_id = None
    try:
        product_id = _find_product_by_sku(sku)
    except Exception:
        logger.info("Woo lookup by SKU failed for sku=%s", sku)

    if product_id:
        response = _request("PUT", _endpoint(f"/products/{product_id}"), json=payload)
    else:
        response = requests.post(
            _endpoint("/products"),
            auth=_get_woo_auth(),
            json=payload,
            timeout=DEFAULT_TIMEOUT_S,
        )
        response.raise_for_status()

    product = response.json()
    inv_id = item.get("inventory_id")
    if inv_id:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE inventory
                SET woo_product_id = ?, woo_synced = 1, woo_last_synced_at = ?
                WHERE id = ?
                """,
                (
                    int(product.get("id")) if product.get("id") else None,
                    datetime.datetime.utcnow().isoformat(),
                    int(inv_id),
                ),
            )
            conn.commit()

    return product


async def upsert_product_async(item: Dict[str, Any], update=None, context=None) -> Dict[str, Any]:
    if not woo_is_configured():
        raise RuntimeError("WooCommerce is not configured")
    return await asyncio.to_thread(_upsert_product_sync, item)


def sync_inventory_to_woo(update=None, context=None):
    """Sync all inventory rows to WooCommerce.

    If update/context are provided, send a short summary message.
    """
    if not woo_is_configured():
        msg = "🛒 Woo sync skipped: WOO_URL / WOO_CONSUMER_KEY / WOO_CONSUMER_SECRET not configured."
        logger.warning(msg)
        if update is not None and getattr(update, "message", None):
            try:
                context.application.create_task(update.message.reply_text(msg))
            except Exception:
                pass
        return

    ok = 0
    fail = 0

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT i.id, i.artist_album, i.genre, i.style, i.label, i.format,
                   i.condition, i.price_gel, i.quantity, i.year, i.description
            FROM inventory i
            WHERE COALESCE(i.quantity, 0) > 0
            ORDER BY i.id ASC
            """
        )
        rows = cur.fetchall() or []

    logger.info("Woo full sync: %d inventory rows", len(rows))

    for row in rows:
        item = {
            "inventory_id": int(row[0]),
            "artist_album": row[1],
            "genre": row[2] or "",
            "style": row[3] or "",
            "label": row[4] or "",
            "format": row[5] or "",
            "condition": row[6] or "",
            "price_gel": float(row[7] or 0.0),
            "quantity": int(row[8] or 0),
            "year": row[9],
            "description": row[10] or "",
        }
        try:
            _upsert_product_sync(item)
            ok += 1
        except Exception as exc:
            logger.exception("Woo upsert failed for inventory %s: %s", row[0], exc)
            fail += 1

    summary = f"🛒 Woo sync finished. OK: {ok}, Failed: {fail}" if fail else f"🛒 Woo sync finished. OK: {ok}"
    logger.info(summary)
    if update is not None and getattr(update, "message", None):
        try:
            context.application.create_task(update.message.reply_text(summary))
        except Exception:
            pass


__all__ = [
    "woo_is_configured",
    "upsert_product_async",
    "sync_inventory_to_woo",
]
