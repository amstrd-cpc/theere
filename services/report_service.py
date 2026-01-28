from __future__ import annotations

import datetime
import os
from typing import Tuple

from openpyxl import Workbook

from services.sales_service import sales_between, summary_between

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPORT_DIR = os.path.join(os.path.dirname(BASE_DIR), "sales_reports")

if not os.path.exists(REPORT_DIR):
    os.makedirs(REPORT_DIR)


def _write_sales(ws, rows, summary_title: str) -> None:
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


def generate_excel_report(start_date: datetime.date, end_date: datetime.date, label: str) -> Tuple[str, str]:
    file_name = (
        f"{label}_report_{start_date}.xlsx"
        if start_date == end_date
        else f"{label}_report_{start_date}_to_{end_date}.xlsx"
    )
    file_path = os.path.join(REPORT_DIR, file_name)

    rows = sales_between(start_date, end_date)
    if not rows:
        raise FileNotFoundError("No sales recorded for this period yet.")

    wb = Workbook()
    ws = wb.active
    ws.title = f"Sales {start_date} to {end_date}"
    _write_sales(ws, rows, f"{label.upper()} SUMMARY")
    wb.save(file_path)

    summary = summary_between(start_date, end_date)
    summary_text = (
        f"Items sold: {summary['items']}\n"
        f"Cash: ₾{summary['cash']:.2f}\n"
        f"POS: ₾{summary['pos']:.2f}\n"
        f"Total Revenue: ₾{summary['total']:.2f}"
    )
    return file_path, summary_text


def generate_daily_excel_report() -> Tuple[str, str]:
    today = datetime.date.today()
    return generate_excel_report(today, today, "daily")


def generate_weekly_excel_report() -> Tuple[str, str]:
    end = datetime.date.today()
    start = end - datetime.timedelta(days=6)
    return generate_excel_report(start, end, "weekly")


def generate_monthly_excel_report() -> Tuple[str, str]:
    end = datetime.date.today()
    start = end - datetime.timedelta(days=29)
    return generate_excel_report(start, end, "monthly")


def generate_daily_report() -> str:
    today = datetime.date.today()
    summary = summary_between(today, today)
    return (
        f"📅 Daily Report for {today}\n\n"
        f"Items sold: {summary['items']}\n"
        f"Cash: ₾{summary['cash']:.2f}\n"
        f"POS: ₾{summary['pos']:.2f}\n"
        f"Total Revenue: ₾{summary['total']:.2f}"
    )


def generate_weekly_report() -> str:
    end = datetime.date.today()
    start = end - datetime.timedelta(days=6)
    summary = summary_between(start, end)
    return (
        f"📅 Weekly Report ({start} to {end})\n\n"
        f"Items sold: {summary['items']}\n"
        f"Cash: ₾{summary['cash']:.2f}\n"
        f"POS: ₾{summary['pos']:.2f}\n"
        f"Total Revenue: ₾{summary['total']:.2f}"
    )


def generate_monthly_report() -> str:
    end = datetime.date.today()
    start = end - datetime.timedelta(days=29)
    summary = summary_between(start, end)
    return (
        f"📅 Monthly Report ({start} to {end})\n\n"
        f"Items sold: {summary['items']}\n"
        f"Cash: ₾{summary['cash']:.2f}\n"
        f"POS: ₾{summary['pos']:.2f}\n"
        f"Total Revenue: ₾{summary['total']:.2f}"
    )
