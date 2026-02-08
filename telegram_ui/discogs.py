from __future__ import annotations

import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ConversationHandler, ContextTypes, MessageHandler, filters

from services.channel_sync_service import reconcile_channel_stock, sync_inventory_item
from services.discogs_sync_service import sync_all_discogs
from services.discogs_service import DiscogsNotConfigured, add_to_collection, create_listing, fetch_listing, get_identity
from services.inventory_service import get_inventory_by_id, search_inventory, update_inventory_fields
from services.product_map_service import clear_discogs_listing, find_mapping_by_internal_id, upsert_product_map
from services.runtime import run_blocking
from services.store_service import get_default_store, update_store_discogs
from telegram_ui.auth import require_admin, require_auth

ASK_TOKEN = 0
SEARCHING, SELECTING, CONFIRMING, EXTRA_INPUT, BULK_SELECTING, FIELD_INPUT, BULK_INPUT, SYNCING = range(1, 9)

DISCogs_ACTIONS = {
    "publish_discogs": "Publish to Discogs",
    "publish_discogs_all": "Publish all to Discogs",
    "publish_discogs_selection": "Publish selection to Discogs",
    "publish_discogs_bulk": "Publish selected to Discogs",
    "collect_discogs": "Add to Discogs collection",
    "collect_discogs_selection": "Add selection to Discogs collection",
    "collect_discogs_bulk": "Add selected to Discogs collection",
    "link_discogs": "Link Discogs listing",
    "unlink_discogs": "Unlink Discogs listing",
    "reconcile_discogs": "Reconcile Discogs",
    "reconcile_woo": "Reconcile Woo",
    "discogs_refresh": "Refresh Discogs quantity",
    "sync_discogs_all": "Sync all to Discogs",
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


def _bulk_done_label(action: str) -> str:
    if action.startswith("collect_discogs"):
        return "🎶 Add selected to collection"
    return "📦 Publish selected"


def _build_bulk_select_keyboard(items: list[dict], selected: set[int], *, action: str) -> InlineKeyboardMarkup:
    buttons = []
    for item in items:
        item_id = int(item["id"])
        prefix = "✅ " if item_id in selected else ""
        text = f"{prefix}{item.get('artist_album', 'Item')}"
        if len(text) > 60:
            text = text[:57] + "..."
        buttons.append([InlineKeyboardButton(text, callback_data=f"discogs_bulk_toggle:{item_id}")])
    buttons.append(
        [
            InlineKeyboardButton(_bulk_done_label(action), callback_data="discogs_bulk_done"),
            InlineKeyboardButton("❌ Cancel", callback_data="discogs_bulk_cancel"),
        ]
    )
    return InlineKeyboardMarkup(buttons)


def _build_bulk_skip_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("⏭️ Skip item", callback_data="discogs_bulk_skip"),
                InlineKeyboardButton("❌ Cancel bulk", callback_data="discogs_bulk_cancel"),
            ]
        ]
    )


def _build_sync_all_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🎶 Sync collection only", callback_data="discogs_sync_all:collection"),
                InlineKeyboardButton("📦 Sync + publish listings", callback_data="discogs_sync_all:publish"),
            ],
            [InlineKeyboardButton("❌ Cancel", callback_data="discogs_sync_all:cancel")],
        ]
    )


def _extract_listing_id(value: str) -> int | None:
    match = re.search(r"(\d+)", value)
    if not match:
        return None
    return int(match.group(1))


def _format_item_summary(item: dict) -> str:
    artist_album = item.get("artist_album", "Unknown")
    condition = item.get("condition", "N/A")
    sleeve_condition = item.get("sleeve_condition", "N/A")
    price = float(item.get("price_gel") or 0)
    quantity = item.get("quantity", 0)
    return (
        f"🎵 {artist_album}\n"
        f"🎚 Condition: {condition}\n"
        f"📀 Sleeve: {sleeve_condition}\n"
        f"💰 Price: ₾{price:.2f}\n"
        f"📦 Stock: {quantity}"
    )


