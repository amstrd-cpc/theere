from __future__ import annotations

from typing import Any, Dict

from core.application.ports.repositories import InventoryRepo
from core.domain.models import InventoryItem


def add_inventory_item(repo: InventoryRepo, payload: Dict[str, Any]) -> int:
    supplier_name = (payload.get("supplier_name") or "Unknown supplier").strip()
    supplier_id = repo.create_supplier_if_missing(supplier_name)
    item = InventoryItem(
        id=None,
        artist_album=str(payload.get("artist_album") or "").strip(),
        quantity=int(payload.get("quantity") or 0),
        price_gel=float(payload.get("price_gel") or 0),
        supplier_id=supplier_id,
        genre=payload.get("genre"),
        style=payload.get("style"),
        label=payload.get("label"),
        format=payload.get("format"),
        condition=payload.get("condition"),
        sleeve_condition=payload.get("sleeve_condition"),
        year=int(payload["year"]) if payload.get("year") not in (None, "") else None,
        description=payload.get("description"),
        cover_url=payload.get("cover_url"),
    )
    if not item.artist_album:
        raise ValueError("artist_album is required")
    return repo.add_item(item)
