from __future__ import annotations

import logging
from typing import Any, Dict

from services.inventory_service import get_inventory_by_id, get_inventory_by_woo_product_id, update_inventory_sync
from services.product_map_service import find_mapping_by_woo_product_id, upsert_product_map
from services.store_service import get_default_store, get_store
from services.woo_service import WooNotConfigured, compute_sync_hash, fetch_products_page, is_configured

logger = logging.getLogger(__name__)


def _normalize_sku(value: Any) -> str:
    return str(value or "").strip()


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

    return {"linked": linked, "skipped": skipped, "ambiguous": ambiguous}
