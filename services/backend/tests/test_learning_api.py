from __future__ import annotations

import os

import os
import pytest

from fastapi.testclient import TestClient

from app import main
from app.learning_loop import LearningLoopStore
from app.research import ResearchStore
from tests.workspace_helpers import trusted_agent_context




pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"),
    reason="BYQ_DATABASE_URL is not set",
)

def test_learning_api_requires_context_and_stops_at_human_gate(monkeypatch, tmp_path) -> None:
    context = trusted_agent_context(
        "alice", trace_id="trace-learning-api", session_id="session-learning-api",
        dsh_run_id="dsh-run-learning-api",
    )
    research = ResearchStore()
    task = research.create_task(
        {
            "owner_principal": "alice",
            "title": "api learning",
            "objective": "exercise learning API",
            "trace_id": "trace-learning-api",
            "idempotency_key": "task-learning-api",
        }
    )
    learning = LearningLoopStore(research_store=research)
    monkeypatch.setattr(main, "research_store", research)
    monkeypatch.setattr(main, "learning_store", learning)
    client = TestClient(main.app)

    missing = client.post(
        "/v1/learning/runs",
        json={"task_id": task["task_id"], "budget": {"max_iterations": 1, "max_repairs": 0}, "idempotency_key": "run-api-1"},
    )
    assert missing.status_code == 401

    started = client.post(
        "/v1/learning/runs",
        headers=context,
        json={"task_id": task["task_id"], "budget": {"max_iterations": 1, "max_repairs": 0}, "idempotency_key": "run-api-1"},
    )
    assert started.status_code == 201, started.text
    run = started.json()["run"]
    assert run["owner_principal"] == "alice"
    assert run["status"] == "active"

    iterated = client.post(
        f"/v1/learning/runs/{run['learning_run_id']}/iterations",
        headers=context,
        json={
            "iteration_index": 1,
            "attempt": 1,
            "outcome": "produced",
            "feedback": {"sharpe": 1.2},
            "idempotency_key": "iteration-api-1",
        },
    )
    assert iterated.status_code == 201, iterated.text
    assert iterated.json()["run"]["status"] == "awaiting_review"

    self_review = client.post(
        f"/v1/learning/runs/{run['learning_run_id']}/review",
        headers=context,
        json={"decision": "approved"},
    )
    assert self_review.status_code == 403

    human_context = {**context, "x-byq-actor-principal": "human-reviewer"}
    reviewed = client.post(
        f"/v1/learning/runs/{run['learning_run_id']}/review",
        headers=human_context,
        json={"decision": "approved", "rationale": "looks good"},
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["run"]["status"] == "completed"

    learning.close()
    research.close()
