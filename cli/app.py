from __future__ import annotations

import argparse
import json
from pathlib import Path

from bootstrap.container import build_container
from core.application.use_cases.add_inventory_item import add_inventory_item
from core.application.use_cases.process_woo_order import process_woo_order
from core.application.use_cases.sync_catalog import sync_catalog


def sync_command(store_id: int | None) -> None:
    container = build_container()
    store = container.settings_provider.get_store(store_id) if store_id else container.settings_provider.get_default_store()
    if not store:
        raise SystemExit("No store configured")
    result = sync_catalog(store_id=int(store["id"]), settings=container.settings_provider, woo_gateway=container.woo_gateway)
    print(json.dumps(result, indent=2))


def process_webhook(payload_file: Path, store_id: int | None) -> None:
    container = build_container()
    store = container.settings_provider.get_store(store_id) if store_id else container.settings_provider.get_default_store()
    if not store:
        raise SystemExit("No store configured")
    payload = json.loads(payload_file.read_text())
    order_id = int(payload.get("id") or 0)
    if not order_id:
        raise SystemExit("Payload must contain order id")
    result = process_woo_order(
        store_id=int(store["id"]),
        woo_order_id=order_id,
        settings=container.settings_provider,
        orders_repo=container.orders_repo,
        inventory_repo=container.inventory_repo,
        sales_repo=container.sales_repo,
        woo_gateway=container.woo_gateway,
        discogs_gateway=container.discogs_gateway,
        notifier=container.notifier,
    )
    print(json.dumps({"order_id": result.order_id, "matched": result.matched_items, "unmapped": result.unmapped_items}, indent=2))


def sandbox_run() -> None:
    container = build_container()
    item_id = add_inventory_item(
        container.inventory_repo,
        {
            "artist_album": "Sandbox Artist - Sandbox Album",
            "quantity": 2,
            "price_gel": 25,
            "supplier_name": "Sandbox Supplier",
        },
    )
    snapshot = container.inventory_repo.get_by_id(item_id)
    print(json.dumps({"status": "ok", "created_item_id": item_id, "item": snapshot}, indent=2, default=str))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="CLI entrypoints for core use-cases")
    sub = parser.add_subparsers(dest="command", required=True)

    sync_p = sub.add_parser("sync")
    sync_p.add_argument("--store-id", type=int, default=None)

    webhook_p = sub.add_parser("process-webhook")
    webhook_p.add_argument("payload_file", type=Path)
    webhook_p.add_argument("--store-id", type=int, default=None)

    sub.add_parser("sandbox-run")

    args = parser.parse_args(argv)
    if args.command == "sync":
        sync_command(args.store_id)
    elif args.command == "process-webhook":
        process_webhook(args.payload_file, args.store_id)
    elif args.command == "sandbox-run":
        sandbox_run()


if __name__ == "__main__":
    main()
