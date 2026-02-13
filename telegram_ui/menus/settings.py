from telegram_ui.menus.common import MenuDefinition, command_button

MENU = MenuDefinition(
    menu_id="settings",
    title="Settings",
    parent_id="main",
    buttons=(
        command_button("⚙️ Settings", "/settings"),
        command_button("🔐 Login", "/login"),
        command_button("🚪 Logout", "/logout"),
        command_button("📡 Status", "/status"),
        command_button("❓ Help", "/help"),
    ),
)
