from __future__ import annotations

import os
import tempfile

from db.migrations import migrate
from services.inventory_service import get_inventory_by_id, insert_inventory


def test_inventory_insert_select_dict(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "clime_db.db")
        monkeypatch.setenv("RECORDSTORE_DB_FILE", db_path)
        migrate()

        item_id = insert_inventory(
            {
                "artist_album": "Test Artist - Test Album",
                "genre": "Rock",
                "style": "Indie",
                "label": "Test Label",
                "format": "Vinyl",
                "condition": "nm",
                "price_gel": 25.0,
                "quantity": 2,
                "supplier_id": None,
            }
        )
        item = get_inventory_by_id(item_id)
        assert item is not None
        assert item["artist_album"] == "Test Artist - Test Album"
        assert item["price_gel"] == 25.0
        assert item["quantity"] == 2
