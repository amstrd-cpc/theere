from __future__ import annotations

import datetime
import json
from typing import Any, Dict, List, Optional

from config.settings import load_settings
from db.connection import get_inventory_db

DEFAULT_SETTINGS = {
    "auto_decrement_enabled": True,
    "auto_decrement_status": "processing",
    "discogs_sync_on_sale": False,
    "discogs_price_sync": False,
    "discogs_polling_enabled": False,
    "discogs_polling_interval_minutes": 30,
    "notification_chat_id": None,
    "verify_ssl": True,
}


def _merge_settings(raw: Optional[str]) -> Dict[str, Any]:
    settings = DEFAULT_SETTINGS.copy()
    if raw:
        try:
            settings.update(json.loads(raw))
        except json.JSONDecodeError:
            pass
    return settings


def list_stores() -> List[Dict[str, Any]]:
    with get_inventory_db() as conn:
        cur = conn.execute("SELECT * FROM stores ORDER BY created_at DESC")
        return [dict(row) for row in cur.fetchall()]


def get_store(store_id: int) -> Optional[Dict[str, Any]]:
    with get_inventory_db() as conn:
        cur = conn.execute("SELECT * FROM stores WHERE id = ?", (store_id,))
        row = cur.fetchone()
        if not row:
            return None
        data = dict(row)
        data["settings"] = _merge_settings(data.get("settings_json"))
        return data


def get_default_store() -> Optional[Dict[str, Any]]:
    settings = load_settings()
    with get_inventory_db() as conn:
        if settings.default_store_id:
            cur = conn.execute(
                "SELECT * FROM stores WHERE id = ? AND is_enabled = 1",
                (settings.default_store_id,),
            )
            row = cur.fetchone()
            if row:
                data = dict(row)
                data["settings"] = _merge_settings(data.get("settings_json"))
                return data
        cur = conn.execute("SELECT * FROM stores WHERE is_enabled = 1 ORDER BY id ASC LIMIT 1")
        row = cur.fetchone()
        if not row:
            return None
        data = dict(row)
        data["settings"] = _merge_settings(data.get("settings_json"))
        return data


def create_store(
    *,
    store_name: str,
    store_url: str,
    consumer_key: str,
    consumer_secret: str,
    webhook_secret: str,
    webhook_ids: Optional[Dict[str, Any]] = None,
    settings: Optional[Dict[str, Any]] = None,
    discogs_token: Optional[str] = None,
    discogs_username: Optional[str] = None,
    discogs_user_id: Optional[int] = None,
) -> int:
    now = datetime.datetime.utcnow().isoformat()
    payload_settings = DEFAULT_SETTINGS.copy()
    if settings:
        payload_settings.update(settings)
    settings_json = json.dumps(payload_settings)
    webhook_json = json.dumps(webhook_ids or {})
    with get_inventory_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO stores (
                store_name,
                store_url,
                woo_consumer_key,
                woo_consumer_secret,
                webhook_secret,
                webhook_ids,
                discogs_token,
                discogs_username,
                discogs_user_id,
                settings_json,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                store_name,
                store_url,
                consumer_key,
                consumer_secret,
                webhook_secret,
                webhook_json,
                discogs_token,
                discogs_username,
                discogs_user_id,
                settings_json,
                now,
                now,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def update_store_webhook_ids(store_id: int, webhook_ids: Dict[str, Any]) -> None:
    now = datetime.datetime.utcnow().isoformat()
    webhook_json = json.dumps(webhook_ids)
    with get_inventory_db() as conn:
        conn.execute(
            "UPDATE stores SET webhook_ids = ?, updated_at = ? WHERE id = ?",
            (webhook_json, now, store_id),
        )
        conn.commit()


def update_store_credentials(
    store_id: int,
    *,
    store_name: Optional[str] = None,
    store_url: Optional[str] = None,
    consumer_key: Optional[str] = None,
    consumer_secret: Optional[str] = None,
) -> None:
    updates: Dict[str, Any] = {}
    if store_name:
        updates["store_name"] = store_name
    if store_url:
        updates["store_url"] = store_url
    if consumer_key:
        updates["woo_consumer_key"] = consumer_key
    if consumer_secret:
        updates["woo_consumer_secret"] = consumer_secret
    if not updates:
        return
    updates["updated_at"] = datetime.datetime.utcnow().isoformat()
    columns = ", ".join(f"{key} = ?" for key in updates.keys())
    values = list(updates.values())
    values.append(store_id)
    with get_inventory_db() as conn:
        conn.execute(f"UPDATE stores SET {columns} WHERE id = ?", values)
        conn.commit()


def update_store_settings(store_id: int, settings: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.datetime.utcnow().isoformat()
    with get_inventory_db() as conn:
        cur = conn.execute("SELECT settings_json FROM stores WHERE id = ?", (store_id,))
        row = cur.fetchone()
        current = _merge_settings(row[0] if row else None)
        current.update(settings)
        settings_json = json.dumps(current)
        conn.execute(
            "UPDATE stores SET settings_json = ?, updated_at = ? WHERE id = ?",
            (settings_json, now, store_id),
        )
        conn.commit()
    return current


def get_store_settings(store_id: int) -> Dict[str, Any]:
    store = get_store(store_id)
    if not store:
        return DEFAULT_SETTINGS.copy()
    return store.get("settings", DEFAULT_SETTINGS.copy())


def set_store_enabled(store_id: int, enabled: bool) -> None:
    now = datetime.datetime.utcnow().isoformat()
    with get_inventory_db() as conn:
        conn.execute(
            "UPDATE stores SET is_enabled = ?, updated_at = ? WHERE id = ?",
            (1 if enabled else 0, now, store_id),
        )
        conn.commit()


def update_store_discogs(
    store_id: int,
    *,
    discogs_token: str,
    discogs_username: Optional[str],
    discogs_user_id: Optional[int],
) -> None:
    now = datetime.datetime.utcnow().isoformat()
    with get_inventory_db() as conn:
        conn.execute(
            """
            UPDATE stores
            SET discogs_token = ?, discogs_username = ?, discogs_user_id = ?, updated_at = ?
            WHERE id = ?
            """,
            (discogs_token, discogs_username, discogs_user_id, now, store_id),
        )
        conn.commit()


def update_discogs_sync_time(store_id: int) -> None:
    now = datetime.datetime.utcnow().isoformat()
    with get_inventory_db() as conn:
        conn.execute(
            "UPDATE stores SET discogs_last_sync_at = ?, updated_at = ? WHERE id = ?",
            (now, now, store_id),
        )
        conn.commit()
