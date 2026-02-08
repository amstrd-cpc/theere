from __future__ import annotations

import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ConversationHandler, ContextTypes, MessageHandler, filters

from services.channel_sync_service import reconcile_channel_stock, sync_inventory_item
from services.discogs_service import DiscogsNotConfigured, create_listing, fetch_listing, get_identity
from services.inventory_service import get_inventory_by_id, search_inventory
from services.product_map_service import clear_discogs_listing, find_mapping_by_internal_id, upsert_product_map
from services.runtime import run_blocking
from services.store_service import get_default_store, update_store_discogs
from telegram_ui.auth import require_admin, require_auth

ASK_TOKEN = 0
SEARCHING, SELECTING, CONFIRMING, EXTRA_INPUT = range(1, 5)

DISCogs_ACTIONS = {
    "publish_discogs": "Publish to Discogs",
    "link_discogs": "Link Discogs listing",
    "unlink_discogs": "Unlink Discogs listing",
    "reconcile_discogs": "Reconcile Discogs",
    "reconcile_woo": "Reconcile Woo",
    "discogs_refresh": "Refresh Discogs quantity",
}


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


def _build_search_keyboard(items: list[dict], action: str) -> InlineKeyboardMarkup:
    buttons = []
    for item in items:
        text = f"{item.get('artist_album', 'Item')} (Qty: {item.get('quantity', 0)})"
        if len(text) > 60:
            text = text[:57] + "..."
        buttons.append([InlineKeyboardButton(text, callback_data=f"discogs_select:{action}:{item['id']}")])
    return InlineKeyboardMarkup(buttons)


def _build_confirm_keyboard(action: str, item_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton("✅ Confirm", callback_data=f"discogs_confirm:{action}:{item_id}:yes"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"discogs_confirm:{action}:{item_id}:no"),
        ]
    ]
    return InlineKeyboardMarkup(buttons)


def _extract_listing_id(value: str) -> int | None:
    match = re.search(r"(\d+)", value)
    if not match:
        return None
    return int(match.group(1))


def _format_item_summary(item: dict) -> str:
    artist_album = item.get("artist_album", "Unknown")
    condition = item.get("condition", "N/A")
    price = float(item.get("price_gel") or 0)
    quantity = item.get("quantity", 0)
    return (
        f"🎵 {artist_album}\n"
        f"🎚 Condition: {condition}\n"
        f"💰 Price: ₾{price:.2f}\n"
        f"📦 Stock: {quantity}"
    )


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
    await update.message.reply_text("Tell me the artist or album name to publish on Discogs:")
    context.user_data["discogs_action"] = "publish_discogs"
    return SEARCHING


@require_auth
@require_admin
async def link_discogs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store = get_default_store()
    if not store:
        await update.message.reply_text("❌ No store configured. Run /setup_woo first.")
        return
    await update.message.reply_text("Tell me the artist or album name you want to link to a Discogs listing:")
    context.user_data["discogs_action"] = "link_discogs"
    return SEARCHING


@require_auth
@require_admin
async def unlink_discogs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store = get_default_store()
    if not store:
        await update.message.reply_text("❌ No store configured. Run /setup_woo first.")
        return
    await update.message.reply_text("Tell me the artist or album name you want to unlink from Discogs:")
    context.user_data["discogs_action"] = "unlink_discogs"
    return SEARCHING


@require_auth
@require_admin
async def reconcile_discogs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store = get_default_store()
    if not store:
        await update.message.reply_text("❌ No store configured. Run /setup_woo first.")
        return
    if context.args:
        await update.message.reply_text("I'll reconcile by name instead. Please send the item name:")
        context.user_data["discogs_action"] = "reconcile_discogs"
        return SEARCHING
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
        await update.message.reply_text("I'll reconcile by name instead. Please send the item name:")
        context.user_data["discogs_action"] = "reconcile_woo"
        return SEARCHING
    synced = reconcile_channel_stock(int(store["id"]), channel="woo")
    await update.message.reply_text(f"✅ Woo reconciled for {len(synced)} items.")


