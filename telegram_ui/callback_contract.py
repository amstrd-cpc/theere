from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

SAFE_CALLBACK_PREFIX = "nav"
_CALLBACK_DELIMITER = ":"
_ALLOWED_ACTIONS = {"menu", "command", "back"}


@dataclass(frozen=True)
class NavigationCallback:
    action: str
    target: str


def build_navigation_callback(action: str, target: str) -> str:
    """Build callback_data payloads for navigation callbacks."""
    normalized_action = action.strip().lower()
    normalized_target = target.strip().lower()
    if normalized_action not in _ALLOWED_ACTIONS:
        raise ValueError(f"Unsupported navigation action: {action}")
    if not normalized_target:
        raise ValueError("Navigation target cannot be empty")
    return f"{SAFE_CALLBACK_PREFIX}{_CALLBACK_DELIMITER}{normalized_action}{_CALLBACK_DELIMITER}{normalized_target}"


def parse_navigation_callback(data: str) -> Optional[NavigationCallback]:
    """Parse callback_data into a typed contract object.

    Returns None when payload does not match the contract.
    """
    if not data:
        return None
    parts = data.split(_CALLBACK_DELIMITER, maxsplit=2)
    if len(parts) != 3:
        return None
    prefix, action, target = (part.strip().lower() for part in parts)
    if prefix != SAFE_CALLBACK_PREFIX:
        return None
    if action not in _ALLOWED_ACTIONS:
        return None
    if not target:
        return None
    return NavigationCallback(action=action, target=target)


def is_navigation_callback(data: str) -> bool:
    return parse_navigation_callback(data) is not None
