from __future__ import annotations

from bootstrap.container import build_container
from core.application.use_cases.sync_catalog import sync_catalog


def run_sync_catalog_job(store_id: int) -> dict:
    container = build_container()
    return sync_catalog(store_id=store_id, settings=container.settings_provider, woo_gateway=container.woo_gateway)
