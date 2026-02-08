from __future__ import annotations

import hashlib
import logging
import mimetypes
from typing import Any, Dict, List, Optional, Tuple

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config.settings import load_settings
from services.store_service import get_default_store, get_store
from services.discogs_service import format_tracklist

logger = logging.getLogger(__name__)
_category_cache: Dict[Tuple[str, int], int] = {}


class WooNotConfigured(RuntimeError):
    pass


class WooError(RuntimeError):
    pass


def _settings(store: dict | None = None, store_id: int | None = None) -> dict:
    if store is None:
        store = get_store(store_id) if store_id else get_default_store()
    if not store:
        raise WooNotConfigured("WooCommerce store not configured")
    settings = load_settings()
    return {
        "base_url": str(store["store_url"]).rstrip("/"),
        "key": store["woo_consumer_key"],
        "secret": store["woo_consumer_secret"],
        "verify": settings.wc_verify_ssl,
    }


def is_configured(store_id: int | None = None) -> bool:
    store = get_store(store_id) if store_id else get_default_store()
    return store is not None


def _build_auth(store: dict | None = None, store_id: int | None = None) -> tuple[str, str]:
    settings = _settings(store, store_id)
    return settings["key"], settings["secret"]


def _base_url(store: dict | None = None, store_id: int | None = None) -> str:
    settings = _settings(store, store_id)
    base = settings["base_url"].rstrip("/")
    if "/wp-json/wc/" in base:
        prefix, _, suffix = base.partition("/wp-json/wc/")
        version = suffix.split("/")[0]
        return f"{prefix}/wp-json/wc/{version}"
    return base.rstrip("/") + "/wp-json/wc/v3"


def _wp_base_url(store: dict | None = None, store_id: int | None = None) -> str:
    settings = _settings(store, store_id)
    base = settings["base_url"].rstrip("/")
    if "/wp-json/wc/" in base:
        prefix, _, _ = base.partition("/wp-json/wc/")
        return f"{prefix}/wp-json/wp/v2"
    return base.rstrip("/") + "/wp-json/wp/v2"


def _request(method: str, path: str, *, store: dict | None = None, store_id: int | None = None, **kwargs: Any) -> requests.Response:
    base_url = _base_url(store, store_id)
    url = f"{base_url}{path}"
    settings = _settings(store, store_id)
    kwargs.setdefault("auth", _build_auth(store, store_id))
    kwargs.setdefault("timeout", 20)
    kwargs.setdefault("verify", settings["verify"])
    response = requests.request(method, url, **kwargs)
    response.raise_for_status()
    return response


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), retry=retry_if_exception_type(requests.RequestException))
def find_product_by_sku(sku: str, store: dict | None = None, store_id: int | None = None) -> Optional[Dict[str, Any]]:
    response = _request("GET", "/products", params={"sku": sku}, store=store, store_id=store_id)
    items = response.json()
    if not items:
        return None
    return items[0]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), retry=retry_if_exception_type(requests.RequestException))
def fetch_products_page(page: int, per_page: int = 100, store: dict | None = None, store_id: int | None = None) -> List[Dict[str, Any]]:
    response = _request("GET", "/products", params={"page": page, "per_page": per_page}, store=store, store_id=store_id)
    return response.json()


def fetch_max_sku(store: dict | None = None, store_id: int | None = None) -> int:
    if not is_configured(store_id):
        raise WooNotConfigured("WooCommerce not configured")
    page = 1
    per_page = 100
    max_sku = 0
    while True:
        products = fetch_products_page(page=page, per_page=per_page, store=store, store_id=store_id)
        if not products:
            break
        for product in products:
            sku = str(product.get("sku") or "").strip()
            if sku.isdigit():
                max_sku = max(max_sku, int(sku))
        if len(products) < per_page:
            break
        page += 1
    return max_sku


def fetch_next_sku(store: dict | None = None, store_id: int | None = None) -> int:
    return fetch_max_sku(store=store, store_id=store_id) + 1


def _slugify(value: str) -> str:
    return value.lower().strip().replace("/", "-").replace(" ", "-")


def _split_categories(value: Optional[str]) -> List[str]:
    if not value:
        return []
    parts = [part.strip() for part in value.split(",")]
    clean = []
    for part in parts:
        if not part:
            continue
        if part.strip().lower() in {"n/a", "na", "none", "unknown"}:
            continue
        clean.append(part)
    return clean


def _cache_key(name: str, parent_id: Optional[int]) -> Tuple[str, int]:
    return name.strip().lower(), int(parent_id or 0)


