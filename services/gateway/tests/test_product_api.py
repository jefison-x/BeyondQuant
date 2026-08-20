from __future__ import annotations

from fastapi.testclient import TestClient

from app import main
from app import product_api
from app import user_session


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


def test_product_profile_loads_and_updates_owner_profile(monkeypatch) -> None:
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    monkeypatch.setattr(product_api, "PRODUCT_PRINCIPAL", "product-user")

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "user": {
                    "user_id": "user_abc123",
                    "username": "testuser",
                    "display_name": "老李",
                    "preferences": "低波动",
                    "default_prompt": "先给结论",
                    "role": "user",
                    "status": "active",
                }
            }

    monkeypatch.setattr(user_session.httpx, "get", lambda *args, **kwargs: FakeResponse())
    monkeypatch.setattr(product_api.httpx, "request", lambda *args, **kwargs: FakeResponse())
    client = TestClient(main.app)
    client.cookies.set(product_api.SESSION_COOKIE, "session_test")

    response = client.get("/api/product/profile")
    assert response.status_code == 200
    assert response.json()["profile"]["display_name"] == "老李"

    response = client.put("/api/product/profile", json={"display_name": "量化小周"})
    assert response.status_code == 200
    assert response.json()["profile"]["display_name"] == "老李"


def test_product_model_settings_are_secret_free(monkeypatch) -> None:
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    monkeypatch.setattr(product_api, "PRODUCT_PRINCIPAL", "product-user")
    client = TestClient(main.app)
    response = client.get(
        "/api/product/settings/models",
        headers={"Authorization": "Bearer product-test-token"},
    )
    assert response.status_code == 200
    assert response.json()["credentials"]["masked"] is True
    assert "token" not in response.text.lower()
    assert "secret" not in response.text.lower()


def test_product_assets_export_and_import_are_owner_scoped(monkeypatch) -> None:
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    monkeypatch.setattr(product_api, "PRODUCT_PRINCIPAL", "product-user")

    class FakeResponse:
        def __init__(self, body: dict[str, object]) -> None:
            self.body = body

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return self.body

    def fake_request(method: str, url: str, **kwargs) -> FakeResponse:
        if url.endswith("/v1/research/artifacts"):
            return FakeResponse({"artifacts": [{"artifact_id": "artifact_1", "kind": "strategy_version", "status": "validated"}]})
        if url.endswith("/v1/research/backtests"):
            return FakeResponse({"backtests": []})
        if url.endswith("/v1/paper/pools"):
            return FakeResponse({"pools": [{"pool_id": "stock_pool_1", "name": "沪深300", "symbols": ["000001.SZ"]}]})
        if url.endswith("/v1/paper/accounts"):
            return FakeResponse({"accounts": []})
        return FakeResponse({})

    monkeypatch.setattr(product_api.httpx, "request", fake_request)
    client = TestClient(main.app)
    auth = {"Authorization": "Bearer product-test-token"}
    exported = client.get("/api/product/settings/assets/export", headers=auth)
    assert exported.status_code == 200
    assert exported.json()["schema_version"] == "byq-workspace-assets-v1"
    assert exported.json()["assets"]["strategies"][0]["artifact_id"] == "artifact_1"

    imported = client.post(
        "/api/product/settings/assets/import",
        headers=auth,
        json={
            "schema_version": "byq-workspace-assets-v1",
            "assets": {
                "pools": [{"name": "新池", "symbols": ["000002.SZ"], "provenance": {"source": "export"}}],
                "paper_accounts": [],
                "strategies": [],
                "backtests": [],
            },
        },
    )
    assert imported.status_code == 200
    assert imported.json()["imported"]["pools"] == 1


def test_product_backtest_result_is_owner_scoped(monkeypatch) -> None:
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    monkeypatch.setattr(product_api, "PRODUCT_PRINCIPAL", "product-user")

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"job_id": "backtest_1", "result": {"total_return": 0.1, "trade_count": 2, "equity_curve": []}}

    captured: dict[str, object] = {}

    def fake_request(method: str, url: str, **kwargs) -> FakeResponse:
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = kwargs.get("headers", {})
        return FakeResponse()

    monkeypatch.setattr(product_api.httpx, "request", fake_request)
    client = TestClient(main.app)
    response = client.get(
        "/api/product/backtests/backtest_1/result",
        headers={"Authorization": "Bearer product-test-token"},
    )
    assert response.status_code == 200
    assert response.json()["result"]["trade_count"] == 2
    assert captured["url"].endswith("/v1/research/backtests/backtest_1/result")
    assert captured["headers"]["x-byq-owner-principal"] == "product-user"


