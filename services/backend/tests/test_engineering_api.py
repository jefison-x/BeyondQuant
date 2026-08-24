from __future__ import annotations

import os
import pytest

from fastapi.testclient import TestClient

from app import main
from app.engineering import EngineeringTaskStore
from tests.workspace_helpers import trusted_agent_context




pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"),
    reason="BYQ_DATABASE_URL is not set",
)

def test_engineering_api_requires_context_and_evidence_gate(monkeypatch, tmp_path) -> None:
    context = trusted_agent_context(
        "alice", trace_id="trace-engineering-api", session_id="session-engineering-api",
        dsh_run_id="dsh-run-engineering-api",
    )
    store = EngineeringTaskStore()
    monkeypatch.setattr(main, "engineering_store", store)
    client = TestClient(main.app)

    missing = client.post(
        "/v1/engineering/tasks",
        json={"title": "fix", "description": "fix", "scope": "services/backend", "idempotency_key": "eng-api-1"},
    )
    assert missing.status_code == 401

    created = client.post(
        "/v1/engineering/tasks",
        headers=context,
        json={"title": "fix", "description": "fix", "scope": "services/backend", "idempotency_key": "eng-api-1"},
    )
    assert created.status_code == 201, created.text
    task = created.json()["task"]
    assert task["owner_principal"] == "alice"
    assert task["status"] == "proposed"

    approved = client.post(
        f"/v1/engineering/tasks/{task['task_id']}/transitions",
        headers={**context, "x-byq-actor-principal": "human-reviewer"},
        json={"target_status": "approved", "idempotency_key": "approve-api"},
    )
    assert approved.status_code == 201, approved.text

    started = client.post(
        f"/v1/engineering/tasks/{task['task_id']}/transitions",
        headers=context,
        json={"target_status": "in_progress", "idempotency_key": "start-api"},
    )
    assert started.status_code == 201, started.text

    evidence = client.post(
        f"/v1/engineering/tasks/{task['task_id']}/evidence",
        headers=context,
        json={
            "worktree_path": "/home/jefison/projects/.byq-worktrees/phase-15-engineering-plane",
            "branch_name": "codex/phase-15-engineering-plane",
            "draft_pr_number": 15,
            "ci_status": "success",
            "self_review": True,
            "architecture_evidence": {"boundary": "Product/Engineering separation"},
            "idempotency_key": "evidence-api",
        },
    )
    assert evidence.status_code == 200, evidence.text

    reviewed = client.post(
        f"/v1/engineering/tasks/{task['task_id']}/transitions",
        headers=context,
        json={"target_status": "review_required", "idempotency_key": "review-api"},
    )
    assert reviewed.status_code == 201, reviewed.text

    completed = client.post(
        f"/v1/engineering/tasks/{task['task_id']}/transitions",
        headers=context,
        json={"target_status": "completed", "idempotency_key": "complete-api"},
    )
    assert completed.status_code == 201, completed.text
    assert completed.json()["task"]["merge_status"] == "not_merged"
    store.close()
