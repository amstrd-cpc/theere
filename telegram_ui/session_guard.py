from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from services.runtime import run_blocking
from services.ui_session_service import extract_session, validate_callback_session

logger = logging.getLogger(__name__)

STALE_SESSION_MESSAGE = "⚠️ This button is no longer valid. Please open the menu again."


async def validate_callback_or_reject(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    expected_node: str,
    expected_state: str | None = None,
) -> tuple[bool, str]:
    query = update.callback_query
    if not query or not query.data:
        return False, "missing_callback"

    user_id = query.from_user.id if query.from_user else 0
    session_token, normalized_data = extract_session(query.data)
    valid, reason = await run_blocking(
        validate_callback_session,
        session_token=session_token,
        user_id=user_id,
        expected_node=expected_node,
        expected_state=expected_state,
    )
    if not valid:
        correlation_id = f"cbq:{query.id}" if query.id else f"upd:{update.update_id}"
        logger.info(
            "Rejected callback session reason=%s node=%s state=%s correlation_id=%s",
            reason,
            expected_node,
            expected_state or "",
            correlation_id,
        )
        try:
            await query.answer("This menu has expired", show_alert=False)
        except Exception:
            pass
        await update.effective_message.reply_text(STALE_SESSION_MESSAGE)
        return False, normalized_data

    query.data = normalized_data
    return True, normalized_data
