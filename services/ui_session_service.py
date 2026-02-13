from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

from db.connection import get_inventory_db

logger = logging.getLogger(__name__)

DEFAULT_TTL = timedelta(minutes=20)
_TOKEN_RE = re.compile(r"^(?P<sid>[a-f0-9]{8})\.(?P<iat>[0-9a-z]+)\.(?P<exp>[0-9a-z]+)\.(?P<node>[a-z0-9_\-]{1,12})$")


def _to_base36(value: int) -> str:
    chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    if value <= 0:
        return "0"
    out = ""
    while value:
        value, rem = divmod(value, 36)
        out = chars[rem] + out
    return out


def _from_base36(value: str) -> int:
    return int(value, 36)


def _node_hint(node: str) -> str:
    normalized = re.sub(r"[^a-z0-9_\-]", "", (node or "").lower())
    return (normalized or "node")[:12]


def create_callback_session(
    *,
    user_id: int,
    expected_node: str,
    expected_state: str | None = None,
    ttl: timedelta = DEFAULT_TTL,
) -> dict[str, str | int]:
    now = datetime.now(timezone.utc)
    expires_at = now + ttl
    session_id = uuid.uuid4().hex[:8]
    issued_unix = int(now.timestamp())
    expires_unix = int(expires_at.timestamp())
    node = _node_hint(expected_node)
    token = f"{session_id}.{_to_base36(issued_unix)}.{_to_base36(expires_unix)}.{node}"

    with get_inventory_db() as conn:
        conn.execute(
            """
            INSERT INTO ui_sessions (
                session_id,
                user_id,
                expected_node,
                expected_state,
                issued_at,
                expires_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                int(user_id),
                expected_node,
                expected_state,
                now.isoformat(),
                expires_at.isoformat(),
            ),
        )
        conn.commit()

    return {
        "session_id": session_id,
        "session_token": token,
        "user_id": int(user_id),
        "expected_node": expected_node,
        "expected_state": expected_state or "",
        "issued_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
    }


def parse_session_token(token: str | None) -> dict[str, str] | None:
    if not token:
        return None
    match = _TOKEN_RE.match(token)
    if not match:
        return None
    return match.groupdict()


def inject_session(callback_data: str, session_token: str | None) -> str:
    if not session_token:
        return callback_data
    parts = (callback_data or "").split(":")
    if len(parts) < 2:
        return callback_data
    return ":".join([parts[0], session_token] + parts[1:])


def extract_session(callback_data: str) -> tuple[str | None, str]:
    parts = (callback_data or "").split(":")
    if len(parts) >= 3:
        return parts[1], ":".join([parts[0]] + parts[2:])
    return None, callback_data


def validate_callback_session(
    *,
    session_token: str | None,
    user_id: int,
    expected_node: str | None = None,
    expected_state: str | None = None,
) -> tuple[bool, str]:
    parsed = parse_session_token(session_token)
    if not parsed:
        return False, "missing_or_malformed_session"

    try:
        expires_unix = _from_base36(parsed["exp"])
    except ValueError:
        return False, "malformed_expiry"

    if expires_unix <= int(datetime.now(timezone.utc).timestamp()):
        return False, "token_expired"

    session_id = parsed["sid"]
    with get_inventory_db() as conn:
        cur = conn.execute(
            """
            SELECT user_id, expected_node, expected_state, expires_at
            FROM ui_sessions
            WHERE session_id = ?
            """,
            (session_id,),
        )
        row = cur.fetchone()

    if not row:
        return False, "session_not_found"
    if int(row["user_id"]) != int(user_id):
        return False, "user_mismatch"
    if expected_node and row["expected_node"] != expected_node:
        return False, "menu_node_mismatch"
    if expected_state and row["expected_state"] != expected_state:
        return False, "state_mismatch"

    expires_at = datetime.fromisoformat(row["expires_at"])
    if expires_at <= datetime.now(timezone.utc):
        return False, "session_expired"

    return True, "ok"
