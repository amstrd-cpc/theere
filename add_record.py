from io import BytesIO
import asyncio
import logging
import os
from datetime import datetime

import discogs_client
import requests
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

load_dotenv()


from db import get_db, get_suppliers, get_or_create_supplier
from woocommerce_client import (
    is_configured,
    create_product_from_inventory,
    upload_image_from_bytes,
)


DISCOGS_TOKEN = os.getenv("DISCOGS_TOKEN")
_discogs_client = None


def get_discogs_client():
    global _discogs_client
    if _discogs_client:
        return _discogs_client
    if not DISCOGS_TOKEN:
        return None
    _discogs_client = discogs_client.Client(
        "RecordStoreApp/1.0", user_token=DISCOGS_TOKEN
    )
    return _discogs_client

(
    PRODUCT_TYPE,
    SEARCH_INPUT,
    SHOW_RESULTS,
    ASK_CONDITION,
    ASK_PRICE,
    ASK_QUANTITY,
    ASK_SUPPLIER,
    GENERIC_NAME,
    GENERIC_DESCRIPTION,
    GENERIC_PRICE,
    GENERIC_QUANTITY,
    GENERIC_IMAGE,
) = range(12)

CONDITION_OPTIONS = ["m", "nm", "vg+", "vg", "g+", "g", "f", "p"]

logger = logging.getLogger(__name__)


def fetch_usd_to_gel():
    try:
        today = datetime.now().strftime("%d.%m.%Y")
        url = f"https://nbg.gov.ge/gw/api/ct/monetarypolicy/currencies/en/json/?date={today}"
        response = requests.get(url)
        data = response.json()
        for item in data[0]["currencies"]:
            if item["code"] == "USD":
                return float(item["rate"])
    except Exception as e:
        print(f"Error fetching GEL rate: {e}")
    return 1.0


