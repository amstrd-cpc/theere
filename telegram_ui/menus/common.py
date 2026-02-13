from __future__ import annotations

from dataclasses import dataclass

from services.ui_session_service import inject_session
from telegram_ui.callback_contract import build_navigation_callback


@dataclass(frozen=True)
class MenuButton:
    label: str
    callback_data: str
    command: str | None = None


@dataclass(frozen=True)
class MenuDefinition:
    menu_id: str
    title: str
    parent_id: str | None
    buttons: tuple[MenuButton, ...]


def _maybe_scoped(callback_data: str, session_token: str | None) -> str:
    return inject_session(callback_data, session_token) if session_token else callback_data


def menu_button(label: str, target_menu_id: str, *, session_token: str | None = None) -> MenuButton:
    return MenuButton(
        label=label,
        callback_data=_maybe_scoped(build_navigation_callback("menu", target_menu_id), session_token),
    )


def command_button(label: str, target_command: str, *, session_token: str | None = None) -> MenuButton:
    command_key = target_command.strip().lstrip("/")
    return MenuButton(
        label=label,
        callback_data=_maybe_scoped(build_navigation_callback("command", command_key), session_token),
        command=target_command,
    )


def back_button(current_menu_id: str, *, session_token: str | None = None) -> MenuButton:
    return MenuButton(
        label="⬅️ Back",
        callback_data=_maybe_scoped(build_navigation_callback("back", current_menu_id), session_token),
    )


def home_button(*, session_token: str | None = None) -> MenuButton:
    return MenuButton(
        label="🏠 Home",
        callback_data=_maybe_scoped(build_navigation_callback("menu", "main"), session_token),
    )
