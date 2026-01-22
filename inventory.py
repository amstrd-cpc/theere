# inventory_conversation.py - Conversation handler for inventory search
import datetime
import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, ConversationHandler, CallbackQueryHandler, filters
from auth import require_auth
from db import get_db
import inventory as inventory_utils
import re
from config import ADMIN_IDS
from woocommerce_client import (
    create_product_from_inventory,
    is_configured,
    update_product_description,
    update_product_metadata,
    update_product_price,
    update_product_stock,
)


def _is_old_schema(conn) -> bool:
    """Return True if the database uses the legacy 'records' table."""
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    return "inventory" not in tables and "records" in tables

# Conversation states
WAITING_FOR_QUERY = 0
(
    EDIT_PRICE,
    EDIT_STOCK,
    EDIT_LABEL,
    EDIT_GENRE,
    EDIT_STYLE,
    EDIT_FORMAT_SELECT,
    EDIT_FORMAT_CUSTOM,
    EDIT_YEAR,
    EDIT_DESCRIPTION,
) = range(1, 10)

logger = logging.getLogger(__name__)

def escape_markdown(text: str) -> str:
    """
    Escape Telegram MarkdownV2 special characters in user-provided text.
    """
    if not isinstance(text, str):
        text = str(text)
    escape_chars = r"_*[]()~`>#+-=|{}.!\\"
    return re.sub(f"([{re.escape(escape_chars)}])", r"\\\1", text)