def test_product_strategy_version_create_proxy(monkeypatch) -> None:
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    monkeypatch.setattr(product_api, "PRODUCT_PRINCIPAL", "product-user")

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"artifact": {"artifact_id": "artifact_version_1", "kind": "strategy_version"}}

    captured: dict[str, object] = {}

    def fake_request(method: str, url: str, **kwargs) -> FakeResponse:
        captured["method"] = method
        captured["url"] = url
        captured["payload"] = kwargs.get("json")
        return FakeResponse()

    monkeypatch.setattr(product_api.httpx, "request", fake_request)
    client = TestClient(main.app)
    response = client.post(
        "/api/product/strategies/versions",
        headers={"Authorization": "Bearer product-test-token"},
        json={"task_id": "task_1", "draft_artifact_id": "artifact_draft_1"},
    )
    assert response.status_code == 201
    assert captured["url"].endswith("/v1/research/strategies/versions")
    assert captured["payload"] == {"task_id": "task_1", "draft_artifact_id": "artifact_draft_1"}


def test_product_strategy_draft_and_projection_routes_forward_owner_headers(monkeypatch) -> None:
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    monkeypatch.setattr(product_api, "PRODUCT_PRINCIPAL", "product-user")

    class FakeResponse:
        def __init__(self, body: dict[str, object]) -> None:
            self.body = body

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return self.body

    captured: dict[str, object] = {}

    def fake_request(method: str, url: str, **kwargs) -> FakeResponse:
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = kwargs.get("headers", {})
        if url.endswith("/v1/research/strategies/drafts"):
            return FakeResponse({"artifact": {"artifact_id": "artifact_draft_1", "kind": "strategy_draft"}})
        if url.endswith("/strategies/MomentumStrategy/versions"):
            return FakeResponse({"strategy_id": "MomentumStrategy", "versions": [{"artifact_id": "artifact_version_1"}]})
        if url.endswith("/strategies/MomentumStrategy/backtest-count"):
            return FakeResponse({"strategy_id": "MomentumStrategy", "version_count": 1, "backtest_count": 2})
        return FakeResponse({"artifact": {"artifact_id": "artifact_draft_1", "status": "superseded"}})

    monkeypatch.setattr(product_api.httpx, "request", fake_request)
    client = TestClient(main.app)
    auth = {"Authorization": "Bearer product-test-token"}

    saved = client.post(
        "/api/product/strategies/drafts",
        headers=auth,
        json={"task_id": "task_1", "strategy": {"strategy_id": "MomentumStrategy", "script": "class CustomStrategy: pass"}},
    )
    assert saved.status_code == 201
    assert captured["url"].endswith("/v1/research/strategies/drafts")
    assert saved.json()["artifact"]["kind"] == "strategy_draft"

    deleted = client.delete("/api/product/strategies/drafts/artifact_draft_1", headers=auth)
    assert deleted.status_code == 200
    assert captured["url"].endswith("/v1/research/strategies/drafts/artifact_draft_1")
    assert captured["headers"]["x-byq-owner-principal"] == "product-user"

    history = client.get("/api/product/strategies/MomentumStrategy/versions", headers=auth)
    assert history.status_code == 200
    assert history.json()["versions"][0]["artifact_id"] == "artifact_version_1"
    assert captured["headers"]["x-byq-owner-principal"] == "product-user"

    counts = client.get("/api/product/strategies/MomentumStrategy/backtest-count", headers=auth)
    assert counts.status_code == 200
    assert counts.json()["backtest_count"] == 2
    assert captured["headers"]["x-byq-owner-principal"] == "product-user"


def test_product_stock_pool_create_forwards_owner_headers(monkeypatch) -> None:
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    monkeypatch.setattr(product_api, "PRODUCT_PRINCIPAL", "product-user")

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"pool": {"pool_id": "stock_pool_1", "name": "测试池", "pool_type": "custom"}}

    captured: dict[str, object] = {}

    def fake_request(method: str, url: str, **kwargs) -> FakeResponse:
        captured["url"] = url
        captured["headers"] = kwargs.get("headers", {})
        return FakeResponse()

    monkeypatch.setattr(product_api.httpx, "request", fake_request)
    client = TestClient(main.app)
    response = client.post(
        "/api/product/paper/pools",
        headers={"Authorization": "Bearer product-test-token"},
        json={"name": "测试池", "symbols": ["000001.SZ"], "pool_type": "custom"},
    )
    assert response.status_code == 201
    assert captured["url"].endswith("/v1/paper/pools")
    assert captured["headers"]["x-byq-owner-principal"] == "product-user"


def test_product_paper_ledger_forwards_owner_headers(monkeypatch) -> None:
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    monkeypatch.setattr(product_api, "PRODUCT_PRINCIPAL", "product-user")

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"ledger": [{"fill_id": "fill_1", "cash_delta": -1000.0}]}

    captured: dict[str, object] = {}

    def fake_request(method: str, url: str, **kwargs) -> FakeResponse:
        captured["url"] = url
        captured["headers"] = kwargs.get("headers", {})
        return FakeResponse()

    monkeypatch.setattr(product_api.httpx, "request", fake_request)
    client = TestClient(main.app)
    response = client.get(
        "/api/product/paper/accounts/paper_account_1/ledger",
        headers={"Authorization": "Bearer product-test-token"},
    )
    assert response.status_code == 200
    assert captured["url"].endswith("/v1/paper/accounts/paper_account_1/ledger")
    assert captured["headers"]["x-byq-owner-principal"] == "product-user"