def _discogs_missing_fields(item: dict, *, action: str) -> list[str]:
    missing = []
    if not item.get("discogs_release_id"):
        missing.append("discogs_release_id")
        return missing
    if action.startswith("collect_discogs"):
        return missing
    if not (item.get("condition") or "").strip():
        missing.append("condition")
    if not (item.get("sleeve_condition") or "").strip():
        missing.append("sleeve_condition")
    if float(item.get("price_gel") or 0) <= 0:
        missing.append("price_gel")
    if not (item.get("description") or "").strip():
        missing.append("description")
    return missing


def _discogs_field_prompt(field: str, item: dict) -> str:
    artist_album = item.get("artist_album", "item")
    if field == "discogs_release_id":
        return f"Enter Discogs release ID for {artist_album}:"
    if field == "condition":
        return f"Enter media condition for {artist_album} (e.g., Mint (M), VG+):"
    if field == "sleeve_condition":
        return f"Enter sleeve condition for {artist_album} (e.g., Generic, VG+):"
    if field == "price_gel":
        return f"Enter price in GEL for {artist_album}:"
    if field == "description":
        return f"Enter listing comments for {artist_album}:"
    return "Enter value:"


def _parse_field_value(field: str, value: str) -> tuple[bool, dict]:
    value = value.strip()
    if field == "discogs_release_id":
        if not value.isdigit():
            return False, {}
        return True, {"discogs_release_id": int(value)}
    if field == "price_gel":
        try:
            price = float(value)
        except ValueError:
            return False, {}
        return True, {"price_gel": price}
    return True, {field: value}


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
async def publish_discogs_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store = get_default_store()
    if not store:
        await update.message.reply_text("❌ No store configured. Run /setup_woo first.")
        return
    await update.message.reply_text("Tell me the artist or album name to publish ALL matches on Discogs:")
    context.user_data["discogs_action"] = "publish_discogs_all"
    return SEARCHING


@require_auth
@require_admin
async def publish_discogs_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store = get_default_store()
    if not store:
        await update.message.reply_text("❌ No store configured. Run /setup_woo first.")
        return
    await update.message.reply_text("Tell me the artist or album name to select items for Discogs publishing:")
    context.user_data["discogs_action"] = "publish_discogs_selection"
    return SEARCHING


@require_auth
@require_admin
async def collect_discogs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store = get_default_store()
    if not store:
        await update.message.reply_text("❌ No store configured. Run /setup_woo first.")
        return
    await update.message.reply_text("Tell me the artist or album name to add to your Discogs collection:")
    context.user_data["discogs_action"] = "collect_discogs"
    return SEARCHING


@require_auth
@require_admin
async def collect_discogs_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store = get_default_store()
    if not store:
        await update.message.reply_text("❌ No store configured. Run /setup_woo first.")
        return
    await update.message.reply_text("Tell me the artist or album name to select items for Discogs collection:")
    context.user_data["discogs_action"] = "collect_discogs_selection"
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
async def sync_discogs_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store = get_default_store()
    if not store:
        await update.message.reply_text("❌ No store configured. Run /setup_woo first.")
        return
    await update.message.reply_text(
        "How should I sync all inventory to Discogs? WooCommerce stock is treated as the source of truth.",
        reply_markup=_build_sync_all_keyboard(),
    )
    return SYNCING


