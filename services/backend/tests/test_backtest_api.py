from __future__ import annotations

import os

import os

import pytest

from fastapi.testclient import TestClient

from app import main
from app.backtest import (
    BacktestJobStore,
    LocalObjectStore,
    ObjectIntegrityError,
    membership_fingerprint,
)
from app.research import ResearchStore
from tests.workspace_helpers import trusted_agent_context


pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"),
    reason="BYQ_DATABASE_URL is not set",
)


SYMBOL = "000001.SZ"


def _strategy() -> dict[str, object]:
    return {
        "strategy_id": "MomentumStrategy",
        "name": "Momentum",
        "category": "momentum",
        "description": "A bounded strategy fixture.",
        "parameters": {"lookback": 20},
        "parameter_schema": {"lookback": {"type": "integer", "minimum": 1}},
        "source_type": "python_script",
        "script": "class CustomStrategy:\n    def generate_signals(self, data, parameters=None):\n        return {}",
    }


def test_backtest_submit_worker_and_get_flow(monkeypatch, tmp_path) -> None:
    store = ResearchStore()
    jobs = BacktestJobStore()
    monkeypatch.setattr(main, "research_store", store)
    monkeypatch.setattr(main, "backtest_store", jobs)
    monkeypatch.setattr(main, "backtest_objects", LocalObjectStore(tmp_path / "objects"))
    client = TestClient(main.app)
    client.headers.update(_owner_headers("product-user"))

    task = client.post(
        "/v1/research/tasks",
        json={
            "owner_principal": "product-user", "title": "Backtest API", "objective": "Run native fixture",
            "trace_id": "byq-trace-backtest-api", "idempotency_key": "task-backtest-api",
        },
    ).json()
    draft = client.post(
        "/v1/research/strategies/validate",
        json={"task_id": task["task_id"], "strategy": _strategy(), "trace_id": task["trace_id"], "idempotency_key": "draft-backtest-api"},
    ).json()
    version = client.post(
        "/v1/research/strategies/versions",
        json={"task_id": task["task_id"], "draft_artifact_id": draft["artifact"]["artifact_id"], "trace_id": task["trace_id"], "idempotency_key": "version-backtest-api"},
    ).json()
    approval = client.post(
        "/v1/research/strategies/approvals",
        json={
            "task_id": task["task_id"], "strategy_version_artifact_id": version["artifact"]["artifact_id"],
            "reviewer_principal": "human-owner", "decision": "approved", "trace_id": task["trace_id"],
            "idempotency_key": "approval-backtest-api",
        },
    ).json()
    universe = {
        "universe_id": "fixture", "version_id": "fixture-v1",
        "membership_fingerprint": membership_fingerprint([SYMBOL]), "symbols": [SYMBOL],
    }
    bars = [
        {"symbol": SYMBOL, "trade_date": "2026-01-05", "open": 10, "high": 10, "low": 10, "close": 10},
        {"symbol": SYMBOL, "trade_date": "2026-01-06", "open": 10, "high": 10, "low": 10, "close": 10},
    ]
    submit = client.post(
        "/v1/research/backtests",
        json={
            "task_id": task["task_id"], "strategy_version_artifact_id": version["artifact"]["artifact_id"],
            "approval_artifact_id": approval["artifact"]["artifact_id"], "trace_id": task["trace_id"],
            "idempotency_key": "backtest-api-1", "universe": universe, "bars": bars,
            "signals": [{"symbol": SYMBOL, "trade_date": "2026-01-05", "side": "buy", "quantity": 100}],
            "execution": {"initial_capital": 2_000, "commission_rate": 0, "stamp_tax_rate": 0, "lot_size": 100},
        },
    )
    assert submit.status_code == 202, submit.text
    job = submit.json()["job"]
    assert job["status"] == "queued"
    assert client.get(
        f"/v1/research/backtests/{job['job_id']}",
        headers=_owner_headers("other-user"),
    ).status_code == 404
    assert client.post(
        f"/v1/research/backtests/{job['job_id']}/run",
        headers=_owner_headers("other-user"),
    ).status_code == 404
    assert client.post(
        f"/v1/research/backtests/{job['job_id']}/cancel",
        headers=_owner_headers("other-user"),
    ).status_code == 404
    run_response = client.post(
        f"/v1/research/backtests/{job['job_id']}/run",
        params={"projection": "summary"},
    )
    assert run_response.json()["job"]["status"] == "completed"
    assert "input_manifest" not in run_response.json()["job"]
    fetched = client.get(f"/v1/research/backtests/{job['job_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["job"]["result_artifact_id"].startswith("artifact_")
    result = client.get(
        f"/v1/research/backtests/{job['job_id']}/result",
        headers=_owner_headers("product-user"),
    )
    assert result.status_code == 200
    result_body = result.json()
    assert result_body["job_id"] == job["job_id"]
    assert result_body["result"]["total_return"] == 0.0
    assert result_body["result"]["trade_count"] == 1
    assert result_body["result"]["equity_curve"][-1]["trade_date"] == "2026-01-06"
    assert result_body["result"]["daily_positions"][-1]["trade_date"] == "2026-01-06"
    assert result_body["result"]["daily_returns"][-1]["trade_date"] == "2026-01-06"
    assert result_body["result"]["logs"]
    assert result_body["result"]["strategy_version_artifact_id"] == version["artifact"]["artifact_id"]
    assert result_body["result"]["approval_artifact_id"] == approval["artifact"]["artifact_id"]

    analysis = client.get(f"/v1/research/backtests/{job['job_id']}/analysis")
    assert analysis.status_code == 200, analysis.text
    analysis_body = analysis.json()["analysis"]
    assert analysis_body["schema_version"] == "backtest-analysis.v1"
    assert analysis_body["section"] == "summary"
    assert analysis_body["summary"]["benchmark_status"] == "not_frozen"
    assert analysis_body["summary"]["transaction_cost_total"] == 0
    assert analysis_body["summary"]["drawdown_diagnostics"]["status"] in {
        "no_drawdown", "recovered", "not_recovered",
    }
    assert analysis_body["summary"]["daily_return_diagnostics"]["observation_count"] > 0
    assert "closed_trade_count" in analysis_body["summary"]["realized_trade_diagnostics"]
    assert analysis_body["summary"]["causal_attribution"]["status"] == "aggregate_only"
    assert "result_reference" not in analysis.text and "object_id" not in analysis.text
    trade_page = client.get(
        f"/v1/research/backtests/{job['job_id']}/analysis",
        params={"section": "trades", "limit": 1, "offset": 0},
    ).json()["analysis"]["page"]
    assert trade_page["total"] == 1
    assert len(trade_page["items"]) == 1
    chart = client.get(
        f"/v1/research/backtests/{job['job_id']}/analysis",
        params={"section": "chart", "limit": 1},
    ).json()["analysis"]
    assert chart["series"]["equity_curve"][-1]["trade_date"] == "2026-01-06"
    daily_page = client.get(
        f"/v1/research/backtests/{job['job_id']}/analysis",
        params={"section": "daily_positions", "query": "2026-01-06", "limit": 1},
    ).json()["analysis"]["page"]
    assert daily_page["total"] == 1
    assert "daily_return" in daily_page["items"][0]

    denied = client.get(
        f"/v1/research/backtests/{job['job_id']}/result",
        headers=_owner_headers("other-user"),
    )
    assert denied.status_code == 404
    assert client.get(
        f"/v1/research/backtests/{job['job_id']}/analysis",
        headers=_owner_headers("other-user"),
    ).status_code == 404
    listed = client.get(
        "/v1/research/backtests",
        headers=_owner_headers("product-user"),
    )
    assert listed.status_code == 200
    assert listed.json()["backtests"][0]["job_id"] == job["job_id"]
    jobs._execute(
        """UPDATE backtest_jobs
           SET input_manifest_json = input_manifest_json || jsonb_build_object('browser_payload_probe', CAST(:payload AS TEXT))
           WHERE job_id = :job_id""",
        {"job_id": job["job_id"], "payload": "x" * 1_000_000},
    )
    catalog = client.get(
        "/v1/research/backtests/catalog",
        params={"query": job["job_id"][-8:], "status": "completed", "limit": 20, "offset": 0},
    )
    assert catalog.status_code == 200, catalog.text
    assert catalog.json()["total"] == 1
    catalog_row = catalog.json()["backtests"][0]
    assert catalog_row["job_id"] == job["job_id"]
    assert "input_manifest" not in catalog_row and "result_reference" not in catalog_row
    assert len(catalog.content) < 16_000
    summary_job = client.get(f"/v1/research/backtests/{job['job_id']}/summary")
    assert summary_job.status_code == 200
    assert summary_job.json()["job"]["execution"]["initial_capital"] == 2000
    assert "input_manifest" not in summary_job.json()["job"] and "result_reference" not in summary_job.json()["job"]
    manifest = client.get(f"/v1/research/backtests/{job['job_id']}/manifest")
    assert manifest.status_code == 200
    assert len(manifest.content) > 1_000_000
    assert len(manifest.json()["input_manifest"]["bars"]) == len(bars)
    assert manifest.json()["input_manifest"]["bars"][0]["symbol"] == SYMBOL
    assert client.get(
        f"/v1/research/backtests/{job['job_id']}/manifest",
        headers=_owner_headers("other-user"),
    ).status_code == 404
    retry = client.post(
        "/v1/research/backtests",
        params={"projection": "summary"},
        json={
            "task_id": task["task_id"], "strategy_version_artifact_id": version["artifact"]["artifact_id"],
            "approval_artifact_id": approval["artifact"]["artifact_id"], "trace_id": task["trace_id"],
            "idempotency_key": "backtest-api-1", "universe": universe, "bars": bars,
            "signals": [{"symbol": SYMBOL, "trade_date": "2026-01-05", "side": "buy", "quantity": 100}],
            "execution": {"initial_capital": 2_000, "commission_rate": 0, "stamp_tax_rate": 0, "lot_size": 100},
        },
    )
    assert retry.status_code == 202
    assert retry.json()["job"]["job_id"] == job["job_id"]
    assert "input_manifest" not in retry.json()["job"]
    assert len(retry.content) < 16_000
    denied_delete = client.delete(
        f"/v1/research/backtests/{job['job_id']}",
        headers=_owner_headers("other-user"),
    )
    assert denied_delete.status_code == 409
    deleted = client.delete(
        f"/v1/research/backtests/{job['job_id']}",
        params={"projection": "summary"},
        headers=_owner_headers("product-user"),
    )
    assert deleted.status_code == 200
    assert "input_manifest" not in deleted.json()["job"]
    assert client.get(f"/v1/research/backtests/{job['job_id']}").status_code == 404

    store.close()
    jobs.close()


def _owner_headers(principal: str) -> dict[str, str]:
    return trusted_agent_context(
        principal, trace_id=f"byq-trace-{principal}", session_id=f"byq-session-{principal}",
        dsh_run_id=f"byq-run-{principal}",
    )


def test_backtest_feature_diagnostics_follow_safe_ml_lineage(monkeypatch) -> None:
    artifacts = {
        "artifact_signal": {
            "owner_principal": "product-user", "kind": "signal_snapshot",
            "content": {"source": {"ml_lineage": {
                "feature_snapshot_artifact_id": "artifact_feature",
            }}},
        },
        "artifact_feature": {
            "owner_principal": "product-user", "kind": "ml_feature_snapshot",
            "content": {
                "coverage": {"usable_rows": 80, "candidate_rows": 100, "usable_ratio": 0.8},
                "excluded": {"warmup_or_missing": 18, "label_outside_split": 2, "non_finite": 0},
                "object_reference": {"must": "not leak"},
            },
        },
    }

    class Research:
        def get_artifact(self, artifact_id):
            return artifacts[artifact_id]

    monkeypatch.setattr(main, "research_store", Research())
    diagnostics = main._backtest_feature_diagnostics(
        owner_principal="product-user", signal_snapshot_artifact_id="artifact_signal",
    )
    assert diagnostics is not None
    assert diagnostics["coverage"]["usable_ratio"] == 0.8
    assert diagnostics["excluded"]["label_outside_split"] == 2
    assert "object_reference" not in str(diagnostics)
    assert main._backtest_feature_diagnostics(
        owner_principal="other-user", signal_snapshot_artifact_id="artifact_signal",
    ) is None


def _create_completed_backtest(client: TestClient, *, key: str) -> dict[str, object]:
    task = client.post(
        "/v1/research/tasks",
        json={
            "owner_principal": "product-user", "title": f"Backtest GC {key}",
            "objective": "Run native fixture", "trace_id": f"byq-trace-{key}",
            "idempotency_key": f"task-{key}",
        },
    ).json()
    draft = client.post(
        "/v1/research/strategies/validate",
        json={
            "task_id": task["task_id"], "strategy": _strategy(), "trace_id": f"byq-trace-{key}",
            "idempotency_key": f"draft-{key}",
        },
    ).json()
    version = client.post(
        "/v1/research/strategies/versions",
        json={
            "task_id": task["task_id"], "draft_artifact_id": draft["artifact"]["artifact_id"],
            "trace_id": f"byq-trace-{key}", "idempotency_key": f"version-{key}",
        },
    ).json()
    approval = client.post(
        "/v1/research/strategies/approvals",
        json={
            "task_id": task["task_id"], "strategy_version_artifact_id": version["artifact"]["artifact_id"],
            "reviewer_principal": "human-owner", "decision": "approved", "trace_id": f"byq-trace-{key}",
            "idempotency_key": f"approval-{key}",
        },
    ).json()
    universe = {
        "universe_id": "fixture", "version_id": "fixture-v1",
        "membership_fingerprint": membership_fingerprint([SYMBOL]), "symbols": [SYMBOL],
    }
    bars = [
        {"symbol": SYMBOL, "trade_date": "2026-01-05", "open": 10, "high": 10, "low": 10, "close": 10},
        {"symbol": SYMBOL, "trade_date": "2026-01-06", "open": 10, "high": 10, "low": 10, "close": 10},
    ]
    submit = client.post(
        "/v1/research/backtests",
        json={
            "task_id": task["task_id"], "strategy_version_artifact_id": version["artifact"]["artifact_id"],
            "approval_artifact_id": approval["artifact"]["artifact_id"], "trace_id": f"byq-trace-{key}",
            "idempotency_key": f"backtest-{key}", "universe": universe, "bars": bars,
            "signals": [{"symbol": SYMBOL, "trade_date": "2026-01-05", "side": "buy", "quantity": 100}],
            "execution": {"initial_capital": 2_000, "commission_rate": 0, "stamp_tax_rate": 0, "lot_size": 100},
        },
    )
    assert submit.status_code == 202, submit.text
    job = submit.json()["job"]
    assert client.post(f"/v1/research/backtests/{job['job_id']}/run").json()["job"]["status"] == "completed"
    return client.get(f"/v1/research/backtests/{job['job_id']}").json()["job"]


def test_backtest_delete_garbage_collects_orphan_result_object(monkeypatch, tmp_path) -> None:
    store = ResearchStore()
    jobs = BacktestJobStore()
    objects = LocalObjectStore(tmp_path / "objects")
    monkeypatch.setattr(main, "research_store", store)
    monkeypatch.setattr(main, "backtest_store", jobs)
    monkeypatch.setattr(main, "backtest_objects", objects)
    client = TestClient(main.app)
    client.headers.update(_owner_headers("product-user"))

    job = _create_completed_backtest(client, key="gc-orphan")
    reference = job["result_reference"]
    assert objects.exists(reference)
    deleted = client.delete(f"/v1/research/backtests/{job['job_id']}", headers=_owner_headers("product-user"))
    assert deleted.status_code == 200
    assert not objects.exists(reference), "orphan result object must be garbage collected"
    store.close()
    jobs.close()


def test_backtest_delete_keeps_shared_result_object(monkeypatch, tmp_path) -> None:
    store = ResearchStore()
    jobs = BacktestJobStore()
    objects = LocalObjectStore(tmp_path / "objects")
    monkeypatch.setattr(main, "research_store", store)
    monkeypatch.setattr(main, "backtest_store", jobs)
    monkeypatch.setattr(main, "backtest_objects", objects)
    client = TestClient(main.app)
    client.headers.update(_owner_headers("product-user"))

    job_a = _create_completed_backtest(client, key="gc-shared-a")
    job_b = _create_completed_backtest(client, key="gc-shared-b")
    reference = job_a["result_reference"]
    # Simulate content-addressed sharing: job B references the same result object.
    jobs._execute(
        "UPDATE backtest_jobs SET result_reference_json = :reference WHERE job_id = :job_id",
        {"reference": reference, "job_id": job_b["job_id"]},
    )
    assert objects.exists(reference)
    deleted_a = client.delete(f"/v1/research/backtests/{job_a['job_id']}", headers=_owner_headers("product-user"))
    assert deleted_a.status_code == 200
    assert objects.exists(reference), "shared result object must survive the first deletion"
    deleted_b = client.delete(f"/v1/research/backtests/{job_b['job_id']}", headers=_owner_headers("product-user"))
    assert deleted_b.status_code == 200
    assert not objects.exists(reference), "orphaned shared result object must be garbage collected"
    store.close()
    jobs.close()


def test_backtest_delete_survives_result_gc_failure(monkeypatch, tmp_path) -> None:
    store = ResearchStore()
    jobs = BacktestJobStore()
    objects = LocalObjectStore(tmp_path / "objects")
    monkeypatch.setattr(main, "research_store", store)
    monkeypatch.setattr(main, "backtest_store", jobs)
    monkeypatch.setattr(main, "backtest_objects", objects)
    client = TestClient(main.app)
    client.headers.update(_owner_headers("product-user"))

    job = _create_completed_backtest(client, key="gc-failure")

    def _boom(*args: object, **kwargs: object) -> None:
        raise ObjectIntegrityError("simulated GC failure")

    monkeypatch.setattr(objects, "delete_if_unreferenced", _boom)
    deleted = client.delete(f"/v1/research/backtests/{job['job_id']}", headers=_owner_headers("product-user"))
    assert deleted.status_code == 200, "best-effort GC must never fail the DELETE request"
    assert client.get(f"/v1/research/backtests/{job['job_id']}").status_code == 404
    store.close()
    jobs.close()


def _create_strategy_chain(client: TestClient, *, key: str) -> dict[str, object]:
    task = client.post(
        "/v1/research/tasks",
        json={
            "owner_principal": "product-user", "title": f"Snapshot {key}",
            "objective": "Create validated strategy chain", "trace_id": f"byq-trace-{key}",
            "idempotency_key": f"task-{key}",
        },
    ).json()
    draft = client.post(
        "/v1/research/strategies/validate",
        json={
            "task_id": task["task_id"], "strategy": _strategy(), "trace_id": f"byq-trace-{key}",
            "idempotency_key": f"draft-{key}",
        },
    ).json()
    version = client.post(
        "/v1/research/strategies/versions",
        json={
            "task_id": task["task_id"], "draft_artifact_id": draft["artifact"]["artifact_id"],
            "trace_id": f"byq-trace-{key}", "idempotency_key": f"version-{key}",
        },
    ).json()
    approval = client.post(
        "/v1/research/strategies/approvals",
        json={
            "task_id": task["task_id"], "strategy_version_artifact_id": version["artifact"]["artifact_id"],
            "reviewer_principal": "human-owner", "decision": "approved", "trace_id": f"byq-trace-{key}",
            "idempotency_key": f"approval-{key}",
        },
    ).json()
    return {"task": task, "draft": draft, "version": version, "approval": approval}


def _snapshot_input() -> dict[str, object]:
    return {
        "universe": {
            "universe_id": "fixture", "version_id": "fixture-v1",
            "membership_fingerprint": membership_fingerprint([SYMBOL]), "symbols": [SYMBOL],
        },
        "bars": [
            {"symbol": SYMBOL, "trade_date": "2026-01-05", "open": 10, "high": 10, "low": 10, "close": 10},
            {"symbol": SYMBOL, "trade_date": "2026-01-06", "open": 10, "high": 10, "low": 10, "close": 10},
        ],
        "signals": [{"symbol": SYMBOL, "trade_date": "2026-01-05", "side": "buy", "quantity": 100}],
        "execution": {"initial_capital": 2_000, "commission_rate": 0, "stamp_tax_rate": 0, "lot_size": 100},
    }


def _fresh_harness(monkeypatch, tmp_path) -> tuple[ResearchStore, BacktestJobStore, LocalObjectStore, TestClient]:
    store = ResearchStore()
    jobs = BacktestJobStore()
    objects = LocalObjectStore(tmp_path / "objects")
    monkeypatch.setattr(main, "research_store", store)
    monkeypatch.setattr(main, "backtest_store", jobs)
    monkeypatch.setattr(main, "backtest_objects", objects)
    client = TestClient(main.app)
    client.headers.update(_owner_headers("product-user"))
    return store, jobs, objects, client


def test_signal_snapshot_create_and_backtest_submit(monkeypatch, tmp_path) -> None:
    store, jobs, objects, client = _fresh_harness(monkeypatch, tmp_path)
    chain = _create_strategy_chain(client, key="snapshot-e2e")
    version_artifact_id = chain["version"]["artifact"]["artifact_id"]
    approval_artifact_id = chain["approval"]["artifact"]["artifact_id"]

    created = client.post(
        "/v1/research/signal-snapshots",
        json={
            "task_id": chain["task"]["task_id"], "strategy_version_artifact_id": version_artifact_id,
            "trace_id": "byq-trace-snapshot-e2e", "idempotency_key": "snapshot-e2e",
            "source": {"producer": "test-fixture"}, **_snapshot_input(),
        },
    )
    assert created.status_code == 201, created.text
    snapshot = created.json()
    assert snapshot["artifact"]["kind"] == "signal_snapshot"
    assert snapshot["artifact"]["status"] == "validated"
    assert snapshot["snapshot"]["strategy"]["strategy_version_artifact_id"] == version_artifact_id
    assert snapshot["snapshot"]["source"]["producer"] == "test-fixture"
    assert snapshot["snapshot"]["source"]["content_sha256"]
    snapshot_artifact_id = snapshot["artifact"]["artifact_id"]

    submit = client.post(
        "/v1/research/backtests",
        json={
            "task_id": chain["task"]["task_id"], "strategy_version_artifact_id": version_artifact_id,
            "approval_artifact_id": approval_artifact_id, "trace_id": "byq-trace-snapshot-e2e",
            "idempotency_key": "backtest-snapshot-e2e",
            "signal_snapshot_artifact_id": snapshot_artifact_id,
        },
    )
    assert submit.status_code == 202, submit.text
    job = submit.json()["job"]
    assert client.post(f"/v1/research/backtests/{job['job_id']}/run").json()["job"]["status"] == "completed"
    result = client.get(
        f"/v1/research/backtests/{job['job_id']}/result", headers=_owner_headers("product-user")
    ).json()["result"]
    assert result["trade_count"] == 1
    assert result["total_return"] == 0.0
    assert result["equity_curve"][-1]["trade_date"] == "2026-01-06"
    store.close()
    jobs.close()


def test_signal_snapshot_mismatch_rejected(monkeypatch, tmp_path) -> None:
    store, jobs, objects, client = _fresh_harness(monkeypatch, tmp_path)
    chain = _create_strategy_chain(client, key="snapshot-mismatch")
    task_id = chain["task"]["task_id"]
    version_a_id = chain["version"]["artifact"]["artifact_id"]
    # Second validated version in the SAME task with a different strategy.
    strategy_v2 = {**_strategy(), "strategy_id": "MomentumStrategyV2", "parameters": {"lookback": 10}}
    draft_b = client.post(
        "/v1/research/strategies/validate",
        json={
            "task_id": task_id, "strategy": strategy_v2, "trace_id": "byq-trace-snapshot-mismatch",
            "idempotency_key": "draft-mismatch-b",
        },
    ).json()
    version_b = client.post(
        "/v1/research/strategies/versions",
        json={
            "task_id": task_id, "draft_artifact_id": draft_b["artifact"]["artifact_id"],
            "trace_id": "byq-trace-snapshot-mismatch", "idempotency_key": "version-mismatch-b",
        },
    ).json()
    approval_b = client.post(
        "/v1/research/strategies/approvals",
        json={
            "task_id": task_id, "strategy_version_artifact_id": version_b["artifact"]["artifact_id"],
            "reviewer_principal": "human-owner", "decision": "approved",
            "trace_id": "byq-trace-snapshot-mismatch", "idempotency_key": "approval-mismatch-b",
        },
    ).json()
    created = client.post(
        "/v1/research/signal-snapshots",
        json={
            "task_id": task_id, "strategy_version_artifact_id": version_a_id,
            "trace_id": "byq-trace-snapshot-mismatch", "idempotency_key": "snapshot-mismatch",
            **_snapshot_input(),
        },
    )
    assert created.status_code == 201
    snapshot_artifact_id = created.json()["artifact"]["artifact_id"]
    # Submit referencing a DIFFERENT strategy version (same task) -> mismatch.
    submit = client.post(
        "/v1/research/backtests",
        json={
            "task_id": task_id, "strategy_version_artifact_id": version_b["artifact"]["artifact_id"],
            "approval_artifact_id": approval_b["artifact"]["artifact_id"],
            "trace_id": "byq-trace-snapshot-mismatch", "idempotency_key": "backtest-snapshot-mismatch",
            "signal_snapshot_artifact_id": snapshot_artifact_id,
        },
    )
    assert submit.status_code == 422, submit.text
    assert "does not match" in submit.text
    store.close()
    jobs.close()
