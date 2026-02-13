from __future__ import annotations

import datetime
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from db.connection import get_inventory_db
from services.inventory_service import get_inventory_by_id, get_or_create_supplier, update_inventory_fields
from services.notification_service import notify_admin
from services.product_map_service import (
    ImportDecision,
    mark_import_conflict,
    queue_manual_mapping,
    record_import_decision,
    resolve_import_decision,
    upsert_product_map,
)
from services.store_service import get_store
from services.woo_service import WooNotConfigured, fetch_products_page, is_configured

logger = logging.getLogger(__name__)


@dataclass
class ImportSummary:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    conflicts: int = 0
    manual_needed: int = 0
    processed: int = 0
    details: list[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, int]:
        return {
            "created": self.created,
            "updated": self.updated,
            "skipped": self.skipped,
            "conflicts": self.conflicts,
            "manual_needed": self.manual_needed,
            "processed": self.processed,
        }


def _clean_text(value: Any) -> str:
    if not value:
        return ""
    text = str(value)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def _parse_short_description(value: Any) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    for line in _clean_text(value).splitlines():
        if ":" not in line:
            continue
        label, raw_value = line.split(":", 1)
        key = label.strip().lower()
        normalized_value = raw_value.strip()
        if normalized_value:
            fields[key] = normalized_value
    return fields


def _parse_price(product: Dict[str, Any]) -> float:
    for key in ("regular_price", "price", "sale_price"):
        value = product.get(key)
        if value not in (None, ""):
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return 0.0


def _parse_year(product: Dict[str, Any], short_fields: Dict[str, str]) -> Optional[int]:
    raw = short_fields.get("year") or product.get("year")
    if raw in (None, ""):
        return None
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _inventory_from_woo(product: Dict[str, Any]) -> Dict[str, Any]:
    short_fields = _parse_short_description(product.get("short_description"))
    supplier_name = short_fields.get("supplier")
    supplier_id = get_or_create_supplier(supplier_name) if supplier_name else None
    images = product.get("images") or []
    return {
        "artist_album": product.get("name") or "Unknown",
        "label": short_fields.get("label"),
        "format": short_fields.get("format"),
        "condition": short_fields.get("condition"),
        "price_gel": _parse_price(product),
        "quantity": int(product.get("stock_quantity") or 0),
        "supplier_id": supplier_id,
        "year": _parse_year(product, short_fields),
        "description": _clean_text(product.get("description")) or None,
        "cover_url": images[0].get("src") if images else None,
    }


def _append_summary_event(store_id: int, summary: ImportSummary) -> None:
    now = datetime.datetime.utcnow().isoformat()
    payload = json.dumps(summary.as_dict(), sort_keys=True)
    with get_inventory_db() as conn:
        conn.execute(
            """
            INSERT INTO woo_import_runs (
                store_id,
                ts_started,
                ts_finished,
                created_count,
                updated_count,
                skipped_count,
                conflict_count,
                manual_needed_count,
                summary_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                store_id,
                now,
                now,
                summary.created,
                summary.updated,
                summary.skipped,
                summary.conflicts,
                summary.manual_needed,
                payload,
            ),
        )
        conn.commit()


def _process_product(*, store_id: int, product: Dict[str, Any], summary: ImportSummary) -> None:
    woo_id = product.get("id")
    if not woo_id:
        summary.skipped += 1
        return

    decision: ImportDecision = record_import_decision(store_id, product)
    summary.processed += 1

    if decision.status == "conflict":
        summary.conflicts += 1
        mark_import_conflict(store_id=store_id, woo_product_id=int(woo_id), reason=decision.reason or "conflict")
        summary.details.append(f"conflict woo_id={woo_id} reason={decision.reason}")
        return

    if decision.status == "manual":
        summary.manual_needed += 1
        queue_manual_mapping(store_id=store_id, woo_product=product, reason=decision.reason or "manual_needed")
        summary.details.append(f"manual woo_id={woo_id} reason={decision.reason}")
        return

    if decision.internal_product_id is None:
        summary.skipped += 1
        return

    internal_id = int(decision.internal_product_id)
    existing = get_inventory_by_id(internal_id)
    if not existing:
        summary.skipped += 1
        return

    payload = _inventory_from_woo(product)
    updates: Dict[str, Any] = {}
    for field in ("artist_album", "label", "format", "condition", "price_gel", "quantity", "year", "description", "cover_url"):
        new_value = payload.get(field)
        if new_value is None:
            continue
        if existing.get(field) != new_value:
            updates[field] = new_value

    if updates:
        update_inventory_fields(internal_id, updates, sync_channels=False, source="manual_woo", store_id=store_id)
        summary.updated += 1
    else:
        summary.skipped += 1

    upsert_product_map(
        store_id=store_id,
        internal_product_id=internal_id,
        woo_product_id=int(woo_id),
        sku=str(product.get("sku") or "").strip() or None,
    )
    resolve_import_decision(store_id=store_id, woo_product_id=int(woo_id))


def import_woo_products(*, store_id: int | None = None, per_page: int = 100, notify: bool = False) -> Dict[str, int]:
    if not is_configured(store_id):
        raise WooNotConfigured("WooCommerce not configured")

    store = get_store(store_id)
    if not store:
        raise WooNotConfigured("WooCommerce store not configured")

    summary = ImportSummary()
    page = 1
    while True:
        products = fetch_products_page(page=page, per_page=per_page, store=store, store_id=store_id)
        if not products:
            break
        for product in products:
            _process_product(store_id=int(store["id"]), product=product, summary=summary)
        if len(products) < per_page:
            break
        page += 1

    _append_summary_event(int(store["id"]), summary)
    if notify:
        notify_admin(store, f"Woo import summary: {summary.as_dict()}")

    return summary.as_dict()


def get_latest_import_summary(store_id: int) -> Optional[Dict[str, Any]]:
    with get_inventory_db() as conn:
        cur = conn.execute(
            "SELECT * FROM woo_import_runs WHERE store_id = ? ORDER BY id DESC LIMIT 1",
            (store_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None
