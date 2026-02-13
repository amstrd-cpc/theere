from telegram_ui.menus.common import MenuDefinition, command_button

MENU = MenuDefinition(
    menu_id="sales",
    title="Sales",
    parent_id="main",
    buttons=(
        command_button("💸 Sell", "/sell"),
        command_button("🧾 Recent Sales", "/sales"),
        command_button("📬 Orders", "/orders"),
    ),
)
