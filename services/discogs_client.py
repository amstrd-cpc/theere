from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, Optional

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)
_RATE_LIMIT_LOCK = threading.Lock()
_LAST_REQUEST_AT: Dict[str, float] = {}
_MIN_REQUEST_INTERVAL = float(os.getenv("DISCOGS_MIN_REQUEST_INTERVAL", "1.1"))


def _sleep_for_request_spacing(token: str) -> None:
    if _MIN_REQUEST_INTERVAL <= 0:
        return
    now = time.monotonic()
    with _RATE_LIMIT_LOCK:
        last_request = _LAST_REQUEST_AT.get(token, 0.0)
    wait_for = _MIN_REQUEST_INTERVAL - (now - last_request)
    if wait_for > 0:
        logger.debug("Discogs throttle: sleeping %.2f seconds between requests", wait_for)
        time.sleep(wait_for)
    with _RATE_LIMIT_LOCK:
        _LAST_REQUEST_AT[token] = time.monotonic()


def _sleep_for_reset_if_needed(response: requests.Response) -> None:
    remaining_raw = response.headers.get("X-Discogs-Ratelimit-Remaining")
    reset_raw = response.headers.get("X-Discogs-Ratelimit-Reset")
    if not remaining_raw or not reset_raw:
        return
    try:
        remaining = int(remaining_raw)
        reset_after = int(reset_raw)
    except ValueError:
        return
    if remaining <= 1 and reset_after > 0:
        logger.warning("Discogs rate limit nearing; sleeping %s seconds", reset_after)
        time.sleep(reset_after)


class DiscogsError(RuntimeError):
    pass


class DiscogsAuthError(DiscogsError):
    pass


class DiscogsRateLimitError(DiscogsError):
    pass


class DiscogsClient:
    def __init__(self, token: str, *, user_agent: str = "RecordStoreBot/1.0") -> None:
        self.token = token
        self.user_agent = user_agent
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Discogs token={token}",
                "User-Agent": user_agent,
            }
        )

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        _sleep_for_request_spacing(self.token)
        response = self.session.request(method, url, timeout=20, **kwargs)
        if response.status_code == 401:
            raise DiscogsAuthError("Invalid Discogs token")
        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", "5"))
            logger.warning("Discogs rate limited; sleeping %s seconds", retry_after)
            time.sleep(retry_after)
            raise DiscogsRateLimitError("Discogs rate limited")
        response.raise_for_status()
        _sleep_for_reset_if_needed(response)
        return response

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((requests.RequestException, DiscogsRateLimitError)),
    )
    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        response = self._request("GET", f"https://api.discogs.com{path}", params=params)
        return response.json()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((requests.RequestException, DiscogsRateLimitError)),
    )
    def post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        response = self._request("POST", f"https://api.discogs.com{path}", json=payload)
        return response.json()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((requests.RequestException, DiscogsRateLimitError)),
    )
    def update(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        response = self._request("POST", f"https://api.discogs.com{path}", json=payload)
        return response.json()

    def get_identity(self) -> Dict[str, Any]:
        return self.get("/oauth/identity")
