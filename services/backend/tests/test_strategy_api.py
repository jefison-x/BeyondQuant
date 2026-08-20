from __future__ import annotations

import os
import pytest

from fastapi.testclient import TestClient

from app import main
from app.backtest import BacktestJobStore, LocalObjectStore, membership_fingerprint
from app.research import ResearchStore
from test_strategy_artifact import strategy_payload




pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"),
    reason="BYQ_DATABASE_URL is not set",
)

def _task(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/v1/research/tasks",
        json={
            "owner_principal": "product-user",
            "title": "Strategy artifact task",
            "objective": "Validate and version a strategy artifact.",
            "trace_id": "byq-trace-strategy-api",
            "idempotency_key": "strategy-api-task-1",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_strategy_draft_version_export_and_approval_flow(monkeypatch) -> None:
    store = ResearchStore()
    monkeypatch.setattr(main, "research_store", store)
    client = TestClient(main.app)
    task = _task(client)

    draft_response = client.post(
        "/v1/research/strategies/validate",
        json={
            "task_id": task["task_id"],
            "strategy": strategy_payload(),
            "trace_id": "byq-trace-strategy-api",
            "idempotency_key": "strategy-draft-1",
        },
    )
    assert draft_response.status_code == 201, draft_response.text
    draft = draft_response.json()
    assert draft["validation"]["success"] is True
    assert draft["artifact"]["kind"] == "strategy_draft"
    assert draft["artifact"]["status"] == "validated"

    version_request = {
        "task_id": task["task_id"],
        "draft_artifact_id": draft["artifact"]["artifact_id"],
        "trace_id": "byq-trace-strategy-api",
        "idempotency_key": "strategy-version-1",
    }
    version_response = client.post("/v1/research/strategies/versions", json=version_request)
    assert version_response.status_code == 201, version_response.text
    version = version_response.json()
    assert version["artifact"]["kind"] == "strategy_version"
    assert version["artifact"]["status"] == "validated"
    version_id = version["strategy_version"]["version_id"]

    retry = client.post(
        "/v1/research/strategies/versions",
        json={**version_request, "idempotency_key": "strategy-version-retry"},
    )
    assert retry.status_code == 201
    assert retry.json()["artifact"]["artifact_id"] == version["artifact"]["artifact_id"]

    exported = client.get(f"/v1/research/strategies/versions/{version['artifact']['artifact_id']}/export")
    assert exported.status_code == 200
    assert exported.json()["export"]["version_id"] == version_id
    assert "trace_id" not in exported.text

    approval = client.post(
        "/v1/research/strategies/approvals",
        json={
            "task_id": task["task_id"],
            "strategy_version_artifact_id": version["artifact"]["artifact_id"],
            "reviewer_principal": "human-owner",
            "decision": "approved",
            "rationale": "Static contract reviewed.",
            "trace_id": "byq-trace-strategy-api",
            "idempotency_key": "strategy-approval-1",
        },
    )
    assert approval.status_code == 201, approval.text
    body = approval.json()
    assert body["approval"]["execution_authorized"] is True
    assert body["approval"]["execution_outcome"] == "not_started"
    assert body["artifact"]["kind"] == "strategy_approval"
    assert body["artifact"]["status"] == "validated"
    store.close()


def test_strategy_api_rejects_invalid_source_without_creating_artifact(monkeypatch) -> None:
    store = ResearchStore()
    monkeypatch.setattr(main, "research_store", store)
    client = TestClient(main.app)
    task = _task(client)
    response = client.post(
        "/v1/research/strategies/validate",
        json={
            "task_id": task["task_id"],
            "strategy": {**strategy_payload(), "script": "import os"},
            "trace_id": "byq-trace-strategy-api",
            "idempotency_key": "strategy-draft-invalid",
        },
    )
    assert response.status_code == 422
    assert store._execute("SELECT COUNT(*) FROM artifacts")[0]["count"] == 0
    store.close()

def _owner_headers(principal: str = "product-user") -> dict[str, str]:
    return {
        "x-byq-owner-principal": principal,
        "x-byq-actor-principal": principal,
        "x-byq-trace-id": f"byq-trace-{principal}",
        "x-byq-session-id": f"byq-session-{principal}",
        "x-byq-dsh-run-id": f"byq-run-{principal}",
    }


def test_strategy_draft_save_tolerates_invalid_and_delete(monkeypatch) -> None:
    store = ResearchStore()
    monkeypatch.setattr(main, "research_store", store)
    client = TestClient(main.app)
    task = _task(client)

    saved = client.post(
        "/v1/research/strategies/drafts",
        json={
            "task_id": task["task_id"], "strategy": strategy_payload(),
            "trace_id": "byq-trace-strategy-p33", "idempotency_key": "strategy-save-1",
        },
    )
    assert saved.status_code == 201, saved.text
    saved_body = saved.json()
    assert saved_body["artifact"]["kind"] == "strategy_draft"
    assert saved_body["artifact"]["status"] == "draft"
    assert saved_body["validation"]["success"] is True

    # Tolerant save of an intermediate draft that fails static validation.
    invalid = strategy_payload(script="import os\nclass CustomStrategy:\n    def generate_signals(self, data, parameters=None):\n        return {}\n")
    saved_invalid = client.post(
        "/v1/research/strategies/drafts",
        json={
            "task_id": task["task_id"], "strategy": invalid,
            "trace_id": "byq-trace-strategy-p33", "idempotency_key": "strategy-save-invalid-1",
        },
    )
    assert saved_invalid.status_code == 201, saved_invalid.text
    assert saved_invalid.json()["validation"]["success"] is False

    deleted = client.delete(
        f"/v1/research/strategies/drafts/{saved_body['artifact']['artifact_id']}",
        headers=_owner_headers(),
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["artifact"]["status"] == "superseded"

    # Non-owner delete must 404 (owner-scoped).
    denied = client.delete(
        f"/v1/research/strategies/drafts/{saved_body['artifact']['artifact_id']}",
        headers=_owner_headers("other-user"),
    )
    assert denied.status_code == 404
    store.close()


def test_strategy_version_history_and_backtest_count(monkeypatch, tmp_path) -> None:
    store = ResearchStore()
    jobs = BacktestJobStore()
    objects = LocalObjectStore(tmp_path / "objects")
    monkeypatch.setattr(main, "research_store", store)
    monkeypatch.setattr(main, "backtest_store", jobs)
    monkeypatch.setattr(main, "backtest_objects", objects)
    client = TestClient(main.app)
    task = _task(client)
    strategy = strategy_payload()
    strategy_id = str(strategy["strategy_id"])

    draft = client.post(
        "/v1/research/strategies/validate",
        json={
            "task_id": task["task_id"], "strategy": strategy,
            "trace_id": "byq-trace-strategy-p33", "idempotency_key": "strategy-draft-p33-1",
        },
    ).json()
    version = client.post(
        "/v1/research/strategies/versions",
        json={
            "task_id": task["task_id"], "draft_artifact_id": draft["artifact"]["artifact_id"],
            "trace_id": "byq-trace-strategy-p33", "idempotency_key": "strategy-version-p33-1",
        },
    ).json()
    approval = client.post(
        "/v1/research/strategies/approvals",
        json={
            "task_id": task["task_id"],
            "strategy_version_artifact_id": version["artifact"]["artifact_id"],
            "reviewer_principal": "human-owner", "decision": "approved",
            "trace_id": "byq-trace-strategy-p33", "idempotency_key": "strategy-approval-p33-1",
        },
    ).json()

    history = client.get(f"/v1/research/strategies/{strategy_id}/versions", headers=_owner_headers())
    assert history.status_code == 200, history.text
    assert any(v["artifact_id"] == version["artifact"]["artifact_id"] for v in history.json()["versions"])

    count0 = client.get(f"/v1/research/strategies/{strategy_id}/backtest-count", headers=_owner_headers())
    assert count0.status_code == 200
    assert count0.json()["backtest_count"] == 0

    sym = "000001.SZ"
    universe = {
        "universe_id": "fixture", "version_id": "fixture-v1",
        "membership_fingerprint": membership_fingerprint([sym]), "symbols": [sym],
    }
    bars = [
        {"symbol": sym, "trade_date": "2026-01-05", "open": 10, "high": 10, "low": 10, "close": 10},
        {"symbol": sym, "trade_date": "2026-01-06", "open": 10, "high": 10, "low": 10, "close": 10},
    ]
    submit = client.post(
        "/v1/research/backtests",
        json={
            "task_id": task["task_id"],
            "strategy_version_artifact_id": version["artifact"]["artifact_id"],
            "approval_artifact_id": approval["artifact"]["artifact_id"],
            "trace_id": "byq-trace-strategy-p33", "idempotency_key": "backtest-p33-1",
            "universe": universe, "bars": bars,
            "signals": [{"symbol": sym, "trade_date": "2026-01-05", "side": "buy", "quantity": 100}],
            "execution": {"initial_capital": 2_000, "commission_rate": 0, "stamp_tax_rate": 0, "lot_size": 100},
        },
    )
    assert submit.status_code == 202, submit.text
    job = submit.json()["job"]
    assert client.post(f"/v1/research/backtests/{job['job_id']}/run").json()["job"]["status"] == "completed"

    count1 = client.get(f"/v1/research/strategies/{strategy_id}/backtest-count", headers=_owner_headers())
    assert count1.status_code == 200
    assert count1.json()["backtest_count"] == 1
    assert count1.json()["version_count"] == 1
    store.close()
    jobs.close()
