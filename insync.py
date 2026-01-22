from __future__ import annotations

import argparse
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

from woocommerce_client import (
    WooNotConfigured,
    create_product_from_inventory,
    find_product_by_sku,
    update_product_from_inventory,
)


def load_env() -> None:
    """Load .env from the script directory, then from default locations."""
    if load_dotenv is None:
        return
    env_path = Path(__file__).resolve().with_name('.env')
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
    else:
        load_dotenv()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def resolve_db_path(cli_db: str | None) -> str:
    if cli_db:
        return cli_db
    env_db = os.getenv('RECORDSTORE_DB_FILE') or os.getenv('DB_PATH')
    if env_db:
        return env_db

    base = Path(__file__).resolve().parent
    for name in ('clime_db_final_219.db', 'clime_db_optimized.db', 'clime_db.db'):
        p = base / name
        if p.exists():
            return str(p)
    return str(base / 'clime_db.db')


def ensure_pragmas(con: sqlite3.Connection) -> None:
    con.execute('PRAGMA foreign_keys = ON;')
    con.execute('PRAGMA journal_mode = WAL;')
    con.execute('PRAGMA synchronous = NORMAL;')
    con.execute(f"PRAGMA busy_timeout = {int(os.getenv('SQLITE_BUSY_TIMEOUT', '5000'))};")


def table_has_column(cur: sqlite3.Cursor, table: str, col: str) -> bool:
    cur.execute(f'PRAGMA table_info({table})')
    return any(r[1] == col for r in cur.fetchall())


def mark_synced(con: sqlite3.Connection, inv_id: int, woo_product_id: int) -> None:
    cur = con.cursor()
    sets = []
    params = []

    if table_has_column(cur, 'inventory', 'woo_product_id'):
        sets.append('woo_product_id = ?')
        params.append(str(woo_product_id))

    if table_has_column(cur, 'inventory', 'woo_synced'):
        sets.append('woo_synced = 1')

    if table_has_column(cur, 'inventory', 'woo_last_synced_at'):
        sets.append('woo_last_synced_at = ?')
        params.append(utc_now_iso())

    if not sets:
        return

    params.append(inv_id)
    cur.execute(f"UPDATE inventory SET {', '.join(sets)} WHERE id = ?", params)
    con.commit()


def needs_update(existing: dict, item: dict) -> bool:
    # Cheap diff check to avoid unnecessary PUTs
    if str(existing.get('name') or '') != str(item.get('artist_album') or ''):
        return True
    if str(existing.get('regular_price') or '') != str(item.get('price_gel') or ''):
        return True
    if int(existing.get('stock_quantity') or 0) != int(item.get('quantity') or 0):
        return True

    # If description doesn't include Tracklist and Discogs is configured, update once.
    desc = existing.get('description') or ''
    if 'Tracklist' not in desc and os.getenv('DISCOGS_TOKEN'):
        return True

    return False


def main() -> None:
    load_env()

    ap = argparse.ArgumentParser(description='Initial Woo sync (safe to rerun).')
    ap.add_argument('--db', default=None, help='Path to sqlite db. Overrides .env')
    ap.add_argument('--force', action='store_true', help='Process all rows, not just unsynced')
    ap.add_argument('--limit', type=int, default=0, help='Limit number of rows')
    ap.add_argument('--dry-run', action='store_true', help='Print actions without calling Woo')
    ap.add_argument('--sleep', type=float, default=float(os.getenv('SYNC_SLEEP', '0')))
    ap.add_argument('--link-only', action='store_true', help='Only link by SKU, do not update fields')
    args = ap.parse_args()

    db_path = resolve_db_path(args.db)
    if not os.path.exists(db_path):
        raise SystemExit(f'DB not found: {db_path}')

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    ensure_pragmas(con)

    cur = con.cursor()

    # Build query for rows to process
    where = '1=1'
    if not args.force:
        clauses = []
        if table_has_column(cur, 'inventory', 'woo_product_id'):
            clauses.append("(woo_product_id IS NULL OR woo_product_id = '')")
        if table_has_column(cur, 'inventory', 'woo_synced'):
            clauses.append('(woo_synced IS NULL OR woo_synced = 0)')
        if clauses:
            where = ' OR '.join(clauses)

    sql = f'SELECT * FROM inventory WHERE {where} ORDER BY id ASC'
    rows = cur.execute(sql).fetchall()
    if args.limit and args.limit > 0:
        rows = rows[: args.limit]

    print(f'Using DB: {os.path.abspath(db_path)}')
    print(f'Rows to sync: {len(rows)}')

    if not rows:
        print('Nothing to sync.')
        return

    ok = updated = skipped = failed = 0

    for idx, row in enumerate(rows, start=1):
        item = dict(row)
        inv_id = item.get('id')
        if inv_id is None:
            print(f'[{idx}/{len(rows)}] SKIP: missing id')
            skipped += 1
            continue

        sku = str(inv_id)
        name = item.get('artist_album')
        print(f'[{idx}/{len(rows)}] id={inv_id} sku={sku} | {name}')

        if args.dry_run:
            print('  DRY RUN: would upsert')
            ok += 1
            continue

        try:
            existing = find_product_by_sku(sku)
        except WooNotConfigured as e:
            raise SystemExit(f'Woo not configured: {e}')
        except Exception as e:
            print(f'  FAILED (lookup): {e}')
            failed += 1
            continue

        try:
            if existing:
                woo_id = int(existing['id'])
                if args.link_only:
                    print(f'  Link-only: linked Woo id={woo_id}')
                    mark_synced(con, int(inv_id), woo_id)
                    ok += 1
                else:
                    if needs_update(existing, item):
                        update_product_from_inventory(woo_id, item)
                        print(f'  Updated Woo id={woo_id}')
                        updated += 1
                    else:
                        print(f'  No diff: keep Woo id={woo_id}')
                        skipped += 1
                    mark_synced(con, int(inv_id), woo_id)
                    ok += 1
            else:
                product = create_product_from_inventory(item)
                woo_id = int(product['id'])
                print(f'  Created Woo id={woo_id}')
                mark_synced(con, int(inv_id), woo_id)
                ok += 1
        except Exception as e:
            print(f'  FAILED: {e}')
            failed += 1

        if args.sleep and args.sleep > 0:
            time.sleep(args.sleep)

    print('\n=== Summary ===')
    print(f'Processed ok: {ok}')
    print(f'Updated: {updated}')
    print(f'Skipped: {skipped}')
    print(f'Failed: {failed}')


if __name__ == '__main__':
    main()
