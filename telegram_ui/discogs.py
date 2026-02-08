from __future__ import annotations

from telegram import Update
from telegram.ext import CommandHandler, ConversationHandler, ContextTypes, MessageHandler, filters

from services.channel_sync_service import reconcile_channel_stock, sync_inventory_item
from services.discogs_service import DiscogsNotConfigured, create_listing, fetch_listing, get_identity
from services.inventory_service import get_inventory_by_id
from services.product_map_service import clear_discogs_listing, find_mapping_by_internal_id, upsert_product_map
from services.store_service import get_default_store, update_store_discogs
from telegram_ui.auth import require_admin, require_auth

ASK_TOKEN = 0


def _discogs_payload(item: dict, *, price: float, condition: str, sleeve_condition: str) -> dict:
    comments = item.get("description") or ""
    return {
        "release_id": int(item.get("discogs_release_id")),
        "condition": condition,
        "sleeve_condition": sleeve_condition,
        "price": f"{price:.2f}",
        "quantity": int(item.get("quantity") or 0),
        "status": "For Sale",
        "comments": comments,
    }


@require_auth
@require_admin
async def connect_discogs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store = get_default_store()
    if not store:
        await update.message.reply_text("❌ No store configured. Run /setup_woo first.")
        return ConversationHandler.END
    await update.message.reply_text("Enter Discogs personal access token:")
    return ASK_TOKEN


@require_auth
@require_admin
async def handle_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store = get_default_store()
    if not store:
        await update.message.reply_text("❌ No store configured. Run /setup_woo first.")
        return ConversationHandler.END
    token = update.message.text.strip()
    temp_store = {"discogs_token": token}
    try:
        identity = get_identity(temp_store)
    except DiscogsNotConfigured:
        await update.message.reply_text("❌ Discogs token missing.")
        return ConversationHandler.END
    except Exception as exc:
        await update.message.reply_text(f"❌ Discogs validation failed: {exc}")
        return ConversationHandler.END

    username = identity.get("username")
    user_id = identity.get("id")
    update_store_discogs(int(store["id"]), discogs_token=token, discogs_username=username, discogs_user_id=user_id)
    await update.message.reply_text(f"✅ Discogs connected for user {username}.")
    return ConversationHandler.END


@require_auth
@require_admin
async def discogs_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store = get_default_store()
    if not store:
        await update.message.reply_text("❌ No store configured. Run /setup_woo first.")
        return
    text = (
        "🎧 Discogs Status\n"
        f"• User: {store.get('discogs_username') or 'not set'}\n"
        f"• Last sync: {store.get('discogs_last_sync_at') or 'never'}\n"
    )
    await update.message.reply_text(text)


@require_auth
@require_admin
async def publish_discogs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store = get_default_store()
    if not store:
        await update.message.reply_text("❌ No store configured. Run /setup_woo first.")
        return
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /publish_discogs <internal_id> [price] [condition] [sleeve_condition]")
        return
    try:
        internal_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Internal ID must be numeric.")
        return

    item = get_inventory_by_id(internal_id)
    if not item:
        await update.message.reply_text("Inventory item not found.")
        return
    if not item.get("discogs_release_id"):
        await update.message.reply_text("Item missing Discogs release ID.")
        return

    price = float(context.args[1]) if len(context.args) > 1 else float(item.get("price_gel") or 0)
    condition = context.args[2] if len(context.args) > 2 else "Mint (M)"
    sleeve_condition = context.args[3] if len(context.args) > 3 else "Generic"

    payload = _discogs_payload(item, price=price, condition=condition, sleeve_condition=sleeve_condition)
    listing = create_listing(store, payload)
    listing_id = listing.get("id")
    if listing_id:
        upsert_product_map(
            store_id=int(store["id"]),
            internal_product_id=internal_id,
            discogs_listing_id=int(listing_id),
            discogs_release_id=int(item.get("discogs_release_id")),
        )
        await update.message.reply_text(f"✅ Discogs listing created: {listing_id}")
        return
    await update.message.reply_text("❌ Discogs listing creation failed.")


