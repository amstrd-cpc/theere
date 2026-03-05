from __future__ import annotations

import base64
import hashlib
import hmac

from fastapi.testclient import TestClient

from api import app as api_app


def _signature(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def test_webhook_rejects_invalid_signature(monkeypatch):
    monkeypatch.setattr(api_app, "get_store", lambda _id: {"webhook_secret": "secret"})
    client = TestClient(api_app.app)
    response = client.post(
        "/webhooks/woo/1",
        json={"id": 1},
        headers={"X-WC-Webhook-Signature": "invalid"},
    )
    assert response.status_code == 401


def test_webhook_idempotency_duplicate(monkeypatch):
    monkeypatch.setattr(api_app, "get_store", lambda _id: {"webhook_secret": "secret"})
    monkeypatch.setattr(api_app, "create_webhook_event", lambda **kwargs: None)
    enqueue_calls = []
    monkeypatch.setattr(
        api_app,
        "enqueue_job",
        lambda *args, **kwargs: enqueue_calls.append((args, kwargs)),
    )

    client = TestClient(api_app.app)
    payload = b'{"id": 11}'
    response = client.post(
        "/webhooks/woo/1",
        data=payload,
        headers={
            "X-WC-Webhook-Signature": _signature("secret", payload),
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "duplicate"
    assert enqueue_calls == []
