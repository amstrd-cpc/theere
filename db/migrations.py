from __future__ import annotations

import sqlite3

from db.connection import get_inventory_db, get_sales_db


INVENTORY_COLUMNS = {
    "artist_album": "TEXT",
    "genre": "TEXT",
    "style": "TEXT",
    "label": "TEXT",
    "format": "TEXT",
    "condition": "TEXT",
    "price_gel": "REAL",
    "quantity": "INTEGER",
    "supplier_id": "INTEGER",
    "created_at": "TEXT",
    "woo_product_id": "INTEGER",
    "woo_synced": "INTEGER",
    "woo_last_synced_at": "TEXT",
    "woo_sync_hash": "TEXT",
    "year": "INTEGER",
    "description": "TEXT",
    "cover_url": "TEXT",
}

SALES_COLUMNS = {
    "date": "TEXT",
    "artist_album": "TEXT",
    "genre": "TEXT",
    "style": "TEXT",
    "label": "TEXT",
    "format": "TEXT",
    "condition": "TEXT",
    "price_gel": "REAL",
    "supplier_id": "INTEGER",
    "payment_method": "TEXT",
    "created_at": "TEXT",
}


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}


def _add_missing_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = _table_columns(conn, table)
    for column, col_type in columns.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")


def _create_inventory(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS supplier (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
        """
    )
    conn.execute(
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
            cover_url TEXT,
            FOREIGN KEY (supplier_id) REFERENCES supplier(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS woo_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER UNIQUE,
            processed_at TEXT
        )
        """
    )
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


def _create_sales(conn: sqlite3.Connection) -> None:
    conn.execute(
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
            created_at TEXT DEFAULT (datetime('now'))
        )
        """
    )


def _ensure_indexes(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE INDEX IF NOT EXISTS idx_inventory_artist_album ON inventory(artist_album)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_inventory_label ON inventory(label)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_inventory_genre ON inventory(genre)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_inventory_style ON inventory(style)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_inventory_year ON inventory(year)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_inventory_qty ON inventory(quantity)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_inventory_woo_product_id ON inventory(woo_product_id)")


def _ensure_sales_indexes(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sales_date ON sales(date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sales_created_at ON sales(created_at)")


def _ensure_fts(conn: sqlite3.Connection) -> None:
    try:
        conn.execute(
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
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS inventory_ai AFTER INSERT ON inventory BEGIN
                INSERT INTO inventory_fts(rowid, artist_album, genre, style, label, format, condition, year, description)
                VALUES (new.id, new.artist_album, new.genre, new.style, new.label, new.format, new.condition, new.year, new.description);
            END;
            """
        )
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS inventory_ad AFTER DELETE ON inventory BEGIN
                INSERT INTO inventory_fts(inventory_fts, rowid, artist_album, genre, style, label, format, condition, year, description)
                VALUES('delete', old.id, old.artist_album, old.genre, old.style, old.label, old.format, old.condition, old.year, old.description);
            END;
            """
        )
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS inventory_au AFTER UPDATE ON inventory BEGIN
                INSERT INTO inventory_fts(inventory_fts, rowid, artist_album, genre, style, label, format, condition, year, description)
                VALUES('delete', old.id, old.artist_album, old.genre, old.style, old.label, old.format, old.condition, old.year, old.description);
                INSERT INTO inventory_fts(rowid, artist_album, genre, style, label, format, condition, year, description)
                VALUES (new.id, new.artist_album, new.genre, new.style, new.label, new.format, new.condition, new.year, new.description);
            END;
            """
        )
    except sqlite3.OperationalError:
        return


def migrate() -> None:
    with get_inventory_db() as conn:
        _create_inventory(conn)
        _add_missing_columns(conn, "inventory", INVENTORY_COLUMNS)
        _add_missing_columns(conn, "user_sessions", {
            "username": "TEXT",
            "first_name": "TEXT",
            "authenticated_at": "TEXT",
            "expires_at": "TEXT",
            "last_activity": "TEXT",
        })
        _ensure_indexes(conn)
        _ensure_fts(conn)
        conn.commit()

    with get_sales_db() as conn:
        _create_sales(conn)
        _add_missing_columns(conn, "sales", SALES_COLUMNS)
        _ensure_sales_indexes(conn)
        conn.commit()
