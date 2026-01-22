import datetime
import hashlib
import json
import os
import sqlite3

from db import get_db
from woocommerce_client import (
    is_configured,
    create_product_from_inventory,
    find_product_by_sku,
    get_product,
    list_products,
    search_products,
    trash_product,
    update_product_fields,
)


def _normalize_attributes(attrs: list[dict] | None) -> list[dict]:
    """Normalize Woo attributes for stable comparison."""
    if not attrs:
        return []
    out = []
    for a in attrs:
        name = (a.get("name") or "").strip()
        opts = a.get("options") or []
        opts_norm = [str(x).strip() for x in opts if str(x).strip()]
        opts_norm.sort(key=lambda s: s.lower())
        if name:
            out.append({"name": name, "options": opts_norm})
    out.sort(key=lambda d: d["name"].lower())
    return out


def _local_signature(item: dict) -> dict:
    """Fields we consider authoritative from local DB."""
    # Keep this intentionally small to avoid churn from HTML/Discogs enrichment.
    attrs = []
    for name, key in [
        ("Genre", "genre"),
        ("Style", "style"),
        ("Label", "label"),
        ("Format", "format"),
        ("Year", "year"),
        ("Condition", "condition"),
    ]:
        val = item.get(key)
        if val is None:
            continue
        sval = str(val).strip()
        if sval:
            attrs.append({"name": name, "options": [sval]})
    attrs = _normalize_attributes(attrs)

    return {
        "sku": str(item.get("id")) if item.get("id") is not None else "",
        "name": (item.get("artist_album") or "").strip(),
        "stock_quantity": int(item.get("quantity") or 0),
        "regular_price": str(float(item.get("price_gel") or 0)),
        "attributes": attrs,
        # Categories are derived server-side in create_product_from_inventory;
        # we don't compare them to avoid expensive category computations.
    }


def _remote_signature(product: dict) -> dict:
    attrs = _normalize_attributes(product.get("attributes") or [])
    return {
        "sku": str(product.get("sku") or ""),
        "name": (product.get("name") or "").strip(),
        "stock_quantity": int(product.get("stock_quantity") or 0),
        "regular_price": str(product.get("regular_price") or "0"),
        "attributes": attrs,
    }