def safe_field(text: str) -> str:
    if not isinstance(text, str):
        text = str(text)
    return escape_markdown(text.strip().replace("\n", " "))


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def build_edit_keyboard(item_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton("📝 Edit Price", callback_data=f"edit_price:{item_id}"),
            InlineKeyboardButton("📦 Edit Stock", callback_data=f"edit_stock:{item_id}"),
        ],
        [
            InlineKeyboardButton("🎚 Edit Condition", callback_data=f"edit_condition:{item_id}"),
            InlineKeyboardButton("🏷 Edit Label", callback_data=f"edit_label:{item_id}"),
        ],
        [
            InlineKeyboardButton("🎼 Edit Genre", callback_data=f"edit_genre:{item_id}"),
            InlineKeyboardButton("🎛 Edit Style", callback_data=f"edit_style:{item_id}"),
        ],
        [
            InlineKeyboardButton("📀 Edit Format", callback_data=f"edit_format:{item_id}"),
            InlineKeyboardButton("📅 Edit Year", callback_data=f"edit_year:{item_id}"),
        ],
        [InlineKeyboardButton("🧾 Edit Description", callback_data=f"edit_description:{item_id}")],
        [InlineKeyboardButton("♻ Rebuild Description", callback_data=f"rebuild_description:{item_id}")],
        [
            InlineKeyboardButton("🛒 View in Woo", callback_data=f"view_woo:{item_id}"),
            InlineKeyboardButton("📤 Sync All", callback_data=f"sync_all:{item_id}"),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


def build_selection_keyboard(items: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for item in items[:25]:
        text = f"{item.get('artist_album', 'Item')} (Qty: {item.get('quantity', 0)})"
        if len(text) > 60:
            text = text[:57] + "..."
        buttons.append([InlineKeyboardButton(text, callback_data=f"inventory_detail:{item['id']}")])
    return InlineKeyboardMarkup(buttons)


def format_inventory_detail(item: dict) -> str:
    lines = [
        f"🎵 {item.get('artist_album', 'Unknown')}",
        f"💰 Price: ₾{float(item.get('price_gel') or 0):.2f}",
        f"📦 Stock: {item.get('quantity', 0)}",
        f"🎚 Condition: {item.get('condition', 'N/A')}",
        f"🏷 Label: {item.get('label', 'N/A')}",
        f"🎼 Genre: {item.get('genre', 'N/A')}",
        f"🎛 Style: {item.get('style', 'N/A')}",
        f"📀 Format: {item.get('format', 'N/A')}",
    ]
    if item.get("year"):
        lines.append(f"📅 Year: {item.get('year')}")
    if item.get("supplier"):
        lines.append(f"🚚 Supplier: {item.get('supplier')}")
    woo_id = item.get("woo_product_id")
    if woo_id:
        lines.append(f"🛒 Woo ID: {woo_id}")
    if item.get("woo_last_synced_at"):
        lines.append(f"🔄 Woo Synced: {item.get('woo_last_synced_at')}")
    if item.get("description"):
        lines.append("\nDescription:\n" + item.get("description"))
    return "\n".join(lines)


@require_auth
async def start_inventory_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the inventory search conversation"""
    await update.message.reply_text(
        "🔍 Inventory Search\n\n"
        "Please enter your search query:\n"
        "• Artist name (e.g., 'Beatles')\n"
        "• Album name (e.g., 'Abbey Road')\n"
        "• Partial match (e.g., 'Dark Side')\n"
        "• Or type 'all' to see everything\n\n"
        "Type /cancel to cancel this operation."
    )
    return WAITING_FOR_QUERY

async def handle_inventory_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the inventory search query"""
    query = update.message.text.strip()

    if not query:
        await update.message.reply_text(
            "❌ Please enter a valid search query or type /cancel to cancel."
        )
        return WAITING_FOR_QUERY

    searching_message = await update.message.reply_text("🔍 Searching inventory...")

    try:
        if query.lower() == "all":
            results = inventory_utils.get_all_inventory()
            title = "📦 All Inventory"
        else:
            results = inventory_utils.search_inventory(query)
            title = f"🔍 Search Results for: {query}"

        await searching_message.delete()

        if not results:
            await update.message.reply_text(
                f"❌ No records found\n\n"
                f"Search query: {query}\n\n"
                "Try a different search term or use /inventory to search again."
            )
            return ConversationHandler.END

        await send_inventory_results(update, context, results, title, query)

    except Exception as e:
        try:
            await searching_message.delete()
        except:
            pass

        await update.message.reply_text(
            f"❌ Error searching inventory\n\n"
            f"An error occurred: {str(e)}\n\n"
            "Please try again with /inventory"
        )

    return ConversationHandler.END


@require_auth
async def send_inventory_results(update: Update, context: ContextTypes.DEFAULT_TYPE, results: list, title: str, query: str):
    """Send formatted inventory results, handling long messages"""
    total_results = len(results)
    results_per_message = 8

    # Remove MarkdownV2 for now - use plain text
    title_clean = title.replace("*", "").replace("\\", "")
    message = f"{title_clean}\n"
    message += f"Found {total_results} record(s)\n\n"

    if total_results == 1:
        item = results[0]
        detail_text = f"{title_clean}\n\n" + format_inventory_detail(item)
        await update.message.reply_text(
            detail_text,
            reply_markup=build_edit_keyboard(item["id"]) if is_admin(update.effective_user.id) else None,
        )
        return

    for i, item in enumerate(results[:results_per_message]):
        message += format_inventory_item(item, i + 1)

    if total_results > results_per_message:
        showing_end = min(results_per_message, total_results)
        message += f"\n📄 Showing 1-{showing_end} of {total_results} results"

    await update.message.reply_text(message)

    for batch_start in range(results_per_message, total_results, results_per_message):
        batch_end = min(batch_start + results_per_message, total_results)
        batch_message = f"📄 Continued results ({batch_start + 1}-{batch_end} of {total_results})\n\n"

        for i, item in enumerate(results[batch_start:batch_end]):
            batch_message += format_inventory_item(item, batch_start + i + 1)

        await update.message.reply_text(batch_message)

    await update.message.reply_text(
        "Select a record to view details and editing options:",
        reply_markup=build_selection_keyboard(results),
    )

def format_inventory_item(item: dict, index: int) -> str:
    # Use plain text formatting - no markdown at all
    price = item.get('price_gel', 0)
    quantity = item.get('quantity', 0)
    
    # Clean up any potential problematic characters in text fields
    def clean_field(value):
        if not isinstance(value, str):
            value = str(value)
        return value.strip().replace("\n", " ")
    
    return (
        f"{index}. {clean_field(item.get('artist_album', 'Unknown'))}\n"
        f"📀 Format: {clean_field(item.get('format', 'N/A'))}\n"
        f"🏷️ Condition: {clean_field(item.get('condition', 'N/A'))}\n"
        f"💰 Price: ₾{price:.2f}\n"
        f"📦 Quantity: {quantity}\n"
        f"🏢 Label: {clean_field(item.get('label', 'N/A'))}\n"
        f"🎵 Genre: {clean_field(item.get('genre', 'N/A'))}\n\n"
    )


@require_auth
async def cancel_inventory_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel inventory search"""
    await update.message.reply_text(
        "✅ Inventory search cancelled\n\n"
        "Use /inventory to start a new search."
    )
    return ConversationHandler.END

def create_inventory_conversation():
    """Create the inventory search conversation handler"""
    return ConversationHandler(
        entry_points=[CommandHandler("inventory", start_inventory_search)],
        states={
            WAITING_FOR_QUERY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_inventory_query)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel_inventory_search)],
        name="inventory_search",
        persistent=False
    )

# === Inventory Utility Functions ===

def search_inventory(query: str) -> list:
    """Search inventory records matching the query string."""
    like = f"%{query.lower()}%"
    with get_db() as conn:
        cursor = conn.cursor()
        if _is_old_schema(conn):
            cursor.execute(
                """
                SELECT id, artist, title, genre, style, label, format, price_gel,
                       quantity, supplier
                FROM records
                WHERE lower(artist) LIKE ?
                   OR lower(title) LIKE ?
                   OR lower(genre) LIKE ?
                   OR lower(style) LIKE ?
                   OR lower(label) LIKE ?
                ORDER BY artist, title
                """,
                (like, like, like, like, like),
            )
            rows = cursor.fetchall()
            return [
                {
                    "id": row[0],
                    "artist_album": f"{row[1]} - {row[2]}",
                    "genre": row[3],
                    "style": row[4],
                    "label": row[5],
                    "format": row[6],
                    "condition": "N/A",
                    "price_gel": row[7],
                    "quantity": row[8],
                    "supplier_id": None,
                    "supplier": row[9],
                }
                for row in rows
            ]
        else:
            # Prefer FTS if available for fast, forgiving search.
            def _fts_available(c) -> bool:
                try:
                    c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='inventory_fts'")
                    return c.fetchone() is not None
                except Exception:
                    return False

            if _fts_available(cursor) and query.strip().lower() not in ("all", "*"):
                # Build a simple prefix-query: token* token* ...
                tokens = re.findall(r"[\w']+", query.lower())
                if not tokens:
                    fts_q = query
                else:
                    fts_q = " ".join(f"{t}*" for t in tokens)
                cursor.execute(
                    """
                    SELECT i.id, i.artist_album, i.genre, i.style, i.label, i.format,
                           i.condition, i.price_gel, i.quantity, i.supplier_id,
                           s.name AS supplier_name,
                           i.woo_product_id, i.woo_synced, i.woo_last_synced_at,
                           i.year, i.description
                    FROM inventory_fts f
                    JOIN inventory i ON i.id = f.rowid
                    LEFT JOIN supplier s ON i.supplier_id = s.id
                    WHERE inventory_fts MATCH ?
                    ORDER BY i.artist_album
                    LIMIT 50
                    """,
                    (fts_q,),
                )
            else:
                cursor.execute(
                    """
                    SELECT i.id, i.artist_album, i.genre, i.style, i.label, i.format,
                           i.condition, i.price_gel, i.quantity, i.supplier_id,
                           s.name AS supplier_name,
                           i.woo_product_id, i.woo_synced, i.woo_last_synced_at,
                           i.year, i.description
                    FROM inventory i
                    LEFT JOIN supplier s ON i.supplier_id = s.id
                    WHERE lower(artist_album) LIKE ?
                       OR lower(genre) LIKE ?
                       OR lower(style) LIKE ?
                       OR lower(label) LIKE ?
                    ORDER BY artist_album
                    LIMIT 50
                    """,
                    (like, like, like, like),
                )
            rows = cursor.fetchall()
            return [
                {
                    "id": row[0],
                    "artist_album": row[1],
                    "genre": row[2],
                    "style": row[3],
                    "label": row[4],
                    "format": row[5],
                    "condition": row[6],
                    "price_gel": row[7],
                    "quantity": row[8],
                    "supplier_id": row[9],
                    "supplier": row[10],
                    "woo_product_id": row[11],
                    "woo_synced": row[12],
                    "woo_last_synced_at": row[13],
                    "year": row[14],
                    "description": row[15],
                }
                for row in rows
            ]


def get_all_inventory() -> list:
    """Return all inventory records."""
    with get_db() as conn:
        cursor = conn.cursor()
        if _is_old_schema(conn):
            cursor.execute(
                """
                SELECT id, artist, title, genre, style, label, format, price_gel,
                       quantity, supplier
                FROM records
                ORDER BY artist, title
                """
            )
            rows = cursor.fetchall()
            return [
                {
                    "id": row[0],
                    "artist_album": f"{row[1]} - {row[2]}",
                    "genre": row[3],
                    "style": row[4],
                    "label": row[5],
                    "format": row[6],
                    "condition": "N/A",
                    "price_gel": row[7],
                    "quantity": row[8],
                    "supplier_id": None,
                    "supplier": row[9],
                }
                for row in rows
            ]
        else:
            cursor.execute(
                """
                SELECT i.id, i.artist_album, i.genre, i.style, i.label, i.format,
                       i.condition, i.price_gel, i.quantity, i.supplier_id,
                       s.name AS supplier_name,
                       i.woo_product_id, i.woo_synced, i.woo_last_synced_at,
                       i.year, i.description
                FROM inventory i
                LEFT JOIN supplier s ON i.supplier_id = s.id
                ORDER BY i.artist_album
                """
            )
            rows = cursor.fetchall()
            return [
                {
                    "id": row[0],
                    "artist_album": row[1],
                    "genre": row[2],
                    "style": row[3],
                    "label": row[4],
                    "format": row[5],
                    "condition": row[6],
                    "price_gel": row[7],
                    "quantity": row[8],
                    "supplier_id": row[9],
                    "supplier": row[10],
                    "woo_product_id": row[11],
                    "woo_synced": row[12],
                    "woo_last_synced_at": row[13],
                    "year": row[14],
                    "description": row[15],
                }
                for row in rows
            ]


def reduce_inventory_quantity(item_id: int, amount: int) -> bool:
    """Decrease quantity for an item. Returns True if successful."""
    if amount <= 0:
        return False
    with get_db() as conn:
        cursor = conn.cursor()
        if _is_old_schema(conn):
            cursor.execute(
                "SELECT quantity FROM records WHERE id = ?",
                (item_id,),
            )
            row = cursor.fetchone()
            if not row:
                return False
            new_qty = row[0] - amount
            if new_qty < 0:
                return False
            cursor.execute(
                "UPDATE records SET quantity = ? WHERE id = ?",
                (new_qty, item_id),
            )
            conn.commit()
            return True
        else:
            # Atomic update to avoid race conditions and ensure quantity never goes negative.
            cursor.execute(
                "UPDATE inventory SET quantity = quantity - ? WHERE id = ? AND quantity >= ?",
                (amount, item_id, amount),
            )
            if cursor.rowcount != 1:
                conn.rollback()
                return False
            conn.commit()
            return True


def get_inventory_by_id(item_id: int):
    """Fetch a single inventory record by id."""
    with get_db() as conn:
        cursor = conn.cursor()
        if _is_old_schema(conn):
            cursor.execute(
                """
                SELECT id, artist, title, genre, style, label, format, price_gel,
                       quantity, supplier
                FROM records
                WHERE id = ?
                """,
                (item_id,),
            )
            row = cursor.fetchone()
            if row:
                return {
                    "id": row[0],
                    "artist_album": f"{row[1]} - {row[2]}",
                    "genre": row[3],
                    "style": row[4],
                    "label": row[5],
                    "format": row[6],
                    "condition": "N/A",
                    "price_gel": row[7],
                    "quantity": row[8],
                    "supplier_id": None,
                    "supplier": row[9],
                }
            return None
        else:
            cursor.execute(
                """
                SELECT i.id, i.artist_album, i.genre, i.style, i.label, i.format,
                       i.condition, i.price_gel, i.quantity, i.supplier_id,
                       s.name AS supplier_name,
                       i.woo_product_id, i.woo_synced, i.woo_last_synced_at,
                       i.year, i.description
                FROM inventory i
                LEFT JOIN supplier s ON i.supplier_id = s.id
                WHERE i.id = ?
                """,
                (item_id,),
            )
            row = cursor.fetchone()
            if row:
                return {
                    "id": row[0],
                    "artist_album": row[1],
                    "genre": row[2],
                    "style": row[3],
                    "label": row[4],
                    "format": row[5],
                    "condition": row[6],
                    "price_gel": row[7],
                    "quantity": row[8],
                    "supplier_id": row[9],
                    "supplier": row[10],
                    "woo_product_id": row[11],
                    "woo_synced": row[12],
                    "woo_last_synced_at": row[13],
                    "year": row[14],
                    "description": row[15],
                }
            return None


def set_woo_sync_flags(item_id: int):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE inventory
            SET woo_synced = 1, woo_last_synced_at = ?
            WHERE id = ?
            """,
            (datetime.datetime.utcnow().isoformat(), item_id),
        )
        conn.commit()


def build_generated_description(item: dict) -> str:
    lines = [
        f"Artist / Title: {item.get('artist_album', 'Unknown')}",
        f"Label: {item.get('label', 'N/A')}",
        f"Format: {item.get('format', 'N/A')}",
        f"Condition: {item.get('condition', 'N/A')}",
        f"Genre/Style: {item.get('genre', 'N/A')} / {item.get('style', 'N/A')}",
        f"Price: {item.get('price_gel', 0)} GEL",
        f"Stock: {item.get('quantity', 0)}",
        "",
        "Notes:",
        "- This description was generated from inventory metadata.",
    ]
    return "\n".join(lines)


def _get_item_for_update(item_id: int) -> dict | None:
    item = inventory_utils.get_inventory_by_id(item_id)
    if not item:
        return None
    return item


async def _ensure_admin(query) -> bool:
    user_id = query.from_user.id if query.from_user else None
    if user_id not in ADMIN_IDS:
        await query.answer("You are not allowed to edit.", show_alert=True)
        return False
    return True


async def inventory_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        item_id = int(query.data.split(":")[1])
    except (IndexError, ValueError):
        await query.answer("Invalid item.", show_alert=True)
        return

    item = inventory_utils.get_inventory_by_id(item_id)
    if not item:
        await query.answer("Item not found.", show_alert=True)
        return

    reply_markup = build_edit_keyboard(item_id) if is_admin(update.effective_user.id) else None
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=format_inventory_detail(item),
        reply_markup=reply_markup,
    )


