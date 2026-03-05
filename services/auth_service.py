from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import List

from db.connection import get_inventory_db

LEGACY_SALT = "your_unique_salt_here_change_this"


@dataclass
class SessionInfo:
    user_id: int
    username: str | None
    first_name: str | None
    authenticated_at: str
    expires_at: str
    last_activity: str


class AuthManager:
    def __init__(self, password: str, session_hours: int) -> None:
        self.password = password
        self.session_hours = session_hours
        self.authenticated_users: dict[int, datetime] = {}
        self._password_hash = self._hash_password(password)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with get_inventory_db() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_sessions (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    authenticated_at TEXT,
                    expires_at TEXT,
                    last_activity TEXT
                )
                """
            )
            conn.commit()

    def _hash_password(self, password: str) -> str:
        salt = secrets.token_bytes(16)
        digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
        return f"scrypt${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"

    def _verify_hashed_password(self, input_password: str, hashed: str) -> bool:
        if hashed.startswith("scrypt$"):
            _, salt_b64, digest_b64 = hashed.split("$", 2)
            salt = base64.b64decode(salt_b64.encode())
            expected = base64.b64decode(digest_b64.encode())
            candidate = hashlib.scrypt(
                input_password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1
            )
            return hmac.compare_digest(candidate, expected)
        legacy = hashlib.sha256((input_password + LEGACY_SALT).encode()).hexdigest()
        return hmac.compare_digest(legacy, hashed)

    def _legacy_hash(self, password: str) -> str:
        return hashlib.sha256((password + LEGACY_SALT).encode()).hexdigest()

    def verify_password(self, input_password: str) -> bool:
        if self._verify_hashed_password(input_password, self._password_hash):
            return True
        legacy_hash = self._legacy_hash(self.password)
        if self._verify_hashed_password(input_password, legacy_hash):
            self._password_hash = self._hash_password(input_password)
            return True
        return False

    def authenticate_user(
        self, user_id: int, username: str | None, first_name: str | None
    ) -> None:
        expiry_time = datetime.now(UTC) + timedelta(hours=self.session_hours)
        self.authenticated_users[user_id] = expiry_time
        now = datetime.now(UTC).isoformat()
        with get_inventory_db() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO user_sessions
                (user_id, username, first_name, authenticated_at, expires_at, last_activity)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, username, first_name, now, expiry_time.isoformat(), now),
            )
            conn.commit()

    def is_authenticated(self, user_id: int) -> bool:
        now = datetime.now(UTC)
        if user_id in self.authenticated_users:
            if now < self.authenticated_users[user_id]:
                self.update_last_activity(user_id)
                return True
            del self.authenticated_users[user_id]
        with get_inventory_db() as conn:
            cur = conn.execute(
                "SELECT expires_at FROM user_sessions WHERE user_id = ?",
                (user_id,),
            )
            row = cur.fetchone()
            if row:
                expires_at = datetime.fromisoformat(row[0])
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=UTC)
                if expires_at > now:
                    self.authenticated_users[user_id] = expires_at
                    self.update_last_activity(user_id)
                    return True
        return False

    def update_last_activity(self, user_id: int) -> None:
        with get_inventory_db() as conn:
            conn.execute(
                "UPDATE user_sessions SET last_activity = ? WHERE user_id = ?",
                (datetime.now(UTC).isoformat(), user_id),
            )
            conn.commit()

    def logout_user(self, user_id: int) -> None:
        self.authenticated_users.pop(user_id, None)
        with get_inventory_db() as conn:
            conn.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
            conn.commit()

    def get_active_users(self) -> List[SessionInfo]:
        with get_inventory_db() as conn:
            cur = conn.execute(
                """
                SELECT user_id, username, first_name, authenticated_at, expires_at, last_activity
                FROM user_sessions
                WHERE expires_at > ?
                ORDER BY last_activity DESC
                """,
                (datetime.now(UTC).isoformat(),),
            )
            rows = cur.fetchall()
        return [
            SessionInfo(
                user_id=row[0],
                username=row[1],
                first_name=row[2],
                authenticated_at=row[3],
                expires_at=row[4],
                last_activity=row[5],
            )
            for row in rows
        ]
