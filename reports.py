"""reports.py

Reporting uses the *same* unified SQLite DB as inventory.

Why:
- No duplicate sales logging.
- One source of truth.
- FK/constraints apply consistently.
"""

from __future__ import annotations

import datetime
import os
from openpyxl import Workbook

# Telegram handler (kept for backwards compatibility with bot.py)
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from db import get_db


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EXCEL_REPORT_FOLDER = os.path.join(BASE_DIR, "sales_reports")

if not os.path.exists(EXCEL_REPORT_FOLDER):
    os.makedirs(EXCEL_REPORT_FOLDER)


def init_report_db() -> None:
    """Backward-compatible initializer.

    The unified DB is initialized in db.init_db(). This is kept so imports
    from older code don't break.
    """
    return


def log_sale_to_report_db(sale_data: dict) -> None:
    """Legacy no-op.

    Sales are already inserted into the unified `sales` table in sales.py.
    Keeping this function avoids touching every call-site.
    """
    return


def _write_sales_to_worksheet(ws, rows, summary_title: str):
    headers = [
        "Artist/Album",
        "Genre",
        "Style",
        "Label",
        "Format",
        "Condition",
        "GEL Price",
        "Supplier",
        "Payment Method",
        "Time",
    ]
    ws.append(headers)
    for row in rows:
        ws.append(row)
    last_row = len(rows) + 1
    ws.append([])
    ws.append([summary_title])
    ws.append(["Total Items Sold:", f"=COUNTA(A2:A{last_row})"])
    ws.append(["Cash Sales:", f'=SUMIF(I2:I{last_row},"cash",G2:G{last_row})'])
    ws.append(["POS Sales:", f'=SUMIF(I2:I{last_row},"pos",G2:G{last_row})'])
    ws.append(["Total Revenue:", f"=SUM(G2:G{last_row})"])


def generate_excel_report(start_date: datetime.date, end_date: datetime.date, label: str):
    file_name = (
        f"{label}_report_{start_date}.xlsx"
        if start_date == end_date
        else f"{label}_report_{start_date}_to_{end_date}.xlsx"
    )
    file_path = os.path.join(EXCEL_REPORT_FOLDER, file_name)

    with get_db(row_factory=None) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                s.artist_album,
                s.genre,
                s.style,
                s.label,
                s.format,
                s.condition,
                s.price_gel,
                COALESCE(sp.name, '') AS supplier,
                COALESCE(s.payment_method, 'cash') AS payment_method,
                s.created_at
            FROM sales s
            LEFT JOIN supplier sp ON s.supplier_id = sp.id
            WHERE s.date BETWEEN ? AND ?
            ORDER BY s.date, s.created_at
            """,
            (start_date.isoformat(), end_date.isoformat()),
        )
        rows = cur.fetchall()

    if not rows:
        raise FileNotFoundError("No sales recorded for this period yet.")

    wb = Workbook()
    ws = wb.active
    ws.title = f"Sales {start_date} to {end_date}"
    _write_sales_to_worksheet(ws, rows, f"{label.upper()} SUMMARY")
    wb.save(file_path)

    summary = _generate_summary(start_date, end_date)
    return file_path, summary


def generate_daily_excel_report():
    today = datetime.date.today()
    return generate_excel_report(today, today, "daily")


def generate_weekly_excel_report():
    end = datetime.date.today()
    start = end - datetime.timedelta(days=6)
    return generate_excel_report(start, end, "weekly")


def generate_monthly_excel_report():
    end = datetime.date.today()
    start = end - datetime.timedelta(days=29)
    return generate_excel_report(start, end, "monthly")


def get_recent_sales(limit: int = 10):
    with get_db(row_factory=None) as conn:
        cur = conn.cursor()
        cur.execute(
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
        {"artist_album": r[0], "price_gel": r[1], "payment_method": r[2], "date": r[3]}
        for r in rows
    ]


def _generate_summary(start_date: datetime.date, end_date: datetime.date) -> str:
    with get_db(row_factory=None) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT price_gel, COALESCE(payment_method, 'cash') AS payment_method
            FROM sales
            WHERE date BETWEEN ? AND ?
            """,
            (start_date.isoformat(), end_date.isoformat()),
        )
        rows = cur.fetchall()
    if not rows:
        return "No sales recorded for this period."
    total_cash = sum(r[0] for r in rows if (r[1] or "cash").lower() == "cash")
    total_pos = sum(r[0] for r in rows if (r[1] or "cash").lower() == "pos")
    total_items = len(rows)
    return (
        f"Items sold: {total_items}\n"
        f"Cash: ₾{total_cash:.2f}\n"
        f"POS: ₾{total_pos:.2f}\n"
        f"Total Revenue: ₾{total_cash + total_pos:.2f}"
    )


def generate_daily_report() -> str:
    today = datetime.date.today()
    return f"📅 Daily Report for {today}\n\n" + _generate_summary(today, today)


def generate_weekly_report() -> str:
    end = datetime.date.today()
    start = end - datetime.timedelta(days=6)
    return f"📅 Weekly Report ({start} to {end})\n\n" + _generate_summary(start, end)


def generate_monthly_report() -> str:
    end = datetime.date.today()
    start = end - datetime.timedelta(days=29)
    return f"📅 Monthly Report ({start} to {end})\n\n" + _generate_summary(start, end)


# --- Telegram command handler (backwards compatible) ---
async def send_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /reports.

    Historically /reports generated a daily Excel report and sent it to the user.
    bot.py still expects reports.report_handler() to exist.
    """
    try:
        file_path, summary = generate_daily_excel_report()
        await update.message.reply_text(summary, parse_mode="Markdown")
        with open(file_path, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=os.path.basename(file_path),
                caption="📊 Daily Sales Report",
            )
    except FileNotFoundError:
        await update.message.reply_text(
            "📭 No sales recorded for today yet.\nStart selling some records to generate a report! 🎵"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error generating report: {str(e)}")


def report_handler():
    """Return the /reports handler expected by bot.py."""
    return CommandHandler("reports", send_report)
