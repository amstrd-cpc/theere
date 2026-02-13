from telegram_ui.menus.common import MenuDefinition, command_button

MENU = MenuDefinition(
    menu_id="woo",
    title="WooCommerce",
    parent_id="main",
    buttons=(
        command_button("🔌 Connect Woo", "/connect"),
        command_button("🧰 Setup Woo", "/setup_woo"),
        command_button("🛠️ Repair Webhooks", "/repair_webhooks"),
        command_button("🧩 Map Products", "/map_woo"),
        command_button("🤖 Auto Map", "/auto_map_woo"),
        command_button("📦 Import Woo Products", "/import_woo"),
        command_button("🧾 Import Summary", "/woo_import_summary"),
        command_button("🏪 Integrations: Woo", "/integrations_woo"),
    ),
)
