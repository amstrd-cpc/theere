from __future__ import annotations

from typing import Iterable, Set

NEVER_ACCEPT_FIELDS: Set[str] = {
    "internal_id",
    "theere_id",
    "sku",
    "mappings",
    "supplier_id",
    "supplier",
    "cost",
    "purchase_price",
    "woo_product_id",
    "discogs_listing_id",
}


def normalize_incoming_fields(fields: Iterable[str]) -> Set[str]:
    return {str(field).strip().lower() for field in fields if str(field).strip()}
