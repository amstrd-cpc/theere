from __future__ import annotations

import requests
from tenacity import RetryError

from services import discogs_service


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


def _http_error(status_code: int) -> requests.HTTPError:
    response = _FakeResponse(status_code)
    return requests.HTTPError(response=response)


def test_fetch_price_suggestions_returns_empty_dict_on_http_404(monkeypatch):
    class _Client:
        def get(self, path):
            raise _http_error(404)

    monkeypatch.setattr(discogs_service, "_client", lambda store: _Client())

    result = discogs_service.fetch_price_suggestions({}, 123)

    assert result == {}


def test_fetch_price_suggestions_returns_empty_dict_on_retry_error_404(monkeypatch):
    class _Client:
        def get(self, path):
            raise RetryError(None) from _http_error(404)

    monkeypatch.setattr(discogs_service, "_client", lambda store: _Client())

    result = discogs_service.fetch_price_suggestions({}, 123)

    assert result == {}