async def edit_price_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await _ensure_admin(query):
        return ConversationHandler.END
    await query.answer()
    item_id = int(query.data.split(":")[1])
    item = _get_item_for_update(item_id)
    if not item:
        await query.answer("Item not found.", show_alert=True)
        return ConversationHandler.END
    context.user_data["edit_item_id"] = item_id
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"Send new price in GEL for: {item['artist_album']}",
    )
    return EDIT_PRICE


async def handle_price_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    item_id = context.user_data.get("edit_item_id")
    try:
        new_price = float(update.message.text.strip())
    except (ValueError, AttributeError):
        await update.message.reply_text("❌ Invalid price. Please send a number.")
        return EDIT_PRICE

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE inventory SET price_gel = ? WHERE id = ?", (new_price, item_id))
        conn.commit()

    woo_message = ""
    item = inventory_utils.get_inventory_by_id(item_id)
    if item and is_configured() and item.get("woo_product_id"):
        try:
            update_product_price(int(item["woo_product_id"]), new_price)
            set_woo_sync_flags(item_id)
        except Exception as e:
            logger.error("WooCommerce price update failed: %s", e)
            woo_message = " Local price updated, but Woo sync failed."

    await update.message.reply_text(
        f"✅ Price updated to {new_price:.2f} GEL and synced to WooCommerce." if not woo_message else f"✅ Price updated to {new_price:.2f} GEL.{woo_message}"
    )
    return ConversationHandler.END


