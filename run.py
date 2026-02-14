from __future__ import annotations

import sys

import uvicorn
from rq import Worker

from config.settings import load_settings
from db import init_db
from jobs.queue import get_queue


def main() -> None:
    init_db()
    if len(sys.argv) < 2:
        print("Usage: python run.py [api|worker|cli]")
        raise SystemExit(1)

    mode = sys.argv[1]

    if mode == "api":
        settings = load_settings()
        uvicorn.run("api.app:app", host="0.0.0.0", port=settings.webhook_port)
        return

    if mode == "worker":
        queue = get_queue()
        worker = Worker([queue], connection=queue.connection)
        worker.work()
        return

    if mode == "cli":
        from cli.app import main as cli_main

        cli_main(sys.argv[2:])
        return

    print("Unknown mode. Use api, worker, or cli.")
    raise SystemExit(1)


if __name__ == "__main__":
    main()
