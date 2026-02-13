from __future__ import annotations

import datetime
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

from db.connection import get_inventory_db
from services.inventory_service import get_all_inventory


@dataclass
class ImportDecision:
    status: str
    internal_product_id: Optional[int] = None
    strategy: Optional[str] = None
    reason: Optional[str] = None


def _normalize_text(value: Any) -> str:
    text = str(value or "").lower().strip()
    return re.sub(r"\s+", " ", text)


def _parse_artist_title(name: str) -> tuple[str, str]:
    if " - " in name:
        left, right = name.split(" - ", 1)
        return _normalize_text(left), _normalize_text(right)
    return "", _normalize_text(name)


def _extract_short_fields(value: Any) -> Dict[str, str]:
    text = str(value or "")
    fields: Dict[str, str] = {}
    for raw in text.splitlines():
        clean = re.sub(r"<[^>]+>", "", raw)
        if ":" not in clean:
            continue
        key, val = clean.split(":", 1)
        norm = _normalize_text(val)
        if norm:
            fields[_normalize_text(key)] = norm
    return fields


def _heuristic_candidates(product: Dict[str, Any]) -> list[Dict[str, Any]]:
    name = str(product.get("name") or "")
    artist, title = _parse_artist_title(name)
    short_fields = _extract_short_fields(product.get("short_description"))
    raw_year = short_fields.get("year")
    year = int(raw_year) if raw_year and raw_year.isdigit() else None
    label = short_fields.get("label")
    candidates: list[Dict[str, Any]] = []
    for item in get_all_inventory():
        item_artist, item_title = _parse_artist_title(str(item.get("artist_album") or ""))
        if title and item_title != title:
            continue
        if artist and item_artist and artist != item_artist:
            continue
        if year and item.get("year") and int(item.get("year") or 0) != year:
            continue
        if label and item.get("label") and _normalize_text(item.get("label")) != label:
            continue
        candidates.append(item)
    return candidates


def record_import_decision(store_id: int, woo_product: Dict[str, Any]) -> ImportDecision:
    woo_id = woo_product.get("id")
    if woo_id:
        exact = find_mapping_by_woo_product_id(store_id, int(woo_id))
        if exact:
            return ImportDecision(status="mapped", internal_product_id=int(exact["internal_product_id"]), strategy="exact_woo_id")

    sku = str(woo_product.get("sku") or "").strip()
    if sku:
        sku_match = find_mapping_by_sku(store_id, sku)
        if sku_match:
            return ImportDecision(status="mapped", internal_product_id=int(sku_match["internal_product_id"]), strategy="sku")

    heuristic = _heuristic_candidates(woo_product)
    if len(heuristic) == 1:
        return ImportDecision(status="mapped", internal_product_id=int(heuristic[0]["id"]), strategy="title_artist_year_label")
    if len(heuristic) > 1:
        return ImportDecision(status="conflict", reason="multiple_heuristic_matches")
    return ImportDecision(status="manual", reason="no_mapping_match")


def mark_import_conflict(*, store_id: int, woo_product_id: int, reason: str) -> None:
    with get_inventory_db() as conn:
        conn.execute(
            """
            INSERT INTO product_map_conflicts (store_id, woo_product_id, status, reason, created_at, updated_at)
            VALUES (?, ?, 'open', ?, ?, ?)
            ON CONFLICT(store_id, woo_product_id)
            DO UPDATE SET status='open', reason=excluded.reason, updated_at=excluded.updated_at
            """,
            (store_id, woo_product_id, reason, datetime.datetime.utcnow().isoformat(), datetime.datetime.utcnow().isoformat()),
        )
        conn.commit()


def queue_manual_mapping(*, store_id: int, woo_product: Dict[str, Any], reason: str) -> None:
    with get_inventory_db() as conn:
        conn.execute(
            """
            INSERT INTO product_mapping_queue (store_id, woo_product_id, woo_sku, woo_name, status, reason, payload_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?)
            ON CONFLICT(store_id, woo_product_id)
            DO UPDATE SET
                woo_sku = excluded.woo_sku,
                woo_name = excluded.woo_name,
                status = 'pending',
                reason = excluded.reason,
                payload_json = excluded.payload_json,
                updated_at = excluded.updated_at
            """,
            (
                store_id,
                int(woo_product.get("id") or 0),
                str(woo_product.get("sku") or "").strip() or None,
                woo_product.get("name") or "Unknown",
                reason,
                json.dumps(woo_product, sort_keys=True),
                datetime.datetime.utcnow().isoformat(),
                datetime.datetime.utcnow().isoformat(),
            ),
        )
        conn.commit()


def resolve_import_decision(*, store_id: int, woo_product_id: int) -> None:
    now = datetime.datetime.utcnow().isoformat()
    with get_inventory_db() as conn:
        conn.execute(
            "UPDATE product_mapping_queue SET status = 'resolved', updated_at = ? WHERE store_id = ? AND woo_product_id = ?",
            (now, store_id, woo_product_id),
        )
        conn.execute(
            "UPDATE product_map_conflicts SET status = 'resolved', updated_at = ? WHERE store_id = ? AND woo_product_id = ?",
            (now, store_id, woo_product_id),
        )
        conn.commit()


