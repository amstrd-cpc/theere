from __future__ import annotations

import datetime
from typing import Any, Dict, List

from db.connection import get_sales_db
from services.inventory_service import reduce_inventory_quantity, get_inventory_by_id


def record_sale(item: Dict[str, Any], price: float, payment_method: str) -> Dict[str, Any]:
    today = datetime.date.today().isoformat()
    with get_sales_db() as conn:
        conn.execute(
            """
            INSERT INTO sales (
                date, artist_album, genre, style, label, format,
                condition, price_gel, supplier_id, payment_method, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                today,
                item.get("artist_album"),
                item.get("genre"),
                item.get("style"),
                item.get("label"),
                item.get("format"),
                item.get("condition"),
                price,
                item.get("supplier_id"),
                payment_method,
                datetime.datetime.utcnow().isoformat(),
            ),
        )
        conn.commit()
    return {
        "date": today,
        "artist_album": item.get("artist_album"),
        "price_gel": price,
        "payment_method": payment_method,
    }


def reduce_stock_and_record_sale(item_id: int, price: float, payment_method: str) -> Dict[str, Any]:
    item = get_inventory_by_id(item_id)
    if not item:
        raise ValueError("Item not found")
    if not reduce_inventory_quantity(item_id, 1):
        raise ValueError("Out of stock")
    return record_sale(item, price, payment_method)


def get_recent_sales(limit: int = 10) -> List[Dict[str, Any]]:
    with get_sales_db(row_factory=None) as conn:
        cur = conn.execute(
            """
            SELECT artist_album, price_gel, COALESCE(payment_method, 'cash') AS payment_method, date
            FROM sales
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cur.fetchall()
    return [
        {"artist_album": row[0], "price_gel": row[1], "payment_method": row[2], "date": row[3]}
        for row in rows
    ]


def sales_between(start_date: datetime.date, end_date: datetime.date) -> List[tuple]:
    with get_sales_db(row_factory=None) as conn:
        cur = conn.execute(
            """
            SELECT
                s.artist_album,
                s.genre,
                s.style,
                s.label,
                s.format,
                s.condition,
                s.price_gel,
                s.supplier_id,
                COALESCE(s.payment_method, 'cash') AS payment_method,
                s.created_at
            FROM sales s
            WHERE s.date BETWEEN ? AND ?
            ORDER BY s.date, s.created_at
            """,
            (start_date.isoformat(), end_date.isoformat()),
        )
        return cur.fetchall()


def summary_between(start_date: datetime.date, end_date: datetime.date) -> Dict[str, Any]:
    with get_sales_db(row_factory=None) as conn:
        cur = conn.execute(
            """
            SELECT price_gel, COALESCE(payment_method, 'cash') AS payment_method
            FROM sales
            WHERE date BETWEEN ? AND ?
            """,
            (start_date.isoformat(), end_date.isoformat()),
        )
        rows = cur.fetchall()
    total_cash = sum(row[0] for row in rows if (row[1] or "cash").lower() == "cash")
    total_pos = sum(row[0] for row in rows if (row[1] or "cash").lower() == "pos")
    return {
        "items": len(rows),
        "cash": total_cash,
        "pos": total_pos,
        "total": total_cash + total_pos,
    }