@require_auth
@require_admin
async def handle_discogs_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = (update.message.text or "").strip()
    action = context.user_data.get("discogs_action")
    if not query or not action:
        await update.message.reply_text("Please enter a valid name to search.")
        return SEARCHING

    items = await run_blocking(
        search_inventory,
        query,
        50 if action in {"publish_discogs_all", "publish_discogs_selection", "collect_discogs_selection"} else 15,
    )
    if not items:
        await update.message.reply_text(f"❌ No matches found for '{query}'. Try another name.")
        return SEARCHING

    if action in {"publish_discogs_selection", "collect_discogs_selection"}:
        context.user_data["discogs_bulk_items"] = items
        context.user_data["discogs_bulk_selected"] = set()
        label = "publish" if action == "publish_discogs_selection" else "add to collection"
        message = f"Select items to {label} ({len(items)} match(es)):"
        await update.message.reply_text(
            message,
            reply_markup=_build_bulk_select_keyboard(items, set(), action=action),
        )
        return BULK_SELECTING

    if action in {"publish_discogs_all"}:
        context.user_data["discogs_bulk_queue"] = [int(item["id"]) for item in items]
        verb = "Publish" if action == "publish_discogs_all" else "Add"
        suffix = "to Discogs" if action == "publish_discogs_all" else "to your collection"
        message = f"{verb} ALL {len(items)} item(s) that match '{query}' {suffix}?"
        await update.message.reply_text(message, reply_markup=_build_confirm_keyboard(action, int(items[0]["id"])))
        return CONFIRMING

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
async def handle_discogs_bulk_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if data == "discogs_bulk_cancel":
        context.user_data.pop("discogs_bulk_items", None)
        context.user_data.pop("discogs_bulk_selected", None)
        await query.edit_message_text("❌ Bulk action cancelled.")
        return ConversationHandler.END
    if data == "discogs_bulk_done":
        selected = context.user_data.get("discogs_bulk_selected", set())
        if not selected:
            await query.edit_message_text("Please select at least one item.")
            return BULK_SELECTING
        context.user_data["discogs_bulk_queue"] = list(selected)
        action = context.user_data.get("discogs_action") or "publish_discogs_selection"
        bulk_action = "collect_discogs_bulk" if action.startswith("collect_discogs") else "publish_discogs_bulk"
        await query.edit_message_text(
            f"{DISCogs_ACTIONS.get(bulk_action, 'Proceed')}?",
            reply_markup=_build_confirm_keyboard(bulk_action, int(list(selected)[0])),
        )
        return CONFIRMING

    _, item_id = data.split(":", 1)
    items = context.user_data.get("discogs_bulk_items") or []
    selected = context.user_data.setdefault("discogs_bulk_selected", set())
    if not item_id.isdigit():
        await query.edit_message_text("Invalid selection.")
        return BULK_SELECTING
    item_id_int = int(item_id)
    if item_id_int in selected:
        selected.remove(item_id_int)
    else:
        selected.add(item_id_int)
    context.user_data["discogs_bulk_selected"] = selected
    await query.edit_message_text(
        f"Selected {len(selected)} item(s).",
        reply_markup=_build_bulk_select_keyboard(items, selected, action=context.user_data.get("discogs_action") or ""),
    )
    return BULK_SELECTING


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


async def _publish_listing_for_item(store: dict, item: dict, item_id: int) -> int | None:
    price = float(item.get("price_gel") or 0)
    condition = item.get("condition") or "Mint (M)"
    sleeve_condition = item.get("sleeve_condition") or "Generic"
    payload = _discogs_payload(item, price=price, condition=condition, sleeve_condition=sleeve_condition)
    listing = create_listing(store, payload)
    listing_id = listing.get("id")
    if listing_id:
        upsert_product_map(
            store_id=int(store["id"]),
            internal_product_id=int(item_id),
            discogs_listing_id=int(listing_id),
            discogs_release_id=int(item.get("discogs_release_id")),
        )
        return int(listing_id)
    return None


async def _collect_release_for_item(store: dict, item: dict) -> bool:
    release_id = item.get("discogs_release_id")
    if not release_id:
        return False
    add_to_collection(store, int(release_id))
    return True


async def _prompt_missing_field(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    item: dict,
    field: str,
    bulk: bool,
) -> int:
    prompt = _discogs_field_prompt(field, item)
    if update.callback_query:
        if bulk:
            await update.callback_query.edit_message_text(prompt, reply_markup=_build_bulk_skip_keyboard())
        else:
            await update.callback_query.edit_message_text(prompt)
    else:
        if bulk:
            await update.message.reply_text(prompt, reply_markup=_build_bulk_skip_keyboard())
        else:
            await update.message.reply_text(prompt)
    return BULK_INPUT if bulk else FIELD_INPUT


