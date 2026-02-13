from __future__ import annotations

import os
import tempfile

from db.migrations import migrate
from services import inventory_service
from services.inventory_service import get_inventory_by_id, insert_inventory
from services.product_map_service import upsert_product_map
from services.store_service import create_store
from services import woo_import_service


def _seed_store() -> int:
    return create_store(
        store_name="Test",
        store_url="https://example.com",
        consumer_key="ck",
        consumer_secret="cs",
        webhook_secret="wh",
    )


def test_import_woo_products_idempotent_update(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "clime_db.db")
        monkeypatch.setenv("RECORDSTORE_DB_FILE", db_path)
        migrate()

        store_id = _seed_store()
        monkeypatch.setattr(inventory_service, "_inventory_sequence_checked", True)
        item_id = insert_inventory(
            {
                "artist_album": "Artist - Album",
                "label": "LabelX",
                "format": "Vinyl",
                "condition": "VG+",
                "price_gel": 10.0,
                "quantity": 1,
            }
        )
        upsert_product_map(store_id=store_id, internal_product_id=item_id, woo_product_id=101, sku="SKU-1")

        product = {
            "id": 101,
            "sku": "SKU-1",
            "name": "Artist - Album",
            "stock_quantity": 4,
            "regular_price": "12.5",
            "short_description": "Label: LabelX\nFormat: Vinyl\nCondition: NM",
            "description": "Updated",
            "images": [],
        }

        monkeypatch.setattr(woo_import_service, "is_configured", lambda *_: True)
        monkeypatch.setattr(woo_import_service, "fetch_products_page", lambda **_: [product])

        first = woo_import_service.import_woo_products(store_id=store_id)
        second = woo_import_service.import_woo_products(store_id=store_id)

        assert first["updated"] == 1
        assert second["updated"] == 0
        assert second["skipped"] >= 1
        updated = get_inventory_by_id(item_id)
        assert updated is not None
        assert int(updated["quantity"]) == 4
        assert float(updated["price_gel"]) == 12.5


def test_import_woo_products_manual_queue(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "clime_db.db")
        monkeypatch.setenv("RECORDSTORE_DB_FILE", db_path)
        migrate()

        store_id = _seed_store()
        monkeypatch.setattr(inventory_service, "_inventory_sequence_checked", True)
        product = {
            "id": 202,
            "sku": "NO-MATCH",
            "name": "Unknown - Missing",
            "stock_quantity": 2,
            "regular_price": "5",
            "short_description": "",
            "description": "",
            "images": [],
        }

        monkeypatch.setattr(woo_import_service, "is_configured", lambda *_: True)
        monkeypatch.setattr(woo_import_service, "fetch_products_page", lambda **_: [product])

        summary = woo_import_service.import_woo_products(store_id=store_id)
        assert summary["manual_needed"] == 1
        assert summary["created"] == 0
