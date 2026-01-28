from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from config.settings import load_settings


def _resolve_db_path(path: str) -> str:
    base = Path(path)
    if base.is_absolute():
        return str(base)
    repo_root = Path(os.getcwd())
    return str(repo_root / base)


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")


def _connect(path: str, row_factory: Any) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = row_factory
    _apply_pragmas(conn)
    return conn


@contextmanager
def get_inventory_db(*, row_factory: Any = sqlite3.Row) -> Iterator[sqlite3.Connection]:
    settings = load_settings()
    path = _resolve_db_path(settings.db_path)
    conn = _connect(path, row_factory)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def get_sales_db(*, row_factory: Any = sqlite3.Row) -> Iterator[sqlite3.Connection]:
    settings = load_settings()
    path = settings.sales_db_path or settings.db_path
    conn = _connect(_resolve_db_path(path), row_factory)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def get_db(*, row_factory: Any = sqlite3.Row) -> Iterator[sqlite3.Connection]:
    """Backward-compatible alias for inventory DB."""
    with get_inventory_db(row_factory=row_factory) as conn:
        yield conn
