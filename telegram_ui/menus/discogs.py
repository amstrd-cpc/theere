from telegram_ui.menus.common import MenuDefinition, command_button

MENU = MenuDefinition(
    menu_id="discogs",
    title="Discogs",
    parent_id="main",
    buttons=(
        command_button("🔌 Connect Discogs", "/connect_discogs"),
        command_button("📊 Discogs Status", "/discogs_status"),
        command_button("📥 Collect Discogs", "/collect_discogs"),
        command_button("📥 Collect Selection", "/collect_discogs_selection"),
        command_button("🔗 Link Discogs", "/link_discogs"),
        command_button("🔓 Unlink Discogs", "/unlink_discogs"),
        command_button("📤 Publish Discogs", "/publish_discogs"),
        command_button("📤 Publish All", "/publish_discogs_all"),
        command_button("📤 Publish Selection", "/publish_discogs_selection"),
        command_button("📝 Update Listing", "/update_discogs_listing"),
        command_button("🛑 Unlist", "/unlist_discogs"),
        command_button("♻️ Relist", "/relist_discogs"),
        command_button("🗑️ Remove Listing", "/remove_discogs_listing"),
    ),
)