def save_to_inventory(row):
    """
    Keep DB schema as-is: store core fields only.
    Extra things like description/image_url live in Woo and in-memory item dicts.
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
        INSERT INTO inventory (
            artist_album, genre, style, label, format,
            condition, price_gel, quantity, supplier_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            row,
        )
        conn.commit()
        return cursor.lastrowid


def fetch_price_suggestions(release_id):
    client = get_discogs_client()
    if not client:
        return {}
    try:
        return client._get(
            f"https://api.discogs.com/marketplace/price_suggestions/{release_id}"
        )
    except Exception:
        return {}


def safe_join_list(data, default="N/A"):
    if not data:
        return default
    try:
        if isinstance(data, list):
            return ", ".join(str(item) for item in data if item)
        else:
            return str(data)
    except Exception:
        return default


def safe_get_labels(release):
    try:
        if hasattr(release, "labels") and release.labels:
            labels = [
                str(label.name) if hasattr(label, "name") else str(label)
                for label in release.labels
            ]
            return ", ".join(labels) if labels else "N/A"
        return "N/A"
    except Exception:
        return "N/A"


def safe_get_format(release):
    try:
        format_data = release.data.get("formats", [])
        format_parts = []
        for fmt in format_data:
            parts = []
            if fmt.get("name"):
                parts.append(str(fmt.get("name")))
            if fmt.get("descriptions"):
                parts.extend(str(desc) for desc in fmt.get("descriptions", []))
            if parts:
                format_parts.append(" ".join(parts))
        return ", ".join(format_parts) if format_parts else "Unknown Format"
    except Exception:
        return "Unknown Format"


# ---------- Entry point ----------


async def start_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """First ask what type of product we're adding."""
    context.user_data.clear()
    context.user_data["_add_flow_active"] = True
    buttons = [
        [InlineKeyboardButton("💿 Record (Vinyl)", callback_data="ptype_record")],
        [InlineKeyboardButton("🎛 Turntable", callback_data="ptype_turntable")],
        [InlineKeyboardButton("🎧 Accessory", callback_data="ptype_accessory")],
        [InlineKeyboardButton("📦 Other", callback_data="ptype_other")],
    ]
    await update.message.reply_text(
        "What kind of product do you want to add?",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return PRODUCT_TYPE


async def handle_product_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ptype = q.data.replace("ptype_", "")
    context.user_data["product_type"] = ptype

    if ptype == "record":
        await q.edit_message_text("Enter album name (Artist - Title):")
        return SEARCH_INPUT
    else:
        await q.edit_message_text("Enter product name:")
        return GENERIC_NAME


# ---------- Record (Discogs) flow ----------


async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not get_discogs_client():
        await update.message.reply_text(
            "❌ Discogs token is missing. Set DISCOGS_TOKEN to add records."
        )
        return ConversationHandler.END
    query = update.message.text.strip()
    context.user_data["query"] = query
    context.user_data["page"] = 1
    return await show_results(update, context)


async def show_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    client = get_discogs_client()
    if not client:
        await update.effective_message.reply_text(
            "❌ Discogs token is missing. Set DISCOGS_TOKEN to add records."
        )
        return ConversationHandler.END
    page = context.user_data["page"]
    query = context.user_data["query"]
    results = list(client.search(query, type="release").page(page))
    context.user_data["results"] = results

    if not results:
        await update.effective_message.reply_text(
            "❌ No releases found. Try another search."
        )
        return SEARCH_INPUT

    buttons = [
        [
            InlineKeyboardButton(
                f"{release.title} [{safe_get_format(release)}]"[:60],
                callback_data=f"select_{i}",
            )
        ]
        for i, release in enumerate(results)
    ]

    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data="prev"))
    if len(results) == 50:
        nav_buttons.append(InlineKeyboardButton("➡️ Next", callback_data="next"))
    if nav_buttons:
        buttons.append(nav_buttons)

    if update.callback_query:
        await update.callback_query.edit_message_text(
            "Select a release:", reply_markup=InlineKeyboardMarkup(buttons)
        )
    else:
        await update.message.reply_text(
            "Select a release:", reply_markup=InlineKeyboardMarkup(buttons)
        )

    return SHOW_RESULTS


async def handle_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query.data == "next":
        context.user_data["page"] += 1
    elif update.callback_query.data == "prev":
        context.user_data["page"] = max(1, context.user_data["page"] - 1)
    return await show_results(update, context)


async def handle_release_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    idx = int(update.callback_query.data.split("_")[1])
    results = context.user_data.get("results") or []
    if idx < 0 or idx >= len(results):
        await update.callback_query.edit_message_text(
            "❌ That selection is no longer available. Please search again."
        )
        return SEARCH_INPUT
    selected = results[idx]
    context.user_data["release"] = selected
    await update.callback_query.edit_message_text(
        f"Selected: {selected.title}\n\nNow choose vinyl condition:",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(c, callback_data=f"cond_{c}")
                    for c in CONDITION_OPTIONS[i : i + 4]
                ]
                for i in range(0, len(CONDITION_OPTIONS), 4)
            ]
        ),
    )
    return ASK_CONDITION


async def handle_condition_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cond = update.callback_query.data.split("_")[1]
    context.user_data["condition"] = cond
    release = context.user_data["release"]
    suggestions = fetch_price_suggestions(release.id)
    full_condition = {
        "m": "Mint (M)",
        "nm": "Near Mint (NM or M-)",
        "vg+": "Very Good Plus (VG+)",
        "vg": "Very Good (VG)",
        "g+": "Good Plus (G+)",
        "g": "Good (G)",
        "f": "Fair (F)",
        "p": "Poor (P)",
    }.get(cond)

    price_usd = suggestions.get(full_condition, {}).get("value", None)
    if price_usd:
        rate = fetch_usd_to_gel()
        price_gel = round(price_usd * rate, 2)
        context.user_data["suggested_price_usd"] = round(price_usd, 2)
        context.user_data["suggested_price_gel"] = price_gel
        msg = (
            f"Suggested price for {full_condition}: "
            f"${price_usd:.2f} ≈ {price_gel:.2f} GEL"
        )
    else:
        context.user_data["suggested_price_usd"] = None
        context.user_data["suggested_price_gel"] = None
        msg = "No price suggestion found."

    await update.callback_query.edit_message_text(
        msg + "\n\nSend your own price in GEL or type 'ok' to accept the suggested price."
    )
    return ASK_PRICE


