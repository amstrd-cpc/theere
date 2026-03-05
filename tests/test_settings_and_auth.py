from __future__ import annotations

import importlib

import pytest

from services.auth_service import AuthManager


def test_load_settings_rejects_missing_bot_password(monkeypatch):
    monkeypatch.delenv("BOT_PASSWORD", raising=False)
    settings = importlib.import_module("config.settings")
    with pytest.raises(ValueError):
        settings.load_settings()


def test_auth_password_verify_accepts_correct_and_rejects_incorrect():
    manager = AuthManager("StrongPass123!", 1)
    assert manager.verify_password("StrongPass123!") is True
    assert manager.verify_password("WrongPass123!") is False
