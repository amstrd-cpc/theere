from __future__ import annotations

from typing import Any, Dict, Protocol


class Notifier(Protocol):
    def notify_admin(self, store: Dict[str, Any], message: str) -> None: ...