async def edit_stock_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await _ensure_admin(query):
        return ConversationHandler.END
    await query.answer()
    item_id = int(query.data.split(":")[1])
    item = _get_item_for_update(item_id)
    if not item:
        await query.answer("Item not found.", show_alert=True)
        return ConversationHandler.END
    context.user_data["edit_item_id"] = item_id
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"Send new stock quantity for: {item['artist_album']}",
    )
    return EDIT_STOCK


async def handle_stock_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    item_id = context.user_data.get("edit_item_id")
    try:
        new_qty = int(update.message.text.strip())
    except (ValueError, AttributeError):
        await update.message.reply_text("❌ Invalid quantity. Please send an integer.")
        return EDIT_STOCK

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE inventory SET quantity = ? WHERE id = ?", (new_qty, item_id))
        conn.commit()

    woo_message = ""
    item = inventory_utils.get_inventory_by_id(item_id)
    if item and is_configured() and item.get("woo_product_id"):
        try:
            update_product_stock(int(item["woo_product_id"]), new_qty)
            set_woo_sync_flags(item_id)
        except Exception as e:
            logger.error("WooCommerce stock update failed: %s", e)
            woo_message = " Local stock updated, but Woo sync failed."

    await update.message.reply_text(
        "✅ Stock updated and synced to WooCommerce." if not woo_message else f"✅ Stock updated.{woo_message}"
    )
    return ConversationHandler.END


