from __future__ import annotations

import datetime
from collections import defaultdict
from typing import Dict, Tuple


class SimpleRateLimiter:
    def __init__(self, max_requests: int = 60, window_seconds: int = 60) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._buckets: Dict[str, Tuple[int, datetime.datetime]] = defaultdict(lambda: (0, datetime.datetime.utcnow()))

    def allow(self, key: str) -> bool:
        count, start = self._buckets[key]
        now = datetime.datetime.utcnow()
        if (now - start).total_seconds() > self.window_seconds:
            self._buckets[key] = (1, now)
            return True
        if count >= self.max_requests:
            return False
        self._buckets[key] = (count + 1, start)
        return True