async def _advance_bulk_discogs(update: Update, context: ContextTypes.DEFAULT_TYPE, *, action: str) -> int:
    store = get_default_store()
    if not store:
        if update.callback_query:
            await update.callback_query.edit_message_text("❌ No store configured. Run /setup_woo first.")
        elif update.message:
            await update.message.reply_text("❌ No store configured. Run /setup_woo first.")
        return ConversationHandler.END

    queue = context.user_data.get("discogs_bulk_queue") or []
    results = context.user_data.setdefault("discogs_bulk_results", {"succeeded": [], "skipped": [], "failed": []})

    while queue:
        item_id = int(queue.pop(0))
        context.user_data["discogs_bulk_queue"] = queue
        item = await run_blocking(get_inventory_by_id, item_id)
        if not item:
            results["failed"].append(item_id)
            continue
        missing = _discogs_missing_fields(item, action=action)
        if missing:
            context.user_data["discogs_pending_item_id"] = item_id
            context.user_data["discogs_pending_fields"] = missing
            context.user_data["discogs_bulk_active"] = True
            return await _prompt_missing_field(update, context, item=item, field=missing[0], bulk=True)
        if action.startswith("collect_discogs"):
            ok = await _collect_release_for_item(store, item)
            if ok:
                results["succeeded"].append(item_id)
            else:
                results["failed"].append(item_id)
        else:
            listing_id = await _publish_listing_for_item(store, item, item_id)
            if listing_id:
                results["succeeded"].append(item_id)
            else:
                results["failed"].append(item_id)

    succeeded = len(results["succeeded"])
    skipped = len(results["skipped"])
    failed = len(results["failed"])
    action_label = "added" if action.startswith("collect_discogs") else "published"
    summary = f"✅ Bulk action complete. {action_label.title()}: {succeeded}, skipped: {skipped}, failed: {failed}."
    if update.callback_query:
        await update.callback_query.edit_message_text(summary)
    elif update.message:
        await update.message.reply_text(summary)
    return ConversationHandler.END


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

    if action == "publish_discogs":
        item = await run_blocking(get_inventory_by_id, int(item_id))
        if not item:
            await query.edit_message_text("Item not found.")
            return ConversationHandler.END
        missing = _discogs_missing_fields(item, action=action)
        if missing:
            context.user_data["discogs_pending_item_id"] = int(item_id)
            context.user_data["discogs_pending_fields"] = missing
            context.user_data["discogs_bulk_active"] = False
            return await _prompt_missing_field(update, context, item=item, field=missing[0], bulk=False)
        listing_id = await _publish_listing_for_item(store, item, int(item_id))
        if listing_id:
            await query.edit_message_text(f"✅ Discogs listing created: {listing_id}")
            return ConversationHandler.END
        await query.edit_message_text("❌ Discogs listing creation failed.")
        return ConversationHandler.END

    if action == "collect_discogs":
        item = await run_blocking(get_inventory_by_id, int(item_id))
        if not item:
            await query.edit_message_text("Item not found.")
            return ConversationHandler.END
        missing = _discogs_missing_fields(item, action=action)
        if missing:
            context.user_data["discogs_pending_item_id"] = int(item_id)
            context.user_data["discogs_pending_fields"] = missing
            context.user_data["discogs_bulk_active"] = False
            return await _prompt_missing_field(update, context, item=item, field=missing[0], bulk=False)
        ok = await _collect_release_for_item(store, item)
        if ok:
            await query.edit_message_text("✅ Added to Discogs collection.")
            return ConversationHandler.END
        await query.edit_message_text("❌ Discogs collection add failed.")
        return ConversationHandler.END

    if action in {"publish_discogs_all", "publish_discogs_bulk", "collect_discogs_bulk"}:
        return await _advance_bulk_discogs(update, context, action=action)

    if action == "link_discogs":
        item = await run_blocking(get_inventory_by_id, int(item_id))
        if not item:
            await query.edit_message_text("Item not found.")
            return ConversationHandler.END
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
        item = await run_blocking(get_inventory_by_id, int(item_id))
        if not item:
            await query.edit_message_text("Item not found.")
            return ConversationHandler.END
        sync_inventory_item(int(store["id"]), int(item_id), sync_price=True)
        await query.edit_message_text("✅ Discogs reconciled for item.")
        return ConversationHandler.END

    if action == "reconcile_woo":
        item = await run_blocking(get_inventory_by_id, int(item_id))
        if not item:
            await query.edit_message_text("Item not found.")
            return ConversationHandler.END
        sync_inventory_item(int(store["id"]), int(item_id), sync_price=True)
        await query.edit_message_text("✅ Woo reconciled for item.")
        return ConversationHandler.END

    if action == "discogs_refresh":
        item = await run_blocking(get_inventory_by_id, int(item_id))
        if not item:
            await query.edit_message_text("Item not found.")
            return ConversationHandler.END
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