async def handle_price_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text.strip()

    if msg.lower() == "ok" and context.user_data.get("suggested_price_gel") is not None:
        final_price = context.user_data["suggested_price_gel"]
    else:
        try:
            final_price = float(msg)
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid price. Please enter a valid number or 'ok' to accept suggested price:"
            )
            return ASK_PRICE

    context.user_data["final_price"] = round(final_price, 2)
    await update.message.reply_text("How many copies do you want to add?")
    return ASK_QUANTITY



async def handle_quantity_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        qty = int(update.message.text.strip())
        if qty < 1:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid quantity. Enter a whole number ≥ 1:"
        )
        return ASK_QUANTITY

    context.user_data["quantity"] = qty

    # If this is a record and Discogs has no image, reuse manual image flow
    ptype = context.user_data.get("product_type", "record")
    if ptype == "record":
        release = context.user_data.get("release")
        has_image = False
        try:
            images = getattr(release, "images", None)
            if images:
                has_image = len(images) > 0
        except Exception:
            has_image = False

        if not has_image:
            await update.message.reply_text(
                "No cover image was found on Discogs for this release.\n"
                "Send a cover photo as a Telegram image, paste an image URL, "
                "or type 'skip' to continue without an image:"
            )
            # We reuse the same generic image handler/state for records as for gear
            return GENERIC_IMAGE

    suppliers = get_suppliers()
    if suppliers:
        buttons = []
        for row in suppliers:
            try:
                sid = row["id"]
                name = row["name"]
            except (TypeError, KeyError, IndexError):
                sid, name = row
            buttons.append([InlineKeyboardButton(str(name), callback_data=f"sup_{sid}")])
        buttons.append([InlineKeyboardButton("➕ Other / Enter name", callback_data="sup_other")])
        await update.message.reply_text(
            "Select supplier (or tap “Other / Enter name” to type one):",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
    else:
        await update.message.reply_text("Enter supplier name:")

    return ASK_SUPPLIER



# ---------- Generic product flow (turntable / accessory / other) ----------


async def handle_generic_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["generic_name"] = update.message.text.strip()
    await update.message.reply_text(
        "Optional: enter product description for the website "
        "(or type 'skip' to leave it empty):"
    )
    return GENERIC_DESCRIPTION


async def handle_generic_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.lower() == "skip":
        context.user_data["generic_description"] = None
    else:
        context.user_data["generic_description"] = text

    await update.message.reply_text("Enter price in GEL:")
    return GENERIC_PRICE


async def handle_generic_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text.strip()
    try:
        price = float(msg)
        if price < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Invalid price. Enter a positive number:")
        return GENERIC_PRICE

    context.user_data["generic_price"] = round(price, 2)
    await update.message.reply_text("How many units do you want to add?")
    return GENERIC_QUANTITY


async def handle_generic_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        qty = int(update.message.text.strip())
        if qty < 1:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid quantity. Enter a whole number ≥ 1:"
        )
        return GENERIC_QUANTITY

    context.user_data["generic_quantity"] = qty

    await update.message.reply_text(
        "Send product photo as a Telegram image, "
        "or type 'skip' if you don't want an image:",
    )
    return GENERIC_IMAGE


