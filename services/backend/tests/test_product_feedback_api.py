from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.main import app
from tests.workspace_helpers import trusted_agent_context


pytestmark = pytest.mark.skipif(not os.environ.get("BYQ_DATABASE_URL"), reason="BYQ_DATABASE_URL is not set")
client = TestClient(app)


def draft_payload() -> dict[str, object]:
    return {
        "schema_version": "product-feedback.v1", "category": "bug", "component": "data_center",
        "title": "数据管理页面初次加载较慢", "description": "打开数据管理页面后需要等待较长时间。",
        "reproduction_steps": ["打开系统设置", "进入数据管理"],
        "expected_behavior": "先显示轻量目录。", "actual_behavior": "首屏等待时间较长。",
        "severity": "normal",
        "diagnostics": {"include_product_version": True, "include_browser_family": True},
        "idempotency_key": "api-feedback-create",
    }


def test_feedback_api_owner_preview_moderation_and_outbox() -> None:
    headers = {
        **trusted_agent_context("feedback-api-owner"),
        "x-byq-feedback-browser-family": "chrome", "x-byq-feedback-os-family": "linux",
    }
    options = client.get("/v1/feedback/options", headers=headers)
    assert options.status_code == 200
    assert options.json()["privacy"]["normal_user_github_configuration"] is False

    created = client.post("/v1/feedback/items", headers=headers, json=draft_payload())
    assert created.status_code == 201, created.text
    draft = created.json()["feedback"]
    feedback_id = draft["feedback_id"]
    assert "workspace_id" not in created.text and "owner_principal" not in created.text

    page = client.get("/v1/feedback/items", headers=headers, params={"limit": 1, "offset": 0})
    assert page.status_code == 200 and page.json()["total"] == 1
    detail = client.get(f"/v1/feedback/items/{feedback_id}", headers=headers)
    assert detail.json()["feedback"]["content"]["component"] == "data_center"
    preview = client.post(
        f"/v1/feedback/items/{feedback_id}/preview", headers=headers, json={"expected_version": draft["version"]},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["public_content"]["environment"] == {
        "browser_family": "chrome", "product_version": "0.1.0",
    }
    submitted_response = client.post(
        f"/v1/feedback/items/{feedback_id}/submit", headers=headers,
        json={"expected_version": draft["version"], "preview_hash": preview.json()["preview_hash"],
              "disclosure_confirmed": True, "idempotency_key": "api-feedback-submit"},
    )
    assert submitted_response.status_code == 200, submitted_response.text
    submitted = submitted_response.json()["feedback"]

    denied = client.get("/v1/feedback/moderation/items", headers={"x-byq-actor-principal": "reader", "x-byq-actor-role": "user"})
    assert denied.status_code == 403
    moderator = {"x-byq-actor-principal": "feedback-admin", "x-byq-actor-role": "admin"}
    inbox = client.get("/v1/feedback/moderation/items", headers=moderator)
    assert inbox.status_code == 200 and inbox.json()["total"] == 1
    assert "owner_principal" not in inbox.text and "workspace_id" not in inbox.text

    triage = client.post(
        f"/v1/feedback/moderation/items/{feedback_id}/triage", headers=moderator,
        json={"expected_version": submitted["version"], "rationale": "复现信息完整", "idempotency_key": "api-triage"},
    )
    assert triage.status_code == 200, triage.text
    accept = client.post(
        f"/v1/feedback/moderation/items/{feedback_id}/accept", headers=moderator,
        json={"expected_version": triage.json()["feedback"]["version"], "rationale": "进入公开发布队列",
              "idempotency_key": "api-accept"},
    )
    assert accept.status_code == 200, accept.text
    assert accept.json()["feedback"]["publication_status"] == "publisher_unconfigured"
    status = client.get("/v1/feedback/moderation/publisher-status", headers=moderator)
    assert status.json()["configured"] is False and status.json()["queue"]["queued"] == 1


def test_feedback_api_fails_closed_for_cross_workspace_and_unsafe_payload() -> None:
    alice = trusted_agent_context("feedback-api-alice")
    bob = trusted_agent_context("feedback-api-bob")
    created = client.post("/v1/feedback/items", headers=alice, json={**draft_payload(), "idempotency_key": "alice-create"})
    feedback_id = created.json()["feedback"]["feedback_id"]
    assert client.get(f"/v1/feedback/items/{feedback_id}", headers=bob).status_code == 404
    unsafe = client.post(
        "/v1/feedback/items", headers=alice,
        json={**draft_payload(), "description": "authorization=Bearer-secret-value", "idempotency_key": "unsafe-create"},
    )
    assert unsafe.status_code == 422
    assert "Bearer-secret-value" not in unsafe.text


def test_feedback_publisher_internal_routes_require_service_token(monkeypatch) -> None:
    monkeypatch.setattr(main_module, "FEEDBACK_PUBLISHER_TOKEN", "publisher-test-token")
    assert client.post("/internal/feedback-publications/claim", json={"worker_id": "worker-api"}).status_code == 401
    headers = {"x-byq-feedback-publisher-token": "publisher-test-token"}
    heartbeat = client.post("/internal/feedback-publications/heartbeat", headers=headers, json={
        "configured": True, "credential_kind": "github_app", "repository": "jefison-x/BeyondQuant",
        "worker_version": "test-v1",
    })
    assert heartbeat.status_code == 200 and heartbeat.json()["accepted"] is True
    claimed = client.post("/internal/feedback-publications/claim", headers=headers,
                          json={"worker_id": "worker-api", "limit": 1, "lease_seconds": 30})
    assert claimed.status_code == 200 and claimed.json()["events"] == []
