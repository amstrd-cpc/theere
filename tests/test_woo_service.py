from __future__ import annotations

from services import woo_service


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP error")


def test_woo_upsert_idempotency(monkeypatch):
    monkeypatch.setenv("WC_API_URL", "https://example.com/wp-json/wc/v3")
    monkeypatch.setenv("WC_CONSUMER_KEY", "ck_test")
    monkeypatch.setenv("WC_CONSUMER_SECRET", "cs_test")

    calls = []
    products = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if method == "GET":
            return FakeResponse(products)
        if method == "POST":
            product = {"id": 123, **kwargs.get("json", {})}
            products.append(product)
            return FakeResponse(product)
        if method == "PUT":
            product = {"id": 123, **kwargs.get("json", {})}
            return FakeResponse(product)
        raise AssertionError("Unexpected method")

    monkeypatch.setattr(woo_service.requests, "request", fake_request)

    item = {
        "id": 10,
        "artist_album": "Test Artist - Test Album",
        "price_gel": 19.99,
        "quantity": 1,
        "condition": "nm",
    }

    first = woo_service.upsert_product_from_inventory(item)
    second = woo_service.upsert_product_from_inventory(item)

    assert first["id"] == 123
    assert second["id"] == 123
    assert sum(1 for call in calls if call[0] == "POST") == 1
    assert sum(1 for call in calls if call[0] == "PUT") == 1