async def edit_condition_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await _ensure_admin(query):
        return
    await query.answer()
    item_id = int(query.data.split(":")[1])
    buttons = [
        [
            InlineKeyboardButton("Mint", callback_data=f"set_condition:Mint:{item_id}"),
            InlineKeyboardButton("NM", callback_data=f"set_condition:NM:{item_id}"),
            InlineKeyboardButton("VG+", callback_data=f"set_condition:VG+:{item_id}"),
        ],
        [
            InlineKeyboardButton("VG", callback_data=f"set_condition:VG:{item_id}"),
            InlineKeyboardButton("G", callback_data=f"set_condition:G:{item_id}"),
            InlineKeyboardButton("Other", callback_data=f"set_condition:Other:{item_id}"),
        ],
    ]
    await query.edit_message_text(
        "Choose new condition:", reply_markup=InlineKeyboardMarkup(buttons)
    )


async def set_condition_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await _ensure_admin(query):
        return
    await query.answer()
    try:
        _, value, item_id = query.data.split(":")
        item_id = int(item_id)
    except ValueError:
        await query.answer("Invalid selection", show_alert=True)
        return

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE inventory SET condition = ? WHERE id = ?", (value, item_id))
        conn.commit()

    woo_message = ""
    item = inventory_utils.get_inventory_by_id(item_id)
    if item and is_configured() and item.get("woo_product_id"):
        try:
            update_product_metadata(int(item["woo_product_id"]), item)
            set_woo_sync_flags(item_id)
        except Exception as e:
            logger.error("WooCommerce condition update failed: %s", e)
            woo_message = " Woo sync failed."

    await query.edit_message_text(
        f"✅ Condition updated to {value}.{woo_message}"
    )


