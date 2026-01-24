"""add_record.py

Discogs-powered add flow for inventory.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from auth import require_auth
from db import get_db, get_or_create_supplier, get_suppliers
from woocommerce_sync import upsert_product_async

load_dotenv()

logger = logging.getLogger(__name__)

DISCogs_BASE_URL = "https://api.discogs.com"
DISCogs_USER_AGENT = os.getenv("DISCOGS_USER_AGENT", "RecordStoreBot/1.0")
RESULTS_PER_PAGE = 5
DISCogs_TOKEN = (os.getenv("DISCOGS_TOKEN") or "").strip()

(
    WAITING_FOR_QUERY,
    WAITING_FOR_RESULTS,
    WAITING_FOR_CONDITION,
    WAITING_FOR_PRICE_CHOICE,
    WAITING_FOR_PRICE_INPUT,
    WAITING_FOR_SUPPLIER,
    WAITING_FOR_SUPPLIER_NAME,
) = range(7)

CONDITIONS = ["M", "NM", "VG+", "VG", "G+", "G", "F", "P"]


def _discogs_headers() -> Dict[str, str]:
    headers = {
        "User-Agent": DISCogs_USER_AGENT,
    }
    if DISCogs_TOKEN:
        headers["Authorization"] = f"Discogs token={DISCogs_TOKEN}"
    return headers


def _discogs_get(path: str, params: Optional[dict] = None) -> Dict[str, Any]:
    url = f"{DISCogs_BASE_URL}{path}"
    response = requests.get(url, headers=_discogs_headers(), params=params, timeout=20)
    response.raise_for_status()
    return response.json()


def _build_artist_album_from_release(release: Dict[str, Any]) -> str:
    artists = release.get("artists_sort") or release.get("artists")
    title = release.get("title") or "Unknown"
    if isinstance(artists, str) and artists.strip():
        return f"{artists.strip()} - {title}".strip()
    if isinstance(artists, list) and artists:
        name = artists[0].get("name") if isinstance(artists[0], dict) else str(artists[0])
        if name:
            return f"{name} - {title}".strip()
    return title


def _build_format(release: Dict[str, Any]) -> str:
    formats = release.get("formats") or []
    if not formats:
        return ""
    parts: List[str] = []
    for fmt in formats:
        if not isinstance(fmt, dict):
            continue
        name = fmt.get("name")
        descriptions = fmt.get("descriptions") or []
        text = fmt.get("text")
        segment = []
        if name:
            segment.append(str(name))
        if descriptions:
            segment.extend([str(d) for d in descriptions])
        if text:
            segment.append(str(text))
        if segment:
            parts.append(", ".join(segment))
    return " / ".join(parts)


def _build_description(release: Dict[str, Any]) -> str:
    notes = (release.get("notes") or "").strip()
    tracklist = release.get("tracklist") or []
    track_lines = []
    for track in tracklist:
        if not isinstance(track, dict):
            continue
        position = track.get("position") or ""
        title = track.get("title") or ""
        if not title:
            continue
        label = f"{position} {title}".strip()
        track_lines.append(label)
    if track_lines:
        track_section = "Tracklist:\n" + "\n".join(track_lines)
    else:
        track_section = ""
    return "\n\n".join(part for part in [notes, track_section] if part)


def _safe_release_title(item: Dict[str, Any]) -> str:
    title = item.get("title") or "Unknown"
    year = item.get("year")
    label = item.get("label") or ""
    parts = [str(title)]
    if year:
        parts.append(str(year))
    if label:
        parts.append(str(label))
    label_text = " · ".join(parts)
    return label_text[:64]


def _build_results_keyboard(results: List[Dict[str, Any]], page: int, pages: int) -> InlineKeyboardMarkup:
    buttons = []
    for idx, item in enumerate(results):
        buttons.append(
            [InlineKeyboardButton(_safe_release_title(item), callback_data=f"add_select:{idx}")]
        )

    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"add_page:{page - 1}"))
    if page < pages:
        nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"add_page:{page + 1}"))
    if nav_row:
        buttons.append(nav_row)
    return InlineKeyboardMarkup(buttons)


def _build_condition_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for idx, condition in enumerate(CONDITIONS, start=1):
        row.append(InlineKeyboardButton(condition, callback_data=f"add_condition:{condition}"))
        if idx % 4 == 0:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)


def _build_price_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Use recommended", callback_data="add_price:recommended")],
            [InlineKeyboardButton("Enter custom", callback_data="add_price:custom")],
        ]
    )


def _build_supplier_keyboard(suppliers: List[Any]) -> InlineKeyboardMarkup:
    buttons = []
    for supplier in suppliers:
        buttons.append(
            [
                InlineKeyboardButton(
                    supplier["name"],
                    callback_data=f"sup_{supplier['id']}",
                )
            ]
        )
    buttons.append([InlineKeyboardButton("Other (type name)", callback_data="sup_other")])
    return InlineKeyboardMarkup(buttons)


def _clear_add_flow(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("add_flow", None)
    context.user_data.pop("discogs_results", None)
    context.user_data.pop("discogs_page", None)
    context.user_data.pop("discogs_pages", None)
    context.user_data.pop("discogs_query", None)


async def _discogs_search(query: str, page: int) -> Tuple[List[Dict[str, Any]], int]:
    params = {
        "q": query,
        "type": "release",
        "page": page,
        "per_page": RESULTS_PER_PAGE,
    }
    data = await asyncio.to_thread(_discogs_get, "/database/search", params)
    results = data.get("results") or []
    pages = data.get("pagination", {}).get("pages") or 1
    return results, int(pages)


async def _discogs_release(release_id: int) -> Dict[str, Any]:
    return await asyncio.to_thread(_discogs_get, f"/releases/{release_id}")


async def _discogs_marketplace_stats(release_id: int) -> Dict[str, Any]:
    return await asyncio.to_thread(_discogs_get, f"/marketplace/stats/{release_id}")


def _format_price_suggestion(stats: Dict[str, Any]) -> Tuple[str, Optional[float]]:
    median = stats.get("median_price")
    lowest = stats.get("lowest_price")
    recommended = None

    if isinstance(median, dict):
        recommended = median.get("value")
    elif median is not None:
        recommended = median

    if recommended is None:
        if isinstance(lowest, dict):
            recommended = lowest.get("value")
        elif lowest is not None:
            recommended = lowest

    if recommended is None:
        return "No marketplace stats available for this release.", None

    try:
        recommended_value = float(recommended)
    except (TypeError, ValueError):
        return "No marketplace stats available for this release.", None

    return f"Discogs median/lowest price: ${recommended_value:.2f} USD", recommended_value


@require_auth
async def start_add_flow_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Add flow started by user=%s", update.effective_user.id)
    context.user_data.clear()
    context.user_data["add_flow"] = {}
    await update.message.reply_text(
        "🔍 Enter artist or album to search Discogs (or /cancel to stop)."
    )
    return WAITING_FOR_QUERY


async def handle_search_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = (update.message.text or "").strip()
    if not query:
        await update.message.reply_text("Please enter a search query (artist or album).")
        return WAITING_FOR_QUERY

    if not DISCogs_TOKEN:
        await update.message.reply_text(
            "Discogs token is not configured. Set DISCOGS_TOKEN in .env and try again."
        )
        logger.warning("Discogs search blocked: missing DISCOGS_TOKEN")
        return WAITING_FOR_QUERY

    logger.info("Add flow search query received: %s", query)
    await update.message.reply_text("Searching Discogs...")

    try:
        results, pages = await _discogs_search(query, page=1)
    except Exception as exc:
        logger.exception("Discogs search failed: %s", exc)
        await update.message.reply_text("❌ Discogs search failed. Please try again.")
        return WAITING_FOR_QUERY

    if not results:
        await update.message.reply_text("No results found. Try another query.")
        return WAITING_FOR_QUERY

    context.user_data["discogs_results"] = results
    context.user_data["discogs_page"] = 1
    context.user_data["discogs_pages"] = pages
    context.user_data["discogs_query"] = query

    keyboard = _build_results_keyboard(results, 1, pages)
    await update.message.reply_text(
        f"Found results for: {query}\nSelect a release:", reply_markup=keyboard
    )
    logger.info("Add flow results page 1/%s shown", pages)
    return WAITING_FOR_RESULTS


async def handle_results_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if "discogs_query" not in context.user_data:
        await query.edit_message_text("This search has expired. Use /add to start again.")
        return ConversationHandler.END

    try:
        page = int(query.data.split(":", 1)[1])
    except (IndexError, ValueError):
        await query.edit_message_text("Invalid page selection. Use /add to start again.")
        return ConversationHandler.END

    search_query = context.user_data.get("discogs_query", "")

    try:
        results, pages = await _discogs_search(search_query, page=page)
    except Exception as exc:
        logger.exception("Discogs pagination failed: %s", exc)
        await query.edit_message_text("❌ Failed to load that page. Try again.")
        return WAITING_FOR_RESULTS

    context.user_data["discogs_results"] = results
    context.user_data["discogs_page"] = page
    context.user_data["discogs_pages"] = pages

    keyboard = _build_results_keyboard(results, page, pages)
    await query.edit_message_text(
        f"Results for: {search_query}\nSelect a release:", reply_markup=keyboard
    )
    logger.info("Add flow results page %s/%s shown", page, pages)
    return WAITING_FOR_RESULTS


async def handle_release_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    results = context.user_data.get("discogs_results") or []
    try:
        idx = int(query.data.split(":", 1)[1])
    except (IndexError, ValueError):
        await query.edit_message_text("Invalid selection. Use /add to start again.")
        return ConversationHandler.END

    if idx < 0 or idx >= len(results):
        await query.edit_message_text("This selection is no longer available. Use /add again.")
        return ConversationHandler.END

    release_summary = results[idx]
    release_id = release_summary.get("id")
    if not release_id:
        await query.edit_message_text("Release ID missing. Use /add again.")
        return ConversationHandler.END

    logger.info("Release selected: discogs_id=%s", release_id)

    try:
        release = await _discogs_release(int(release_id))
    except Exception as exc:
        logger.exception("Discogs release fetch failed: %s", exc)
        await query.edit_message_text("❌ Failed to load release details. Try again.")
        return WAITING_FOR_RESULTS

    artist_album = _build_artist_album_from_release(release)
    genre = ", ".join(release.get("genres") or [])
    style = ", ".join(release.get("styles") or [])
    label = ""
    labels = release.get("labels") or []
    if labels and isinstance(labels[0], dict):
        label = labels[0].get("name") or ""
    year = release.get("year")
    fmt = _build_format(release)
    description = _build_description(release)

    context.user_data["add_flow"] = {
        "discogs_id": int(release_id),
        "artist_album": artist_album,
        "genre": genre,
        "style": style,
        "label": label,
        "format": fmt,
        "year": year,
        "description": description,
        "quantity": 1,
    }

    await query.edit_message_text(
        f"Selected: {artist_album}\nNow choose condition:",
        reply_markup=_build_condition_keyboard(),
    )
    logger.info("Condition prompt shown for discogs_id=%s", release_id)
    return WAITING_FOR_CONDITION


async def handle_condition(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = context.user_data.get("add_flow")
    if not data:
        await query.edit_message_text("This add flow has expired. Use /add again.")
        return ConversationHandler.END

    condition = query.data.split(":", 1)[1]
    data["condition"] = condition
    logger.info("Condition set: %s", condition)

    stats_msg = "Fetching Discogs marketplace stats..."
    await query.edit_message_text(stats_msg)

    stats_text = ""
    try:
        stats = await _discogs_marketplace_stats(int(data["discogs_id"]))
        stats_text, recommended = _format_price_suggestion(stats)
        data["discogs_price_usd"] = recommended
    except Exception as exc:
        logger.exception("Discogs marketplace stats failed: %s", exc)
        stats_text = "No marketplace stats available for this release."
        data["discogs_price_usd"] = None

    await query.edit_message_text(
        f"{stats_text}\n\nChoose how to set price:",
        reply_markup=_build_price_keyboard(),
    )
    logger.info("Price choice prompt shown")
    return WAITING_FOR_PRICE_CHOICE


async def handle_price_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = context.user_data.get("add_flow")
    if not data:
        await query.edit_message_text("This add flow has expired. Use /add again.")
        return ConversationHandler.END

    choice = query.data.split(":", 1)[1]
    data["price_choice"] = choice
    suggested = data.get("discogs_price_usd")

    if choice == "recommended" and suggested is not None:
        prompt = f"Suggested (USD): ${suggested:.2f}\nEnter price in GEL:"
    else:
        prompt = "Enter price in GEL:"

    await query.edit_message_text(prompt)
    logger.info("Price choice made: %s", choice)
    return WAITING_FOR_PRICE_INPUT


async def handle_price_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = context.user_data.get("add_flow")
    if not data:
        await update.message.reply_text("This add flow has expired. Use /add again.")
        return ConversationHandler.END

    raw = (update.message.text or "").strip()
    try:
        price_gel = float(raw)
        if price_gel < 0:
            raise ValueError("negative")
    except ValueError:
        await update.message.reply_text("Please enter a valid GEL price (e.g., 45 or 45.50).")
        return WAITING_FOR_PRICE_INPUT

    data["price_gel"] = price_gel
    logger.info("Price set: %.2f", price_gel)

    suppliers = get_suppliers()
    keyboard = _build_supplier_keyboard(suppliers)
    await update.message.reply_text("Select supplier:", reply_markup=keyboard)
    logger.info("Supplier list shown")
    return WAITING_FOR_SUPPLIER


async def handle_supplier_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = context.user_data.get("add_flow")
    if not data:
        await query.edit_message_text("This add flow has expired. Use /add again.")
        return ConversationHandler.END

    supplier_token = query.data.split("_", 1)[1]
    if supplier_token == "other":
        await query.edit_message_text("Type supplier name:")
        logger.info("Supplier custom name requested")
        return WAITING_FOR_SUPPLIER_NAME

    try:
        supplier_id = int(supplier_token)
    except ValueError:
        await query.edit_message_text("Invalid supplier selection. Use /add again.")
        return ConversationHandler.END

    data["supplier_id"] = supplier_id
    logger.info("Supplier selected: %s", supplier_id)

    await query.edit_message_text("Saving record locally...")
    return await _finalize_add_flow(update, context)


async def handle_supplier_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = context.user_data.get("add_flow")
    if not data:
        await update.message.reply_text("This add flow has expired. Use /add again.")
        return ConversationHandler.END

    name = (update.message.text or "").strip()
    if not name:
        await update.message.reply_text("Supplier name cannot be empty. Please enter a name.")
        return WAITING_FOR_SUPPLIER_NAME

    try:
        supplier_id = get_or_create_supplier(name)
    except Exception as exc:
        logger.exception("Supplier create failed: %s", exc)
        await update.message.reply_text("Failed to save supplier. Try again.")
        return WAITING_FOR_SUPPLIER_NAME

    data["supplier_id"] = supplier_id
    logger.info("Supplier created: %s", supplier_id)

    await update.message.reply_text("Saving record locally...")
    return await _finalize_add_flow(update, context)


def _insert_inventory_row(item: Dict[str, Any]) -> int:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO inventory (
                artist_album, genre, style, label, format, condition,
                price_gel, quantity, supplier_id, year, description
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.get("artist_album"),
                item.get("genre"),
                item.get("style"),
                item.get("label"),
                item.get("format"),
                item.get("condition"),
                item.get("price_gel"),
                item.get("quantity", 1),
                item.get("supplier_id"),
                item.get("year"),
                item.get("description"),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


async def _finalize_add_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = context.user_data.get("add_flow")
    if not data:
        return ConversationHandler.END

    try:
        inventory_id = await asyncio.to_thread(_insert_inventory_row, data)
    except Exception as exc:
        logger.exception("DB insert failed: %s", exc)
        if update.callback_query:
            await update.callback_query.edit_message_text("❌ Failed to save record locally.")
        else:
            await update.message.reply_text("❌ Failed to save record locally.")
        _clear_add_flow(context)
        return ConversationHandler.END

    data["inventory_id"] = inventory_id
    logger.info("Inventory insert OK: id=%s", inventory_id)

    if update.callback_query:
        await update.callback_query.edit_message_text("Saved locally ✅")
    else:
        await update.message.reply_text("Saved locally ✅")

    _clear_add_flow(context)

    await _start_woo_sync(update, context, data)
    return ConversationHandler.END


async def _start_woo_sync(update: Update, context: ContextTypes.DEFAULT_TYPE, item: Dict[str, Any]):
    logger.info("Woo sync started for inventory %s", item.get("inventory_id"))

    if update.callback_query:
        await update.callback_query.message.reply_text("🛒 Woo sync started...")
    else:
        await update.message.reply_text("🛒 Woo sync started...")

    async def _run():
        try:
            product = await upsert_product_async(item, update=update, context=context)
            product_id = product.get("id") if isinstance(product, dict) else None
            logger.info("Woo sync success for inventory %s", item.get("inventory_id"))
            message = "🛒 Woo sync success ✅"
            if product_id:
                message += f" (Product ID: {product_id})"
        except Exception as exc:
            logger.exception("Woo sync failed: %s", exc)
            message = "🛒 Woo sync failed ❌"

        if update.callback_query:
            await update.callback_query.message.reply_text(message)
        else:
            await update.message.reply_text(message)

    context.application.create_task(_run())


async def cancel_add_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Add flow cancelled by user=%s", update.effective_user.id)
    _clear_add_flow(context)
    await update.message.reply_text("Add flow cancelled.")
    return ConversationHandler.END


async def orphan_supplier_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("This supplier selection has expired. Use /add to start again.")
    return ConversationHandler.END


def build_add_record_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("add", start_add_flow_handler)],
        states={
            WAITING_FOR_QUERY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search_query),
            ],
            WAITING_FOR_RESULTS: [
                CallbackQueryHandler(handle_results_pagination, pattern=r"^add_page:\d+$"),
                CallbackQueryHandler(handle_release_select, pattern=r"^add_select:\d+$"),
            ],
            WAITING_FOR_CONDITION: [
                CallbackQueryHandler(handle_condition, pattern=r"^add_condition:"),
            ],
            WAITING_FOR_PRICE_CHOICE: [
                CallbackQueryHandler(handle_price_choice, pattern=r"^add_price:"),
            ],
            WAITING_FOR_PRICE_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_price_input),
            ],
            WAITING_FOR_SUPPLIER: [
                CallbackQueryHandler(handle_supplier_callback, pattern=r"^sup_(\d+|other)$"),
            ],
            WAITING_FOR_SUPPLIER_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_supplier_name),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_add_flow)],
        name="add_record_flow",
        persistent=False,
    )


def start_add_flow():
    """Compatibility wrapper for bot.py (returns ConversationHandler)."""
    return build_add_record_conversation()


__all__ = [
    "start_add_flow_handler",
    "start_add_flow",
    "build_add_record_conversation",
    "orphan_supplier_callback",
]
