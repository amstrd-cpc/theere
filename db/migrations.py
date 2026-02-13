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
    "sleeve_condition": "TEXT",
    "price_gel": "REAL",
    "quantity": "INTEGER",
    "supplier_id": "INTEGER",
    "created_at": "TEXT",
    "updated_at": "TEXT",
    "local_rev": "INTEGER NOT NULL DEFAULT 0",
    "last_change_source": "TEXT",
    "woo_product_id": "INTEGER",
    "woo_synced": "INTEGER",
    "woo_last_synced_at": "TEXT",
    "woo_sync_hash": "TEXT",
    "year": "INTEGER",
    "description": "TEXT",
    "cover_url": "TEXT",
    "discogs_release_id": "INTEGER",
    "discogs_master_id": "INTEGER",
    "discogs_uri": "TEXT",
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


LATEST_VERSION = 7


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}


def _add_missing_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = _table_columns(conn, table)
    for column, col_type in columns.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY
        )
        """
    )


def _get_version(conn: sqlite3.Connection) -> int:
    _ensure_migrations_table(conn)
    cur = conn.execute("SELECT MAX(version) FROM schema_migrations")
    row = cur.fetchone()
    return int(row[0] or 0) if row else 0


def _set_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute("INSERT OR REPLACE INTO schema_migrations (version) VALUES (?)", (version,))


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
            sleeve_condition TEXT,
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

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ui_sessions (
            session_id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            expected_node TEXT NOT NULL,
            expected_state TEXT,
            issued_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ui_sessions_user_id ON ui_sessions(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ui_sessions_expires_at ON ui_sessions(expires_at)")


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


def _create_woo_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS stores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_name TEXT,
            store_url TEXT NOT NULL,
            woo_consumer_key TEXT NOT NULL,
            woo_consumer_secret TEXT NOT NULL,
            webhook_secret TEXT NOT NULL,
            webhook_ids TEXT,
            discogs_token TEXT,
            discogs_username TEXT,
            discogs_user_id INTEGER,
            discogs_last_sync_at TEXT,
            settings_json TEXT,
            is_enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS product_map (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id INTEGER NOT NULL,
            internal_product_id INTEGER NOT NULL,
            woo_product_id INTEGER,
            woo_variation_id INTEGER,
            sku TEXT,
            discogs_listing_id INTEGER,
            discogs_release_id INTEGER,
            discogs_last_seen_quantity INTEGER,
            discogs_last_seen_price REAL,
            discogs_last_seen_at TEXT,
            discogs_last_seen_hash TEXT,
            woo_last_seen_quantity INTEGER,
            woo_last_seen_price REAL,
            woo_last_seen_at TEXT,
            woo_last_seen_hash TEXT,
            woo_last_seen_modified_at TEXT,
            last_sync_direction TEXT,
            last_sync_hash TEXT,
            last_sync_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (store_id) REFERENCES stores(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_product_map_store_internal
        ON product_map(store_id, internal_product_id)
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_product_map_store_woo
        ON product_map(store_id, woo_product_id)
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_product_map_store_variation
        ON product_map(store_id, woo_variation_id)
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_product_map_store_sku
        ON product_map(store_id, sku)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id INTEGER NOT NULL,
            woo_order_id INTEGER NOT NULL,
            status TEXT,
            total REAL,
            currency TEXT,
            billing_name TEXT,
            billing_email TEXT,
            billing_phone TEXT,
            shipping_name TEXT,
            created_at TEXT,
            updated_at TEXT,
            last_seen_hash TEXT,
            inventory_applied_at TEXT,
            needs_review INTEGER DEFAULT 0,
            FOREIGN KEY (store_id) REFERENCES stores(id) ON DELETE CASCADE,
            UNIQUE (store_id, woo_order_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS order_line_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            woo_line_item_id INTEGER,
            internal_product_id INTEGER,
            sku TEXT,
            quantity INTEGER,
            price REAL,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_order_line_item_unique
        ON order_line_items(order_id, woo_line_item_id, internal_product_id)
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_order_line_item_woo_id
        ON order_line_items(order_id, woo_line_item_id)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS webhook_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id INTEGER NOT NULL,
            event_key TEXT NOT NULL UNIQUE,
            woo_order_id INTEGER,
            topic TEXT,
            payload_hash TEXT,
            received_at TEXT DEFAULT (datetime('now')),
            processed_at TEXT,
            status TEXT,
            error_message TEXT,
            FOREIGN KEY (store_id) REFERENCES stores(id) ON DELETE CASCADE
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            store_id INTEGER,
            internal_product_id INTEGER NOT NULL,
            theere_id TEXT,
            field TEXT CHECK(field IN ('quantity', 'regular_price')) NOT NULL,
            old_value TEXT,
            new_value TEXT,
            source TEXT CHECK(source IN (
                'manual_bot',
                'manual_woo',
                'order_decrement',
                'sync_pull',
                'sync_push',
                'import_restore'
            )) NOT NULL,
            correlation_id TEXT,
            note TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sync_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_started TEXT NOT NULL,
            ts_finished TEXT,
            store_id INTEGER NOT NULL,
            run_type TEXT CHECK(run_type IN ('periodic', 'instant', 'manual')) NOT NULL,
            pulled_count INTEGER DEFAULT 0,
            pushed_count INTEGER DEFAULT 0,
            created_local_count INTEGER DEFAULT 0,
            mapping_fixed_count INTEGER DEFAULT 0,
            incoming_count INTEGER DEFAULT 0,
            drifted_count INTEGER DEFAULT 0,
            conflict_count INTEGER DEFAULT 0,
            errors_count INTEGER DEFAULT 0,
            last_error TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sync_locks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id INTEGER NOT NULL,
            internal_product_id INTEGER NOT NULL,
            lock_owner TEXT NOT NULL,
            locked_at TEXT NOT NULL,
            UNIQUE(store_id, internal_product_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS backup_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_started TEXT NOT NULL,
            ts_finished TEXT,
            backup_type TEXT NOT NULL,
            status TEXT NOT NULL,
            path TEXT,
            error TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tri_sync_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_started TEXT NOT NULL,
            ts_finished TEXT,
            store_id INTEGER NOT NULL,
            run_type TEXT CHECK(run_type IN ('discogs', 'woo')) NOT NULL,
            incoming_count INTEGER DEFAULT 0,
            applied_count INTEGER DEFAULT 0,
            drifted_count INTEGER DEFAULT 0,
            conflict_count INTEGER DEFAULT 0,
            errors_count INTEGER DEFAULT 0,
            last_error TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS discogs_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER UNIQUE,
            processed_at TEXT
        )
        """
    )