@require_auth
@require_admin
async def discogs_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store = get_default_store()
    if not store:
        await update.message.reply_text("❌ No store configured. Run /setup_woo first.")
        return
    await update.message.reply_text("Tell me the artist or album name to refresh Discogs quantity:")
    context.user_data["discogs_action"] = "discogs_refresh"
    return SEARCHING


@require_auth
@require_admin
async def handle_discogs_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = (update.message.text or "").strip()
    action = context.user_data.get("discogs_action")
    if not query or not action:
        await update.message.reply_text("Please enter a valid name to search.")
        return SEARCHING

    items = await run_blocking(search_inventory, query)
    if not items:
        await update.message.reply_text(f"❌ No matches found for '{query}'. Try another name.")
        return SEARCHING

    label = DISCogs_ACTIONS.get(action, "Select an item")
    message = f"{label}\n\nFound {len(items)} match(es). Tap the correct item:"
    await update.message.reply_text(message, reply_markup=_build_search_keyboard(items, action))
    return SELECTING


@require_auth
@require_admin
async def handle_discogs_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    _, action, item_id = data.split(":", 2)
    item = await run_blocking(get_inventory_by_id, int(item_id))
    if not item:
        await query.edit_message_text("Item not found. Please try again.")
        return ConversationHandler.END

    context.user_data["discogs_action"] = action
    context.user_data["discogs_item_id"] = int(item_id)

    if action == "link_discogs":
        await query.edit_message_text(
            f"{_format_item_summary(item)}\n\nPaste the Discogs listing URL or ID to link:",
        )
        return EXTRA_INPUT

    confirm_text = f"{_format_item_summary(item)}\n\nProceed with: {DISCogs_ACTIONS.get(action, action)}?"
    await query.edit_message_text(confirm_text, reply_markup=_build_confirm_keyboard(action, int(item_id)))
    return CONFIRMING


@require_auth
@require_admin
async def handle_discogs_extra(update: Update, context: ContextTypes.DEFAULT_TYPE):
    action = context.user_data.get("discogs_action")
    item_id = context.user_data.get("discogs_item_id")
    if action != "link_discogs" or not item_id:
        await update.message.reply_text("Please start again with the command.")
        return ConversationHandler.END

    listing_id = _extract_listing_id(update.message.text or "")
    if not listing_id:
        await update.message.reply_text("Please paste a valid Discogs listing URL or ID.")
        return EXTRA_INPUT

    context.user_data["discogs_listing_id"] = listing_id
    item = await run_blocking(get_inventory_by_id, int(item_id))
    if not item:
        await update.message.reply_text("Item not found. Please start again.")
        return ConversationHandler.END

    confirm_text = (
        f"{_format_item_summary(item)}\n"
        f"🔗 Listing ID: {listing_id}\n\n"
        "Confirm linking this listing?"
    )
    await update.message.reply_text(
        confirm_text,
        reply_markup=_build_confirm_keyboard(action, int(item_id)),
    )
    return CONFIRMING


