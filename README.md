# Record Store Telegram Bot

Production-grade Telegram bot for inventory management, sales logging, Discogs enrichment, and WooCommerce sync.

## Features
- Inventory CRUD with suppliers (SQLite)
- Discogs search + enrichment (tracklist/cover)
- WooCommerce upsert by SKU (idempotent)
- Sales logging + Excel reports
- Periodic Woo sync + order polling
- Auth-protected bot commands

## Requirements
- Python 3.10+
- Telegram bot token
- Existing SQLite DB files (`clime_db.db`, `sales_log.db`) are supported; migrations are automatic

## Setup (Windows friendly)
1. **Create and activate a virtual environment**
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Create `.env`** (in repo root)
   ```env
   BOT_TOKEN=your_telegram_bot_token
   BOT_PASSWORD=your_password
   ADMIN_CHAT_ID=123456789
   ADMIN_IDS=123456789

   # Discogs
   DISCOGS_TOKEN=your_discogs_token

   # WooCommerce
   WC_API_URL=https://yourstore.com/wp-json/wc/v3
   WC_CONSUMER_KEY=ck_...
   WC_CONSUMER_SECRET=cs_...
   WC_VERIFY_SSL=true

   # Optional
   RECORDSTORE_DB_FILE=clime_db.db
   SALES_DB_PATH=sales_log.db
   WC_WEBHOOK_SECRET=your_webhook_secret
   WEBHOOK_PORT=32412
   AUTO_SELL_WOO=1
   SESSION_TIMEOUT_HOURS=24
   ```

4. **Run migrations (optional, happens on startup)**
   ```bash
   python -m db.migrate
   ```

5. **Run the bot**
   ```bash
   python bot.py
   ```

## Notes
- `/add` uses Discogs and immediately syncs to WooCommerce after saving locally.
- Long operations include retries and timeouts.
- Woo order polling runs every 5 minutes (configurable in `bot.py`).

## Tests
```bash
pytest
```
