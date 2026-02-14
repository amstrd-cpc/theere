from __future__ import annotations

from typing import Any, Dict


class StdoutNotifier:
    def notify_admin(self, store: Dict[str, Any], message: str) -> None:
        store_name = store.get("store_name") if isinstance(store, dict) else "unknown"
        print(f"[NOTIFY:{store_name}] {message}")
