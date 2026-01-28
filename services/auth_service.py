from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List

from db.connection import get_inventory_db


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
        salt = "your_unique_salt_here_change_this"
        return hashlib.sha256((password + salt).encode()).hexdigest()

    def verify_password(self, input_password: str) -> bool:
        return self._hash_password(input_password) == self._hash_password(self.password)

    def authenticate_user(self, user_id: int, username: str | None, first_name: str | None) -> None:
        expiry_time = datetime.now() + timedelta(hours=self.session_hours)
        self.authenticated_users[user_id] = expiry_time
        now = datetime.now().isoformat()
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
        if user_id in self.authenticated_users:
            if datetime.now() < self.authenticated_users[user_id]:
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
                if expires_at > datetime.now():
                    self.authenticated_users[user_id] = expires_at
                    self.update_last_activity(user_id)
                    return True
        return False

    def update_last_activity(self, user_id: int) -> None:
        with get_inventory_db() as conn:
            conn.execute(
                "UPDATE user_sessions SET last_activity = ? WHERE user_id = ?",
                (datetime.now().isoformat(), user_id),
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
                (datetime.now().isoformat(),),
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