async def handle_generic_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    For non-record products:
    - If user sends a Telegram photo → use Telegram file URL directly.
    - If user types 'skip'        → no image.
    - If user types http(s) URL   → use that.
    """
    image_url = None

    # user sent a photo
    if update.message.photo:
        tg_photo = update.message.photo[-1]
        tg_file = await tg_photo.get_file()
        # python-telegram-bot File.file_path is a full URL like:
        # https://api.telegram.org/file/bot<token>/<path>
        # Woo can fetch this and will download it as product image.
        image_url = tg_file.file_path
    else:
        # user sent text
        msg = update.message.text.strip()
        if msg.lower() == "skip":
            image_url = None
        elif msg.lower().startswith("http"):
            image_url = msg
        else:
            await update.message.reply_text(
                "Send a photo, or type 'skip', or paste an http(s) image URL."
            )
            return GENERIC_IMAGE

    context.user_data["generic_image_url"] = image_url

    await prompt_supplier(update, context)
    return ASK_SUPPLIER


async def prompt_supplier(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    suppliers = get_suppliers()
    if suppliers:
        buttons = []
        for row in suppliers:
            try:
                sid = row["id"]
                name = row["name"]
            except (TypeError, KeyError, IndexError):
                sid, name = row
            buttons.append([InlineKeyboardButton(str(name), callback_data=f"sup_{sid}")])
        buttons.append([InlineKeyboardButton("➕ Other / Enter name", callback_data="sup_other")])
        await update.message.reply_text(
            "Select supplier (or tap “Other / Enter name” to type one):",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
    else:
        await update.message.reply_text("Enter supplier name:")


# ---------- Supplier + final save ----------


async def handle_supplier_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("SUPPLIER STEP ENTER: has_callback=%s data=%s user_data_keys=%s", bool(update.callback_query), getattr(getattr(update, "callback_query", None), "data", None), list(getattr(context, "user_data", {}).keys()))
    """Finalize add flow: save to DB and optionally create a Woo product.

    Why this exists:
    - Your current version can "do nothing" if conversation state is missing (KeyError before try).
    - Woo calls are blocking; if Woo is slow, the bot looks frozen.
    - If an exception happens, you weren't guaranteed to send a message back.
    """

    q = update.callback_query
    context.chat_data["_skip_orphan_supplier_once"] = True

    
    # Always stop Telegram "loading…" instantly and show progress text
    if q:
        await q.answer()
        try:
            status_msg = await q.edit_message_text("⏳ Saving…")
        except Exception:
            status_msg = await update.effective_chat.send_message("⏳ Saving…")
    else:
        status_msg = await update.message.reply_text("⏳ Saving…")

    try:
        # --- Supplier selection / creation ---
        supplier_name = None
        supplier_id = None
        if q:
            raw_choice = (q.data or "").strip()
            if raw_choice == "sup_other":
                context.user_data["supplier_needs_name"] = True
                await status_msg.edit_text("Enter supplier name:")
                return ASK_SUPPLIER
            try:
                supplier_id = int(raw_choice.split("_", 1)[1])
            except (ValueError, IndexError):
                context.user_data["supplier_needs_name"] = True
                await status_msg.edit_text("Enter supplier name:")
                return ASK_SUPPLIER
        else:
            supplier_name = (update.message.text or "").strip()
            if not supplier_name:
                await status_msg.edit_text("Supplier name cannot be empty. Enter supplier name:")
                return ASK_SUPPLIER
            supplier_id = get_or_create_supplier(supplier_name)

        ptype = (context.user_data.get("product_type") or "record").strip().lower()

        # Helper: resolve supplier display name
        def supplier_display() -> str:
            if supplier_name:
                return supplier_name
            try:
                return next((row["name"] for row in get_suppliers() if int(row["id"]) == int(supplier_id)), "")
            except Exception:
                try:
                    return next((n for i, n in get_suppliers() if int(i) == int(supplier_id)), "")
                except Exception:
                    return ""

        # --- Record path ---
        if ptype == "record":
            release = context.user_data.get("release")
            cond = context.user_data.get("condition")
            price = context.user_data.get("final_price")
            qty = context.user_data.get("quantity")

            if not release or cond is None or price is None or qty is None:
                await status_msg.edit_text(
                    "❌ Add flow state was lost (missing release/condition/price/qty).\n"
                    "Run /add again."
                )
                return ConversationHandler.END

            row = [
                str(release.title),
                safe_join_list(getattr(release, "genres", None)),
                safe_join_list(getattr(release, "styles", None)),
                safe_get_labels(release),
                safe_get_format(release),
                str(cond),
                float(price),
                int(qty),
                supplier_id,
            ]

            new_id = save_to_inventory(row)

            item = {
                "id": new_id,
                "artist_album": str(release.title),
                "genre": safe_join_list(getattr(release, "genres", None)),
                "style": safe_join_list(getattr(release, "styles", None)),
                "label": safe_get_labels(release),
                "format": safe_get_format(release),
                "condition": str(cond),
                "price_gel": float(price),
                "quantity": int(qty),
                "supplier_id": supplier_id,
                "product_type": "record",
                "description": None,
            }

            # Prefer a manually provided image (if user was asked for one)
            image_url = context.user_data.get("generic_image_url")

            # If no manual image, try Discogs cover
            if not image_url:
                try:
                    images = getattr(release, "images", None)
                    if images:
                        first = images[0]
                        if isinstance(first, dict):
                            image_url = first.get("uri") or first.get("uri150")
                        else:
                            image_url = getattr(first, "uri", None) or getattr(first, "uri150", None)
                except Exception:
                    pass

            woo_note = ""
            if is_configured():
                # Update progress so you can tell it reached Woo sync
                await status_msg.edit_text("⏳ Saving…\n⏳ Syncing to Woo…")
                try:
                    # Woo requests are blocking -> run in thread
                    response = await asyncio.to_thread(create_product_from_inventory, item, image_url)
                    woo_id = (response or {}).get("id")
                    if woo_id:
                        now = datetime.utcnow().isoformat()
                        with get_db() as conn:
                            cur = conn.cursor()
                            cur.execute(
                                """
                                UPDATE inventory
                                SET woo_product_id = ?, woo_synced = 1, woo_last_synced_at = ?
                                WHERE id = ?
                                """,
                                (woo_id, now, new_id),
                            )
                            conn.commit()
                        woo_note = " (Woo ✅)"
                    else:
                        woo_note = " (Woo ⚠️ no id)"
                except Exception as e:
                    logger.exception("WooCommerce product creation failed for inventory %s", new_id)
                    woo_note = f" (Woo ❌ {e})"

            await status_msg.edit_text(
                f"✅ {qty} copy(ies) of '{release.title}' added from "
                f"{supplier_display()} at {float(price):.2f} GEL each.{woo_note}"
            )

        # --- Generic path ---
        else:
            name = context.user_data.get("generic_name")
            price = context.user_data.get("generic_price")
            qty = context.user_data.get("generic_quantity")

            if not name or price is None or qty is None:
                await status_msg.edit_text(
                    "❌ Add flow state was lost (missing name/price/qty).\n"
                    "Run /add again."
                )
                return ConversationHandler.END

            desc = context.user_data.get("generic_description")
            img = context.user_data.get("generic_image_url")

            row = [
                name,
                None,
                None,
                None,
                ptype,
                "N/A",
                float(price),
                int(qty),
                supplier_id,
            ]

            new_id = save_to_inventory(row)

            item = {
                "id": new_id,
                "artist_album": name,
                "genre": None,
                "style": None,
                "label": None,
                "format": ptype,
                "condition": "N/A",
                "price_gel": float(price),
                "quantity": int(qty),
                "supplier_id": supplier_id,
                "product_type": ptype,
                "description": desc,
            }

            woo_note = ""
            if is_configured():
                await status_msg.edit_text("⏳ Saving…\n⏳ Syncing to Woo…")
                try:
                    response = await asyncio.to_thread(create_product_from_inventory, item, img)
                    woo_id = (response or {}).get("id")
                    if woo_id:
                        now = datetime.utcnow().isoformat()
                        with get_db() as conn:
                            cur = conn.cursor()
                            cur.execute(
                                """
                                UPDATE inventory
                                SET woo_product_id = ?, woo_synced = 1, woo_last_synced_at = ?
                                WHERE id = ?
                                """,
                                (woo_id, now, new_id),
                            )
                            conn.commit()
                        woo_note = " (Woo ✅)"
                    else:
                        woo_note = " (Woo ⚠️ no id)"
                except Exception as e:
                    logger.exception("WooCommerce product creation failed for inventory %s", new_id)
                    woo_note = f" (Woo ❌ {e})"

            await status_msg.edit_text(
                f"✅ {qty} × '{name}' ({ptype}) added from "
                f"{supplier_display()} at {float(price):.2f} GEL each.{woo_note}"
            )

    except Exception as e:
        logger.exception("handle_supplier_input crashed")
        try:
            await status_msg.edit_text(f"❌ Error in supplier step: {e}")
        except Exception:
            await update.effective_message.reply_text(f"❌ Error in supplier step: {e}")

    finally:
        # mark flow inactive (even if we clear user_data)
        context.user_data.pop("_add_flow_active", None)
        context.user_data.clear()

    return ConversationHandler.END


async def handle_supplier_other(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        return ASK_SUPPLIER
    await q.answer()
    await q.edit_message_text("Enter supplier name:")
    return ASK_SUPPLIER


async def orphan_supplier_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fallback for stale supplier buttons.

    If the user clicks an old 'Select supplier' inline keyboard after the /add flow ended
    (or after the bot restarted), the ConversationHandler won't be active, so nothing will happen.
    This handler exists purely to ACK the callback and tell the user what to do.

    It is safe during an active /add flow because we set _add_flow_active=True at /add entry.
    """
    q = update.callback_query
    if not q:
        return

    if context.chat_data.pop("_skip_orphan_supplier_once", None):
        return

    try:
        await q.answer()
    except Exception:
        pass

    msg = "⚠️ This supplier picker is no longer active.\nRun /add again and pick the supplier there."
    try:
        await q.edit_message_text(msg)
    except Exception:
        await update.effective_chat.send_message(msg)


