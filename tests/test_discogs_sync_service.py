from __future__ import annotations

from services import discogs_sync_service


def test_sync_discogs_item_skips_listing_when_disabled(monkeypatch):
    monkeypatch.setattr(discogs_sync_service, "get_store", lambda store_id: {"id": store_id})
    monkeypatch.setattr(
        discogs_sync_service,
        "get_all_inventory",
        lambda: [{"id": 42, "quantity": 1, "price_gel": 10.0, "discogs_release_id": 123}],
    )
    monkeypatch.setattr(
        discogs_sync_service,
        "get_store_settings",
        lambda store_id: {
            "discogs_price_sync": True,
            "discogs_listings_enabled": False,
            "discogs_collection_sync_enabled": False,
        },
    )
    monkeypatch.setattr(discogs_sync_service, "find_mapping_by_internal_id", lambda *_: {})

    result = discogs_sync_service.sync_discogs_item(1, 42)

    assert result["errors"] == 0
    assert result["listing_updated"] == 0
    assert result["listing_published"] == 0


def test_sync_discogs_item_updates_listing(monkeypatch):
    calls: dict[str, int] = {"qty": 0, "price": 0}

    monkeypatch.setattr(discogs_sync_service, "get_store", lambda store_id: {"id": store_id})
    monkeypatch.setattr(
        discogs_sync_service,
        "get_all_inventory",
        lambda: [{"id": 7, "quantity": 3, "price_gel": 25.5, "discogs_release_id": 321}],
    )
    monkeypatch.setattr(
        discogs_sync_service,
        "get_store_settings",
        lambda store_id: {
            "discogs_price_sync": True,
            "discogs_listings_enabled": True,
            "discogs_collection_sync_enabled": False,
        },
    )
    monkeypatch.setattr(
        discogs_sync_service,
        "find_mapping_by_internal_id",
        lambda *_: {"discogs_listing_id": 999},
    )
    monkeypatch.setattr(discogs_sync_service, "update_discogs_sync_time", lambda *_: None)

    def _update_qty(store, listing_id, qty):
        calls["qty"] += 1

    def _update_price(store, listing_id, payload):
        calls["price"] += 1

    monkeypatch.setattr(discogs_sync_service, "update_listing_quantity", _update_qty)
    monkeypatch.setattr(discogs_sync_service, "update_listing", _update_price)

    result = discogs_sync_service.sync_discogs_item(1, 7)

    assert result["listing_updated"] == 1
    assert result["errors"] == 0
    assert calls == {"qty": 1, "price": 1}
