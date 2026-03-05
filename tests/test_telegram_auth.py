from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from telegram_ui import auth


@pytest.mark.asyncio
async def test_reply_via_available_channel_prefers_message_reply():
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(message=message, callback_query=None, effective_chat=None)
    context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))

    await auth.reply_via_available_channel(update, context, "hello")

    message.reply_text.assert_awaited_once_with("hello")
    context.bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_reply_via_available_channel_uses_callback_message_when_no_message():
    callback_message = SimpleNamespace(reply_text=AsyncMock(), edit_text=AsyncMock())
    callback_query = SimpleNamespace(answer=AsyncMock(), message=callback_message)
    update = SimpleNamespace(
        message=None, callback_query=callback_query, effective_chat=None
    )
    context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))

    await auth.reply_via_available_channel(update, context, "hello")

    callback_query.answer.assert_awaited_once()
    callback_message.reply_text.assert_awaited_once_with("hello")
