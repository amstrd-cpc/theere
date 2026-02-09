# Sync Overview

This project uses a sync engine (`SyncEngine`) plus optional three-way polling to keep local inventory, WooCommerce, and Discogs listings in sync. Sync touches **quantity** and **regular_price** (local field `price_gel`) by default, and can include other fields via incoming whitelists. Currency is GEL across systems.

## Instant vs Periodic

**Instant sync** runs immediately after manual bot edits to quantity or price. It pushes local changes to WooCommerce (local → Woo). This keeps Woo updated right away.

**Periodic sync** runs every 5 minutes as a safety net. It always:

1. Syncs orders first (to apply inventory decrements idempotently)
2. Reconciles catalog changes (quantity + price) with last-write-wins

Instant sync does not replace periodic sync; both run together.

## Orders-first rule

Before catalog reconciliation, the engine syncs Woo orders and applies inventory decrements **exactly once** per order. The order record tracks `inventory_applied_at` to ensure idempotency. Admin notifications include order ID, items, totals, and notes.

## Conflict resolution (LWW)

Catalog reconciliation uses Last-Write-Wins (LWW):

- **Woo timestamp:** `date_modified` from Woo API (stored as `product_map.woo_last_seen_modified_at`)
- **Local timestamp:** `inventory.updated_at`

Decision:

- Woo modified time > local updated time → **pull Woo → local**
- Local updated time > Woo modified time → **push local → Woo**
- Equal/ambiguous → no change, wait for next cycle

Alternative strategies can be selected in the WooCommerce integration screen:

- **Woo wins** (always pull)
- **Local wins** (always push)

## Push-only vs bidirectional

Incoming changes are blocked by default (push-only mode). Enable incoming changes per channel:

- `woo_allow_incoming`
- `discogs_allow_incoming`

Incoming field whitelists control which fields are applied:

- Woo: `quantity`, `price`, `description`, `images`
- Discogs: `quantity`, `listing_price`, `condition`, `comments`

Fields like internal IDs, SKUs, mappings, supplier info, and costs are never accepted.

## Three-way sync (Woo + Discogs)

When `three_way_sync_enabled` is on, the bot schedules two polling jobs:

- Discogs listings: `three_way_discogs_interval_minutes`
- Woo products: `three_way_woo_interval_minutes`

Each run records:

- **Incoming** changes detected
- **Applied** changes written locally
- **Drifted** changes ignored due to push-only mode/whitelists
- **Conflicts** where both local + remote changed after `last_sync_at`

Hard conflicts default to **local wins** while logging conflict counts for review.

## Business events

Business events always apply locally (even when incoming sync is disabled):

- Woo paid/completed orders decrement stock and create sales records.
- Discogs paid orders decrement stock based on listing mappings.

## Mapping and identity

The primary mapping key is Woo product meta **`theere_id`**. If a Woo product has no mapping:

1. A local inventory item is created
2. A new `theere_id` is generated
3. The `theere_id` is written back into Woo meta
4. `product_map` is updated

## Sync status and events

- **Sync Status** screen shows last periodic/instant runs and counts.
- **Inventory events** are append-only audit records for every quantity or price change.

## Backups

SQLite backups run on a schedule:

- **Rolling:** every 15 minutes, kept for 24 hours
- **Daily:** once per day, kept for 30 days

Backups are stored in `./backups` and use `VACUUM INTO` for consistency.
