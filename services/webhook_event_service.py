from __future__ import annotations

import datetime
import sqlite3
from typing import Optional

from db.connection import get_inventory_db


def create_webhook_event(
    *,
    store_id: int,
    event_key: str,
    woo_order_id: Optional[int],
    topic: str,
    payload_hash: str,
) -> Optional[int]:
    with get_inventory_db() as conn:
        try:
            cur = conn.execute(
                """
                INSERT INTO webhook_events (
                    store_id,
                    event_key,
                    woo_order_id,
                    topic,
                    payload_hash,
                    status
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (store_id, event_key, woo_order_id, topic, payload_hash, "received"),
            )
            conn.commit()
            return int(cur.lastrowid)
        except sqlite3.IntegrityError:
            return None


def mark_webhook_processed(event_id: int) -> None:
    now = datetime.datetime.utcnow().isoformat()
    with get_inventory_db() as conn:
        conn.execute(
            "UPDATE webhook_events SET processed_at = ?, status = ? WHERE id = ?",
            (now, "processed", event_id),
        )
        conn.commit()


def mark_webhook_failed(event_id: int, error_message: str) -> None:
    now = datetime.datetime.utcnow().isoformat()
    with get_inventory_db() as conn:
        conn.execute(
            "UPDATE webhook_events SET processed_at = ?, status = ?, error_message = ? WHERE id = ?",
            (now, "failed", error_message[:500], event_id),
        )
        conn.commit()


def get_webhook_event(event_id: int) -> Optional[dict]:
    with get_inventory_db() as conn:
        cur = conn.execute("SELECT * FROM webhook_events WHERE id = ?", (event_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def get_last_webhook_received_at() -> Optional[str]:
    with get_inventory_db() as conn:
        cur = conn.execute("SELECT MAX(received_at) FROM webhook_events")
        row = cur.fetchone()
        return row[0] if row and row[0] else None


def get_last_webhook_processed_at() -> Optional[str]:
    with get_inventory_db() as conn:
        cur = conn.execute("SELECT MAX(processed_at) FROM webhook_events WHERE status = 'processed'")
        row = cur.fetchone()
        return row[0] if row and row[0] else None
