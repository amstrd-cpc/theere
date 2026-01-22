import os
import requests
from requests.auth import HTTPBasicAuth

import discogs_client


class WooNotConfigured(Exception):
    pass


# ---------- Helpers for human-friendly formatting ----------

_CONDITION_LABELS = {
    "M": "Mint (M)",
    "MINT": "Mint (M)",
    "NM": "Near Mint (NM)",
    "NM-": "Near Mint (NM)",
    "NEAR MINT": "Near Mint (NM)",
    "VG+": "Very Good Plus (VG+)",
    "VG": "Very Good (VG)",
    "G+": "Good Plus (G+)",
    "G": "Good (G)",
    "F": "Fair (F)",
    "P": "Poor (P)",
}


def _human_condition(raw: str | None) -> str:
    if not raw:
        return ""
    code = str(raw).strip().upper()
    return _CONDITION_LABELS.get(code, raw)


def _build_pretty_description(item: dict, ptype: str) -> str:
    """Build a nicer product description for Woo.

    Records:
      - Title on first line
      - Label / Format / Condition on second
      - Any custom description after that

    Other types:
      - Just use item['description'] if present.
    """
    desc = (item.get("description") or "").strip()

    if ptype == "record":
        title = (item.get("artist_album") or "").strip()
        label = (item.get("label") or "").strip()
        fmt = (item.get("format") or "").strip()
        cond_full = _human_condition(item.get("condition"))

        lines: list[str] = []

        if title:
            lines.append(f"<strong>{title}</strong>")

        meta_parts: list[str] = []
        if label:
            meta_parts.append(label)
        if fmt:
            meta_parts.append(fmt)
        if cond_full:
            meta_parts.append(f"Condition: {cond_full}")

        if meta_parts:
            lines.append(" · ".join(meta_parts))

        if desc:
            lines.append(desc)

        return "<br>".join(lines) if lines else desc

    # Non-records: keep whatever custom description was provided
    return desc


def _get_wc_config():
    url = os.getenv("WC_API_URL")
    key = os.getenv("WC_CONSUMER_KEY")
    secret = os.getenv("WC_CONSUMER_SECRET")
    return url, key, secret


# whether to verify SSL certs when talking to Woo / WP
VERIFY_SSL = os.getenv("WC_VERIFY_SSL", "true").lower() == "true"
REQUEST_TIMEOUT = float(os.getenv("WC_REQUEST_TIMEOUT", "30"))

_discogs_client = None


def _get_discogs_client():
    """Lazy-init Discogs client if DISCOGS_TOKEN is set."""
    global _discogs_client
    token = os.getenv("DISCOGS_TOKEN")
    if not token:
        return None
    if _discogs_client is None:
        _discogs_client = discogs_client.Client(
            "RecordStoreBot/1.0", user_token=token
        )
    return _discogs_client


def _get_base_and_auth():
    base_url, key, secret = _get_wc_config()
    if not all([base_url, key, secret]):
        raise WooNotConfigured("WooCommerce is not configured")
    base_url = base_url.rstrip("/")
    return base_url, HTTPBasicAuth(key, secret)


def is_configured() -> bool:
    url, key, secret = _get_wc_config()
    return all([url, key, secret])


# ---------- Discogs enrichment (for records) ----------


def _build_discogs_enrichment(item: dict):
    """
    For records:
    - cover image url
    - tracklist HTML
    """
    client = _get_discogs_client()
    if not client:
        return None, None, None

    query = item.get("artist_album")
    if not query:
        return None, None, None

    try:
        results = list(client.search(query, type="release"))
        if not results:
            return None, None, None
        release = results[0]
    except Exception:
        return None, None, None

    # cover image
    image_url = None
    try:
        images = getattr(release, "images", None) or release.data.get("images", [])
    except Exception:
        images = []
    if images:
        first = images[0]
        image_url = first.get("uri") or first.get("resource_url")

    # tracklist
    tracklist_html = None
    try:
        tracks = getattr(release, "tracklist", []) or []
    except Exception:
        tracks = []

    if tracks:
        parts = ["<h3>Tracklist</h3>", "<ol>"]
        for t in tracks:
            try:
                pos = getattr(t, "position", "") or ""
                title = getattr(t, "title", "") or ""
                duration = getattr(t, "duration", "") or ""
            except Exception:
                continue

            label = f"{pos} {title}".strip() or title or pos
            if not label:
                continue

            if duration:
                parts.append(f"<li>{label} ({duration})</li>")
            else:
                parts.append(f"<li>{label}</li>")
        parts.append("</ol>")
        tracklist_html = "\n".join(parts)
    # discogs meta
    meta = {}
    try:
        rid = getattr(release, 'id', None) or (getattr(release, 'data', {}) or {}).get('id')
        if rid is not None:
            meta['discogs_release_id'] = str(rid)
    except Exception:
        pass
    try:
        mid = getattr(release, 'master_id', None) or (getattr(release, 'data', {}) or {}).get('master_id')
        if mid is not None:
            meta['discogs_master_id'] = str(mid)
    except Exception:
        pass
    try:
        uri = getattr(release, 'uri', None) or (getattr(release, 'data', {}) or {}).get('uri')
        if uri:
            meta['discogs_uri'] = str(uri)
    except Exception:
        pass

    return image_url, tracklist_html, meta


