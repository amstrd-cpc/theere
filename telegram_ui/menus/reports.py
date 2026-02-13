from telegram_ui.menus.common import MenuDefinition, command_button

MENU = MenuDefinition(
    menu_id="reports",
    title="Reports",
    parent_id="main",
    buttons=(
        command_button("📈 Reports Home", "/reports"),
        command_button("📆 Daily", "/daily"),
        command_button("🗓️ Weekly", "/weekly"),
        command_button("🗓️ Monthly", "/monthly"),
    ),
)
