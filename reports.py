from __future__ import annotations

from telegram.ext import CommandHandler


def init_report_db() -> None:
    return


def log_sale_to_report_db(sale_data: dict) -> None:
    return


def report_handler() -> CommandHandler:
    from telegram_ui.reports import reports_command

    return CommandHandler("reports", reports_command)
