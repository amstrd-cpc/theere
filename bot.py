#!/usr/bin/env python3
from __future__ import annotations

import datetime
import logging

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, JobQueue, MessageHandler, filters

from config.settings import load_settings
from db import init_db
from jobs.discogs_jobs import reconcile_discogs_inventory
from jobs.woo_jobs import sync_inventory_to_woo
from services.backup_service import run_backup
from services.sync_engine import SyncEngine
from services.runtime import run_blocking
from services.store_service import get_default_store
from telegram_ui.add import orphan_supplier_callback, start_add_flow
from telegram_ui.auth import check_auth_middleware, create_auth_handlers
from telegram_ui.core import error_handler, help_command, recent_sales, start
from telegram_ui.discogs import create_discogs_handlers
from telegram_ui.inventory import create_inventory_conversation, low_stock, register_inventory_callbacks
from telegram_ui.integrations import create_integrations_handlers
from telegram_ui.menu import create_menu_handler
from telegram_ui.orders import create_orders_callback_handler, create_orders_handler
from telegram_ui.product_mapping import create_auto_map_handler, create_map_handler
from telegram_ui.reports import daily_report, monthly_report, report_handler, weekly_report
from telegram_ui.sales import start_sell_flow
from telegram_ui.store_settings import create_settings_handler
from telegram_ui.woo_setup import create_repair_handler, create_setup_handler

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

settings = load_settings()


async def unauthorized_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth_middleware(update, context):
        return


async def sync_inventory_job(context: ContextTypes.DEFAULT_TYPE):
    await sync_inventory_to_woo()


async def periodic_sync_job(context: ContextTypes.DEFAULT_TYPE):
    store = await run_blocking(get_default_store)
    if not store:
        return
    await run_blocking(SyncEngine().run_periodic_sync, int(store["id"]))


async def discogs_reconcile_job(context: ContextTypes.DEFAULT_TYPE):
    await run_blocking(reconcile_discogs_inventory)


async def rolling_backup_job(context: ContextTypes.DEFAULT_TYPE):
    await run_blocking(run_backup, "rolling")


async def daily_backup_job(context: ContextTypes.DEFAULT_TYPE):
    await run_blocking(run_backup, "daily")


def main() -> None:
    init_db()

    application = Application.builder().token(settings.bot_token).job_queue(JobQueue()).build()

    if application.job_queue:
        application.job_queue.run_repeating(
            periodic_sync_job,
            interval=datetime.timedelta(minutes=5),
            first=datetime.timedelta(minutes=2),
            name="woo-periodic-sync",
        )
        application.job_queue.run_repeating(
            discogs_reconcile_job,
            interval=datetime.timedelta(minutes=5),
            first=datetime.timedelta(minutes=3),
            name="discogs-collection-sync",
        )
        application.job_queue.run_repeating(
            rolling_backup_job,
            interval=datetime.timedelta(minutes=15),
            first=datetime.timedelta(minutes=1),
            name="db-backup-rolling",
        )
        application.job_queue.run_repeating(
            daily_backup_job,
            interval=datetime.timedelta(days=1),
            first=datetime.timedelta(minutes=10),
            name="db-backup-daily",
        )
    else:
        logger.warning("JobQueue unavailable; install python-telegram-bot[job-queue] to enable Woo polling.")

    for handler in create_auth_handlers():
        application.add_handler(handler)

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(report_handler())

    application.add_handler(CommandHandler("sales", recent_sales))
    application.add_handler(CommandHandler("daily", daily_report))
    application.add_handler(CommandHandler("weekly", weekly_report))
    application.add_handler(CommandHandler("monthly", monthly_report))
    application.add_handler(CommandHandler("stock", low_stock))
    application.add_handler(create_setup_handler())
    application.add_handler(create_repair_handler())
    application.add_handler(create_settings_handler())
    application.add_handler(create_orders_handler())
    application.add_handler(create_orders_callback_handler())
    application.add_handler(create_map_handler())
    application.add_handler(create_auto_map_handler())
    for handler in create_discogs_handlers():
        application.add_handler(handler)
    for handler in create_integrations_handlers():
        application.add_handler(handler)

    application.add_handler(start_add_flow())
    application.add_handler(CallbackQueryHandler(orphan_supplier_callback, pattern=r"^add:supplier:"), group=1)
    application.add_handler(start_sell_flow())
    application.add_handler(create_inventory_conversation())
    register_inventory_callbacks(application)

    application.add_handler(create_menu_handler())
    application.add_handler(MessageHandler(filters.ALL, unauthorized_handler))
    application.add_error_handler(error_handler)

    logger.info("🤖 Starting protected record store bot...")
    logger.info("🔒 Session timeout: %s hours", settings.session_timeout_hours)

    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
