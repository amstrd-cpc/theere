from __future__ import annotations

import logging
from telegram import Update
from telegram.ext import ContextTypes

from services.sales_service import get_recent_sales
from services.runtime import run_blocking
from telegram_ui import messages
from telegram_ui.keyboards import build_main_menu
from telegram_ui.menus import build_inline_menu
from telegram_ui.utils import escape_markdown_v2
from telegram_ui.auth import auth_manager

logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = messages.START_MESSAGE.format(first_name=escape_markdown_v2(user.first_name))
    is_authed = await run_blocking(auth_manager.is_authenticated, user.id)
    if is_authed:
        prompt, menu_markup = build_inline_menu("main")
        await update.message.reply_text(message, parse_mode="MarkdownV2")
        await update.message.reply_text(prompt, reply_markup=menu_markup)
    else:
        await update.message.reply_text(
            message,
            parse_mode="MarkdownV2",
            reply_markup=build_main_menu(is_authed),
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_authed = await run_blocking(auth_manager.is_authenticated, user_id)
    if is_authed:
        help_text = messages.HELP_AUTHENTICATED
    else:
        help_text = messages.HELP_UNAUTHENTICATED
    await update.message.reply_text(
        help_text,
        parse_mode="MarkdownV2",
        reply_markup=build_main_menu(is_authed),
    )


async def recent_sales(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sales = await run_blocking(get_recent_sales, 10)
    if not sales:
        await update.message.reply_text(messages.RECENT_SALES_EMPTY, parse_mode="MarkdownV2")
        return

    message = "💰 *Recent Sales*\n\n"
    for sale in sales:
        safe_artist_album = escape_markdown_v2(str(sale["artist_album"]))
        safe_payment_method = escape_markdown_v2(str(sale["payment_method"]))
        safe_date = escape_markdown_v2(str(sale["date"]))
        price = sale["price_gel"]
        message += (
            f"🎵 {safe_artist_album}\n"
            f"💰 ₾{price:.2f} \\({safe_payment_method}\\)\n"
            f"📅 {safe_date}\n\n"
        )

    await update.message.reply_text(message, parse_mode="MarkdownV2")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception while handling an update:", exc_info=context.error)
