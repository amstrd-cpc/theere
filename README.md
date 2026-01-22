# Record Store Bot

A password-protected Telegram assistant for running a vinyl shop from your phone. Add and edit inventory with Discogs-powered metadata, process multi-item sales, generate Excel reports, and keep WooCommerce product stock in sync automatically.

## What it does

- **Secure by default** – All core flows require login; per-user sessions time out automatically.
- **Inventory search & editing** – Browse the catalog, update price/stock/metadata, rebuild descriptions, and view low-stock items.
- **Discogs-powered add flow** – Search Discogs, pull artwork/tracklists, and create new items in both SQLite and WooCommerce.
- **Sales with cart support** – Ring up multiple items at once, log payment method (cash/POS), and store sales history.
- **WooCommerce integration** – Sync inventory to Woo, update descriptions/metadata, receive order webhooks, and poll recent orders for redundancy.
- **Reports on demand** – Generate daily/weekly/monthly Excel summaries and view recent sales directly in Telegram.

## Requirements

- Python 3.9+
- A Telegram bot token
- SQLite (bundled with Python) – a single local database (`clime_db_optimized.db`) stores inventory, sales, Woo info, and search indexes.
- Optional: WooCommerce API keys for product sync and order ingestion
- Optional: Discogs token for richer metadata when adding records

## Setup

1. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure environment** – create a `.env` file (loaded by `config.py`):
   ```env
   # Telegram
   BOT_TOKEN=123456:ABC-your-telegram-token
   ADMIN_IDS=123456789,987654321  # comma-separated Telegram user IDs
   ADMIN_CHAT_ID=123456789        # optional override for outbound alerts

   # Discogs enrichment (optional but recommended for /add)
   DISCOGS_TOKEN=your_discogs_token

   # WooCommerce sync (optional)
   WC_API_URL=https://yourshop.com/wp-json/wc/v3
   WC_CONSUMER_KEY=ck_...
   WC_CONSUMER_SECRET=cs_...
   WC_VERIFY_SSL=true           # set to false only if you knowingly use self-signed certs
   WOO_WEBHOOK_SECRET=supersecretpath  # used in webhook URL /wc-webhook/<secret>
   WEBHOOK_PORT=32412           # port for the Flask webhook server
   ```

3. **Run the bot**
   ```bash
   python bot.py
   ```
   The Telegram bot runs in polling mode. A lightweight Flask server starts in the same process to accept WooCommerce webhooks on `/wc-webhook/<WOO_WEBHOOK_SECRET>`.

4. **(Optional) Configure WooCommerce webhooks**
   - Point an order-created/updated webhook to `https://<your-host>/wc-webhook/<WOO_WEBHOOK_SECRET>`.
   - The bot also polls Woo every 5 minutes to backfill missed orders.

### Initial population (empty Woo shop)

If your WooCommerce store is currently empty and you want to publish your entire local inventory in one go (with **Discogs cover + tracklist enrichment** and stable identifiers), run:

```bash
python initial_sync_woo.py
```

The script is **idempotent**: it uses `SKU = inventory.id`, so re-running it will **not** create duplicates.

## Commands

All commands below require authentication unless noted.

- `/start`, `/help` – public welcome/help
- `/login`, `/logout`, `/status`, `/users` – session management
- `/add` – guided Discogs search → add inventory → sync to Woo (if configured)
- `/inventory` – search catalog, open item detail, and edit price/stock/condition/label/genre/style/format/year/description; rebuild descriptions; sync/view Woo product
- `/stock` – view low-quantity items
- `/sell` – cart-based checkout with payment method capture; updates inventory and Woo stock
- `/sales` – list recent sales
- `/reports` – command helper for report options
- `/daily`, `/weekly`, `/monthly` – send Excel reports and summaries

## Data & files

- `clime_db_optimized.db` – unified database (inventory + sales + Woo + FTS)
- `sales_reports/` – generated Excel reports
- `add_record.py`, `inventory.py`, `sales.py`, `reports.py`, `woocommerce_sync.py` – feature-specific modules used by `bot.py`

## Deployment notes

- The bot is self-contained; standard `python bot.py` works locally or on hosts like Railway/Render/Heroku.
- Ensure the webhook port is exposed if you expect WooCommerce to reach the bot; otherwise polling will still backfill orders.
- Do **not** share your `.env` file or database files publicly—both contain sensitive information.

## Troubleshooting

- **Auth errors:** confirm your Telegram user ID is listed in `ADMIN_IDS`.
- **Discogs lookups failing:** make sure `DISCOGS_TOKEN` is set and valid.
- **Woo sync issues:** verify `WC_API_URL`, keys, and that your host/port is reachable; check `WC_VERIFY_SSL` when using self-signed certs.
- **Reports missing data:** ensure sales are being inserted into the `sales` table in `clime_db_optimized.db` (use `/sales` to confirm recent entries).


## WooCommerce auto-sell

When a WooCommerce order comes in (status `processing` or `completed`), the bot will automatically:
- decrement local inventory quantity
- insert the sale into the `sales` table
- mark the order as processed to avoid double-selling on webhook retries

You can disable this behavior (notifications only) by setting:

- `AUTO_SELL_WOO=0`