@require_auth
@require_admin
async def handle_discogs_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    _, action, item_id, decision = data.split(":", 3)
    if decision != "yes":
        await query.edit_message_text("❌ Cancelled.")
        return ConversationHandler.END

    store = get_default_store()
    if not store:
        await query.edit_message_text("❌ No store configured. Run /setup_woo first.")
        return ConversationHandler.END

    item = await run_blocking(get_inventory_by_id, int(item_id))
    if not item:
        await query.edit_message_text("Item not found.")
        return ConversationHandler.END

    if action == "publish_discogs":
        if not item.get("discogs_release_id"):
            await query.edit_message_text("Item missing Discogs release ID.")
            return ConversationHandler.END
        price = float(item.get("price_gel") or 0)
        condition = item.get("condition") or "Mint (M)"
        payload = _discogs_payload(item, price=price, condition=condition, sleeve_condition="Generic")
        listing = create_listing(store, payload)
        listing_id = listing.get("id")
        if listing_id:
            upsert_product_map(
                store_id=int(store["id"]),
                internal_product_id=int(item_id),
                discogs_listing_id=int(listing_id),
                discogs_release_id=int(item.get("discogs_release_id")),
            )
            await query.edit_message_text(f"✅ Discogs listing created: {listing_id}")
            return ConversationHandler.END
        await query.edit_message_text("❌ Discogs listing creation failed.")
        return ConversationHandler.END

    if action == "link_discogs":
        listing_id = context.user_data.get("discogs_listing_id")
        if not listing_id:
            await query.edit_message_text("Missing listing ID. Please start again.")
            return ConversationHandler.END
        listing = fetch_listing(store, int(listing_id))
        release_id = listing.get("release", {}).get("id")
        upsert_product_map(
            store_id=int(store["id"]),
            internal_product_id=int(item_id),
            discogs_listing_id=int(listing_id),
            discogs_release_id=int(release_id) if release_id else None,
        )
        await query.edit_message_text("✅ Discogs listing linked.")
        return ConversationHandler.END

    if action == "unlink_discogs":
        clear_discogs_listing(int(store["id"]), int(item_id))
        await query.edit_message_text("✅ Discogs listing mapping removed.")
        return ConversationHandler.END

    if action == "reconcile_discogs":
        sync_inventory_item(int(store["id"]), int(item_id), sync_price=True)
        await query.edit_message_text("✅ Discogs reconciled for item.")
        return ConversationHandler.END

    if action == "reconcile_woo":
        sync_inventory_item(int(store["id"]), int(item_id), sync_price=True)
        await query.edit_message_text("✅ Woo reconciled for item.")
        return ConversationHandler.END

    if action == "discogs_refresh":
        mapping = find_mapping_by_internal_id(int(store["id"]), int(item_id))
        if not mapping or not mapping.get("discogs_listing_id"):
            await query.edit_message_text("No Discogs listing mapping for this item.")
            return ConversationHandler.END
        listing = fetch_listing(store, int(mapping["discogs_listing_id"]))
        qty = listing.get("quantity")
        await query.edit_message_text(f"Discogs listing quantity: {qty}")
        return ConversationHandler.END

    await query.edit_message_text("Unsupported action.")
    return ConversationHandler.END


async def cancel_discogs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text("❌ Discogs action cancelled.")
    return ConversationHandler.END


def create_discogs_handlers() -> list:
    setup_handler = ConversationHandler(
        entry_points=[CommandHandler("connect_discogs", connect_discogs)],
        states={ASK_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_token)]},
        fallbacks=[CommandHandler("cancel", cancel_discogs)],
        name="connect_discogs",
        persistent=False,
    )
    discogs_action_handler = ConversationHandler(
        entry_points=[
            CommandHandler("publish_discogs", publish_discogs),
            CommandHandler("link_discogs", link_discogs),
            CommandHandler("unlink_discogs", unlink_discogs),
            CommandHandler("reconcile_discogs", reconcile_discogs),
            CommandHandler("reconcile_woo", reconcile_woo),
            CommandHandler("discogs_refresh", discogs_refresh),
        ],
        states={
            SEARCHING: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_discogs_search)],
            SELECTING: [CallbackQueryHandler(handle_discogs_select, pattern=r"^discogs_select:")],
            EXTRA_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_discogs_extra)],
            CONFIRMING: [CallbackQueryHandler(handle_discogs_confirm, pattern=r"^discogs_confirm:")],
        },
        fallbacks=[CommandHandler("cancel", cancel_discogs)],
        name="discogs_actions",
        persistent=False,
    )
    return [
        setup_handler,
        CommandHandler("discogs_status", discogs_status),
        discogs_action_handler,
    ]
