"""woocommerce_sync.py

WooCommerce REST API helpers + backwards-compatible entrypoints expected by older bot.py

This module is intentionally defensive:
- If Woo env vars are missing, functions become no-ops (and log why).
- Exposes `sync_inventory_to_woo(update=None, context=None)` so it can be called
  either as a startup function (no args) or as a Telegram command handler.

Required environment variables (to actually sync):
- WOO_URL=https://your-site.com
- WOO_CONSUMER_KEY=ck_...
- WOO_CONSUMER_SECRET=cs_...

Notes:
- Prices are sent as strings (Woo requirement).
- Uses simple products with stock management.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import requests

from db import get_db
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WooConfig:
    url: str
    consumer_key: str
    consumer_secret: str
    api_base: str = "/wp-json/wc/v3"
    timeout_s: int = 25

    @staticmethod
    def from_env() -> "WooConfig":
        url = (os.getenv("WOO_URL") or "").strip().rstrip("/")
        ck = (os.getenv("WOO_CONSUMER_KEY") or "").strip()
        cs = (os.getenv("WOO_CONSUMER_SECRET") or "").strip()
        if not url or not ck or not cs:
            raise ValueError("WOO_URL / WOO_CONSUMER_KEY / WOO_CONSUMER_SECRET must be set")
        return WooConfig(url=url, consumer_key=ck, consumer_secret=cs)


def woo_is_configured() -> bool:
    return bool((os.getenv("WOO_URL") or "").strip()) and bool((os.getenv("WOO_CONSUMER_KEY") or "").strip()) and bool(
        (os.getenv("WOO_CONSUMER_SECRET") or "").strip()
    )


class WooSync:
    def __init__(self, cfg: WooConfig):
        self.cfg = cfg

    def _endpoint(self, path: str) -> str:
        path = path if path.startswith("/") else f"/{path}"
        return f"{self.cfg.url}{self.cfg.api_base}{path}"

    def _request(self, method: str, url: str, *, params=None, json=None) -> requests.Response:
        return requests.request(
            method,
            url,
            params=params,
            json=json,
            auth=(self.cfg.consumer_key, self.cfg.consumer_secret),
            timeout=self.cfg.timeout_s,
        )

    def build_product_payload(
        self,
        *,
        sku: str,
        title: str,
        price_gel: float,
        quantity: int,
        description: str,
        meta: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        meta_data = []
        if meta:
            meta_data = [{"key": k, "value": v} for k, v in meta.items()]

        return {
            "name": title,
            "type": "simple",
            "sku": sku,
            "regular_price": f"{float(price_gel):.2f}",
            "manage_stock": True,
            "stock_quantity": int(quantity),
            "description": description,
            "short_description": description,
            "meta_data": meta_data,
        }

    def upsert_product_by_sku(self, product: Dict[str, Any]) -> Dict[str, Any]:
        sku = (product.get("sku") or "").strip()
        if not sku:
            raise ValueError("Product payload must include sku")

        # Search by SKU
        r = self._request("GET", self._endpoint("/products"), params={"sku": sku})
        r.raise_for_status()
        matches = r.json() or []

        if matches:
            existing = matches[0]
            pid = existing.get("id")
            if not pid:
                raise ValueError("Woo response missing product id")

            # Merge stock if Woo returns integer stock
            existing_qty = existing.get("stock_quantity")
            incoming_qty = int(product.get("stock_quantity") or 0)
            new_qty = incoming_qty
            if isinstance(existing_qty, int):
                new_qty = max(0, existing_qty + incoming_qty)

            update_payload = {
                "regular_price": str(product.get("regular_price")),
                "manage_stock": True,
                "stock_quantity": new_qty,
                "description": product.get("description"),
                "short_description": product.get("short_description"),
                "meta_data": product.get("meta_data", []),
            }
            u = self._request("PUT", self._endpoint(f"/products/{pid}"), json=update_payload)
            u.raise_for_status()
            return u.json()

        c = self._request("POST", self._endpoint("/products"), json=product)
        c.raise_for_status()
        return c.json()


def _get_sync() -> Optional[WooSync]:
    if not woo_is_configured():
        return None
    try:
        return WooSync(WooConfig.from_env())
    except Exception as e:
        logger.error("Woo config error: %s", e)
        return None


def _format_desc(row: Tuple, supplier_name: str) -> str:
    # row order: inventory.* plus supplier_name if joined
    # Inventory schema in this project: id, artist_album, genre, style, label, format, condition, price_gel, quantity, supplier_id, created_at
    inv_id = row[0]
    artist_album = row[1]
    genre = row[2] or ""
    style = row[3] or ""
    label = row[4] or ""
    fmt = row[5] or ""
    cond = row[6] or ""
    return (
        f"ID: {inv_id}\n"
        f"Condition: {cond}\n"
        f"Format: {fmt}\n"
        f"Label: {label}\n"
        f"Genre: {genre}\n"
        f"Style: {style}\n"
        f"Supplier: {supplier_name}".strip()
    )


def upsert_product(
    *,
    inventory_id: int,
    title: str,
    price_gel: float,
    quantity: int,
    condition: str,
    supplier_name: str,
    genre: str = "",
    style: str = "",
    label: str = "",
    vinyl_format: str = "",
    discogs_release_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Upsert one inventory item as a Woo product."""
    sync = _get_sync()
    if sync is None:
        raise RuntimeError("Woo is not configured")

    sku = f"inv-{inventory_id}-{condition}" if condition else f"inv-{inventory_id}"
    desc = (
        f"Condition: {condition}\n"
        f"Format: {vinyl_format}\n"
        f"Label: {label}\n"
        f"Genre: {genre}\n"
        f"Style: {style}\n"
        f"Supplier: {supplier_name}\n"
        f"Inventory ID: {inventory_id}".strip()
    )

    meta = {
        "inventory_id": str(inventory_id),
        "condition": str(condition),
        "supplier": str(supplier_name),
    }
    if discogs_release_id is not None:
        meta["discogs_release_id"] = str(discogs_release_id)

    payload = sync.build_product_payload(
        sku=sku,
        title=title,
        price_gel=price_gel,
        quantity=quantity,
        description=desc,
        meta=meta,
    )
    return sync.upsert_product_by_sku(payload)


