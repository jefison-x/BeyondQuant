from __future__ import annotations

import os
import pytest

from fastapi.testclient import TestClient

from app import main
from app.backtest import BacktestJobStore, LocalObjectStore, membership_fingerprint
from app.db import execute
from app.research import ResearchStore
from test_strategy_artifact import strategy_payload
from tests.workspace_helpers import trusted_agent_context




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


def test_strategy_queries_remain_exact_beyond_generic_200_row_limit(monkeypatch) -> None:
    store = ResearchStore()
    backtests = BacktestJobStore()
    monkeypatch.setattr(main, "research_store", store)
    monkeypatch.setattr(main, "backtest_store", backtests)
    client = TestClient(main.app)
    client.headers.update(_owner_headers("scale-owner"))
    task = client.post(
        "/v1/research/tasks",
        json={
            "owner_principal": "scale-owner", "title": "Scale strategy query",
            "objective": "Prove direct strategy counts", "trace_id": "scale-trace",
            "idempotency_key": "scale-task",
        },
    ).json()
    with store._transaction() as connection:
        execute(
            connection,
            """INSERT INTO artifacts
               (artifact_id, task_id, experiment_id, owner_principal, kind, status, content,
                content_sha256, lineage, trace_id, idempotency_key, request_hash,
                created_at, updated_at, version)
               SELECT 'artifact_' || lpad(to_hex(n), 32, '0'), :task_id, NULL, 'scale-owner',
                      'strategy_version', 'validated',
                      jsonb_build_object('strategy_id', 'ScaleStrategy', 'version_id', 'v-' || n),
                      repeat('a', 64), '[]'::jsonb, 'scale-trace', 'scale-version-' || n,
                      repeat('b', 64), now(), now(), 1
               FROM generate_series(1, 205) AS n""",
            {"task_id": task["task_id"]},
        )

    first = client.get("/v1/research/strategies?lifecycle=active&limit=50&offset=0")
    assert first.status_code == 200
    assert first.json()["total"] == 205
    assert len(first.json()["strategies"]) == 50
    last = client.get("/v1/research/strategies?lifecycle=active&limit=50&offset=200")
    assert len(last.json()["strategies"]) == 5
    history = client.get("/v1/research/strategies/ScaleStrategy/versions")
    assert len(history.json()["versions"]) == 205
    counts = client.get("/v1/research/strategies/ScaleStrategy/backtest-count")
    assert counts.json()["version_count"] == 205
    assert counts.json()["backtest_count"] == 0
    assert len(counts.json()["by_version"]) == 205
    backtests.close()
    store.close()


def test_strategy_draft_version_export_and_approval_flow(monkeypatch) -> None:
    store = ResearchStore()
    monkeypatch.setattr(main, "research_store", store)
    client = TestClient(main.app)
    client.headers.update(_owner_headers("product-user"))
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

    denied_version = client.post(
        "/v1/research/strategies/versions",
        headers=_owner_headers("other-user"),
        json={
            "task_id": task["task_id"],
            "draft_artifact_id": draft["artifact"]["artifact_id"],
            "trace_id": "byq-trace-other-user",
            "idempotency_key": "strategy-version-denied",
        },
    )
    assert denied_version.status_code == 404

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
    denied_export = client.get(
        f"/v1/research/strategies/versions/{version['artifact']['artifact_id']}/export",
        headers=_owner_headers("other-user"),
    )
    assert denied_export.status_code == 404

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
    exact_approval = client.get(
        f"/v1/research/strategies/versions/{version['artifact']['artifact_id']}/approval"
    )
    assert exact_approval.status_code == 200
    assert exact_approval.json()["approval"]["artifact_id"] == body["artifact"]["artifact_id"]
    denied_approval = client.get(
        f"/v1/research/strategies/versions/{version['artifact']['artifact_id']}/approval",
        headers=_owner_headers("other-user"),
    )
    assert denied_approval.status_code == 404
    task_options = client.get("/v1/research/task-options?limit=10")
    assert task_options.status_code == 200
    assert task_options.json()["tasks"][0]["task_id"] == task["task_id"]
    assert "objective" not in task_options.text
    store.close()


def test_strategy_api_rejects_invalid_source_without_creating_artifact(monkeypatch) -> None:
    store = ResearchStore()
    monkeypatch.setattr(main, "research_store", store)
    client = TestClient(main.app)
    client.headers.update(_owner_headers("product-user"))
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
    return trusted_agent_context(
        principal, trace_id=f"byq-trace-{principal}", session_id=f"byq-session-{principal}",
        dsh_run_id=f"byq-run-{principal}",
    )


def test_strategy_draft_save_tolerates_invalid_and_delete(monkeypatch) -> None:
    store = ResearchStore()
    monkeypatch.setattr(main, "research_store", store)
    client = TestClient(main.app)
    client.headers.update(_owner_headers("product-user"))
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
    client.headers.update(_owner_headers("product-user"))
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
