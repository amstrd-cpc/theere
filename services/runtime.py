from __future__ import annotations

import asyncio
from typing import Any, Callable, TypeVar

T = TypeVar("T")


class ServiceTimeoutError(RuntimeError):
    pass


async def run_blocking(func: Callable[..., T], *args: Any, timeout: float = 30.0, **kwargs: Any) -> T:
    try:
        return await asyncio.wait_for(asyncio.to_thread(func, *args, **kwargs), timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise ServiceTimeoutError("Operation timed out") from exc
