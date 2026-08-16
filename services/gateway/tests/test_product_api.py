from __future__ import annotations

from fastapi.testclient import TestClient

from app import main
from app import product_api


def test_product_api_uses_error_envelope_and_auth_boundary(monkeypatch) -> None:
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    monkeypatch.setattr(product_api, "PRODUCT_PRINCIPAL", "product-user")
    client = TestClient(main.app)

    missing = client.get("/api/product/health")
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "product_authentication_required"

    healthy = client.get(
        "/api/product/health",
        headers={"Authorization": "Bearer product-test-token"},
    )
    assert healthy.status_code == 200
    assert healthy.json()["status"] == "ok"


def test_product_dashboard_is_safe_and_normalized(monkeypatch) -> None:
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    monkeypatch.setattr(product_api, "PRODUCT_PRINCIPAL", "product-user")

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {"status": "ok"}

    monkeypatch.setattr(product_api.httpx, "get", lambda *args, **kwargs: FakeResponse())
    monkeypatch.setattr(
        product_api.httpx,
        "request",
        lambda *args, **kwargs: FakeResponse(),
    )
    client = TestClient(main.app)
    response = client.get(
        "/api/product/dashboard",
        headers={"Authorization": "Bearer product-test-token"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["resources"]["migration"] == "not_started"
