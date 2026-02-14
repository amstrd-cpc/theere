from __future__ import annotations

from typing import Any, Dict

from services.discogs_service import update_listing, update_listing_quantity


class DiscogsServiceGateway:
    def update_listing_quantity(self, store: Dict[str, Any], listing_id: int, quantity: int) -> Dict[str, Any]:
        return update_listing_quantity(store, listing_id, quantity)

    def update_listing(self, store: Dict[str, Any], listing_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        return update_listing(store, listing_id, payload)
