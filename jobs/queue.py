from __future__ import annotations

import logging
from typing import Any, Callable

import redis
from rq import Queue

from config.settings import load_settings

logger = logging.getLogger(__name__)

_REDIS_CONNECTION: redis.Redis | None = None
_QUEUE: Queue | None = None


def _get_redis_connection() -> redis.Redis:
    global _REDIS_CONNECTION
    if _REDIS_CONNECTION is None:
        settings = load_settings()
        _REDIS_CONNECTION = redis.from_url(settings.redis_url)
    return _REDIS_CONNECTION


def get_queue() -> Queue:
    global _QUEUE
    if _QUEUE is None:
        _QUEUE = Queue(
            "webhooks", connection=_get_redis_connection(), default_timeout=600
        )
    return _QUEUE


def enqueue_job(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    queue = get_queue()
    job = queue.enqueue(func, *args, **kwargs)
    logger.info("Enqueued job %s", job.id)
    return job
