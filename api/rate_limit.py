from __future__ import annotations

import datetime
from collections import defaultdict
from typing import Dict, Tuple


class SimpleRateLimiter:
    def __init__(
        self,
        max_requests: int = 60,
        window_seconds: int = 60,
        eviction_windows: int = 5,
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.eviction_windows = eviction_windows
        self._buckets: Dict[str, Tuple[int, datetime.datetime]] = defaultdict(
            lambda: (0, datetime.datetime.now(datetime.UTC))
        )

    def _evict_stale(self, now: datetime.datetime) -> None:
        ttl_seconds = self.window_seconds * self.eviction_windows
        stale_keys = [
            key
            for key, (_, start) in self._buckets.items()
            if (now - start).total_seconds() > ttl_seconds
        ]
        for key in stale_keys:
            self._buckets.pop(key, None)

    def allow(self, key: str) -> bool:
        now = datetime.datetime.now(datetime.UTC)
        self._evict_stale(now)
        count, start = self._buckets[key]
        if start.tzinfo is None:
            start = start.replace(tzinfo=datetime.UTC)

        if (now - start).total_seconds() > self.window_seconds:
            self._buckets[key] = (1, now)
            return True
        if count >= self.max_requests:
            return False
        self._buckets[key] = (count + 1, start)
        return True
