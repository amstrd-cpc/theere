from __future__ import annotations

import datetime
import logging
import os
import sqlite3
from pathlib import Path
from typing import Optional

from config.settings import load_settings
from db.connection import get_inventory_db

logger = logging.getLogger(__name__)


def run_backup(backup_type: str) -> Optional[str]:
    settings = load_settings()
    db_path = Path(settings.db_path)
    if not db_path.is_absolute():
        db_path = Path(os.getcwd()) / db_path
    timestamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
    base_dir = Path(os.getcwd()) / "backups" / backup_type
    base_dir.mkdir(parents=True, exist_ok=True)
    backup_path = base_dir / f"inventory_{timestamp}.sqlite"

    run_id = _start_backup_run(backup_type)
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute(f"VACUUM INTO '{backup_path.as_posix()}'")
        finally:
            conn.close()
        _finish_backup_run(run_id, status="success", path=str(backup_path))
        _apply_retention(backup_type)
        return str(backup_path)
    except Exception as exc:
        logger.exception("Backup failed (%s)", backup_type)
        _finish_backup_run(run_id, status="failed", error=str(exc))
        return None


def _start_backup_run(backup_type: str) -> int:
    now = datetime.datetime.now(datetime.UTC).isoformat()
    with get_inventory_db() as conn:
        cur = conn.execute(
            "INSERT INTO backup_runs (ts_started, backup_type, status) VALUES (?, ?, ?)",
            (now, backup_type, "running"),
        )
        conn.commit()
        return int(cur.lastrowid)


def _finish_backup_run(run_id: int, *, status: str, path: Optional[str] = None, error: Optional[str] = None) -> None:
    now = datetime.datetime.now(datetime.UTC).isoformat()
    with get_inventory_db() as conn:
        conn.execute(
            """
            UPDATE backup_runs
            SET ts_finished = ?, status = ?, path = ?, error = ?
            WHERE id = ?
            """,
            (now, status, path, error, run_id),
        )
        conn.commit()


def _apply_retention(backup_type: str) -> None:
    now = datetime.datetime.now(datetime.UTC)
    base_dir = Path(os.getcwd()) / "backups" / backup_type
    if backup_type == "rolling":
        cutoff = now - datetime.timedelta(hours=24)
    else:
        cutoff = now - datetime.timedelta(days=30)
    for path in base_dir.glob("inventory_*.sqlite"):
        try:
            mtime = datetime.datetime.utcfromtimestamp(path.stat().st_mtime)
        except FileNotFoundError:
            continue
        if mtime < cutoff:
            path.unlink(missing_ok=True)
