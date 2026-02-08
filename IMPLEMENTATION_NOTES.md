# Implementation Notes

## Architecture Summary
- **Core domain**: order processing logic in `jobs/worker_tasks.py` + DB services (`services/order_service.py`, `services/product_map_service.py`).
- **Integrations**: WooCommerce REST client in `services/woo_service.py`, Discogs marketplace updates in `services/discogs_service.py`.
- **Webhook/API**: FastAPI app in `api/app.py` receives Woo webhooks and enqueues jobs.
- **Queue + Worker**: Redis + RQ (`jobs/queue.py`, `run.py worker`).
- **Telegram UI**: new commands in `telegram_ui/` for onboarding, settings, and orders.

## Idempotency Strategy
- **Webhook events** are deduplicated by `webhook_events.event_key` (Woo delivery ID or a deterministic hash).
- **Order line items** are deduplicated by a unique index on `(order_id, woo_line_item_id)`.
- **Inventory decrement** only occurs for line items that have not been recorded in `order_line_items`.
- Orders are marked `needs_review` when unmapped items exist; inventory application is skipped until mapping is resolved.
- Discogs listing updates use idempotent updates (quantity/price set to Local values).

## Mapping Strategy
1. Woo line item meta `theere_id`
2. SKU mapping (`product_map.sku`)
3. Woo product ID mapping (`product_map.woo_product_id`)
4. Unmapped items are reported to admin and stored for review

## Discogs Integration Notes
- Discogs tokens are stored per store and validated via `/oauth/identity`.
- Discogs listing lifecycle uses explicit publish/link actions; listings are updated to match Local stock.
- Discogs polling is optional (default disabled) and uses the store-configured interval to reconcile stock drift.

## Sync & Conflict Rules
- Local inventory is the source of truth for quantity and price.
- Woo/Discogs are reconciled to Local using `/reconcile_woo` and `/reconcile_discogs`.
- Discogs sales are not auto-ingested (MVP); use `/discogs_refresh` and manual reconciliation if needed.

## Store Configuration
- Woo credentials, webhook secrets, and webhook IDs are stored in `stores` table.
- Global settings (bot token, Redis URL, API base URL) remain in `.env`.

## Operational Notes
- Webhook endpoint only validates + persists + enqueues (fast path).
- Worker fetches full order payload from Woo to avoid relying on webhook payload alone.
- `run.py` provides three modes: `bot`, `api`, and `worker`.
