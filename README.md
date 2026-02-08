# Record Store Telegram Bot

Production-ready record store management bot for inventory, sales logging, Discogs enrichment, and WooCommerce sync.

## Features
- Inventory CRUD with suppliers (SQLite)
- Discogs search + enrichment (tracklist/cover)
- WooCommerce upsert by SKU (idempotent)
- Sales logging + Excel reports
- WooCommerce webhooks (FastAPI) with queue-backed processing
- Telegram-based order management (Woo-style status transitions)
- Discogs listing management and three-way sync (Local → Woo → Discogs)
- Auth-protected bot commands

## Requirements
- Python 3.10+
- Telegram bot token
- Redis (for webhook queue)
- Existing SQLite DB files (`clime_db.db`, `sales_log.db`) are supported; migrations are automatic

## Setup
1. **Create and activate a virtual environment**
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Create `.env`** (global settings only)
   ```env
   BOT_TOKEN=your_telegram_bot_token
   BOT_PASSWORD=your_password
   ADMIN_CHAT_ID=123456789
   ADMIN_IDS=123456789

   # Database
   RECORDSTORE_DB_FILE=clime_db.db
   SALES_DB_PATH=sales_log.db

   # Queue + API
   REDIS_URL=redis://localhost:6379/0
   API_BASE_URL=https://your-domain.example
   WEBHOOK_PORT=8080
   DEFAULT_STORE_ID=
   ```

   > WooCommerce and Discogs credentials are stored in the database via `/setup_woo` and `/connect_discogs`.

4. **Run migrations (optional, happens on startup)**
   ```bash
   python -m db.migrate
   ```

5. **Run services**
   - Bot: `python run.py bot`
   - Webhook API: `python run.py api`
   - Worker: `python run.py worker`

## Docker Compose (recommended)
```bash
docker compose up --build
```

## WooCommerce Webhook Verification
Woo sends a `X-WC-Webhook-Signature` header. The API validates it with the per-store webhook secret stored in the DB. Requests without a valid signature are rejected.

## Store Onboarding (Telegram)
1. `/setup_woo` → enter store URL + Woo REST credentials
2. Bot validates credentials and creates webhooks for `order.created` and `order.updated`
3. Webhook secrets and IDs are stored in the DB
4. Use `/settings` to control auto-decrement status and notifications

## Order Management
Use `/orders` in Telegram to list recent orders and move between Woo statuses (pending → processing → completed, etc.). The bot updates WooCommerce as the source of truth.

## Discogs Setup
1. Run `/connect_discogs` in Telegram and paste your personal access token.
2. Use `/discogs_status` to verify the connection.
3. Publish or link listings with `/publish_discogs` and `/link_discogs`.

## Mapping Strategy
- Best: Woo product meta `theere_id=<internal_id>`
- Else: SKU mapping
- Else: Woo product ID mapping
- If no mapping found, the order is flagged for review and inventory is not decremented

Use `/map_woo <woo_product_id> <internal_id> [sku]` to add mappings.
Use `/link_discogs <listing_id> <internal_id>` to link Discogs listings.

## Sync Model (Local → Woo → Discogs)
- **Local inventory is the source of truth** for quantity and identity.
- Woo and Discogs are treated as channels and reconciled to Local.
- Use `/reconcile_woo` and `/reconcile_discogs` to force a drift repair.
- Discogs polling (optional) uses the configured interval in `/settings`.

## Conflict Rules
- If Woo stock differs from Local, Local wins and `/reconcile_woo` re-applies Local quantities.
- If Discogs listing quantity differs from Local, Local wins and `/reconcile_discogs` re-applies Local quantities.
- Discogs sales outside the system are not auto-ingested (MVP); use `/discogs_refresh` to view a listing and reconcile if needed.

## Health Check
- `GET /health` returns queue length

## Development Notes
- Webhook endpoint is fast: validate → persist event → enqueue
- Worker does heavy processing: order fetch, inventory decrement, sales log, Discogs sync

## Tests
```bash
pytest
```
