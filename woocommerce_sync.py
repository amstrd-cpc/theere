from __future__ import annotations

"""WooCommerce sync helpers.

This module is intentionally defensive because different versions of your bot have
imported different symbols from here over time.

Goals:
- Never crash on import because a symbol is missing.
- Allow `sync_inventory_to_woo()` to be called in 2 ways:
  1) As a PTB callback: sync_inventory_to_woo(update, context)
  2) On startup with no args: sync_inventory_to_woo()

Bulk syncing a whole database is NOT implemented here (schema/project-specific).
Instead, the add flow should call `upsert_product_async(payload)` after saving.
"""

from dataclasses import dataclass
import asyncio
import inspect
import os
from typing import TYPE_CHECKING, Any, Optional

import requests

if TYPE_CHECKING:  # pragma: no cover
    from telegram import Update  # type: ignore
    from telegram.ext import ContextTypes  # type: ignore


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

def _env_value(primary: str, fallback: str) -> str:
    return (os.getenv(primary) or os.getenv(fallback) or "").strip()


def _parse_wc_api_url(api_url: str) -> tuple[str, str]:
    if "/wp-json/wc/" in api_url:
        base, suffix = api_url.split("/wp-json/wc/", 1)
        return base.rstrip("/"), f"/wp-json/wc/{suffix.strip('/')}"
    return api_url.rstrip("/"), "/wp-json/wc/v3"


def woo_is_configured() -> bool:
    url = _env_value("WC_API_URL", "WOO_URL")
    ck = _env_value("WC_CONSUMER_KEY", "WOO_CONSUMER_KEY")
    cs = _env_value("WC_CONSUMER_SECRET", "WOO_CONSUMER_SECRET")
    return bool(url and ck and cs)


@dataclass(frozen=True)
class WooConfig:
    url: str
    consumer_key: str
    consumer_secret: str
    api_base: str = "/wp-json/wc/v3"
    timeout_s: int = 25

    @staticmethod
    def from_env() -> "WooConfig":
        raw_url = _env_value("WC_API_URL", "WOO_URL")
        ck = _env_value("WC_CONSUMER_KEY", "WOO_CONSUMER_KEY")
        cs = _env_value("WC_CONSUMER_SECRET", "WOO_CONSUMER_SECRET")
        if not raw_url or not ck or not cs:
            raise ValueError(
                "WC_API_URL / WC_CONSUMER_KEY / WC_CONSUMER_SECRET must be set "
                "(WOO_URL / WOO_CONSUMER_KEY / WOO_CONSUMER_SECRET also supported)"
            )
        url, api_base = _parse_wc_api_url(raw_url)
        return WooConfig(url=url, consumer_key=ck, consumer_secret=cs, api_base=api_base)


# -----------------------------------------------------------------------------
# Core client
# -----------------------------------------------------------------------------

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
        release_id: int,
        title: str,
        price_gel: float,
        quantity: int,
        condition: str,
        supplier_name: str,
        genres: str = "",
        styles: str = "",
        labels: str = "",
        vinyl_format: str = "",
        image_url: str | None = None,
    ) -> dict:
        """Create a Woo product payload.

        Note: image handling is optional; if you want to attach Discogs image URLs,
        pass image_url.
        """
        safe_release = int(release_id) if release_id else 0
        sku = f"discogs-{safe_release}-{condition}" if safe_release else (f"record-{title}-{condition}"[:40])

        desc = (
            f"Condition: {condition}\n"
            f"Format: {vinyl_format}\n"
            f"Label: {labels}\n"
            f"Genre: {genres}\n"
            f"Style: {styles}\n"
            f"Supplier: {supplier_name}\n"
            f"Discogs release: {safe_release}"
        )

        payload: dict[str, Any] = {
            "name": title,
            "type": "simple",
            "sku": sku,
            "regular_price": f"{float(price_gel):.2f}",
            "manage_stock": True,
            "stock_quantity": int(quantity),
            "description": desc,
            "short_description": desc,
            "meta_data": [
                {"key": "discogs_release_id", "value": str(safe_release)},
                {"key": "condition", "value": condition},
                {"key": "supplier", "value": supplier_name},
            ],
        }

        if image_url:
            payload["images"] = [{"src": image_url}]

        return payload

    def upsert_product_by_sku(self, product: dict) -> dict:
        """Create product if SKU doesn't exist; otherwise update it.

        If product exists, stock is incremented by incoming stock_quantity.
        """
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
            if product.get("images"):
                update_payload["images"] = product.get("images")

            u = self._request("PUT", self._endpoint(f"/products/{pid}"), json=update_payload)
            u.raise_for_status()
            return u.json()

        # Create new
        c = self._request("POST", self._endpoint("/products"), json=product)
        c.raise_for_status()
        return c.json()


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------

def upsert_product(product_payload: dict) -> dict:
    """Blocking upsert."""
    if not woo_is_configured():
        raise ValueError("WooCommerce is not configured")
    sync = WooSync(WooConfig.from_env())
    return sync.upsert_product_by_sku(product_payload)


async def upsert_product_async(product_payload: dict) -> dict:
    """Async wrapper around blocking upsert (runs in a thread)."""
    return await asyncio.to_thread(upsert_product, product_payload)


def _schedule_reply(update: Any, context: Any, text: str) -> None:
    """Reply safely across PTB versions (sync/async)."""
    msg = getattr(update, "effective_message", None) or getattr(update, "message", None)
    if not msg:
        return
    reply = getattr(msg, "reply_text", None)
    if not reply:
        return

    try:
        if inspect.iscoroutinefunction(reply):
            # PTB v20+ style
            app = getattr(context, "application", None)
            if app and hasattr(app, "create_task"):
                app.create_task(reply(text))
            else:
                # fallback: run it in the current loop if possible
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(reply(text))
                except RuntimeError:
                    asyncio.run(reply(text))
        else:
            # PTB v13 style
            reply(text)
    except Exception:
        return


def sync_inventory_to_woo(update: Optional[Any] = None, context: Optional[Any] = None) -> None:
    """Compatibility entrypoint.

    Your older bot.py versions sometimes call this on startup with no args.
    Newer ones may register it as a command callback.

    This function intentionally does NOT attempt to bulk sync your whole DB.
    It only reports whether Woo is configured and reminds that /add does auto-sync.
    """

    # Called on startup (no update/context) -> do nothing except avoid crashing.
    if update is None or context is None:
        return

    if not woo_is_configured():
        _schedule_reply(
            update,
            context,
            "🛒 Woo sync is not configured. Set WC_API_URL / WC_CONSUMER_KEY / WC_CONSUMER_SECRET in .env",
        )
        return

    _schedule_reply(
        update,
        context,
        "🛒 Woo sync is available, but bulk inventory sync isn't enabled in this build.\n\n"
        "New items added via /add will sync automatically in the background.",
    )


# Backwards-compat aliases (in case older code imports these names)
__all__ = [
    "woo_is_configured",
    "WooConfig",
    "WooSync",
    "upsert_product",
    "upsert_product_async",
    "sync_inventory_to_woo",
]