@require_auth
@require_admin
async def handle_discogs_field_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    action = context.user_data.get("discogs_action") or "publish_discogs"
    item_id = context.user_data.get("discogs_pending_item_id")
    fields = context.user_data.get("discogs_pending_fields") or []
    if not item_id or not fields:
        await update.message.reply_text("Please start again with the command.")
        return ConversationHandler.END

    current_field = fields[0]
    valid, updates = _parse_field_value(current_field, update.message.text or "")
    if not valid:
        await update.message.reply_text("Invalid value. Please try again.")
        return FIELD_INPUT
    await run_blocking(update_inventory_fields, int(item_id), updates, sync_channels=False)
    fields = fields[1:]
    context.user_data["discogs_pending_fields"] = fields
    item = await run_blocking(get_inventory_by_id, int(item_id))
    if fields:
        return await _prompt_missing_field(update, context, item=item, field=fields[0], bulk=False)

    store = get_default_store()
    if not store:
        await update.message.reply_text("❌ No store configured. Run /setup_woo first.")
        return ConversationHandler.END
    if action.startswith("collect_discogs"):
        ok = await _collect_release_for_item(store, item)
        if ok:
            await update.message.reply_text("✅ Added to Discogs collection.")
        else:
            await update.message.reply_text("❌ Discogs collection add failed.")
        return ConversationHandler.END
    listing_id = await _publish_listing_for_item(store, item, int(item_id))
    if listing_id:
        await update.message.reply_text(f"✅ Discogs listing created: {listing_id}")
    else:
        await update.message.reply_text("❌ Discogs listing creation failed.")
    return ConversationHandler.END


@require_auth
@require_admin
async def handle_discogs_bulk_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    action = context.user_data.get("discogs_action") or "publish_discogs_bulk"
    item_id = context.user_data.get("discogs_pending_item_id")
    fields = context.user_data.get("discogs_pending_fields") or []
    if not item_id or not fields:
        await update.message.reply_text("Bulk action state missing. Please start again.")
        return ConversationHandler.END

    current_field = fields[0]
    valid, updates = _parse_field_value(current_field, update.message.text or "")
    if not valid:
        await update.message.reply_text("Invalid value. Please try again.")
        return BULK_INPUT
    await run_blocking(update_inventory_fields, int(item_id), updates, sync_channels=False)
    fields = fields[1:]
    context.user_data["discogs_pending_fields"] = fields
    item = await run_blocking(get_inventory_by_id, int(item_id))
    if fields:
        return await _prompt_missing_field(update, context, item=item, field=fields[0], bulk=True)

    store = get_default_store()
    if not store:
        await update.message.reply_text("❌ No store configured. Run /setup_woo first.")
        return ConversationHandler.END
    results = context.user_data.setdefault("discogs_bulk_results", {"succeeded": [], "skipped": [], "failed": []})
    if action.startswith("collect_discogs"):
        ok = await _collect_release_for_item(store, item)
        if ok:
            results["succeeded"].append(int(item_id))
        else:
            results["failed"].append(int(item_id))
    else:
        listing_id = await _publish_listing_for_item(store, item, int(item_id))
        if listing_id:
            results["succeeded"].append(int(item_id))
        else:
            results["failed"].append(int(item_id))
    return await _advance_bulk_discogs(update, context, action=action)


