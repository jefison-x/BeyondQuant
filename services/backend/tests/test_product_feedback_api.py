from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.agent_research import AgentResearchStore
from app.main import app
from app.product_feedback import ProductFeedbackStore
from tests.workspace_helpers import trusted_agent_context, trusted_product_agent_context


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


def test_feedback_api_owner_preview_submit_and_hub_outbox() -> None:
    headers = {
        **trusted_agent_context("feedback-api-owner"),
        "x-byq-feedback-browser-family": "chrome", "x-byq-feedback-os-family": "linux",
    }
    options = client.get("/v1/feedback/options", headers=headers)
    assert options.status_code == 200
    assert options.json()["privacy"]["normal_user_github_configuration"] is False
    assert "publisher" not in options.json()
    assert "central_hub" in options.json()

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
    assert submitted["central_hub"] == {"status": "queued", "receipt_id": None, "last_error_category": None}
    hub_outbox = main_module.feedback_store._fetch_one(
        "SELECT state,snapshot_hash FROM product_feedback_hub_outbox WHERE feedback_id=:feedback",
        {"feedback": feedback_id},
    )
    assert hub_outbox["state"] == "queued" and len(hub_outbox["snapshot_hash"]) == 64
    assert "publication_status" not in submitted
    assert client.get("/v1/feedback/moderation/items", headers=headers).status_code == 404
    assert client.post("/internal/feedback-publications/claim", json={"worker_id": "legacy-worker"}).status_code == 404


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


def test_feedback_hub_relay_route_remains_service_authenticated(monkeypatch) -> None:
    monkeypatch.setattr(main_module, "FEEDBACK_HUB_RELAY_TOKEN", "hub-relay-test-token")
    payload = {"worker_id": "hub-relay-api", "limit": 1, "lease_seconds": 30}
    assert client.post("/internal/feedback-hub/claim", json=payload).status_code == 401
    claimed = client.post("/internal/feedback-hub/claim", headers={
        "x-byq-feedback-hub-relay-token": "hub-relay-test-token",
    }, json=payload)
    assert claimed.status_code == 200 and isinstance(claimed.json()["events"], list)


def test_agent_feedback_submit_requires_exact_global_approval(monkeypatch) -> None:
    feedback = ProductFeedbackStore()
    agents = AgentResearchStore()
    monkeypatch.setattr(main_module, "feedback_store", feedback)
    monkeypatch.setattr(main_module, "agent_store", agents)
    agent_headers = trusted_product_agent_context(
        "feedback-agent-owner", actor="byq-product-agent-feedback",
        trace_id="feedback-agent-trace", session_id="feedback-agent-session", dsh_run_id="feedback-agent-run",
    )
    human_headers = trusted_agent_context(
        "feedback-agent-owner", actor="feedback-agent-owner",
        trace_id="feedback-agent-trace", session_id="feedback-agent-session", dsh_run_id="feedback-agent-run",
    )
    agent = TestClient(app); agent.headers.update(agent_headers)
    created = agent.post("/v1/feedback/items", json={**draft_payload(), "idempotency_key": "agent-feedback-create"})
    item = created.json()["feedback"]
    preview = agent.post(f"/v1/feedback/items/{item['feedback_id']}/preview", json={"expected_version": item["version"]}).json()
    run = agent.post("/v1/agents/runs", json={"role_id":"quant_orchestrator","idempotency_key":"agent-feedback-run"}).json()["run"]
    authorization = agent.post("/v1/agents/authorize", json={
        "run_id":run["run_id"],"action":"byq_feedback_submit","resource_type":"product_feedback","resource_id":item["feedback_id"],
    })
    assert authorization.json()["authorization"]["decision"] == "approval_required"
    approval = agent.post("/v1/agents/approvals", json={
        "run_id":run["run_id"],"action":"byq_feedback_submit","reason":"Submit the reviewed public candidate.",
        "resource_type":"product_feedback","resource_id":item["feedback_id"],"idempotency_key":"agent-feedback-approval",
    }).json()["approval"]
    decided = agent.post(f"/v1/agents/approvals/{approval['approval_id']}/decision", headers=human_headers,
                         json={"decision":"approved","rationale":"已检查公开候选内容"})
    assert decided.status_code == 200
    submit_payload = {
        "expected_version": item["version"], "preview_hash": preview["preview_hash"],
        "disclosure_confirmed": True, "idempotency_key": "agent-feedback-submit",
    }
    missing_grant = agent.post(
        f"/v1/feedback/items/{item['feedback_id']}/submit", json=submit_payload,
    )
    assert missing_grant.status_code == 403, missing_grant.text
    wrong_grant = agent.post(
        f"/v1/feedback/items/{item['feedback_id']}/submit",
        json={**submit_payload, "agent_approval_id": "agent_approval_" + "0" * 32},
    )
    assert wrong_grant.status_code == 403, wrong_grant.text
    assert agent.get(f"/v1/feedback/items/{item['feedback_id']}").json()["feedback"]["status"] == "draft"
    submitted = agent.post(f"/v1/feedback/items/{item['feedback_id']}/submit", json={
        "expected_version":item["version"],"preview_hash":preview["preview_hash"],"disclosure_confirmed":True,
        "agent_approval_id":approval["approval_id"],"idempotency_key":"agent-feedback-submit",
    })
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["feedback"]["status"] == "submitted"
    feedback.close(); agents.close()
