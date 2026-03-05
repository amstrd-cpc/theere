from __future__ import annotations

import datetime

from api.rate_limit import SimpleRateLimiter


def test_rate_limiter_window_reset_and_eviction():
    limiter = SimpleRateLimiter(max_requests=1, window_seconds=10, eviction_windows=2)
    assert limiter.allow("a") is True
    assert limiter.allow("a") is False

    start = datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=11)
    limiter._buckets["a"] = (1, start)
    assert limiter.allow("a") is True

    limiter._buckets["stale"] = (
        1,
        datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=25),
    )
    limiter.allow("fresh")
    assert "stale" not in limiter._buckets