def _get_categories(
    *,
    search: Optional[str] = None,
    parent_id: Optional[int] = None,
    store: dict | None = None,
    store_id: int | None = None,
) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"per_page": 100}
    if search:
        params["search"] = search
    if parent_id is not None:
        params["parent"] = parent_id
    response = _request("GET", "/products/categories", params=params, store=store, store_id=store_id)
    return response.json()


def _find_category(name: str, parent_id: Optional[int], store: dict | None = None, store_id: int | None = None) -> Optional[Dict[str, Any]]:
    try:
        candidates = _get_categories(search=name, parent_id=parent_id, store=store, store_id=store_id)
    except requests.RequestException:
        logger.exception("Failed to fetch Woo categories for %s", name)
        raise
    name_lower = name.strip().lower()
    for cat in candidates:
        if (cat.get("name") or "").strip().lower() != name_lower:
            continue
        if parent_id is None or int(cat.get("parent") or 0) == int(parent_id or 0):
            return cat
    return None


def _ensure_category(name: str, parent_id: Optional[int] = None, store: dict | None = None, store_id: int | None = None) -> int:
    key = _cache_key(name, parent_id)
    if key in _category_cache:
        return _category_cache[key]

    existing = _find_category(name, parent_id, store=store, store_id=store_id)
    if existing and existing.get("id"):
        cat_id = int(existing["id"])
        _category_cache[key] = cat_id
        return cat_id

    payload: Dict[str, Any] = {"name": name}
    if parent_id:
        payload["parent"] = int(parent_id)
    try:
        response = _request("POST", "/products/categories", json=payload, store=store, store_id=store_id)
        category = response.json()
    except requests.RequestException:
        logger.exception("Failed creating Woo category %s (parent=%s)", name, parent_id)
        raise
    cat_id = int(category["id"])
    logger.info("Created Woo category '%s' (id=%s parent=%s)", name, cat_id, parent_id or 0)
    _category_cache[key] = cat_id
    return cat_id


def _ordered_unique(names: List[str]) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for name in names:
        key = name.strip().lower()
        if key in seen or not name.strip():
            continue
        seen.add(key)
        ordered.append(name)
    return ordered


def _build_categories(item: Dict[str, Any]) -> List[Dict[str, Any]]:
    product_type = (item.get("product_type") or "record").lower()
    category_ids: List[int] = []

    if product_type == "turntable":
        gear_id = _ensure_category("Gear")
        turntables_id = _ensure_category("Turntables", parent_id=gear_id)
        category_ids.extend([gear_id, turntables_id])
    elif product_type == "other":
        sounds_id = _ensure_category("Sounds")
        vinyl_id = _ensure_category("Vinyl", parent_id=sounds_id)
        category_ids.extend([sounds_id, vinyl_id])
        category_text = (item.get("genre") or "").strip()
        if category_text:
            category_ids.append(_ensure_category(category_text, parent_id=vinyl_id))
        else:
            category_ids.append(_ensure_category("Other", parent_id=vinyl_id))
    else:
        sounds_id = _ensure_category("Sounds")
        vinyl_id = _ensure_category("Vinyl", parent_id=sounds_id)
        electronic_id = _ensure_category("Electronic", parent_id=vinyl_id)
        category_ids.extend([sounds_id, vinyl_id, electronic_id])

        genres = _split_categories(item.get("genre"))
        styles = _split_categories(item.get("style"))
        electronic_genre = any(name.strip().lower() == "electronic" for name in genres)

        for name in genres:
            category_ids.append(_ensure_category(name, parent_id=vinyl_id))

        if electronic_genre:
            for name in styles:
                category_ids.append(_ensure_category(name, parent_id=electronic_id))

    unique_ids = _ordered_unique([str(cat_id) for cat_id in category_ids])
    final_ids = [int(cat_id) for cat_id in unique_ids]
    logger.info("Woo category IDs chosen for sku=%s: %s", item.get("id"), final_ids)
    return [{"id": cat_id} for cat_id in final_ids]


def category_names_from_inventory(item: Dict[str, Any]) -> List[str]:
    product_type = (item.get("product_type") or "record").lower()
    names: List[str] = []
    if product_type == "turntable":
        names = ["Gear", "Turntables"]
    elif product_type == "other":
        names = ["Sounds", "Vinyl"]
        category_text = (item.get("genre") or "").strip()
        if category_text:
            names.append(category_text)
        else:
            names.append("Other")
    else:
        names = ["Sounds", "Vinyl", "Electronic"]
        genres = _split_categories(item.get("genre"))
        styles = _split_categories(item.get("style"))
        electronic_genre = any(name.strip().lower() == "electronic" for name in genres)
        names.extend(genres)
        if electronic_genre:
            names.extend(styles)
    return _ordered_unique(names)


