from __future__ import annotations

from typing import Any, Dict, Optional

from services.store_service import get_default_store, get_store, get_store_settings


class EnvSettingsProvider:
    def get_store(self, store_id: int) -> Optional[Dict[str, Any]]:
        return get_store(store_id)

    def get_default_store(self) -> Optional[Dict[str, Any]]:
        return get_default_store()

    def get_store_settings(self, store_id: int) -> Dict[str, Any]:
        return get_store_settings(store_id)
