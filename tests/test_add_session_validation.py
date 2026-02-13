from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.add_session_service import create_add_session, validate_add_callback


def test_validate_add_callback_valid() -> None:
    now = datetime.now(timezone.utc)
    session = create_add_session(now=now)

    ok, reason = validate_add_callback(
        session=session,
        callback_session_id=session["session_id"],
        callback_action="type",
        now=now,
    )

    assert ok is True
    assert reason == "ok"


def test_validate_add_callback_wrong_session() -> None:
    now = datetime.now(timezone.utc)
    session = create_add_session(now=now)

    ok, reason = validate_add_callback(
        session=session,
        callback_session_id="wrong123",
        callback_action="type",
        now=now,
    )

    assert ok is False
    assert reason == "missing_or_mismatched_session_id"


def test_validate_add_callback_expired_session() -> None:
    now = datetime.now(timezone.utc)
    session = create_add_session(now=now - timedelta(minutes=30))

    ok, reason = validate_add_callback(
        session=session,
        callback_session_id=session["session_id"],
        callback_action="type",
        now=now,
    )

    assert ok is False
    assert reason == "expired_ttl"


def test_validate_add_callback_wrong_step_action() -> None:
    now = datetime.now(timezone.utc)
    session = create_add_session(now=now)
    session["expected_step"] = "ask_condition"

    ok, reason = validate_add_callback(
        session=session,
        callback_session_id=session["session_id"],
        callback_action="supplier",
        now=now,
    )

    assert ok is False
    assert reason == "invalid_action_for_expected_step"
