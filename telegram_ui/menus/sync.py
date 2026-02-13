from telegram_ui.menus.common import MenuDefinition, command_button

MENU = MenuDefinition(
    menu_id="sync",
    title="Sync",
    parent_id="main",
    buttons=(
        command_button("🔄 Sync Status", "/sync_status"),
        command_button("💾 Backups", "/backups"),
        command_button("🧮 Reconcile Discogs", "/reconcile_discogs"),
        command_button("🧮 Reconcile Woo", "/reconcile_woo"),
        command_button("🪄 Discogs Refresh", "/discogs_refresh"),
        command_button("🚀 Sync Discogs All", "/sync_discogs_all"),
    ),
)
