from telegram_ui.menus.common import MenuDefinition, command_button

MENU = MenuDefinition(
    menu_id="admin",
    title="Admin",
    parent_id="main",
    buttons=(
        command_button("👥 Users", "/users"),
    ),
)