async def edit_label_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await _ensure_admin(query):
        return ConversationHandler.END
    await query.answer()
    item_id = int(query.data.split(":")[1])
    item = _get_item_for_update(item_id)
    if not item:
        await query.answer("Item not found.", show_alert=True)
        return ConversationHandler.END
    context.user_data["edit_item_id"] = item_id
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"Send new label name for: {item['artist_album']}",
    )
    return EDIT_LABEL


async def handle_label_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    item_id = context.user_data.get("edit_item_id")
    new_label = update.message.text.strip()
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE inventory SET label = ? WHERE id = ?", (new_label, item_id))
        conn.commit()

    woo_message = ""
    item = inventory_utils.get_inventory_by_id(item_id)
    if item and is_configured() and item.get("woo_product_id"):
        try:
            update_product_metadata(int(item["woo_product_id"]), item)
            set_woo_sync_flags(item_id)
        except Exception as e:
            logger.error("WooCommerce label update failed: %s", e)
            woo_message = " Woo sync failed."

    await update.message.reply_text(
        "✅ Label updated." + woo_message
    )
    return ConversationHandler.END


async def edit_genre_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await _ensure_admin(query):
        return ConversationHandler.END
    await query.answer()
    item_id = int(query.data.split(":")[1])
    item = _get_item_for_update(item_id)
    if not item:
        await query.answer("Item not found.", show_alert=True)
        return ConversationHandler.END
    context.user_data["edit_item_id"] = item_id
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"Send new genre for: {item['artist_album']} (e.g., Electronic, Rock, Jazz)",
    )
    return EDIT_GENRE


async def handle_genre_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    item_id = context.user_data.get("edit_item_id")
    new_genre = update.message.text.strip()
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE inventory SET genre = ? WHERE id = ?", (new_genre, item_id))
        conn.commit()

    woo_message = ""
    item = inventory_utils.get_inventory_by_id(item_id)
    if item and is_configured() and item.get("woo_product_id"):
        try:
            update_product_metadata(int(item["woo_product_id"]), item)
            set_woo_sync_flags(item_id)
        except Exception as e:
            logger.error("WooCommerce genre update failed: %s", e)
            woo_message = " Woo sync failed."

    await update.message.reply_text("✅ Genre updated." + woo_message)
    return ConversationHandler.END


async def edit_style_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await _ensure_admin(query):
        return ConversationHandler.END
    await query.answer()
    item_id = int(query.data.split(":")[1])
    item = _get_item_for_update(item_id)
    if not item:
        await query.answer("Item not found.", show_alert=True)
        return ConversationHandler.END
    context.user_data["edit_item_id"] = item_id
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"Send new style for: {item['artist_album']} (e.g., Techno, Drum & Bass)",
    )
    return EDIT_STYLE


async def handle_style_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    item_id = context.user_data.get("edit_item_id")
    new_style = update.message.text.strip()
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE inventory SET style = ? WHERE id = ?", (new_style, item_id))
        conn.commit()

    woo_message = ""
    item = inventory_utils.get_inventory_by_id(item_id)
    if item and is_configured() and item.get("woo_product_id"):
        try:
            update_product_metadata(int(item["woo_product_id"]), item)
            set_woo_sync_flags(item_id)
        except Exception as e:
            logger.error("WooCommerce style update failed: %s", e)
            woo_message = " Woo sync failed."

    await update.message.reply_text("✅ Style updated." + woo_message)
    return ConversationHandler.END


async def edit_format_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await _ensure_admin(query):
        return ConversationHandler.END
    await query.answer()
    item_id = int(query.data.split(":")[1])
    buttons = [
        [
            InlineKeyboardButton("LP", callback_data=f"set_format:LP:{item_id}"),
            InlineKeyboardButton('12"', callback_data=f"set_format:12\":{item_id}"),
            InlineKeyboardButton('10"', callback_data=f"set_format:10\":{item_id}"),
        ],
        [
            InlineKeyboardButton('7"', callback_data=f"set_format:7\":{item_id}"),
            InlineKeyboardButton("Cassette", callback_data=f"set_format:Cassette:{item_id}"),
            InlineKeyboardButton("CD", callback_data=f"set_format:CD:{item_id}"),
        ],
        [InlineKeyboardButton("Other", callback_data=f"set_format:Other:{item_id}")],
    ]
    await query.edit_message_text(
        "Choose new format:", reply_markup=InlineKeyboardMarkup(buttons)
    )
    return EDIT_FORMAT_SELECT