def _build_short_description(item: Dict[str, Any]) -> str:
    product_type = (item.get("product_type") or "record").lower()
    tracklist = item.get("tracklist") or []
    tracklist_html = format_tracklist(tracklist)

    if product_type == "other":
        category_text = (item.get("genre") or "").strip()
        supplier_name = (item.get("supplier_name") or "").strip()
        lines = []
        if category_text:
            lines.append(f"Category: {category_text}")
        if supplier_name:
            lines.append(f"Supplier: {supplier_name}")
        summary = "<br>".join(lines)
        if tracklist_html:
            return "\n".join(filter(None, [summary, tracklist_html]))
        return summary

    label = (item.get("label") or "N/A").strip() or "N/A"
    fmt = (item.get("format") or "N/A").strip() or "N/A"
    condition = (item.get("condition") or "N/A").strip() or "N/A"
    lines = [
        f"Label: {label}",
        f"Format: {fmt}",
        f"Condition: {condition}",
    ]
    summary = "\n".join(lines)
    if tracklist_html:
        return "\n".join([summary, tracklist_html])
    return summary


def _build_description(item: Dict[str, Any]) -> str:
    parts: List[str] = []
    notes = (item.get("description") or "").strip()
    if notes:
        parts.append(f"<p>{notes}</p>")
    return "".join(parts)


def _build_metadata(item: Dict[str, Any]) -> List[Dict[str, Any]]:
    meta = []
    release_id = item.get("discogs_release_id")
    if release_id:
        meta.append({"key": "discogs_release_id", "value": str(release_id)})
    master_id = item.get("discogs_master_id")
    if master_id:
        meta.append({"key": "discogs_master_id", "value": str(master_id)})
    discogs_uri = item.get("discogs_uri")
    if discogs_uri:
        meta.append({"key": "discogs_uri", "value": str(discogs_uri)})
    return meta


def payload_from_inventory(item: Dict[str, Any]) -> Dict[str, Any]:
    sku = str(item.get("id") or "").strip()
    name = item.get("artist_album") or "Unknown"
    price = float(item.get("price_gel") or 0)
    quantity = int(item.get("quantity") or 0)
    short_description = _build_short_description(item)
    description = _build_description(item)
    logger.info(
        "Woo descriptions for sku=%s: short=%s chars, long=%s chars",
        sku,
        len(short_description),
        len(description),
    )
    payload: Dict[str, Any] = {
        "name": name,
        "sku": sku,
        "regular_price": f"{price:.2f}",
        "manage_stock": True,
        "stock_quantity": quantity,
        "short_description": short_description,
        "description": description,
        "categories": _build_categories(item),
    }
    images = item.get("woo_images") or []
    if images:
        payload["images"] = images
    else:
        cover_url = item.get("cover_url")
        if cover_url:
            payload["images"] = [{"src": cover_url}]
    metadata = _build_metadata(item)
    if metadata:
        payload["meta_data"] = metadata
    return payload


def payload_for_update_from_inventory(item: Dict[str, Any]) -> Dict[str, Any]:
    name = item.get("artist_album") or "Unknown"
    price = float(item.get("price_gel") or 0)
    quantity = int(item.get("quantity") or 0)
    short_description = _build_short_description(item)
    description = _build_description(item)
    payload: Dict[str, Any] = {
        "name": name,
        "regular_price": f"{price:.2f}",
        "manage_stock": True,
        "stock_quantity": quantity,
        "short_description": short_description,
        "categories": _build_categories(item),
    }
    if description:
        payload["description"] = description
    return payload


def compute_sync_hash(payload: Dict[str, Any]) -> str:
    raw = str(sorted(payload.items())).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), retry=retry_if_exception_type(requests.RequestException))
def create_product(payload: Dict[str, Any]) -> Dict[str, Any]:
    response = _request("POST", "/products", json=payload)
    return response.json()


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), retry=retry_if_exception_type(requests.RequestException))
def update_product(
    product_id: int,
    payload: Dict[str, Any],
    store: dict | None = None,
    store_id: int | None = None,
) -> Dict[str, Any]:
    response = _request("PUT", f"/products/{product_id}", json=payload, store=store, store_id=store_id)
    return response.json()


