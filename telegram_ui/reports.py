from __future__ import annotations

import os
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from services.report_service import (
    generate_daily_excel_report,
    generate_weekly_excel_report,
    generate_monthly_excel_report,
)
from telegram_ui import messages
from telegram_ui.utils import escape_markdown_v2


async def daily_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        file_path, summary = await context.application.run_in_executor(None, generate_daily_excel_report)
        await update.message.reply_text(summary, parse_mode="Markdown")
        with open(file_path, "rb") as f:
            await update.message.reply_document(document=f, filename=os.path.basename(file_path), caption="📊 Daily Sales Report")
    except FileNotFoundError:
        await update.message.reply_text(messages.DAILY_REPORT_EMPTY)
    except Exception as exc:
        await update.message.reply_text(
            messages.REPORT_DAILY_ERROR.format(error=escape_markdown_v2(str(exc))),
            parse_mode="MarkdownV2",
        )


async def weekly_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        file_path, summary = await context.application.run_in_executor(None, generate_weekly_excel_report)
        await update.message.reply_text(summary, parse_mode="Markdown")
        with open(file_path, "rb") as f:
            await update.message.reply_document(document=f, filename=os.path.basename(file_path), caption="📊 Weekly Sales Report")
    except FileNotFoundError:
        await update.message.reply_text(messages.WEEKLY_REPORT_EMPTY)
    except Exception as exc:
        await update.message.reply_text(
            messages.REPORT_WEEKLY_ERROR.format(error=escape_markdown_v2(str(exc))),
            parse_mode="MarkdownV2",
        )


async def monthly_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        file_path, summary = await context.application.run_in_executor(None, generate_monthly_excel_report)
        await update.message.reply_text(summary, parse_mode="Markdown")
        with open(file_path, "rb") as f:
            await update.message.reply_document(document=f, filename=os.path.basename(file_path), caption="📊 Monthly Sales Report")
    except FileNotFoundError:
        await update.message.reply_text(messages.MONTHLY_REPORT_EMPTY)
    except Exception as exc:
        await update.message.reply_text(
            messages.REPORT_MONTHLY_ERROR.format(error=escape_markdown_v2(str(exc))),
            parse_mode="MarkdownV2",
        )


async def reports_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        file_path, summary = await context.application.run_in_executor(None, generate_daily_excel_report)
        await update.message.reply_text(summary, parse_mode="Markdown")
        with open(file_path, "rb") as f:
            await update.message.reply_document(document=f, filename=os.path.basename(file_path), caption="📊 Daily Sales Report")
    except FileNotFoundError:
        await update.message.reply_text(messages.REPORTS_EMPTY)
    except Exception as exc:
        await update.message.reply_text(messages.REPORT_ERROR.format(error=str(exc)))


def report_handler() -> CommandHandler:
    return CommandHandler("reports", reports_command)