async def set_format_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await _ensure_admin(query):
        return ConversationHandler.END
    await query.answer()
    try:
        _, value, item_id = query.data.split(":")
        item_id = int(item_id)
    except ValueError:
        await query.answer("Invalid selection", show_alert=True)
        return ConversationHandler.END

    if value == "Other":
        context.user_data["edit_item_id"] = item_id
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Send custom format value:",
        )
        return EDIT_FORMAT_CUSTOM

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE inventory SET format = ? WHERE id = ?", (value, item_id))
        conn.commit()

    woo_message = ""
    item = inventory_utils.get_inventory_by_id(item_id)
    if item and is_configured() and item.get("woo_product_id"):
        try:
            update_product_metadata(int(item["woo_product_id"]), item)
            set_woo_sync_flags(item_id)
        except Exception as e:
            logger.error("WooCommerce format update failed: %s", e)
            woo_message = " Woo sync failed."

    await query.edit_message_text(f"✅ Format updated to {value}." + woo_message)
    return ConversationHandler.END


async def handle_format_custom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    item_id = context.user_data.get("edit_item_id")
    value = update.message.text.strip()
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE inventory SET format = ? WHERE id = ?", (value, item_id))
        conn.commit()

    woo_message = ""
    item = inventory_utils.get_inventory_by_id(item_id)
    if item and is_configured() and item.get("woo_product_id"):
        try:
            update_product_metadata(int(item["woo_product_id"]), item)
            set_woo_sync_flags(item_id)
        except Exception as e:
            logger.error("WooCommerce format update failed: %s", e)
            woo_message = " Woo sync failed."

    await update.message.reply_text("✅ Format updated." + woo_message)
    return ConversationHandler.END


async def edit_year_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await _ensure_admin(query):
        return ConversationHandler.END
    await query.answer()
    item_id = int(query.data.split(":")[1])
    item = _get_item_for_update(item_id)
    if not item:
        await query.answer("Item not found.", show_alert=True)
        return ConversationHandler.END
    context.user_data["edit_item_id"] = item_id
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"Send release year (e.g. 1998) for: {item['artist_album']}",
    )
    return EDIT_YEAR


async def handle_year_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    item_id = context.user_data.get("edit_item_id")
    value = update.message.text.strip()
    if not value.isdigit() or len(value) != 4:
        await update.message.reply_text("❌ Please send a 4-digit year (e.g. 1998).")
        return EDIT_YEAR
    year_int = int(value)
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE inventory SET year = ? WHERE id = ?", (year_int, item_id))
        conn.commit()

    woo_message = ""
    item = inventory_utils.get_inventory_by_id(item_id)
    if item and is_configured() and item.get("woo_product_id"):
        try:
            update_product_metadata(int(item["woo_product_id"]), item)
            set_woo_sync_flags(item_id)
        except Exception as e:
            logger.error("WooCommerce year update failed: %s", e)
            woo_message = " Woo sync failed."

    await update.message.reply_text("✅ Year updated." + woo_message)
    return ConversationHandler.END


async def edit_description_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await _ensure_admin(query):
        return ConversationHandler.END
    await query.answer()
    item_id = int(query.data.split(":")[1])
    item = _get_item_for_update(item_id)
    if not item:
        await query.answer("Item not found.", show_alert=True)
        return ConversationHandler.END
    context.user_data["edit_item_id"] = item_id
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"Send new description for this product. This will overwrite the WooCommerce description for: {item['artist_album']}",
    )
    return EDIT_DESCRIPTION


async def handle_description_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    item_id = context.user_data.get("edit_item_id")
    description = update.message.text
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE inventory SET description = ? WHERE id = ?", (description, item_id))
        conn.commit()

    woo_message = ""
    item = inventory_utils.get_inventory_by_id(item_id)
    if item and is_configured() and item.get("woo_product_id"):
        try:
            update_product_description(int(item["woo_product_id"]), description)
            set_woo_sync_flags(item_id)
        except Exception as e:
            logger.error("WooCommerce description update failed: %s", e)
            woo_message = " Woo sync failed."

    await update.message.reply_text("✅ Description updated." + woo_message)
    return ConversationHandler.END


async def rebuild_description_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await _ensure_admin(query):
        return
    await query.answer()
    item_id = int(query.data.split(":")[1])
    item = inventory_utils.get_inventory_by_id(item_id)
    if not item:
        await query.answer("Item not found.", show_alert=True)
        return
    description = build_generated_description(item)
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE inventory SET description = ? WHERE id = ?", (description, item_id))
        conn.commit()

    woo_message = ""
    if is_configured() and item.get("woo_product_id"):
        try:
            update_product_description(int(item["woo_product_id"]), description)
            set_woo_sync_flags(item_id)
        except Exception as e:
            logger.error("WooCommerce description rebuild failed: %s", e)
            woo_message = " Woo sync failed."

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="✅ Description rebuilt from current metadata and synced to Woo." + woo_message,
    )