# ---------- Category helpers ----------


def _find_category_by_name(base_url, auth, name, parent_id=None):
    params = {"per_page": 100, "search": name}
    resp = requests.get(
        f"{base_url}/products/categories",
        auth=auth,
        params=params,
        timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL,
    )
    resp.raise_for_status()
    for cat in resp.json():
        if cat["name"].lower() == name.lower():
            if parent_id is None or cat.get("parent") == parent_id:
                return cat
    return None


def _ensure_category(base_url, auth, name, parent_id=None):
    existing = _find_category_by_name(base_url, auth, name, parent_id)
    if existing:
        return existing["id"]
    payload = {"name": name}
    if parent_id:
        payload["parent"] = parent_id
    resp = requests.post(
        f"{base_url}/products/categories",
        auth=auth,
        json=payload,
        timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def _get_categories_for_item(base_url, auth, item: dict):
    """
    Decide WooCommerce product categories based on product_type + genre/style.

    Records:
        Sounds / Vinyl / <Genre>
        If genre == Electronic:
            Also create child categories under <Electronic> for each style.
    Turntables:
        Gear / Turntables
    Accessories:
        Accessories
    Others:
        Other
    """
    ptype = (item.get("product_type") or "record").strip().lower()

    if ptype == "record":
        root_id = _ensure_category(base_url, auth, "Sounds", None)
        vinyl_id = _ensure_category(base_url, auth, "Vinyl", root_id)

        raw_genre = (item.get("genre") or "").split(",")[0].strip() or "Other"
        genre_id = _ensure_category(base_url, auth, raw_genre, vinyl_id)

        categories = [{"id": root_id}, {"id": vinyl_id}, {"id": genre_id}]

        # If it's Electronic, add style subcategories under the Electronic node
        if raw_genre.lower() == "electronic":
            styles_raw = item.get("style") or ""
            for s in styles_raw.split(","):
                s_name = s.strip()
                if not s_name:
                    continue
                try:
                    style_id = _ensure_category(base_url, auth, s_name, genre_id)
                    categories.append({"id": style_id})
                except Exception as e:
                    print(f"Warning: could not ensure style category '{s_name}': {e}")

        return categories

    if ptype == "turntable":
        gear_id = _ensure_category(base_url, auth, "Gear", None)
        tt_id = _ensure_category(base_url, auth, "Turntables", gear_id)
        return [{"id": gear_id}, {"id": tt_id}]

    if ptype == "accessory":
        acc_id = _ensure_category(base_url, auth, "Accessories", None)
        return [{"id": acc_id}]

    other_id = _ensure_category(base_url, auth, "Other", None)
    return [{"id": other_id}]


# ---------- Media upload (Telegram photo -> WP media) ----------


def upload_image_from_bytes(image_bytes: bytes, filename: str) -> str | None:
    """
    Upload raw image bytes to WP media and return source_url.
    Uses the same creds as Woo (Basic Auth).
    """
    base_url, auth = _get_base_and_auth()

    # WC_API_URL looks like: https://site.test/wp-json/wc/v3
    # Media endpoint is:      https://site.test/wp-json/wp/v2/media
    if "/wp-json/" in base_url:
        root = base_url.split("/wp-json/")[0]
    else:
        root = base_url.rstrip("/")
    media_url = f"{root}/wp-json/wp/v2/media"

    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
    }

    resp = requests.post(
        media_url,
        headers=headers,
        data=image_bytes,
        auth=auth,
        timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("source_url") or data.get("guid", {}).get("rendered")


# ---------- Product CRUD ----------


def create_product_from_inventory(item: dict, image_url: str | None = None) -> dict:
    """
    Build a Woo product from DB row (item dict).

    For records:
      - base description: label/format/condition
      - optional Discogs cover + tracklist

    For other product types:
      - uses item['description'] and image_url (e.g. from Telegram upload).
    """
    base_url, auth = _get_base_and_auth()
    url = f"{base_url}/products"

    ptype = (item.get("product_type") or "record").strip().lower()

    description = _build_pretty_description(item, ptype)

    attributes = []
    for name, key in [
        ("Genre", "genre"),
        ("Style", "style"),
        ("Label", "label"),
        ("Format", "format"),
        ("Year", "year"),
        ("Condition", "condition"),
    ]:
        value = item.get(key)
        if value:
            attributes.append({"name": name, "options": [str(value)]})

    payload: dict = {
        "name": item.get("artist_album"),
        # CRITICAL: set SKU so we can idempotently find/link products on restart.
        # This prevents duplicates when the bot restarts.
        "sku": str(item.get("id")) if item.get("id") is not None else "",
        "regular_price": str(item.get("price_gel")),
        "manage_stock": True,
        "stock_quantity": item.get("quantity"),
        "status": "publish",
        "description": description,
        "attributes": attributes,
    }

    # categories
    try:
        payload["categories"] = _get_categories_for_item(base_url, auth, item)
    except Exception as e:
        print(f"Warning: could not assign categories: {e}")


    # images: priority:
    # 1) explicit image_url from caller (Telegram upload or manual URL)
    # 2) Discogs cover (records only)
    discogs_tracklist = None

    if image_url:
        payload.setdefault("images", []).append({"src": image_url})
    elif ptype == "record":
        discogs_image, discogs_tracklist, discogs_meta = _build_discogs_enrichment(item)
        if discogs_image:
            payload.setdefault("images", []).append({"src": discogs_image})

    # tracklist only for records
    if discogs_tracklist:
        if payload.get("description"):
            payload["description"] = payload["description"] + "<br><br>" + discogs_tracklist
        else:
            payload["description"] = discogs_tracklist
    # add Discogs meta for long-term linkage
    try:
        if discogs_meta:
            payload.setdefault('meta_data', [])
            for k, v in discogs_meta.items():
                payload['meta_data'].append({'key': k, 'value': v})
    except Exception:
        pass


    response = requests.post(url, auth=auth, json=payload, timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL)
    response.raise_for_status()
    return response.json()




def update_product_from_inventory(product_id: int, item: dict) -> dict:
    """Update core Woo fields for a product from an inventory row.

    This is used for rerun-safe initial sync and diff-based updates.
    It intentionally does not remove existing images; it only sets fields we manage.
    """
    base_url, auth = _get_base_and_auth()
    url = f"{base_url}/products/{product_id}"

    ptype = (item.get("product_type") or "record").strip().lower()
    description = _build_pretty_description(item, ptype)

    attributes = []
    for name, key in [
        ("Genre", "genre"),
        ("Style", "style"),
        ("Label", "label"),
        ("Format", "format"),
        ("Year", "year"),
        ("Condition", "condition"),
    ]:
        value = item.get(key)
        if value:
            attributes.append({"name": name, "options": [str(value)]})

    payload: dict = {
        "name": item.get("artist_album"),
        "regular_price": str(item.get("price_gel")),
        "manage_stock": True,
        "stock_quantity": int(item.get("quantity") or 0),
        "description": description,
        "attributes": attributes,
    }

    # keep SKU stable
    if item.get("id") is not None:
        payload["sku"] = str(item.get("id"))

    try:
        payload["categories"] = _get_categories_for_item(base_url, auth, item)
    except Exception as e:
        print(f"Warning: could not assign categories: {e}")

    # Optionally add Discogs cover/tracklist/meta if record and description lacks Tracklist
    if ptype == "record" and os.getenv("DISCOGS_TOKEN"):
        try:
            discogs_image, discogs_tracklist, discogs_meta = _build_discogs_enrichment(item)
            if discogs_tracklist and 'Tracklist' not in (payload.get('description') or ''):
                payload['description'] = (payload.get('description') or '') + '<br><br>' + discogs_tracklist
            if discogs_meta:
                payload.setdefault('meta_data', [])
                for k, v in discogs_meta.items():
                    payload['meta_data'].append({'key': k, 'value': v})
            # do not overwrite images on update; leave existing images intact
        except Exception:
            pass

    resp = requests.put(url, auth=auth, json=payload, timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL)
    resp.raise_for_status()
    return resp.json()
def update_product_stock(product_id: int, new_qty: int):
    base_url, auth = _get_base_and_auth()
    url = f"{base_url}/products/{product_id}"
    payload = {"stock_quantity": new_qty}
    response = requests.put(url, auth=auth, json=payload, timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL)
    response.raise_for_status()
    return response.json()


def update_product_price(product_id: int, new_price: float):
    base_url, auth = _get_base_and_auth()
    url = f"{base_url}/products/{product_id}"
    payload = {"regular_price": str(new_price)}
    response = requests.put(url, auth=auth, json=payload, timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL)
    response.raise_for_status()
    return response.json()


def update_product_metadata(product_id: int, item: dict) -> dict:
    base_url, auth = _get_base_and_auth()
    url = f"{base_url}/products/{product_id}"
    attributes = []
    for name, key in [
        ("Genre", "genre"),
        ("Style", "style"),
        ("Label", "label"),
        ("Format", "format"),
        ("Year", "year"),
        ("Condition", "condition"),
    ]:
        value = item.get(key)
        if value:
            attributes.append({"name": name, "options": [str(value)]})

    payload: dict = {"attributes": attributes}
    if item.get("description"):
        payload["description"] = item["description"]

    response = requests.put(url, auth=auth, json=payload, timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL)
    response.raise_for_status()
    return response.json()


def get_product(product_id: int) -> dict:
    """Fetch a single WooCommerce product by ID."""
    base_url, auth = _get_base_and_auth()
    url = f"{base_url}/products/{product_id}"
    resp = requests.get(url, auth=auth, timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL)
    resp.raise_for_status()
    return resp.json()


def update_product_fields(product_id: int, payload: dict) -> dict:
    """Patch multiple product fields in one request."""
    base_url, auth = _get_base_and_auth()
    url = f"{base_url}/products/{product_id}"
    resp = requests.put(url, auth=auth, json=payload, timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL)
    resp.raise_for_status()
    return resp.json()


def list_products(page: int = 1, per_page: int = 100) -> list[dict]:
    """List Woo products (paged)."""
    base_url, auth = _get_base_and_auth()
    url = f"{base_url}/products"
    resp = requests.get(
        url,
        auth=auth,
        params={"page": page, "per_page": per_page, "status": "any"},
        timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL,
    )
    resp.raise_for_status()
    return resp.json()


def search_products(query: str, *, per_page: int = 20) -> list[dict]:
    """Search products by name/description using Woo 'search' param."""
    base_url, auth = _get_base_and_auth()
    url = f"{base_url}/products"
    resp = requests.get(
        url,
        auth=auth,
        params={"search": query, "per_page": per_page, "status": "any"},
        timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL,
    )
    resp.raise_for_status()
    return resp.json()


def trash_product(product_id: int, *, force: bool = False) -> dict:
    """Delete a product.

    Woo supports soft-delete (trash) and hard delete via force=true.
    """
    base_url, auth = _get_base_and_auth()
    url = f"{base_url}/products/{product_id}"
    resp = requests.delete(url, auth=auth, params={"force": bool(force)}, timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL)
    resp.raise_for_status()
    return resp.json()


def set_product_status(product_id: int, status: str) -> dict:
    """Soft-delete helper (e.g., status='draft')."""
    return update_product_fields(product_id, {"status": status})


def update_product_description(product_id: int, description: str) -> dict:
    base_url, auth = _get_base_and_auth()
    url = f"{base_url}/products/{product_id}"
    payload = {"description": description}
    response = requests.put(url, auth=auth, json=payload, timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL)
    response.raise_for_status()
    return response.json()


def quick_test_connection():
    base_url, auth = _get_base_and_auth()
    url = f"{base_url}/products"
    response = requests.get(url, auth=auth, timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL)
    print(f"WooCommerce test status: {response.status_code}")
    return response


def find_product_by_sku(sku: str) -> dict | None:
    """
    Fetch a single WooCommerce product by SKU. Returns None if not found.
    """
    base_url, auth = _get_base_and_auth()
    url = f"{base_url}/products"
    resp = requests.get(
        url,
        auth=auth,
        params={"sku": sku, "per_page": 1},
        timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL,
    )
    resp.raise_for_status()
    items = resp.json()
    if not items:
        return None
    return items[0]


def fetch_orders(
    statuses: list[str] | str | None = None,
    after: str | None = None,
    page: int = 1,
    per_page: int = 50,
):
    """
    Fetch WooCommerce orders for polling/backfill.

    Args:
        statuses: list or comma-separated statuses (e.g. ["processing", "completed"]).
        after: ISO8601 datetime string; only orders created after this are returned.
        page: page number (1-based).
        per_page: number of orders per page.
    """
    base_url, auth = _get_base_and_auth()
    url = f"{base_url}/orders"
    params: dict[str, str | int] = {"page": page, "per_page": per_page}
    if statuses:
        if isinstance(statuses, (list, tuple)):
            params["status"] = ",".join(statuses)
        else:
            params["status"] = statuses
    if after:
        params["after"] = after

    resp = requests.get(url, auth=auth, params=params, timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL)
    resp.raise_for_status()
    return resp.json()
