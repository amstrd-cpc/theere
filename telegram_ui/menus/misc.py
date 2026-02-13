from telegram_ui.menus.common import MenuDefinition, command_button

MENU = MenuDefinition(
    menu_id="misc",
    title="Misc",
    parent_id="main",
    buttons=(
        command_button("🧯 Cancel Current Flow", "/cancel"),
        command_button("🩺 Diagnostics Status", "/status"),
        command_button("🔁 Sync Diagnostics", "/sync_status"),
        command_button("🧰 Bootstrap /start", "/start"),
        command_button("🧹 Maintenance Backups", "/backups"),
        command_button("🛠️ Maintenance Repair Webhooks", "/repair_webhooks"),
        command_button("🏪 Integrations: Discogs", "/integrations_discogs"),
    ),
)
