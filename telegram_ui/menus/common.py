from __future__ import annotations

from dataclasses import dataclass

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


def menu_button(label: str, target_menu_id: str) -> MenuButton:
    return MenuButton(label=label, callback_data=build_navigation_callback("menu", target_menu_id))


def command_button(label: str, target_command: str) -> MenuButton:
    command_key = target_command.strip().lstrip("/")
    return MenuButton(
        label=label,
        callback_data=build_navigation_callback("command", command_key),
        command=target_command,
    )


def back_button(current_menu_id: str) -> MenuButton:
    return MenuButton(label="⬅️ Back", callback_data=build_navigation_callback("back", current_menu_id))


def home_button() -> MenuButton:
    return MenuButton(label="🏠 Home", callback_data=build_navigation_callback("menu", "main"))
