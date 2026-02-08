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
        print("Usage: python run.py [bot|api|worker]")
        raise SystemExit(1)

    mode = sys.argv[1]
    if mode == "bot":
        from bot import main as bot_main

        bot_main()
        return

    if mode == "api":
        settings = load_settings()
        uvicorn.run("api.app:app", host="0.0.0.0", port=settings.webhook_port)
        return

    if mode == "worker":
        queue = get_queue()
        worker = Worker([queue], connection=queue.connection)
        worker.work()
        return

    print("Unknown mode. Use bot, api, or worker.")
    raise SystemExit(1)


if __name__ == "__main__":
    main()
