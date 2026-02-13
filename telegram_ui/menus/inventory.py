from telegram_ui.menus.common import MenuDefinition, command_button

MENU = MenuDefinition(
    menu_id="inventory",
    title="Inventory",
    parent_id="main",
    buttons=(
        command_button("📦 View Inventory", "/inventory"),
        command_button("📉 Low Stock", "/stock"),
        command_button("➕ Add Record", "/add"),
    ),
)
