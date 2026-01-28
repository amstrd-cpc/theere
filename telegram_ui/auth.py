from __future__ import annotations

from datetime import datetime
from telegram import Update
from telegram.ext import CommandHandler, ConversationHandler, ContextTypes, MessageHandler, filters

from config.settings import load_settings
from services.auth_service import AuthManager
from services.runtime import run_blocking
from telegram_ui import messages

settings = load_settings()
auth_manager = AuthManager(settings.bot_password, settings.session_timeout_hours)

WAITING_FOR_PASSWORD = 0


def require_auth(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if not await run_blocking(auth_manager.is_authenticated, user_id):
            await update.message.reply_text(messages.AUTH_REQUIRED)
            return
        return await func(update, context, *args, **kwargs)

    return wrapper


async def start_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if await run_blocking(auth_manager.is_authenticated, user_id):
        expiry = auth_manager.authenticated_users[user_id]
        time_left = expiry - datetime.now()
        await update.message.reply_text(messages.LOGIN_ALREADY.format(time_left=time_left))
        return ConversationHandler.END

    await update.message.reply_text(messages.LOGIN_PROMPT, parse_mode="Markdown")
    return WAITING_FOR_PASSWORD


async def handle_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text.strip()
    user = update.effective_user
    try:
        await update.message.delete()
    except Exception:
        pass

    if auth_manager.verify_password(password):
        await run_blocking(auth_manager.authenticate_user, user.id, user.username, user.first_name)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=messages.LOGIN_SUCCESS.format(first_name=user.first_name, hours=settings.session_timeout_hours),
            parse_mode="Markdown",
        )
    else:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=messages.LOGIN_FAILURE,
            parse_mode="Markdown",
        )
    return ConversationHandler.END


async def logout_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if await run_blocking(auth_manager.is_authenticated, user_id):
        await run_blocking(auth_manager.logout_user, user_id)
        await update.message.reply_text(messages.LOGOUT_SUCCESS, parse_mode="Markdown")
    else:
        await update.message.reply_text(messages.LOGOUT_ALREADY)


async def show_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if await run_blocking(auth_manager.is_authenticated, user_id):
        expiry = auth_manager.authenticated_users[user_id]
        time_left = expiry - datetime.now()
        await update.message.reply_text(messages.STATUS_ACTIVE.format(time_left=time_left), parse_mode="Markdown")
    else:
        await update.message.reply_text(messages.STATUS_INACTIVE, parse_mode="Markdown")


async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await run_blocking(auth_manager.is_authenticated, user_id):
        await update.message.reply_text(messages.ADMIN_AUTH_REQUIRED)
        return

    active_users = await run_blocking(auth_manager.get_active_users)
    if not active_users:
        await update.message.reply_text(messages.ADMIN_USERS_EMPTY)
        return

    text = messages.ADMIN_USERS_HEADER
    for session in active_users:
        username_str = f"@{session.username}" if session.username else "No username"
        text += (
            f"• {session.first_name} ({username_str})\n"
            f"  ID: {session.user_id}\n"
            f"  Last active: {session.last_activity}\n\n"
        )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cancel_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(messages.CANCEL_LOGIN)
    return ConversationHandler.END


def create_auth_handlers():
    login_handler = ConversationHandler(
        entry_points=[CommandHandler("login", start_login)],
        states={
            WAITING_FOR_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_password)]
        },
        fallbacks=[CommandHandler("cancel", cancel_login)],
        name="login",
        persistent=False,
    )

    return [
        login_handler,
        CommandHandler("logout", logout_user),
        CommandHandler("status", show_status),
        CommandHandler("users", admin_users),
    ]


async def check_auth_middleware(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if update.message and update.message.text:
        command = update.message.text.split()[0].lower()
        if command in ["/login", "/start", "/help"]:
            return True
    if not await run_blocking(auth_manager.is_authenticated, user_id):
        await update.message.reply_text(messages.AUTH_REQUIRED_MARKDOWN, parse_mode="Markdown")
        return False
    return True