def migrate() -> None:
    with get_inventory_db() as conn:
        current_version = _get_version(conn)
        if current_version < 1:
            _create_inventory(conn)
            _add_missing_columns(conn, "inventory", INVENTORY_COLUMNS)
            _add_missing_columns(
                conn,
                "user_sessions",
                {
                    "username": "TEXT",
                    "first_name": "TEXT",
                    "authenticated_at": "TEXT",
                    "expires_at": "TEXT",
                    "last_activity": "TEXT",
                },
            )
            _ensure_indexes(conn)
            _ensure_fts(conn)
            _set_version(conn, 1)
            current_version = 1
        if current_version < 2:
            _create_woo_tables(conn)
            _set_version(conn, 2)
            current_version = 2
        if current_version < 3:
            _add_missing_columns(
                conn,
                "stores",
                {
                    "discogs_token": "TEXT",
                    "discogs_username": "TEXT",
                    "discogs_user_id": "INTEGER",
                    "discogs_last_sync_at": "TEXT",
                },
            )
            _add_missing_columns(
                conn,
                "product_map",
                {
                    "discogs_release_id": "INTEGER",
                },
            )
            _add_missing_columns(conn, "inventory", INVENTORY_COLUMNS)
            _set_version(conn, 3)
            current_version = 3
        if current_version < 4:
            _add_missing_columns(conn, "inventory", INVENTORY_COLUMNS)
            _add_missing_columns(
                conn,
                "product_map",
                {
                    "discogs_last_seen_quantity": "INTEGER",
                    "discogs_last_seen_price": "REAL",
                    "discogs_last_seen_at": "TEXT",
                    "discogs_last_seen_hash": "TEXT",
                    "woo_last_seen_quantity": "INTEGER",
                    "woo_last_seen_price": "REAL",
                    "woo_last_seen_at": "TEXT",
                    "woo_last_seen_hash": "TEXT",
                    "last_sync_direction": "TEXT",
                    "last_sync_hash": "TEXT",
                    "last_sync_at": "TEXT",
                },
            )
            _set_version(conn, 4)
            current_version = 4
        if current_version < 5:
            _add_missing_columns(
                conn,
                "inventory",
                {
                    "updated_at": "TEXT",
                    "local_rev": "INTEGER NOT NULL DEFAULT 0",
                    "last_change_source": "TEXT",
                },
            )
            _add_missing_columns(
                conn,
                "product_map",
                {
                    "woo_last_seen_modified_at": "TEXT",
                },
            )
            _create_woo_tables(conn)
            _set_version(conn, 5)
            current_version = 5
        if current_version < 6:
            _add_missing_columns(
                conn,
                "sync_runs",
                {
                    "incoming_count": "INTEGER DEFAULT 0",
                    "drifted_count": "INTEGER DEFAULT 0",
                    "conflict_count": "INTEGER DEFAULT 0",
                },
            )
            _create_woo_tables(conn)
            _set_version(conn, 6)
            current_version = 6
        if current_version < 7:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ui_sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    expected_node TEXT NOT NULL,
                    expected_state TEXT,
                    issued_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ui_sessions_user_id ON ui_sessions(user_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ui_sessions_expires_at ON ui_sessions(expires_at)")
            _set_version(conn, 7)
            current_version = 7
        conn.commit()

    with get_sales_db() as conn:
        _create_sales(conn)
        _add_missing_columns(conn, "sales", SALES_COLUMNS)
        _ensure_sales_indexes(conn)
        conn.commit()
