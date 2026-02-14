from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class InventoryItem:
    id: Optional[int]
    artist_album: str
    quantity: int
    price_gel: float
    supplier_id: Optional[int] = None
    genre: Optional[str] = None
    style: Optional[str] = None
    label: Optional[str] = None
    format: Optional[str] = None
    condition: Optional[str] = None
    sleeve_condition: Optional[str] = None
    year: Optional[int] = None
    description: Optional[str] = None
    cover_url: Optional[str] = None


@dataclass
class ProcessingResult:
    order_id: int
    matched_items: List[Dict[str, Any]] = field(default_factory=list)
    unmapped_items: List[str] = field(default_factory=list)
