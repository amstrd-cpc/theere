from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, List, Optional

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config.settings import load_settings
from services.discogs_service import format_tracklist

logger = logging.getLogger(__name__)


class WooNotConfigured(RuntimeError):
    pass


class WooError(RuntimeError):
    pass


def _settings() -> dict:
    settings = load_settings()
    if not (settings.wc_api_url and settings.wc_consumer_key and settings.wc_consumer_secret):
        raise WooNotConfigured("WooCommerce not configured")
    return {
        "base_url": settings.wc_api_url.rstrip("/"),
        "key": settings.wc_consumer_key,
        "secret": settings.wc_consumer_secret,
        "verify": settings.wc_verify_ssl,
    }


def is_configured() -> bool:
    settings = load_settings()
    return bool(settings.wc_api_url and settings.wc_consumer_key and settings.wc_consumer_secret)


def _build_auth() -> tuple[str, str]:
    settings = _settings()
    return settings["key"], settings["secret"]


def _base_url() -> str:
    settings = _settings()
    base = settings["base_url"]
    if "/wp-json/wc/" in base:
        return base
    return base.rstrip("/") + "/wp-json/wc/v3"


def _request(method: str, path: str, **kwargs: Any) -> requests.Response:
    base_url = _base_url()
    url = f"{base_url}{path}"
    settings = _settings()
    kwargs.setdefault("auth", _build_auth())
    kwargs.setdefault("timeout", 20)
    kwargs.setdefault("verify", settings["verify"])
    response = requests.request(method, url, **kwargs)
    response.raise_for_status()
    return response


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), retry=retry_if_exception_type(requests.RequestException))
def find_product_by_sku(sku: str) -> Optional[Dict[str, Any]]:
    response = _request("GET", "/products", params={"sku": sku})
    items = response.json()
    if not items:
        return None
    return items[0]


def _slugify(value: str) -> str:
    return value.lower().strip().replace("/", "-").replace(" ", "-")


def _build_categories(item: Dict[str, Any]) -> List[Dict[str, Any]]:
    categories = []
    product_type = (item.get("product_type") or "record").lower()
    if product_type == "turntable":
        categories.append({"name": "Gear"})
        categories.append({"name": "Turntables"})
    else:
        categories.append({"name": "Sounds"})
        categories.append({"name": "Vinyl"})
        genre = item.get("genre")
        if genre:
            categories.append({"name": genre})
    return categories


def _build_short_description(item: Dict[str, Any]) -> str:
    tracklist = item.get("tracklist") or []
    tracklist_html = format_tracklist(tracklist)
    base_lines = []
    label = item.get("label") or "N/A"
    fmt = item.get("format") or "N/A"
    condition = item.get("condition") or "N/A"
    base_lines.append(f"<strong>Label:</strong> {label}")
    base_lines.append(f"<strong>Format:</strong> {fmt}")
    base_lines.append(f"<strong>Condition:</strong> {condition}")
    base_html = "<br/>".join(base_lines)
    return base_html + (tracklist_html or "")


def payload_from_inventory(item: Dict[str, Any]) -> Dict[str, Any]:
    sku = str(item.get("id") or "").strip()
    name = item.get("artist_album") or "Unknown"
    price = float(item.get("price_gel") or 0)
    quantity = int(item.get("quantity") or 0)
    payload: Dict[str, Any] = {
        "name": name,
        "sku": sku,
        "regular_price": f"{price:.2f}",
        "manage_stock": True,
        "stock_quantity": quantity,
        "short_description": _build_short_description(item),
        "categories": _build_categories(item),
    }
    cover_url = item.get("cover_url")
    if cover_url:
        payload["images"] = [{"src": cover_url}]
    return payload


def compute_sync_hash(payload: Dict[str, Any]) -> str:
    raw = str(sorted(payload.items())).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), retry=retry_if_exception_type(requests.RequestException))
def create_product(payload: Dict[str, Any]) -> Dict[str, Any]:
    response = _request("POST", "/products", json=payload)
    return response.json()


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), retry=retry_if_exception_type(requests.RequestException))
def update_product(product_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    response = _request("PUT", f"/products/{product_id}", json=payload)
    return response.json()


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), retry=retry_if_exception_type(requests.RequestException))
def update_stock(product_id: int, quantity: int) -> None:
    _request("PUT", f"/products/{product_id}", json={"stock_quantity": quantity, "manage_stock": True})


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), retry=retry_if_exception_type(requests.RequestException))
def fetch_orders(params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    response = _request("GET", "/orders", params=params or {"status": "processing"})
    return response.json()


def upsert_product_from_inventory(item: Dict[str, Any]) -> Dict[str, Any]:
    if not item.get("id"):
        raise WooError("Inventory item id missing")
    payload = payload_from_inventory(item)
    existing = find_product_by_sku(str(item["id"]))
    if existing and existing.get("id"):
        return update_product(int(existing["id"]), payload)
    return create_product(payload)


def create_product_from_inventory(item: Dict[str, Any]) -> Dict[str, Any]:
    payload = payload_from_inventory(item)
    return create_product(payload)


def update_product_from_inventory(product_id: int, item: Dict[str, Any]) -> Dict[str, Any]:
    payload = payload_from_inventory(item)
    return update_product(product_id, payload)