@require_auth
@require_admin
async def link_discogs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store = get_default_store()
    if not store:
        await update.message.reply_text("❌ No store configured. Run /setup_woo first.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /link_discogs <listing_id> <internal_id>")
        return
    try:
        listing_id = int(context.args[0])
        internal_id = int(context.args[1])
    except ValueError:
        await update.message.reply_text("IDs must be numeric.")
        return

    listing = fetch_listing(store, listing_id)
    release_id = listing.get("release", {}).get("id")
    upsert_product_map(
        store_id=int(store["id"]),
        internal_product_id=internal_id,
        discogs_listing_id=listing_id,
        discogs_release_id=int(release_id) if release_id else None,
    )
    await update.message.reply_text("✅ Discogs listing linked.")


@require_auth
@require_admin
async def unlink_discogs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store = get_default_store()
    if not store:
        await update.message.reply_text("❌ No store configured. Run /setup_woo first.")
        return
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /unlink_discogs <internal_id>")
        return
    try:
        internal_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Internal ID must be numeric.")
        return
    clear_discogs_listing(int(store["id"]), internal_id)
    await update.message.reply_text("✅ Discogs listing mapping removed.")


@require_auth
@require_admin
async def reconcile_discogs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store = get_default_store()
    if not store:
        await update.message.reply_text("❌ No store configured. Run /setup_woo first.")
        return
    if context.args:
        try:
            internal_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("Internal ID must be numeric.")
            return
        sync_inventory_item(int(store["id"]), internal_id, sync_price=True)
        await update.message.reply_text("✅ Discogs reconciled for item.")
        return
    synced = reconcile_channel_stock(int(store["id"]), channel="discogs")
    await update.message.reply_text(f"✅ Discogs reconciled for {len(synced)} items.")


@require_auth
@require_admin
async def reconcile_woo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store = get_default_store()
    if not store:
        await update.message.reply_text("❌ No store configured. Run /setup_woo first.")
        return
    if context.args:
        try:
            internal_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("Internal ID must be numeric.")
            return
        sync_inventory_item(int(store["id"]), internal_id, sync_price=True)
        await update.message.reply_text("✅ Woo reconciled for item.")
        return
    synced = reconcile_channel_stock(int(store["id"]), channel="woo")
    await update.message.reply_text(f"✅ Woo reconciled for {len(synced)} items.")


@require_auth
@require_admin
async def discogs_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store = get_default_store()
    if not store:
        await update.message.reply_text("❌ No store configured. Run /setup_woo first.")
        return
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /discogs_refresh <internal_id>")
        return
    try:
        internal_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Internal ID must be numeric.")
        return
    mapping = find_mapping_by_internal_id(int(store["id"]), internal_id)
    if not mapping or not mapping.get("discogs_listing_id"):
        await update.message.reply_text("No Discogs listing mapping for this item.")
        return
    listing = fetch_listing(store, int(mapping["discogs_listing_id"]))
    qty = listing.get("quantity")
    await update.message.reply_text(f"Discogs listing quantity: {qty}")


def create_discogs_handlers() -> list:
    setup_handler = ConversationHandler(
        entry_points=[CommandHandler("connect_discogs", connect_discogs)],
        states={ASK_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_token)]},
        fallbacks=[],
        name="connect_discogs",
        persistent=False,
    )
    return [
        setup_handler,
        CommandHandler("discogs_status", discogs_status),
        CommandHandler("publish_discogs", publish_discogs),
        CommandHandler("link_discogs", link_discogs),
        CommandHandler("unlink_discogs", unlink_discogs),
        CommandHandler("reconcile_discogs", reconcile_discogs),
        CommandHandler("reconcile_woo", reconcile_woo),
        CommandHandler("discogs_refresh", discogs_refresh),
    ]