def update_product_by_id(
    product_id: int,
    payload: Dict[str, Any],
    store: dict | None = None,
    store_id: int | None = None,
) -> Dict[str, Any]:
    return update_product(product_id, payload, store=store, store_id=store_id)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), retry=retry_if_exception_type(requests.RequestException))
def update_stock(product_id: int, quantity: int, store: dict | None = None, store_id: int | None = None) -> None:
    _request(
        "PUT",
        f"/products/{product_id}",
        json={"stock_quantity": quantity, "manage_stock": True},
        store=store,
        store_id=store_id,
    )


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), retry=retry_if_exception_type(requests.RequestException))
def upload_media(
    file_bytes: bytes,
    filename: str,
    content_type: str | None = None,
    store: dict | None = None,
    store_id: int | None = None,
) -> Dict[str, Any]:
    url = f"{_wp_base_url(store, store_id)}/media"
    settings = _settings(store, store_id)
    resolved_type = content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": resolved_type,
    }
    logger.info("Uploading Woo media %s (%s bytes)", filename, len(file_bytes))
    response = requests.post(
        url,
        data=file_bytes,
        headers=headers,
        auth=_build_auth(store, store_id),
        timeout=30,
        verify=settings["verify"],
    )
    response.raise_for_status()
    return response.json()


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), retry=retry_if_exception_type(requests.RequestException))
def fetch_orders(params: Optional[Dict[str, Any]] = None, store: dict | None = None, store_id: int | None = None) -> List[Dict[str, Any]]:
    response = _request(
        "GET",
        "/orders",
        params=params or {"status": "processing"},
        store=store,
        store_id=store_id,
    )
    return response.json()


def upsert_product_from_inventory(item: Dict[str, Any]) -> Dict[str, Any]:
    if not item.get("id"):
        raise WooError("Inventory item id missing")
    payload = payload_from_inventory(item)
    existing = find_product_by_sku(str(item["id"]))
    if existing and existing.get("id"):
        if not item.get("woo_product_id"):
            logger.warning(
                "Unexpected Woo product already exists for sku=%s (product id=%s)",
                item["id"],
                existing["id"],
            )
        logger.info("Woo update for sku=%s (id=%s)", item["id"], existing["id"])
        return update_product(int(existing["id"]), payload)
    logger.info("Woo create for sku=%s", item["id"])
    return create_product(payload)


def create_product_from_inventory(item: Dict[str, Any]) -> Dict[str, Any]:
    payload = payload_from_inventory(item)
    return create_product(payload)


def update_product_from_inventory(product_id: int, item: Dict[str, Any]) -> Dict[str, Any]:
    payload = payload_from_inventory(item)
    return update_product(product_id, payload)


def validate_credentials(store: dict) -> bool:
    try:
        response = _request("GET", "/system_status", store=store)
        return response.status_code == 200
    except Exception:
        logger.exception("Woo credential validation failed")
        return False


def fetch_order_by_id(store: dict, order_id: int) -> Dict[str, Any] | None:
    try:
        response = _request("GET", f"/orders/{order_id}", store=store)
        return response.json()
    except Exception:
        logger.exception("Failed fetching Woo order %s", order_id)
        return None


def update_order_status(store: dict, order_id: int, status: str) -> Dict[str, Any] | None:
    try:
        response = _request("PUT", f"/orders/{order_id}", json={"status": status}, store=store)
        return response.json()
    except Exception:
        logger.exception("Failed updating Woo order %s", order_id)
        return None


def create_webhook(store: dict, *, name: str, topic: str, delivery_url: str, secret: str) -> Dict[str, Any] | None:
    payload = {
        "name": name,
        "topic": topic,
        "delivery_url": delivery_url,
        "secret": secret,
        "status": "active",
    }
    try:
        response = _request("POST", "/webhooks", json=payload, store=store)
        return response.json()
    except Exception:
        logger.exception("Failed creating Woo webhook %s", topic)
        return None


def list_webhooks(store: dict) -> List[Dict[str, Any]]:
    response = _request("GET", "/webhooks", params={"per_page": 100}, store=store)
    return response.json()


def fetch_webhook(store: dict, webhook_id: int) -> Dict[str, Any] | None:
    try:
        response = _request("GET", f"/webhooks/{webhook_id}", store=store)
        return response.json()
    except Exception:
        logger.exception("Failed fetching Woo webhook %s", webhook_id)
        return None
