from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from telegram_ui import auth, integrations


class _Queue:
    def __init__(self, count: int) -> None:
        self.count = count


def test_queue_length_returns_unavailable_on_failure(monkeypatch):
    monkeypatch.setattr(
        integrations,
        "get_queue",
        lambda: (_ for _ in ()).throw(RuntimeError("no redis")),
    )
    assert integrations._queue_length() == "unavailable"


@pytest.mark.asyncio
async def test_sync_status_includes_live_queue(monkeypatch):
    monkeypatch.setattr(integrations, "get_default_store", lambda: {"id": 1})
    monkeypatch.setattr(integrations, "_latest_sync_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        integrations, "_latest_tri_sync_run", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        integrations, "_latest_woo_import_run", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(integrations, "_queue_length", lambda: "7")

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, *args, **kwargs):
            class _Cur:
                def fetchone(self):
                    return {
                        "last_applied": None,
                        "last_received": None,
                        "last_processed": None,
                    }

            return _Cur()

    monkeypatch.setattr(integrations, "get_inventory_db", lambda: _Conn())

    async def _allow(*args, **kwargs):
        return True

    monkeypatch.setattr(auth, "run_blocking", _allow)

    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(message=message, effective_user=SimpleNamespace(id=1))
    context = SimpleNamespace()
    await integrations.sync_status(update, context)

    sent_text = message.reply_text.await_args.args[0]
    assert "Queue length: 7" in sent_text