def _sig_hash(sig: dict) -> str:
    blob = json.dumps(sig, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def bootstrap_sync_inventory_to_woo():
    """Backward-compatible entrypoint.

    Historically this tried to create/link missing products. Now we just run the
    idempotent diff sync.
    """
    sync_inventory_to_woo()


def sync_inventory_to_woo():
    """Idempotent, diff-based sync.

    Goals:
    - Never create duplicates on restart.
    - Only create/update/delete when there is a real diff between local and Woo.
    - Link products using SKU = local inventory.id.

    Deletions:
      If WOO_SYNC_APPLY_DELETES=1 (default), any Woo product with a numeric SKU
      that is not present locally will be soft-deleted (status=draft, stock=0).
      If WOO_SYNC_HARD_DELETE=1, the product will be hard-deleted.
    """

    if not is_configured():
        print("WooCommerce not configured; skipping sync.")
        return

    apply_deletes = os.getenv("WOO_SYNC_APPLY_DELETES", "1").lower() in ("1", "true", "yes")
    hard_delete = os.getenv("WOO_SYNC_HARD_DELETE", "0").lower() in ("1", "true", "yes")

    try:
        with get_db() as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT * FROM inventory")
            rows = [dict(r) for r in cur.fetchall()]

            local_ids = {int(r.get("id")) for r in rows if r.get("id") is not None}
            now = datetime.datetime.utcnow().isoformat()

            for item in rows:
                local_sig = _local_signature(item)
                local_hash = _sig_hash(local_sig)

                woo_id = item.get("woo_product_id")

                # 1) Ensure link exists (woo_product_id) without creating duplicates
                if not woo_id:
                    existing = None
                    try:
                        existing = find_product_by_sku(str(item.get("id")))
                    except Exception:
                        existing = None

                    if existing:
                        woo_id = existing.get("id")
                        # Ensure SKU is set on the existing product (older products may be missing it)
                        try:
                            if str(existing.get("sku") or "") != str(item.get("id")):
                                update_product_fields(int(woo_id), {"sku": str(item.get("id"))})
                        except Exception:
                            pass

                        cur.execute(
                            """
                            UPDATE inventory
                            SET woo_product_id = ?, woo_synced = 1, woo_last_synced_at = ?, woo_sync_hash = ?
                            WHERE id = ?
                            """,
                            (woo_id, now, local_hash, item["id"]),
                        )
                        conn.commit()
                    else:
                        # Try to rescue older duplicates that were created without SKU:
                        # if we find exactly one strong name match, stamp SKU and link it.
                        created_new = False
                        try:
                            name = (item.get("artist_album") or "").strip()
                            if name:
                                cands = search_products(name, per_page=10)
                                exact = [p for p in cands if (p.get("name") or "").strip().lower() == name.lower()]
                                if len(exact) == 1:
                                    cand = exact[0]
                                    cand_id = cand.get("id")
                                    if cand_id:
                                        update_product_fields(int(cand_id), {"sku": str(item.get("id"))})
                                        woo_id = cand_id
                        except Exception:
                            woo_id = None

                        # If still not linked, create once (SKU is set during creation)
                        try:
                            if not woo_id:
                                created = create_product_from_inventory(item, image_url=None)
                                woo_id = created.get("id")
                                created_new = True
                        except Exception as e:
                            print(f"Error creating Woo product for inventory item {item.get('id')}: {e}")
                            continue

                        if woo_id:
                            cur.execute(
                                """
                                UPDATE inventory
                                SET woo_product_id = ?, woo_synced = 1, woo_last_synced_at = ?, woo_sync_hash = ?
                                WHERE id = ?
                                """,
                                (woo_id, now, local_hash, item["id"]),
                            )
                            conn.commit()
                            if created_new:
                                print(f"Created Woo product {woo_id} for inventory item {item.get('id')}")
                            else:
                                print(f"Linked existing Woo product {woo_id} to inventory item {item.get('id')}")

                # 2) Diff update for linked products
                if woo_id:
                    try:
                        product = get_product(int(woo_id))
                    except Exception as e:
                        print(f"Error fetching Woo product {woo_id} for inventory item {item.get('id')}: {e}")
                        continue

                    remote_sig = _remote_signature(product)
                    remote_hash = _sig_hash(remote_sig)

                    # If Woo matches local, update local markers and move on.
                    if remote_hash == local_hash:
                        cur.execute(
                            """
                            UPDATE inventory
                            SET woo_synced = 1, woo_last_synced_at = ?, woo_sync_hash = ?
                            WHERE id = ?
                            """,
                            (now, local_hash, item["id"]),
                        )
                        conn.commit()
                        continue

                    # Only push the fields that differ (minimize API calls)
                    payload: dict = {}
                    if str(remote_sig.get("sku")) != str(local_sig.get("sku")) and local_sig.get("sku"):
                        payload["sku"] = local_sig["sku"]
                    if (remote_sig.get("name") or "") != (local_sig.get("name") or "") and local_sig.get("name"):
                        payload["name"] = local_sig["name"]
                    if int(remote_sig.get("stock_quantity") or 0) != int(local_sig.get("stock_quantity") or 0):
                        payload["stock_quantity"] = int(local_sig["stock_quantity"])
                    if str(remote_sig.get("regular_price") or "") != str(local_sig.get("regular_price") or ""):
                        payload["regular_price"] = str(local_sig["regular_price"])
                    if remote_sig.get("attributes") != local_sig.get("attributes"):
                        payload["attributes"] = local_sig.get("attributes")

                    if payload:
                        try:
                            update_product_fields(int(woo_id), payload)
                        except Exception as e:
                            print(f"Error updating Woo product {woo_id}: {e}")
                            continue

                    # Re-fetch once to confirm and store the correct hash
                    try:
                        product2 = get_product(int(woo_id))
                        remote2_hash = _sig_hash(_remote_signature(product2))
                    except Exception:
                        remote2_hash = local_hash

                    cur.execute(
                        """
                        UPDATE inventory
                        SET woo_synced = 1, woo_last_synced_at = ?, woo_sync_hash = ?
                        WHERE id = ?
                        """,
                        (now, remote2_hash, item["id"]),
                    )
                    conn.commit()
                    print(f"Updated Woo product {woo_id} for inventory item {item.get('id')}")

        # 3) Deletions / missing locally
        if apply_deletes:
            try:
                page = 1
                while True:
                    prods = list_products(page=page, per_page=100)
                    if not prods:
                        break

                    for p in prods:
                        sku = str(p.get("sku") or "").strip()
                        if not sku or not sku.isdigit():
                            continue
                        sku_id = int(sku)
                        if sku_id in local_ids:
                            continue
                        pid = int(p.get("id"))
                        try:
                            if hard_delete:
                                trash_product(pid, force=True)
                                print(f"Deleted Woo product {pid} (SKU {sku}) because it is missing locally")
                            else:
                                # Soft-delete: draft + stock=0
                                update_product_fields(pid, {"status": "draft", "stock_quantity": 0})
                                print(f"Drafted Woo product {pid} (SKU {sku}) because it is missing locally")
                        except Exception as e:
                            print(f"Error deleting/drafting Woo product {pid} (SKU {sku}): {e}")

                    # Next page: Woo returns <per_page when last page
                    if len(prods) < 100:
                        break
                    page += 1
            except Exception as e:
                print(f"Woo deletion reconciliation failed: {e}")

    except Exception as e:
        print(f"WooCommerce diff sync failed: {e}")
