from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
from uuid import uuid4

ADD_SESSION_TTL = timedelta(minutes=20)

_ALLOWED_ACTIONS_BY_STEP = {
    "choose_type": {"type"},
    "show_results": {"select", "page"},
    "ask_condition": {"cond"},
    "ask_supplier": {"supplier"},
    "other_photos": {"photos"},
    "confirm": {"confirm"},
}


def create_add_session(*, ttl: timedelta = ADD_SESSION_TTL, now: datetime | None = None) -> dict[str, str]:
    started_at_dt = now or datetime.now(timezone.utc)
    expires_at_dt = started_at_dt + ttl
    return {
        "session_id": uuid4().hex[:8],
        "started_at": started_at_dt.isoformat(),
        "expires_at": expires_at_dt.isoformat(),
        "expected_step": "choose_type",
    }


def validate_add_callback(
    *,
    session: Mapping[str, Any] | None,
    callback_session_id: str | None,
    callback_action: str | None,
    now: datetime | None = None,
) -> tuple[bool, str]:
    if not session or not callback_session_id or callback_session_id != session.get("session_id"):
        return False, "missing_or_mismatched_session_id"

    expires_at_raw = session.get("expires_at")
    if not isinstance(expires_at_raw, str):
        return False, "expired_ttl"
    try:
        expires_at = datetime.fromisoformat(expires_at_raw)
    except ValueError:
        return False, "expired_ttl"
    now_dt = now or datetime.now(timezone.utc)
    if expires_at <= now_dt:
        return False, "expired_ttl"

    expected_step = session.get("expected_step")
    allowed_actions = _ALLOWED_ACTIONS_BY_STEP.get(str(expected_step), set())
    if not callback_action or callback_action not in allowed_actions:
        return False, "invalid_action_for_expected_step"

    return True, "ok"