def _derive_shop_base_url() -> str | None:
    base_env = os.getenv("SHOP_BASE_URL")
    if base_env:
        return base_env.rstrip("/")
    api_url = os.getenv("WC_API_URL")
    if not api_url:
        return None
    if "/wp-json/wc/" in api_url:
        return api_url.split("/wp-json/wc/")[0]
    return api_url.rsplit("/", 1)[0]


async def view_in_woo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await _ensure_admin(query):
        return
    await query.answer()
    item_id = int(query.data.split(":")[1])
    item = inventory_utils.get_inventory_by_id(item_id)
    if not item or not item.get("woo_product_id"):
        await query.answer("This item is not linked to a WooCommerce product.", show_alert=True)
        return
    base_url = _derive_shop_base_url()
    if not base_url:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="WooCommerce base URL is not configured.",
        )
        return
    product_url = f"{base_url}/?post_type=product&p={item['woo_product_id']}"
    admin_url = f"{base_url}/wp-admin/post.php?post={item['woo_product_id']}&action=edit"
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🛒 View product: {product_url}\nAdmin: {admin_url}",
    )


async def sync_all_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await _ensure_admin(query):
        return
    await query.answer()
    item_id = int(query.data.split(":")[1])
    item = inventory_utils.get_inventory_by_id(item_id)
    if not item:
        await query.answer("Item not found.", show_alert=True)
        return
    if not is_configured():
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="WooCommerce is not configured.",
        )
        return
    try:
        if not item.get("woo_product_id"):
            response = create_product_from_inventory(item, image_url=None)
            woo_id = response.get("id")
            if woo_id:
                with get_db() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "UPDATE inventory SET woo_product_id = ?, woo_synced = 1, woo_last_synced_at = ? WHERE id = ?",
                        (woo_id, datetime.datetime.utcnow().isoformat(), item_id),
                    )
                    conn.commit()
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"✅ Synced item to WooCommerce (ID: {woo_id}).",
                )
                return

        woo_id = int(item["woo_product_id"])
        update_product_price(woo_id, float(item.get("price_gel") or 0))
        update_product_stock(woo_id, int(item.get("quantity") or 0))
        update_product_metadata(woo_id, item)
        description = item.get("description") or build_generated_description(item)
        update_product_description(woo_id, description)
        set_woo_sync_flags(item_id)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="✅ All current inventory data synced to WooCommerce.",
        )
    except Exception as e:
        logger.error("WooCommerce sync failed: %s", e)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Sync encountered errors but local data remains updated.",
        )


def create_inventory_edit_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(edit_price_callback, pattern=r"^edit_price:\d+$"),
            CallbackQueryHandler(edit_stock_callback, pattern=r"^edit_stock:\d+$"),
            CallbackQueryHandler(edit_label_callback, pattern=r"^edit_label:\d+$"),
            CallbackQueryHandler(edit_genre_callback, pattern=r"^edit_genre:\d+$"),
            CallbackQueryHandler(edit_style_callback, pattern=r"^edit_style:\d+$"),
            CallbackQueryHandler(edit_format_callback, pattern=r"^edit_format:\d+$"),
            CallbackQueryHandler(edit_year_callback, pattern=r"^edit_year:\d+$"),
            CallbackQueryHandler(edit_description_callback, pattern=r"^edit_description:\d+$"),
        ],
        states={
            EDIT_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_price_update)],
            EDIT_STOCK: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_stock_update)],
            EDIT_LABEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_label_update)],
            EDIT_GENRE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_genre_update)],
            EDIT_STYLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_style_update)],
            EDIT_FORMAT_SELECT: [CallbackQueryHandler(set_format_callback, pattern=r"^set_format:.*")],
            EDIT_FORMAT_CUSTOM: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_format_custom)],
            EDIT_YEAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_year_update)],
            EDIT_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_description_update)],
        },
        fallbacks=[CommandHandler("cancel", cancel_inventory_search)],
        allow_reentry=True,
    )


def register_inventory_callbacks(application):
    application.add_handler(CallbackQueryHandler(inventory_detail_callback, pattern=r"^inventory_detail:\d+$"))
    application.add_handler(create_inventory_edit_conversation())
    application.add_handler(CallbackQueryHandler(edit_condition_callback, pattern=r"^edit_condition:\d+$"))
    application.add_handler(CallbackQueryHandler(set_condition_callback, pattern=r"^set_condition:.*"))
    application.add_handler(CallbackQueryHandler(rebuild_description_callback, pattern=r"^rebuild_description:\d+$"))
    application.add_handler(CallbackQueryHandler(view_in_woo_callback, pattern=r"^view_woo:\d+$"))
    application.add_handler(CallbackQueryHandler(sync_all_callback, pattern=r"^sync_all:\d+$"))