def test_product_paper_order_create_forwards_owner_headers(monkeypatch) -> None:
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    monkeypatch.setattr(product_api, "PRODUCT_PRINCIPAL", "product-user")

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"order": {"order_id": "order_1", "status": "filled"}}

    captured: dict[str, object] = {}

    def fake_request(method: str, url: str, **kwargs) -> FakeResponse:
        captured["url"] = url
        captured["headers"] = kwargs.get("headers", {})
        return FakeResponse()

    monkeypatch.setattr(product_api.httpx, "request", fake_request)
    client = TestClient(main.app)
    response = client.post(
        "/api/product/paper/orders",
        headers={"Authorization": "Bearer product-test-token"},
        json={"account_id": "paper_account_1", "symbol": "000001.SZ", "side": "buy"},
    )
    assert response.status_code == 201
    assert captured["url"].endswith("/v1/paper/orders")
    assert captured["headers"]["x-byq-owner-principal"] == "product-user"


def test_product_approval_decision_forwards_owner_headers(monkeypatch) -> None:
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    monkeypatch.setattr(product_api, "PRODUCT_PRINCIPAL", "product-user")

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"approval": {"approval_id": "agent_approval_1", "status": "approved"}}

    captured: dict[str, object] = {}

    def fake_request(method: str, url: str, **kwargs) -> FakeResponse:
        captured["url"] = url
        captured["headers"] = kwargs.get("headers", {})
        captured["payload"] = kwargs.get("json")
        return FakeResponse()

    monkeypatch.setattr(product_api.httpx, "request", fake_request)
    client = TestClient(main.app)
    response = client.post(
        "/api/product/approvals/agent_approval_1/decision",
        headers={"Authorization": "Bearer product-test-token"},
        json={"decision": "approved", "rationale": "ok"},
    )
    assert response.status_code == 200
    assert captured["url"].endswith("/v1/agents/approvals/agent_approval_1/decision")
    assert captured["headers"]["x-byq-owner-principal"] == "product-user"
    assert captured["payload"] == {"decision": "approved", "rationale": "ok"}


def test_product_agent_policy_get_and_update(monkeypatch) -> None:
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    monkeypatch.setattr(product_api, "PRODUCT_PRINCIPAL", "product-user")

    class FakeResponse:
        def __init__(self, body: dict[str, object]) -> None:
            self.body = body

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return self.body

    def fake_request(method: str, url: str, **kwargs) -> FakeResponse:
        if url.endswith("/v1/agents/approvals"):
            return FakeResponse({"approvals": []})
        if method == "PUT":
            return FakeResponse({"policy": {"owner_principal": "product-user", "automation_enabled": False, "paused": True, "default_decision_mode": "manual"}})
        return FakeResponse({"policy": {"owner_principal": "product-user", "automation_enabled": True, "default_decision_mode": "manual"}})

    monkeypatch.setattr(product_api.httpx, "request", fake_request)
    client = TestClient(main.app)
    auth = {"Authorization": "Bearer product-test-token"}
    response = client.get("/api/product/settings/agent-policy", headers=auth)
    assert response.status_code == 200
    assert response.json()["personal_policy"]["automation_enabled"] is True

    updated = client.put(
        "/api/product/settings/agent-policy",
        headers=auth,
        json={"automation_enabled": False, "paused": True},
    )
    assert updated.status_code == 200
    assert updated.json()["personal_policy"]["paused"] is True


def test_product_data_center_status_exposes_masked_provider_capability(monkeypatch) -> None:
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    monkeypatch.setattr(product_api, "PRODUCT_PRINCIPAL", "product-user")
    monkeypatch.setattr(product_api.os, "environ", {**product_api.os.environ, "TUSHARE_TOKEN": "ci-test"})
    client = TestClient(main.app)
    response = client.get(
        "/api/product/data-center/status",
        headers={"Authorization": "Bearer product-test-token"},
    )
    assert response.status_code == 200
    assert response.json()["provider_status"] == {"configured": True, "sync": "not_started"}
    assert "ci-test" not in response.text


def test_product_asset_import_rejects_secret_fields(monkeypatch) -> None:
    monkeypatch.setattr(product_api, "PRODUCT_TOKEN", "product-test-token")
    monkeypatch.setattr(product_api, "PRODUCT_PRINCIPAL", "product-user")
    client = TestClient(main.app)
    response = client.post(
        "/api/product/settings/assets/import",
        headers={"Authorization": "Bearer product-test-token"},
        json={
            "schema_version": "byq-workspace-assets-v1",
            "assets": {"pools": [{"name": "bad", "api_token": "secret"}]},
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "product_asset_bundle_invalid"
