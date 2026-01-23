"""db.py

SQLite access layer for the Record Store Telegram bot.

Goals:
- Single source of truth DB (inventory + sales + Woo tables).
- Connection-level pragmas for concurrency and integrity.
- Keep function names used across the project.
"""

from __future__ import annotations

import os
import sqlite3
from typing import Any, Iterable


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Prefer the optimized DB name, but allow an override for deployments.
DB_FILE = (
    os.getenv("RECORDSTORE_DB_FILE")
    or os.getenv("DB_PATH")
    or os.path.join(BASE_DIR, "clime_db.db")
)

def _apply_connection_pragmas(conn: sqlite3.Connection) -> None:
    """Pragmas that must be set per-connection."""
    # Integrity
    conn.execute("PRAGMA foreign_keys = ON;")

    # Concurrency + bot UX (avoid 'database is locked')
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")


def get_db(*, row_factory: Any = sqlite3.Row) -> sqlite3.Connection:
    """Open a new connection.

    We intentionally create short-lived connections (one per operation). This
    plays nicely with python-telegram-bot's async handlers.
    """
    conn = sqlite3.connect(DB_FILE, timeout=5)
    conn.row_factory = row_factory
    _apply_connection_pragmas(conn)
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?", (name,))
    return cur.fetchone() is not None


def init_db() -> None:
    """Ensure required tables / indexes / FTS exist.

    Note: Some constraints (CHECK/NOT NULL) cannot be retrofitted with ALTER in
    SQLite. The optimized DB you generated already contains the stronger schema.
    This initializer focuses on safety and compatibility in case the DB is fresh.
    """
    with get_db() as conn:
        cur = conn.cursor()

        # Core tables (minimal compatible schema; existing DB won't be modified).
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS supplier (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                artist_album TEXT NOT NULL,
                genre TEXT,
                style TEXT,
                label TEXT,
                format TEXT,
                condition TEXT,
                price_gel REAL NOT NULL DEFAULT 0,
                quantity INTEGER NOT NULL DEFAULT 0,
                supplier_id INTEGER,
                created_at TEXT DEFAULT (datetime('now')),
                woo_product_id INTEGER,
                woo_synced INTEGER DEFAULT 0,
                woo_last_synced_at TEXT,
                woo_sync_hash TEXT,
                year INTEGER,
                description TEXT,
                FOREIGN KEY (supplier_id) REFERENCES supplier(id)
            )
            """
        )

        # If the inventory table existed before we added woo_sync_hash, retrofit it.
        try:
            cur.execute("ALTER TABLE inventory ADD COLUMN woo_sync_hash TEXT")
        except sqlite3.OperationalError:
            pass

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                artist_album TEXT,
                genre TEXT,
                style TEXT,
                label TEXT,
                format TEXT,
                condition TEXT,
                price_gel REAL NOT NULL DEFAULT 0,
                supplier_id INTEGER,
                payment_method TEXT DEFAULT 'cash',
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (supplier_id) REFERENCES supplier(id)
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS user_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE,
                authenticated INTEGER DEFAULT 0,
                last_activity TEXT
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS woo_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER UNIQUE,
                processed_at TEXT
            )
            """
        )

        # Indexes (read-heavy bot operations)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_inventory_artist_album ON inventory(artist_album)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_inventory_label ON inventory(label)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_inventory_genre ON inventory(genre)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_inventory_style ON inventory(style)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_inventory_year ON inventory(year)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_inventory_qty ON inventory(quantity)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sales_date ON sales(date)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sales_created_at ON sales(created_at)")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_inventory_woo_product_id ON inventory(woo_product_id)")

        # FTS (optional, but makes search feel instant)
        # If FTS5 is not available in a given Python build, creation will fail.
        # We keep it best-effort: fallback search uses LIKE.
        try:
            cur.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS inventory_fts
                USING fts5(
                    artist_album,
                    genre,
                    style,
                    label,
                    format,
                    condition,
                    year,
                    description,
                    content='inventory',
                    content_rowid='id'
                )
                """
            )

            # Triggers to keep FTS in sync
            cur.execute(
                """
                CREATE TRIGGER IF NOT EXISTS inventory_ai AFTER INSERT ON inventory BEGIN
                    INSERT INTO inventory_fts(rowid, artist_album, genre, style, label, format, condition, year, description)
                    VALUES (new.id, new.artist_album, new.genre, new.style, new.label, new.format, new.condition, new.year, new.description);
                END;
                """
            )
            cur.execute(
                """
                CREATE TRIGGER IF NOT EXISTS inventory_ad AFTER DELETE ON inventory BEGIN
                    INSERT INTO inventory_fts(inventory_fts, rowid, artist_album, genre, style, label, format, condition, year, description)
                    VALUES('delete', old.id, old.artist_album, old.genre, old.style, old.label, old.format, old.condition, old.year, old.description);
                END;
                """
            )
            cur.execute(
                """
                CREATE TRIGGER IF NOT EXISTS inventory_au AFTER UPDATE ON inventory BEGIN
                    INSERT INTO inventory_fts(inventory_fts, rowid, artist_album, genre, style, label, format, condition, year, description)
                    VALUES('delete', old.id, old.artist_album, old.genre, old.style, old.label, old.format, old.condition, old.year, old.description);
                    INSERT INTO inventory_fts(rowid, artist_album, genre, style, label, format, condition, year, description)
                    VALUES (new.id, new.artist_album, new.genre, new.style, new.label, new.format, new.condition, new.year, new.description);
                END;
                """
            )

            # Backfill FTS if empty
            cur.execute("SELECT COUNT(*) AS c FROM inventory_fts")
            c = cur.fetchone()[0]
            if c == 0:
                cur.execute(
                    """
                    INSERT INTO inventory_fts(rowid, artist_album, genre, style, label, format, condition, year, description)
                    SELECT id, artist_album, genre, style, label, format, condition, year, description
                    FROM inventory
                    """
                )
        except sqlite3.OperationalError:
            # FTS5 not available - ignore.
            pass

        conn.commit()


def backup_db() -> None:
    if os.path.exists(DB_FILE):
        backup_file = f"{DB_FILE}.backup"
        try:
            import shutil

            shutil.copy2(DB_FILE, backup_file)
            print(f"✅ Backup saved to {backup_file}")
        except Exception as e:
            print(f"❌ Backup failed: {e}")


def get_db_stats() -> dict[str, int]:
    with get_db(row_factory=None) as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM inventory")
        inventory_count = cur.fetchone()[0]
        cur.execute("SELECT COALESCE(SUM(quantity), 0) FROM inventory")
        total_quantity = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM sales")
        sales_count = cur.fetchone()[0]
        return {
            "inventory_records": int(inventory_count),
            "total_quantity": int(total_quantity),
            "sales_records": int(sales_count),
        }


def cleanup_sold_out_items() -> int:
    with get_db(row_factory=None) as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM inventory WHERE quantity <= 0")
        deleted = cur.rowcount
        conn.commit()
        return int(deleted)


def get_suppliers() -> list[sqlite3.Row]:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, name FROM supplier ORDER BY name")
        return cur.fetchall()


def get_or_create_supplier(name: str) -> int:
    name = (name or "").strip()
    if not name:
        raise ValueError("Supplier name cannot be empty")
    with get_db(row_factory=None) as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM supplier WHERE name = ?", (name,))
        row = cur.fetchone()
        if row:
            return int(row[0])
        cur.execute("INSERT INTO supplier (name) VALUES (?)", (name,))
        conn.commit()
        return int(cur.lastrowid)
