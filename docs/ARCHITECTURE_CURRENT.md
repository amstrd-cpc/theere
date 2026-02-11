# Current Architecture

## Runtime entrypoint: `run.py`
- Initializes DB via `init_db()` before selecting mode.
- `python run.py bot`: imports `bot.main` and starts Telegram polling runtime.
- `python run.py api`: launches FastAPI with Uvicorn on `0.0.0.0:<WEBHOOK_PORT>`.
- `python run.py worker`: starts RQ `Worker` bound to the shared queue connection.
- Invalid/no mode exits with usage guidance.

## Webhook path: `api/app.py`
- `POST /webhooks/woo/{store_id}` flow:
  1. Rate-limit by client IP (`SimpleRateLimiter`).
  2. Resolve store by `store_id`; 404 when missing.
  3. Validate Woo HMAC signature (`X-WC-Webhook-Signature`) against store secret.
  4. Parse JSON payload; build idempotency key from delivery header or topic+order+payload hash.
  5. Persist webhook event via `create_webhook_event` (dedupe-aware).
  6. Enqueue `process_woo_webhook_event(event_id)` on RQ.
- Duplicate events return `{status: "duplicate"}` without enqueueing.
- `GET /health` reports queue length and last webhook receive/process timestamps.

## Worker path: `jobs/worker_tasks.py`
- `process_woo_webhook_event(event_id)` loads event + store, then calls `sync_order_state(store_id, woo_order_id)` when present.
- On success: marks event processed; on exception: marks failed and notifies admin with failure message.
- `sync_order_state` fetches Woo order and applies local effects when target statuses match settings (default trigger `processing`).
- `apply_inventory_decrement_for_order` resolves local products via mapping strategy (theere_id → SKU → Woo IDs), decrements inventory, records sales, and optionally syncs listing quantities to Discogs.
- Missing mappings/items are collected into warnings and surfaced through admin notification + order note path.

## Sync flow: `services/sync_engine.py`
- `SyncEngine.run_periodic_sync` is the orchestrator for Woo sync runs:
  - validates store/config/settings, starts `sync_runs` record, runs `sync_orders`, then `reconcile_catalog`, and finalizes run counters/errors.
- `sync_orders` fetches Woo orders at configured trigger status and reuses worker-grade `sync_order_state` logic for consistency.
- `reconcile_catalog` pages Woo products and performs per-product reconciliation via `_reconcile_product` with incoming-policy controls.
- Reconciliation outcomes include pull, push, local-create, mapping-fix, drift/conflict counters, and structured inventory event logging.
- `run_instant_sync_for_item` enables per-item push behavior when instant sync is enabled.

## Three-way sync flow: `services/tri_sync_service.py`
- Maintains separate tri-sync runs (`tri_sync_runs`) with start/finish bookkeeping and counters (`incoming/applied/drifted/conflict/errors`).
- `poll_discogs_listings(store_id)`: compares Discogs snapshots vs local snapshots + mapping hashes/timestamps; decides pull/push using `_should_pull_remote` / `_should_push_local`.
- `poll_woo_products(store_id)`: same three-way decision model for Woo product snapshots.
- Conflict rule: when both local and remote changed after `last_sync_at`, a hard conflict is counted and local wins (push local).
- Incoming-disabled channels mark remote deltas as drift instead of applying to local inventory.
- After each item decision, map rows are updated with `*_last_seen_*` fields and (when applied/pushed) sync direction/hash timestamps.
