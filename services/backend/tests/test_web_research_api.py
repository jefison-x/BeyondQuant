from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app import main
from app.research import ResearchStore
from tests.test_web_research import evidence_fixture
from tests.workspace_helpers import trusted_agent_context


pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"),
    reason="BYQ_DATABASE_URL is not set",
)


def test_web_evidence_promotion_is_owner_scoped_and_trace_bound(monkeypatch) -> None:
    context = trusted_agent_context("alice", trace_id="trace-web-api-1")
    store = ResearchStore()
    monkeypatch.setattr(main, "research_store", store)
    task = store.create_task(
        {
            "owner_principal": "alice",
            "title": "Web evidence",
            "objective": "Persist qualified public research evidence.",
            "trace_id": "trace-web-api-1",
            "idempotency_key": "web-task-1",
        }
    )
    request = {
        "task_id": task["task_id"],
        "content": evidence_fixture(),
        "lineage": [],
        "idempotency_key": "web-evidence-api-1",
    }
    client = TestClient(main.app)

    missing = client.post("/v1/research/web-evidence", json=request)
    assert missing.status_code == 401

    wrong_owner = client.post(
        "/v1/research/web-evidence",
        headers=trusted_agent_context("bob", trace_id="trace-web-api-bob"),
        json=request,
    )
    assert wrong_owner.status_code == 404

    created = client.post("/v1/research/web-evidence", headers=context, json=request)
    assert created.status_code == 201, created.text
    artifact = created.json()
    assert artifact["kind"] == "web_research_evidence"
    assert artifact["owner_principal"] == "alice"
    assert artifact["trace_id"] == "trace-web-api-1"
    assert artifact["content"]["usage_policy"]["deterministic_input"] is False
    assert "credential" not in created.text.lower()
    store.close()
