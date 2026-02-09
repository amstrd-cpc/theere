from __future__ import annotations

import datetime
import logging
import threading
import uuid
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional, Tuple

from db.connection import get_inventory_db
from services.inventory_service import (
    get_inventory_by_id,
    insert_inventory,
    log_inventory_event,
    update_inventory_fields,
    update_inventory_sync,
)
from services.product_map_service import (
    find_mapping_by_internal_id,
    update_product_map_fields,
    upsert_product_map,
)
from services.store_service import get_store, get_store_settings
from services.sync_policy import NEVER_ACCEPT_FIELDS, normalize_incoming_fields
from services.woo_service import (
    compute_sync_hash,
    fetch_orders,
    fetch_products_page,
    is_configured,
    payload_from_inventory,
    update_product_by_id,
)
from jobs.worker_tasks import sync_order_state

logger = logging.getLogger(__name__)

_LOCKS: Dict[Tuple[int, int], threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


class SyncEngine:
    def __init__(self, *, lock_ttl_seconds: int = 300) -> None:
        self.lock_ttl_seconds = lock_ttl_seconds
        self.lock_owner = str(uuid.uuid4())

    def run_periodic_sync(self, store_id: int, *, run_type: str = "periodic") -> Optional[int]:
        store = get_store(store_id)
        if not store or not is_configured(store_id):
            return None
        settings = get_store_settings(store_id)
        if not settings.get("woo_sync_enabled"):
            return None
        run_id = self._start_sync_run(store_id, run_type=run_type)
        try:
            self.sync_orders(store_id)
            results = self.reconcile_catalog(store_id, sync_run_id=run_id)
            self._finish_sync_run(run_id, **results)
        except Exception as exc:
            logger.exception("Periodic sync failed for store %s", store_id)
            self._finish_sync_run(run_id, errors_count=1, last_error=str(exc))
        return run_id

    def run_manual_sync(self, store_id: int) -> Optional[int]:
        return self.run_periodic_sync(store_id, run_type="manual")

    def run_instant_sync_for_item(self, store_id: int, internal_product_id: int) -> Optional[int]:
        store = get_store(store_id)
        if not store or not is_configured(store_id):
            return None
        settings = get_store_settings(store_id)
        if not settings.get("woo_instant_sync_enabled"):
            return None
        run_id = self._start_sync_run(store_id, run_type="instant")
        try:
            result = self._push_item_to_woo(store_id, internal_product_id, sync_run_id=run_id)
            self._finish_sync_run(run_id, **result)
        except Exception as exc:
            logger.exception("Instant sync failed for store %s item %s", store_id, internal_product_id)
            self._finish_sync_run(run_id, errors_count=1, last_error=str(exc))
        return run_id

    def sync_orders(self, store_id: int) -> int:
        store = get_store(store_id)
        if not store or not is_configured(store_id):
            return 0
        settings = get_store_settings(store_id)
        trigger_status = (settings.get("auto_decrement_status") or "processing").lower()
        try:
            orders = fetch_orders(params={"status": trigger_status, "per_page": 50}, store=store)
        except Exception:
            logger.exception("Failed fetching Woo orders for store %s", store_id)
            return 0
        count = 0
        for order in orders:
            order_id = order.get("id")
            if not order_id:
                continue
            sync_order_state(store_id, int(order_id))
            count += 1
        return count

    def reconcile_catalog(
        self,
        store_id: int,
        *,
        sync_run_id: Optional[int] = None,
        initial_load: bool = False,
    ) -> Dict[str, int]:
        store = get_store(store_id)
        if not store or not is_configured(store_id):
            return self._empty_results()
        settings = get_store_settings(store_id)
        strategy = (settings.get("woo_sync_strategy") or "lww").lower()
        allow_incoming = bool(settings.get("woo_allow_incoming") or initial_load)
        incoming_fields = normalize_incoming_fields(settings.get("woo_incoming_fields") or [])

        results = self._empty_results()
        page = 1
        per_page = 100
        while True:
            products = fetch_products_page(page=page, per_page=per_page, store=store)
            if not products:
                break
            for product in products:
                item_results = self._reconcile_product(
                    store_id,
                    product,
                    strategy=strategy,
                    sync_run_id=sync_run_id,
                    allow_incoming=allow_incoming,
                    incoming_fields=incoming_fields,
                )
                for key, value in item_results.items():
                    results[key] += value
            if len(products) < per_page:
                break
            page += 1

        return results

    def _reconcile_product(
        self,
        store_id: int,
        product: Dict[str, Any],
        *,
        strategy: str,
        sync_run_id: Optional[int],
        allow_incoming: bool,
        incoming_fields: set[str],
    ) -> Dict[str, int]:
        results = self._empty_results()
        woo_id = product.get("id")
        if not woo_id:
            return results
        theere_id = self._extract_theere_id(product)
        sku = str(product.get("sku") or "").strip()

        if theere_id is None and sku.isdigit():
            theere_id = int(sku)

        item = get_inventory_by_id(theere_id) if theere_id else None
        created_local = False
        if not item:
            item = self._create_local_from_woo(store_id, product)
            created_local = True
            theere_id = int(item["id"])
            results["created_local_count"] += 1
        if theere_id:
            mapping = find_mapping_by_internal_id(store_id, int(theere_id))
            if not mapping or mapping.get("woo_product_id") != int(woo_id):
                upsert_product_map(store_id=store_id, internal_product_id=int(theere_id), woo_product_id=int(woo_id), sku=sku or None)
                results["mapping_fixed_count"] += 1
            update_product_map_fields(
                store_id,
                int(theere_id),
                {
                    "woo_last_seen_quantity": int(product.get("stock_quantity") or 0),
                    "woo_last_seen_price": float(product.get("regular_price") or product.get("price") or 0),
                    "woo_last_seen_at": datetime.datetime.utcnow().isoformat(),
                    "woo_last_seen_modified_at": self._format_woo_modified(product),
                },
            )
            if self._extract_theere_id(product) is None:
                self._write_theere_id_meta(store_id, int(woo_id), int(theere_id))

        if created_local:
            if not product.get("meta_data") or not self._extract_theere_id(product):
                self._write_theere_id_meta(store_id, int(woo_id), int(theere_id))
            return results

        if not item or not theere_id:
            return results

        with self._acquire_item_lock(store_id, int(theere_id)) as acquired:
            if not acquired:
                return results
            local_snapshot = self._local_snapshot(item)
            woo_snapshot = self._woo_snapshot(product)
            decision = self._decide_sync(local_snapshot, woo_snapshot, strategy=strategy)
            if decision == "pull":
                results["incoming_count"] += 1
                if not allow_incoming:
                    results["drifted_count"] += 1
                    logger.info("Woo incoming change drifted (incoming disabled) for item %s", theere_id)
                    return results
                if not self._local_rev_matches(int(theere_id), local_snapshot["local_rev"]):
                    return results
                updates = self._filter_incoming_updates(woo_snapshot, incoming_fields)
                if not updates:
                    results["drifted_count"] += 1
                    logger.info("Woo incoming change ignored (no allowed fields) for item %s", theere_id)
                    return results
                update_inventory_fields(
                    int(theere_id),
                    updates,
                    sync_channels=False,
                    source="sync_pull" if strategy == "lww" else "manual_woo",
                    store_id=store_id,
                    correlation_id=str(sync_run_id) if sync_run_id else None,
                    note="Woo update applied during catalog reconcile",
                )
                results["pulled_count"] += 1
            elif decision == "push":
                if not self._local_rev_matches(int(theere_id), local_snapshot["local_rev"]):
                    return results
                self._push_snapshot_to_woo(
                    store_id,
                    int(woo_id),
                    local_snapshot,
                    sync_run_id=sync_run_id,
                )
                results["pushed_count"] += 1
        return results

    def _push_item_to_woo(self, store_id: int, internal_product_id: int, *, sync_run_id: Optional[int]) -> Dict[str, int]:
        results = self._empty_results()
        item = get_inventory_by_id(internal_product_id)
        if not item:
            return results
        with self._acquire_item_lock(store_id, internal_product_id) as acquired:
            if not acquired:
                return results
            mapping = find_mapping_by_internal_id(store_id, internal_product_id)
            if not mapping or not mapping.get("woo_product_id"):
                from services.woo_service import create_product_from_inventory

                response = create_product_from_inventory(item)
                woo_id = int(response["id"])
                upsert_product_map(
                    store_id=store_id,
                    internal_product_id=internal_product_id,
                    woo_product_id=woo_id,
                    sku=str(internal_product_id),
                    discogs_release_id=item.get("discogs_release_id"),
                )
                try:
                    sync_hash = compute_sync_hash(payload_from_inventory(item))
                    update_inventory_sync(internal_product_id, woo_id, sync_hash)
                except Exception:
                    logger.exception("Failed updating inventory sync metadata for %s", internal_product_id)
                update_product_map_fields(
                    store_id,
                    internal_product_id,
                    {"woo_last_seen_modified_at": self._format_woo_modified(response)},
                )
            else:
                woo_id = int(mapping["woo_product_id"])
            local_snapshot = self._local_snapshot(item)
            self._push_snapshot_to_woo(store_id, woo_id, local_snapshot, sync_run_id=sync_run_id)
            results["pushed_count"] += 1
        return results

    def _push_snapshot_to_woo(
        self,
        store_id: int,
        woo_id: int,
        local_snapshot: Dict[str, Any],
        *,
        sync_run_id: Optional[int],
    ) -> None:
        payload = {
            "stock_quantity": local_snapshot["quantity"],
            "manage_stock": True,
            "regular_price": f"{local_snapshot['price_gel']:.2f}",
            "meta_data": [{"key": "theere_id", "value": str(local_snapshot["theere_id"])}],
        }
        response = update_product_by_id(woo_id, payload, store_id=store_id)
        update_product_map_fields(
            store_id,
            int(local_snapshot["theere_id"]),
            {"woo_last_seen_modified_at": self._format_woo_modified(response)},
        )
        log_inventory_event(
            store_id=store_id,
            internal_product_id=int(local_snapshot["theere_id"]),
            theere_id=str(local_snapshot["theere_id"]),
            field="quantity",
            old_value=local_snapshot["quantity"],
            new_value=local_snapshot["quantity"],
            source="sync_push",
            correlation_id=str(sync_run_id) if sync_run_id else None,
            note=f"Pushed quantity to Woo product {woo_id}",
        )
        log_inventory_event(
            store_id=store_id,
            internal_product_id=int(local_snapshot["theere_id"]),
            theere_id=str(local_snapshot["theere_id"]),
            field="regular_price",
            old_value=local_snapshot["price_gel"],
            new_value=local_snapshot["price_gel"],
            source="sync_push",
            correlation_id=str(sync_run_id) if sync_run_id else None,
            note=f"Pushed price to Woo product {woo_id}",
        )

    def _create_local_from_woo(self, store_id: int, product: Dict[str, Any]) -> Dict[str, Any]:
        now = datetime.datetime.utcnow().isoformat()
        qty = int(product.get("stock_quantity") or 0)
        try:
            price = float(product.get("regular_price") or product.get("price") or 0)
        except (TypeError, ValueError):
            price = 0.0
        payload = {
            "artist_album": product.get("name") or "Woo Product",
            "price_gel": price,
            "quantity": qty,
            "created_at": now,
            "updated_at": now,
            "local_rev": 1,
            "last_change_source": "sync_pull",
        }
        item_id = insert_inventory(payload)
        log_inventory_event(
            store_id=store_id,
            internal_product_id=item_id,
            theere_id=str(item_id),
            field="quantity",
            old_value=None,
            new_value=qty,
            source="sync_pull",
            correlation_id=None,
            note=f"Created from Woo product {product.get('id')}",
        )
        log_inventory_event(
            store_id=store_id,
            internal_product_id=item_id,
            theere_id=str(item_id),
            field="regular_price",
            old_value=None,
            new_value=price,
            source="sync_pull",
            correlation_id=None,
            note=f"Created from Woo product {product.get('id')}",
        )
        return get_inventory_by_id(item_id) or {"id": item_id, **payload}

    def _start_sync_run(self, store_id: int, *, run_type: str) -> int:
        now = datetime.datetime.utcnow().isoformat()
        with get_inventory_db() as conn:
            cur = conn.execute(
                """
                INSERT INTO sync_runs (ts_started, store_id, run_type)
                VALUES (?, ?, ?)
                """,
                (now, store_id, run_type),
            )
            conn.commit()
            return int(cur.lastrowid)

    def _finish_sync_run(
        self,
        run_id: int,
        *,
        pulled_count: int = 0,
        pushed_count: int = 0,
        created_local_count: int = 0,
        mapping_fixed_count: int = 0,
        incoming_count: int = 0,
        drifted_count: int = 0,
        conflict_count: int = 0,
        errors_count: int = 0,
        last_error: Optional[str] = None,
    ) -> None:
        now = datetime.datetime.utcnow().isoformat()
        with get_inventory_db() as conn:
            conn.execute(
                """
                UPDATE sync_runs
                SET ts_finished = ?,
                    pulled_count = ?,
                    pushed_count = ?,
                    created_local_count = ?,
                    mapping_fixed_count = ?,
                    incoming_count = ?,
                    drifted_count = ?,
                    conflict_count = ?,
                    errors_count = ?,
                    last_error = ?
                WHERE id = ?
                """,
                (
                    now,
                    pulled_count,
                    pushed_count,
                    created_local_count,
                    mapping_fixed_count,
                    incoming_count,
                    drifted_count,
                    conflict_count,
                    errors_count,
                    last_error,
                    run_id,
                ),
            )
            conn.commit()

    def _local_snapshot(self, item: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "theere_id": int(item.get("id") or 0),
            "quantity": int(item.get("quantity") or 0),
            "price_gel": float(item.get("price_gel") or 0),
            "updated_at": item.get("updated_at") or item.get("created_at"),
            "local_rev": int(item.get("local_rev") or 0),
        }

    def _woo_snapshot(self, product: Dict[str, Any]) -> Dict[str, Any]:
        quantity = int(product.get("stock_quantity") or 0)
        try:
            price = float(product.get("regular_price") or product.get("price") or 0)
        except (TypeError, ValueError):
            price = 0.0
        return {
            "quantity": quantity,
            "price_gel": price,
            "modified_at": self._parse_woo_modified(product),
            "description": product.get("description"),
            "images": product.get("images"),
        }

    def _decide_sync(self, local: Dict[str, Any], woo: Dict[str, Any], *, strategy: str) -> str:
        if strategy == "woo":
            return "pull" if self._values_differ(local, woo) else "noop"
        if strategy == "local":
            return "push" if self._values_differ(local, woo) else "noop"
        local_ts = self._parse_local_ts(local.get("updated_at"))
        woo_ts = woo.get("modified_at")
        if not local_ts or not woo_ts:
            return "noop"
        if woo_ts > local_ts:
            return "pull"
        if local_ts > woo_ts:
            return "push"
        return "noop"

    def _values_differ(self, local: Dict[str, Any], woo: Dict[str, Any]) -> bool:
        return local["quantity"] != woo["quantity"] or float(local["price_gel"]) != float(woo["price_gel"])

    def _parse_local_ts(self, value: Any) -> Optional[datetime.datetime]:
        if not value:
            return None
        try:
            return datetime.datetime.fromisoformat(str(value))
        except ValueError:
            return None

    def _parse_woo_modified(self, product: Dict[str, Any]) -> Optional[datetime.datetime]:
        value = product.get("date_modified_gmt") or product.get("date_modified")
        if not value:
            return None
        text = str(value).replace("Z", "+00:00")
        try:
            return datetime.datetime.fromisoformat(text)
        except ValueError:
            return None

    def _format_woo_modified(self, product: Dict[str, Any]) -> Optional[str]:
        ts = self._parse_woo_modified(product)
        return ts.isoformat() if ts else None

    def _extract_theere_id(self, product: Dict[str, Any]) -> Optional[int]:
        for item in product.get("meta_data") or []:
            if str(item.get("key") or "").lower() == "theere_id":
                try:
                    return int(item.get("value"))
                except (TypeError, ValueError):
                    return None
        return None

    def _write_theere_id_meta(self, store_id: int, woo_id: int, theere_id: int) -> None:
        payload = {"meta_data": [{"key": "theere_id", "value": str(theere_id)}]}
        update_product_by_id(woo_id, payload, store_id=store_id)

    def _local_rev_matches(self, internal_id: int, expected_rev: int) -> bool:
        with get_inventory_db() as conn:
            cur = conn.execute("SELECT local_rev FROM inventory WHERE id = ?", (internal_id,))
            row = cur.fetchone()
            if not row:
                return False
            return int(row["local_rev"] or 0) == expected_rev

    @contextmanager
    def _acquire_item_lock(self, store_id: int, internal_product_id: int) -> Iterator[bool]:
        key = (store_id, internal_product_id)
        with _LOCKS_GUARD:
            lock = _LOCKS.setdefault(key, threading.Lock())
        lock.acquire()
        acquired = self._acquire_db_lock(store_id, internal_product_id)
        try:
            yield acquired
        finally:
            if acquired:
                self._release_db_lock(store_id, internal_product_id)
            lock.release()

    def _acquire_db_lock(self, store_id: int, internal_product_id: int) -> bool:
        now = datetime.datetime.utcnow()
        stale_before = now - datetime.timedelta(seconds=self.lock_ttl_seconds)
        now_str = now.isoformat()
        with get_inventory_db() as conn:
            cur = conn.execute(
                "SELECT lock_owner, locked_at FROM sync_locks WHERE store_id = ? AND internal_product_id = ?",
                (store_id, internal_product_id),
            )
            row = cur.fetchone()
            if row:
                locked_at = row["locked_at"]
                try:
                    locked_ts = datetime.datetime.fromisoformat(str(locked_at))
                except ValueError:
                    locked_ts = now
                if locked_ts < stale_before:
                    conn.execute(
                        """
                        UPDATE sync_locks
                        SET lock_owner = ?, locked_at = ?
                        WHERE store_id = ? AND internal_product_id = ?
                        """,
                        (self.lock_owner, now_str, store_id, internal_product_id),
                    )
                    conn.commit()
                    return True
                return False
            conn.execute(
                """
                INSERT INTO sync_locks (store_id, internal_product_id, lock_owner, locked_at)
                VALUES (?, ?, ?, ?)
                """,
                (store_id, internal_product_id, self.lock_owner, now_str),
            )
            conn.commit()
            return True

    def _release_db_lock(self, store_id: int, internal_product_id: int) -> None:
        with get_inventory_db() as conn:
            conn.execute(
                """
                DELETE FROM sync_locks
                WHERE store_id = ? AND internal_product_id = ? AND lock_owner = ?
                """,
                (store_id, internal_product_id, self.lock_owner),
            )
            conn.commit()

    def _empty_results(self) -> Dict[str, int]:
        return {
            "pulled_count": 0,
            "pushed_count": 0,
            "created_local_count": 0,
            "mapping_fixed_count": 0,
            "incoming_count": 0,
            "drifted_count": 0,
            "conflict_count": 0,
            "errors_count": 0,
        }

    def _filter_incoming_updates(self, woo_snapshot: Dict[str, Any], allowed_fields: set[str]) -> Dict[str, Any]:
        updates: Dict[str, Any] = {}
        if "quantity" in allowed_fields and "quantity" not in NEVER_ACCEPT_FIELDS:
            updates["quantity"] = woo_snapshot["quantity"]
        if "price" in allowed_fields and "price" not in NEVER_ACCEPT_FIELDS:
            updates["price_gel"] = woo_snapshot["price_gel"]
        if "description" in allowed_fields and "description" not in NEVER_ACCEPT_FIELDS:
            updates["description"] = woo_snapshot.get("description")
        if "images" in allowed_fields and "images" not in NEVER_ACCEPT_FIELDS:
            image = (woo_snapshot.get("images") or [{}])[0].get("src") if woo_snapshot.get("images") else None
            if image:
                updates["cover_url"] = image
        return updates