@require_auth
@require_admin
async def handle_discogs_bulk_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if data == "discogs_bulk_cancel":
        await query.edit_message_text("❌ Bulk action cancelled.")
        return ConversationHandler.END

    item_id = context.user_data.get("discogs_pending_item_id")
    results = context.user_data.setdefault("discogs_bulk_results", {"succeeded": [], "skipped": [], "failed": []})
    if item_id:
        results["skipped"].append(int(item_id))
    context.user_data["discogs_pending_item_id"] = None
    context.user_data["discogs_pending_fields"] = []
    action = context.user_data.get("discogs_action") or "publish_discogs_bulk"
    return await _advance_bulk_discogs(update, context, action=action)


@require_auth
@require_admin
async def handle_discogs_sync_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    _, mode = data.split(":", 1)
    if mode == "cancel":
        await query.edit_message_text("❌ Discogs sync cancelled.")
        return ConversationHandler.END

    store = get_default_store()
    if not store:
        await query.edit_message_text("❌ No store configured. Run /setup_woo first.")
        return ConversationHandler.END

    publish_missing = mode == "publish"
    await query.edit_message_text("🔄 Syncing all inventory with Discogs. This may take a while...")
    results = await run_blocking(sync_all_discogs, int(store["id"]), publish_missing=publish_missing)

    summary = (
        "✅ Discogs sync complete.\n"
        f"• Items checked: {results.get('total_items', 0)}\n"
        f"• Woo synced: {results.get('woo_synced', 0)} (failed: {results.get('woo_failed', 0)})\n"
        "• Collection adds: "
        f"{results.get('collection_added', 0)} "
        f"(skipped: {results.get('collection_skipped', 0)}, "
        f"failed: {results.get('collection_failed', 0)})\n"
        f"• Listings updated: {results.get('listing_updated', 0)}\n"
        f"• Listings published: {results.get('listing_published', 0)} (failed: {results.get('listing_failed', 0)})\n"
        f"• Skipped (missing listing fields): {results.get('skipped_missing', 0)}\n"
        f"• Skipped (missing release ID): {results.get('skipped_no_release', 0)}"
    )
    await query.edit_message_text(summary)
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
            CommandHandler("publish_discogs_all", publish_discogs_all),
            CommandHandler("publish_discogs_selection", publish_discogs_selection),
            CommandHandler("collect_discogs", collect_discogs),
            CommandHandler("collect_discogs_selection", collect_discogs_selection),
            CommandHandler("link_discogs", link_discogs),
            CommandHandler("unlink_discogs", unlink_discogs),
            CommandHandler("reconcile_discogs", reconcile_discogs),
            CommandHandler("reconcile_woo", reconcile_woo),
            CommandHandler("discogs_refresh", discogs_refresh),
            CommandHandler("sync_discogs_all", sync_discogs_all),
        ],
        states={
            SEARCHING: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_discogs_search)],
            SELECTING: [CallbackQueryHandler(handle_discogs_select, pattern=r"^discogs_select:")],
            BULK_SELECTING: [CallbackQueryHandler(handle_discogs_bulk_select, pattern=r"^discogs_bulk_")],
            EXTRA_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_discogs_extra)],
            CONFIRMING: [CallbackQueryHandler(handle_discogs_confirm, pattern=r"^discogs_confirm:")],
            FIELD_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_discogs_field_input)],
            BULK_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_discogs_bulk_input),
                CallbackQueryHandler(handle_discogs_bulk_skip, pattern=r"^discogs_bulk_"),
            ],
            SYNCING: [CallbackQueryHandler(handle_discogs_sync_all, pattern=r"^discogs_sync_all:")],
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