async def cancel_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the add flow from any state."""
    context.user_data.clear()
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("🚫 Add flow cancelled.")
    else:
        await update.message.reply_text("🚫 Add flow cancelled.")
    return ConversationHandler.END


def start_add_flow():
    return ConversationHandler(
        entry_points=[CommandHandler("add", start_add)],
        states={
            PRODUCT_TYPE: [
                CallbackQueryHandler(handle_product_type, pattern=r"^ptype_")
            ],
            SEARCH_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search)
            ],
            SHOW_RESULTS: [
                CallbackQueryHandler(handle_release_select, pattern=r"^select_"),
                CallbackQueryHandler(handle_pagination, pattern="^(next|prev)$"),
            ],
            ASK_CONDITION: [
                CallbackQueryHandler(handle_condition_select, pattern=r"^cond_")
            ],
            ASK_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_price_input)
            ],
            ASK_QUANTITY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_quantity_input)
            ],
            GENERIC_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_generic_name)
            ],
            GENERIC_DESCRIPTION: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, handle_generic_description
                )
            ],
            GENERIC_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_generic_price)
            ],
            GENERIC_QUANTITY: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, handle_generic_quantity
                )
            ],
            GENERIC_IMAGE: [
                MessageHandler(
                    (filters.PHOTO | (filters.TEXT & ~filters.COMMAND)),
                    handle_generic_image,
                )
            ],
            ASK_SUPPLIER: [
                CallbackQueryHandler(
                    handle_supplier_input, pattern=r"^sup_(\d+|other)$"
                ),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_supplier_input),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_add)],
        name="add_record",
        persistent=False,
    )
