from __future__ import annotations

import datetime
import html
import logging
import re
from typing import Any, Dict, Iterable, Optional

from services.inventory_service import (
    get_inventory_by_id,
    get_inventory_by_woo_product_id,
    get_or_create_supplier,
    insert_inventory,
    insert_inventory_with_id,
    update_inventory_sync,
)
from services.product_map_service import find_mapping_by_woo_product_id, upsert_product_map
from services.store_service import get_default_store, get_store
from services.woo_service import WooNotConfigured, compute_sync_hash, fetch_products_page, is_configured

logger = logging.getLogger(__name__)


def _normalize_sku(value: Any) -> str:
    return str(value or "").strip()


def _clean_text(value: Any) -> str:
    if not value:
        return ""
    text = str(value)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def _parse_short_description(value: Any) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    text = _clean_text(value)
    for line in text.splitlines():
        if ":" not in line:
            continue
        label, raw_value = line.split(":", 1)
        key = label.strip().lower()
        normalized_value = raw_value.strip()
        if not normalized_value:
            continue
        if key in {"label", "format", "condition", "supplier", "category"}:
            fields[key] = normalized_value
    return fields


def _extract_category_ids(categories: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    ids = {}
    for cat in categories:
        name = (cat.get("name") or "").strip().lower()
        cat_id = cat.get("id")
        if not name or not cat_id:
            continue
        if name in {"sounds", "vinyl", "electronic", "gear", "turntables"}:
            ids[name] = int(cat_id)
    return ids


def _extract_genre_style(categories: Iterable[Dict[str, Any]]) -> tuple[Optional[str], Optional[str]]:
    categories_list = list(categories)
    base_ids = _extract_category_ids(categories_list)
    vinyl_id = base_ids.get("vinyl")
    electronic_id = base_ids.get("electronic")

    genres: list[str] = []
    styles: list[str] = []
    if vinyl_id:
        for cat in categories_list:
            if int(cat.get("parent") or 0) == int(vinyl_id):
                name = (cat.get("name") or "").strip()
                if name:
                    genres.append(name)
    if electronic_id:
        for cat in categories_list:
            if int(cat.get("parent") or 0) == int(electronic_id):
                name = (cat.get("name") or "").strip()
                if name:
                    styles.append(name)

    if not genres:
        base_names = {"sounds", "vinyl", "electronic", "gear", "turntables"}
        genres = [
            (cat.get("name") or "").strip()
            for cat in categories_list
            if (cat.get("name") or "").strip().lower() not in base_names
        ]

    genre_text = ", ".join(name for name in genres if name) or None
    style_text = ", ".join(name for name in styles if name) or None
    return genre_text, style_text


def _parse_price(product: Dict[str, Any]) -> float:
    for key in ("regular_price", "price", "sale_price"):
        value = product.get(key)
        if value not in (None, ""):
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return 0.0


def _extract_meta_value(meta_data: Iterable[Dict[str, Any]], key: str) -> Optional[str]:
    for entry in meta_data:
        if entry.get("key") == key:
            value = entry.get("value")
            if value in (None, ""):
                return None
            return str(value)
    return None


def _parse_int(value: Optional[str]) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _inventory_from_woo(product: Dict[str, Any]) -> Dict[str, Any]:
    short_fields = _parse_short_description(product.get("short_description"))
    genre, style = _extract_genre_style(product.get("categories") or [])
    category_text = short_fields.get("category")
    if category_text:
        if genre:
            if category_text.lower() not in {name.strip().lower() for name in genre.split(",")}:
                genre = f"{genre}, {category_text}"
        else:
            genre = category_text

    supplier_name = short_fields.get("supplier")
    supplier_id = get_or_create_supplier(supplier_name) if supplier_name else None

    meta_data = product.get("meta_data") or []
    cover_url = None
    images = product.get("images") or []
    if images:
        cover_url = images[0].get("src") or None

    description = _clean_text(product.get("description"))
    created_at = product.get("date_created_gmt") or product.get("date_created") or datetime.datetime.utcnow().isoformat()

    return {
        "artist_album": product.get("name") or "Unknown",
        "genre": genre,
        "style": style,
        "label": short_fields.get("label"),
        "format": short_fields.get("format"),
        "condition": short_fields.get("condition"),
        "sleeve_condition": None,
        "price_gel": _parse_price(product),
        "quantity": int(product.get("stock_quantity") or 0),
        "supplier_id": supplier_id,
        "created_at": created_at,
        "year": None,
        "description": description or None,
        "cover_url": cover_url,
        "discogs_release_id": _parse_int(_extract_meta_value(meta_data, "discogs_release_id")),
        "discogs_master_id": _parse_int(_extract_meta_value(meta_data, "discogs_master_id")),
        "discogs_uri": _extract_meta_value(meta_data, "discogs_uri"),
    }


def _create_inventory_from_woo(product: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    item = _inventory_from_woo(product)
    sku = _normalize_sku(product.get("sku"))
    if sku.isdigit():
        try:
            item_id = int(sku)
            insert_inventory_with_id(item_id, item)
            item["id"] = item_id
            return item
        except Exception:
            logger.exception("Failed inserting inventory using Woo sku=%s", sku)
            return None
    try:
        item_id = insert_inventory(item)
        item["id"] = item_id
        return item
    except Exception:
        logger.exception("Failed inserting inventory for Woo product id=%s", product.get("id"))
        return None


def auto_map_woo_products(
    *,
    store_id: int | None = None,
    per_page: int = 100,
    update_inventory: bool = True,
) -> Dict[str, int]:
    if not is_configured(store_id):
        raise WooNotConfigured("WooCommerce not configured")

    store = get_store(store_id) if store_id else get_default_store()
    if not store:
        raise WooNotConfigured("WooCommerce store not configured")

    linked = 0
    skipped = 0
    ambiguous = 0
    created = 0
    page = 1

    while True:
        products = fetch_products_page(page=page, per_page=per_page, store=store, store_id=store_id)
        if not products:
            break

        for product in products:
            woo_id = product.get("id")
            name = product.get("name") or "Unknown"
            if not woo_id:
                logger.warning("Skipping Woo product without id (name=%s)", name)
                skipped += 1
                continue

            sku = _normalize_sku(product.get("sku"))
            inventory = None

            if sku.isdigit():
                inventory = get_inventory_by_id(int(sku))
                if inventory and inventory.get("woo_product_id") not in (None, "", 0):
                    existing_woo = int(inventory["woo_product_id"])
                    if existing_woo != int(woo_id):
                        logger.warning(
                            "Ambiguous Woo mapping for SKU=%s (woo_id=%s name=%s existing_woo=%s)",
                            sku,
                            woo_id,
                            name,
                            existing_woo,
                        )
                        ambiguous += 1
                        continue

            if not inventory:
                inventory = get_inventory_by_woo_product_id(int(woo_id))

            if not inventory:
                mapping = find_mapping_by_woo_product_id(int(store["id"]), int(woo_id))
                if mapping:
                    inventory = get_inventory_by_id(int(mapping["internal_product_id"]))
                    if not inventory:
                        logger.warning(
                            "Woo mapping references missing inventory (woo_id=%s name=%s internal_id=%s)",
                            woo_id,
                            name,
                            mapping.get("internal_product_id"),
                        )

            if not inventory:
                inventory = _create_inventory_from_woo(product)
                if inventory:
                    created += 1
                    logger.info(
                        "Created inventory from Woo product (woo_id=%s sku=%s name=%s)",
                        woo_id,
                        sku or "n/a",
                        name,
                    )
                else:
                    logger.info(
                        "No inventory match for Woo product (woo_id=%s sku=%s name=%s)",
                        woo_id,
                        sku or "n/a",
                        name,
                    )
                    skipped += 1
                    continue

            internal_id = int(inventory["id"])
            upsert_product_map(
                store_id=int(store["id"]),
                internal_product_id=internal_id,
                woo_product_id=int(woo_id),
                sku=sku or None,
            )
            if update_inventory:
                sync_hash = compute_sync_hash(product)
                update_inventory_sync(internal_id, int(woo_id), sync_hash)

            linked += 1

        if len(products) < per_page:
            break
        page += 1

    return {"linked": linked, "skipped": skipped, "ambiguous": ambiguous, "created": created}
