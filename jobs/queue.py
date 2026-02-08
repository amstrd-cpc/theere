from __future__ import annotations

import logging
from typing import Any, Callable

import redis
from rq import Queue

from config.settings import load_settings

logger = logging.getLogger(__name__)


def get_queue() -> Queue:
    settings = load_settings()
    connection = redis.from_url(settings.redis_url)
    return Queue("webhooks", connection=connection, default_timeout=600)


def enqueue_job(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    queue = get_queue()
    job = queue.enqueue(func, *args, **kwargs)
    logger.info("Enqueued job %s", job.id)
    return job