def upsert_product_map(
    *,
    store_id: int,
    internal_product_id: int,
    woo_product_id: Optional[int] = None,
    woo_variation_id: Optional[int] = None,
    sku: Optional[str] = None,
    discogs_listing_id: Optional[int] = None,
    discogs_release_id: Optional[int] = None,
) -> None:
    now = datetime.datetime.utcnow().isoformat()
    with get_inventory_db() as conn:
        conn.execute(
            """
            INSERT INTO product_map (
                store_id,
                internal_product_id,
                woo_product_id,
                woo_variation_id,
                sku,
                discogs_listing_id,
                discogs_release_id,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(store_id, internal_product_id)
            DO UPDATE SET
                woo_product_id = COALESCE(excluded.woo_product_id, product_map.woo_product_id),
                woo_variation_id = COALESCE(excluded.woo_variation_id, product_map.woo_variation_id),
                sku = COALESCE(excluded.sku, product_map.sku),
                discogs_listing_id = COALESCE(excluded.discogs_listing_id, product_map.discogs_listing_id),
                discogs_release_id = COALESCE(excluded.discogs_release_id, product_map.discogs_release_id),
                updated_at = excluded.updated_at
            """,
            (
                store_id,
                internal_product_id,
                woo_product_id,
                woo_variation_id,
                sku,
                discogs_listing_id,
                discogs_release_id,
                now,
                now,
            ),
        )
        conn.commit()


def find_mapping_by_sku(store_id: int, sku: str) -> Optional[Dict[str, Any]]:
    with get_inventory_db() as conn:
        cur = conn.execute(
            "SELECT * FROM product_map WHERE store_id = ? AND sku = ?",
            (store_id, sku),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def find_mapping_by_woo_product_id(store_id: int, woo_product_id: int) -> Optional[Dict[str, Any]]:
    with get_inventory_db() as conn:
        cur = conn.execute(
            "SELECT * FROM product_map WHERE store_id = ? AND woo_product_id = ?",
            (store_id, woo_product_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def find_mapping_by_variation_id(store_id: int, variation_id: int) -> Optional[Dict[str, Any]]:
    with get_inventory_db() as conn:
        cur = conn.execute(
            "SELECT * FROM product_map WHERE store_id = ? AND woo_variation_id = ?",
            (store_id, variation_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def find_mapping_by_discogs_listing_id(store_id: int, listing_id: int) -> Optional[Dict[str, Any]]:
    with get_inventory_db() as conn:
        cur = conn.execute(
            "SELECT * FROM product_map WHERE store_id = ? AND discogs_listing_id = ?",
            (store_id, listing_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def find_mapping_by_internal_id(store_id: int, internal_product_id: int) -> Optional[Dict[str, Any]]:
    with get_inventory_db() as conn:
        cur = conn.execute(
            "SELECT * FROM product_map WHERE store_id = ? AND internal_product_id = ?",
            (store_id, internal_product_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def list_product_mappings(store_id: int) -> list[Dict[str, Any]]:
    with get_inventory_db() as conn:
        cur = conn.execute("SELECT * FROM product_map WHERE store_id = ?", (store_id,))
        return [dict(row) for row in cur.fetchall()]


def clear_discogs_listing(store_id: int, internal_product_id: int) -> None:
    now = datetime.datetime.utcnow().isoformat()
    with get_inventory_db() as conn:
        conn.execute(
            """
            UPDATE product_map
            SET discogs_listing_id = NULL, updated_at = ?
            WHERE store_id = ? AND internal_product_id = ?
            """,
            (now, store_id, internal_product_id),
        )
        conn.commit()


def update_product_map_fields(store_id: int, internal_product_id: int, fields: Dict[str, Any]) -> None:
    if not fields:
        return
    now = datetime.datetime.utcnow().isoformat()
    fields = dict(fields)
    fields.setdefault("updated_at", now)
    keys = sorted(fields.keys())
    assignments = ", ".join(f"{key} = ?" for key in keys)
    values = [fields[key] for key in keys]
    values.extend([store_id, internal_product_id])
    with get_inventory_db() as conn:
        conn.execute(
            f"UPDATE product_map SET {assignments} WHERE store_id = ? AND internal_product_id = ?",
            values,
        )
        conn.commit()


def get_latest_seen_at(store_id: int, *, channel: str) -> Optional[str]:
    column = "discogs_last_seen_at" if channel == "discogs" else "woo_last_seen_at"
    with get_inventory_db() as conn:
        cur = conn.execute(
            f"SELECT MAX({column}) AS last_seen FROM product_map WHERE store_id = ?",
            (store_id,),
        )
        row = cur.fetchone()
        return row["last_seen"] if row else None
