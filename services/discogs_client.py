from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


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
        response = self.session.request(method, url, timeout=20, **kwargs)
        if response.status_code == 401:
            raise DiscogsAuthError("Invalid Discogs token")
        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", "5"))
            logger.warning("Discogs rate limited; sleeping %s seconds", retry_after)
            time.sleep(retry_after)
            raise DiscogsRateLimitError("Discogs rate limited")
        response.raise_for_status()
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