async def upsert_product_async(**kwargs) -> Dict[str, Any]:
    return await asyncio.to_thread(upsert_product, **kwargs)


def sync_inventory_to_woo(update=None, context=None):
    """Backwards-compatible entrypoint.

    - If called with (update, context): replies to the user with a short summary.
    - If called with no args: runs silently and logs.
    """
    if not woo_is_configured():
        msg = "🛒 Woo sync skipped: WOO_URL / key / secret not configured."
        logger.warning(msg)
        if update is not None and getattr(update, "message", None):
            # schedule send (can't await in sync function)
            try:
                context.application.create_task(update.message.reply_text(msg))
            except Exception:
                pass
        return

    sync = _get_sync()
    if sync is None:
        msg = "🛒 Woo sync skipped: config error (see logs)."
        logger.error(msg)
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
                   i.condition, i.price_gel, i.quantity, i.supplier_id, i.created_at,
                   COALESCE(s.name, '') AS supplier_name
            FROM inventory i
            LEFT JOIN supplier s ON s.id = i.supplier_id
            WHERE COALESCE(i.quantity, 0) > 0
            ORDER BY i.id ASC
            """
        )
        rows = cur.fetchall() or []

    logger.info("Woo full sync: %d inventory rows", len(rows))

    for row in rows:
        try:
            inv_id = int(row[0])
            title = str(row[1])
            genre = row[2] or ""
            style = row[3] or ""
            label = row[4] or ""
            fmt = row[5] or ""
            cond = row[6] or ""
            price = float(row[7] or 0.0)
            qty = int(row[8] or 0)
            supplier_name = row[11] or ""

            product = upsert_product(
                inventory_id=inv_id,
                title=title,
                price_gel=price,
                quantity=qty,
                condition=cond,
                supplier_name=supplier_name,
                genre=str(genre),
                style=str(style),
                label=str(label),
                vinyl_format=str(fmt),
            )
            pid = product.get("id")
            logger.info("Woo upsert OK: inv=%s -> product_id=%s", inv_id, pid)
            ok += 1
        except Exception as e:
            logger.exception("Woo upsert FAIL for row %s: %s", row[0], e)
            fail += 1

    summary = f"🛒 Woo sync finished. OK: {ok}, Failed: {fail}" if fail else f"🛒 Woo sync finished. OK: {ok}"
    logger.info(summary)
    if update is not None and getattr(update, "message", None):
        try:
            context.application.create_task(update.message.reply_text(summary))
        except Exception:
            pass


__all__ = [
    "WooConfig",
    "WooSync",
    "woo_is_configured",
    "upsert_product",
    "upsert_product_async",
    "sync_inventory_to_woo",
]
