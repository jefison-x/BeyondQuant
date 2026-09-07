from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from app import main as backend_main
from app.main import _ml_pool_market_scope, app
from tests.test_ml_strategy import valid_strategy, valid_strategy_v2
from tests.workspace_helpers import trusted_agent_context


client = TestClient(app)


def test_training_receipt_precedes_coverage_scan_and_repair_and_retries_stay_stable(monkeypatch):
    owner = "ml-receipt-owner"
    headers = trusted_agent_context(owner)
    task = backend_main.research_store.create_task({
        "owner_principal": owner, "title": "Receipt", "objective": "Synthetic acceptance",
        "trace_id": "receipt-trace", "idempotency_key": "receipt-task",
    })
    artifact = backend_main.research_store.create_artifact({
        "task_id": task["task_id"], "kind": "ml_strategy_version", "content": backend_main.normalize_ml_strategy(valid_strategy()),
        "lineage": [], "trace_id": "receipt-trace", "idempotency_key": "receipt-strategy",
    })
    backend_main.research_store.transition("artifact", artifact["artifact_id"], "validated", "receipt-validate")
    monkeypatch.setattr(backend_main, "_approved_ml_strategy_artifact", lambda **kwargs: artifact)
    pool = backend_main.paper_store.create_pool(
        {"name": "Receipt synthetic pool", "symbols": ["000001.SZ"]}, trusted_owner=owner,
    )
    monkeypatch.setattr(backend_main.security_master_store, "latest_snapshot", lambda: {"snapshot_id": "master_original"})
    def forbidden(*args, **kwargs):
        raise AssertionError("expensive preparation ran before durable receipt")
    monkeypatch.setattr(backend_main.market_readiness_store, "assess", forbidden)
    monkeypatch.setattr(backend_main.market_automation_store, "request_data_repair", forbidden)
    payload = {"task_id": task["task_id"], "ml_strategy_artifact_id": artifact["artifact_id"],
               "stock_pool_snapshot_id": pool["current_snapshot_id"], "trace_id": "receipt-trace", "idempotency_key": "receipt-1"}
    registered = client.post("/v1/research/ml/training-submissions", headers=headers, json=payload)
    assert registered.status_code == 202, registered.text
    watch = registered.json()["receipt_watch"]
    assert watch["registration_created"] is True and watch["state"] == "awaiting_receipt"
    duplicate_watch = client.post("/v1/research/ml/training-submissions", headers=headers, json=payload).json()["receipt_watch"]
    assert duplicate_watch["watch_id"] == watch["watch_id"] and duplicate_watch["registration_created"] is False
    assert client.post("/v1/research/ml/training-submissions", headers=headers,
                       json={**payload, "experiment_id": "experiment_changed"}).status_code == 409
    assert "identity_json" not in watch and "request_hash" not in watch
    for mismatched in ({**payload, "stock_pool_snapshot_id": "snapshot_other"},
                       {**payload, "unexpected": "invalid"}):
        backend_main.ml_training_store.reject_receipt_watch(
            mismatched, trusted_workspace=headers["x-byq-workspace-id"], trusted_owner=owner)
        assert backend_main.ml_training_store.get_receipt_watch(
            "receipt-1", trusted_workspace=headers["x-byq-workspace-id"], trusted_owner=owner,
        )["state"] == "awaiting_receipt"
    other_headers = trusted_agent_context("receipt-other-owner")
    assert client.get("/v1/research/ml/training-submissions/reconcile", headers=other_headers,
                      params={"idempotency_key": "receipt-1"}).status_code == 404
    # Bound scheduled exact reads; restarting the store cannot reset the budget.
    from app.ml_training import MLTrainingRunStore
    for attempt in range(1, 9):
        restarted = MLTrainingRunStore()
        restarted._execute("UPDATE ml_training_receipt_watches SET next_check_at=now()-interval '1 second' WHERE watch_id=:id",
                           {"id": watch["watch_id"]})
        if attempt == 1:
            from concurrent.futures import ThreadPoolExecutor
            concurrent = MLTrainingRunStore()
            with ThreadPoolExecutor(max_workers=2) as executor:
                assert sum(executor.map(lambda store: store.reconcile_receipt_watches(), [restarted, concurrent])) == 1
            concurrent.close()
        else:
            assert restarted.reconcile_receipt_watches() == 1
        current_watch = restarted.get_receipt_watch("receipt-1", trusted_workspace=headers["x-byq-workspace-id"], trusted_owner=owner)
        assert current_watch["check_count"] == attempt
        assert restarted.reconcile_receipt_watches() == 0
        restarted.close()
    assert current_watch["state"] == "needs_attention"
    # A failure after inserting the reference must roll back the run and alias too.
    from app.paper_trading import PaperTradingStore
    original = PaperTradingStore.record_pool_reference_in_transaction
    def fail_after_reference(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("synthetic transaction interruption")
    with monkeypatch.context() as patch:
        patch.setattr(PaperTradingStore, "record_pool_reference_in_transaction", staticmethod(fail_after_reference))
        with pytest.raises(RuntimeError, match="synthetic transaction interruption"):
            client.post("/v1/research/ml/training-runs", headers=headers, json=payload)
    assert backend_main.ml_training_store._fetch_one(
        "SELECT COUNT(*) AS n FROM ml_training_runs WHERE owner_principal=:owner", {"owner": owner},
    )["n"] == 0
    assert backend_main.ml_training_store._fetch_one(
        "SELECT COUNT(*) AS n FROM ml_training_submission_keys WHERE owner_principal=:owner", {"owner": owner},
    )["n"] == 0
    assert backend_main.paper_store.pool_references(pool["pool_id"], trusted_owner=owner)["references"] == []
    response = client.post("/v1/research/ml/training-runs", headers=headers, json=payload)
    assert response.status_code == 202, response.text
    run = response.json()["training_run"]
    assert run["status"] == "waiting_for_data"
    assert run["readiness"]["state"] == "pending"
    confirmed_watch = client.get("/v1/research/ml/training-submissions/reconcile", headers=headers,
                                 params={"idempotency_key": "receipt-1"}).json()["receipt_watch"]
    assert confirmed_watch["state"] == "confirmed"
    assert confirmed_watch["training_run_id"] == run["training_run_id"]
    assert confirmed_watch["check_count"] == 8
    references = backend_main.paper_store.pool_references(pool["pool_id"], trusted_owner=owner)["references"]
    assert len(references) == 1 and references[0]["reference_count"] == 1
    monkeypatch.setattr(backend_main.security_master_store, "latest_snapshot", lambda: {"snapshot_id": "master_new"})
    retry = client.post("/v1/research/ml/training-runs", headers=headers, json=payload)
    assert retry.status_code == 202, retry.text
    assert retry.json()["training_run"]["training_run_id"] == run["training_run_id"]
    alias = client.post("/v1/research/ml/training-runs", headers=headers, json={**payload, "idempotency_key": "receipt-2"})
    assert alias.status_code == 202, alias.text
    assert alias.json()["training_run"]["training_run_id"] == run["training_run_id"]
    reconciled = client.get("/v1/research/ml/training-runs/reconcile", headers=headers,
                            params={"idempotency_key": "receipt-2"})
    assert reconciled.status_code == 200
    assert reconciled.json()["training_run"]["training_run_id"] == run["training_run_id"]
    other_pool = backend_main.paper_store.create_pool(
        {"name": "Other receipt pool", "symbols": ["600000.SH"]}, trusted_owner=owner,
    )
    conflict = client.post("/v1/research/ml/training-runs", headers=headers,
                           json={**payload, "stock_pool_snapshot_id": other_pool["current_snapshot_id"]})
    assert conflict.status_code == 409
    rejected_payload = {**payload, "idempotency_key": "rejected-submission"}
    assert client.post("/v1/research/ml/training-submissions", headers=headers, json=rejected_payload).status_code == 202
    with monkeypatch.context() as patch:
        patch.setattr(backend_main, "_approved_ml_strategy_artifact", lambda **kwargs: None)
        assert client.post("/v1/research/ml/training-runs", headers=headers, json=rejected_payload).status_code == 422
    rejection = client.get("/v1/research/ml/training-submissions/reconcile", headers=headers,
                           params={"idempotency_key": "rejected-submission"}).json()["receipt_watch"]
    assert rejection["state"] == "rejected"
    deadline_payload = {**payload, "idempotency_key": "deadline-submission"}
    assert client.post("/v1/research/ml/training-submissions", headers=headers, json=deadline_payload).status_code == 202
    backend_main.ml_training_store._execute("""UPDATE ml_training_receipt_watches
        SET deadline_at=now()-interval '1 second' WHERE idempotency_key='deadline-submission'""")
    deadline = client.get("/v1/research/ml/training-submissions/reconcile", headers=headers,
                          params={"idempotency_key": "deadline-submission"}).json()["receipt_watch"]
    assert deadline["state"] == "needs_attention" and deadline["check_count"] == 0


def test_index_ml_pool_freezes_same_index_as_universe_and_benchmark() -> None:
    declared, membership_mode = _ml_pool_market_scope(
        {"pool_type": "index"},
        {"provenance": {"index_symbol": "000300.SH"}},
    )
    assert membership_mode == "point_in_time"
    assert declared == {"index_universe": "000300.SH", "benchmark": "000300.SH"}

    fixed, fixed_mode = _ml_pool_market_scope({"pool_type": "custom"}, {})
    assert fixed == {} and fixed_mode == "fixed_snapshot"


def test_ml_capabilities_and_workspace_are_closed_safe_projections() -> None:
    headers = trusted_agent_context("ml-capability-owner")
    capabilities = client.get("/v1/research/ml/capabilities", headers=headers)
    assert capabilities.status_code == 200
    body = capabilities.json()
    assert body["schema_version"] == "ml-capabilities.v1"
    assert body["capabilities"][0]["learner"]["kind"] == "lightgbm_regression"
    assert body["registry"]["schema_version"] == "ml-capability-registry.v2"
    assert any(
        item["id"] == "byq-ridge-cpu-v1" and item["status"] == "qualified"
        for item in body["registry"]["components"]
    )
    assert any(
        item["id"] == "hs300-trend-volatility-v1" and item["status"] == "qualified"
        for item in body["registry"]["components"]
    )
    assert any(
        item["id"] == "regime-expert-map-v1" and item["status"] == "qualified"
        for item in body["registry"]["components"]
    )
    assert "xgboost" not in capabilities.text.lower()
    workspace = client.get("/v1/research/ml/workspace", headers=headers)
    assert workspace.status_code == 200
    assert workspace.json()["schema_version"] == "ml-agent-workspace.v1"
    assert workspace.json()["prediction_available_via_agent"] is True
    assert workspace.json()["prediction_runs"] == []
    assert "object_reference" not in workspace.text and "rows" not in workspace.text


def test_ml_training_reconcile_route_uses_trusted_workspace_and_owner(monkeypatch) -> None:
    headers = trusted_agent_context("ml-reconcile-owner")
    captured: dict[str, str] = {}

    def reconcile(key, *, trusted_workspace, trusted_owner):
        captured.update(
            key=key, workspace=trusted_workspace, owner=trusted_owner,
        )
        return {
            "training_run_id": "mlrun_" + "a" * 32,
            "status": "waiting_for_data",
        }

    monkeypatch.setattr(backend_main.ml_training_store, "get_by_idempotency", reconcile)
    response = client.get(
        "/v1/research/ml/training-runs/reconcile",
        params={"idempotency_key": "training-reconcile-1"}, headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["training_run"]["training_run_id"] == "mlrun_" + "a" * 32
    assert captured == {
        "key": "training-reconcile-1",
        "workspace": headers["x-byq-workspace-id"],
        "owner": "ml-reconcile-owner",
    }


def test_agent_context_inbox_requires_exact_session_ml_progress(monkeypatch) -> None:
    headers = trusted_agent_context("ml-notification-owner")
    captured: dict[str, str] = {}
    monkeypatch.setattr(backend_main.data_demand_store, "list_for_session", lambda **_kwargs: [])

    def notifications(*, trusted_workspace, trusted_owner, trusted_session, trusted_trace, limit=10):
        captured.update(workspace=trusted_workspace, owner=trusted_owner, session=trusted_session, trace=trusted_trace)
        return [{
            "kind": "ml_training_progress", "notification_id": "ml-training:run:now",
            "training_run_id": "mlrun_" + "c" * 32, "status": "running",
            "notification": "模型训练中",
        }]

    monkeypatch.setattr(backend_main.ml_training_store, "list_agent_notifications", notifications)
    response = client.get("/v1/agent/data-demand-notifications", headers=headers)
    assert response.status_code == 200
    assert response.json()["notifications"][0]["kind"] == "ml_training_progress"
    assert captured == {
        "workspace": headers["x-byq-workspace-id"], "owner": "ml-notification-owner",
        "session": headers["x-byq-session-id"], "trace": headers["x-byq-trace-id"],
    }


def test_ml_workspace_and_prediction_pages_never_materialise_large_rows() -> None:
    headers = trusted_agent_context("ml-bounded-owner")
    task = client.post("/v1/research/tasks", headers=headers, json={
        "owner_principal": "ml-bounded-owner", "title": "Bounded ML", "objective": "Page rows",
        "trace_id": "trace-ml-bounded", "idempotency_key": "task-ml-bounded",
    }).json()
    artifact = backend_main.research_store.create_artifact({
        "task_id": task["task_id"], "kind": "ml_prediction_snapshot",
        "content": {"schema_version": "ml-prediction-snapshot.v1", "rows": [
            {"session": "2026-01-02", "rank": 1, "symbol": "000001.SZ", "score": 0.9, "private": "drop"},
            {"session": "2026-01-02", "rank": 2, "symbol": "000002.SZ", "score": 0.8},
            {"session": "2026-01-03", "rank": 1, "symbol": "000001.SZ", "score": 0.7},
        ]},
        "lineage": [], "trace_id": "trace-ml-bounded", "idempotency_key": "artifact-ml-bounded",
    })
    projected = backend_main.research_store.list_ml_workspace_artifacts(
        owner_principal="ml-bounded-owner", workspace_id=headers["x-byq-workspace-id"],
    )
    assert projected[0]["artifact_id"] == artifact["artifact_id"]
    assert "rows" not in projected[0]["content"]
    page = backend_main.research_store.list_ml_prediction_rows(
        artifact_id=str(artifact["artifact_id"]), owner_principal="ml-bounded-owner",
        workspace_id=headers["x-byq-workspace-id"], query="000001", limit=1, offset=1,
    )
    assert page == {
        "rows": [{"session": "2026-01-03", "rank": 1, "symbol": "000001.SZ", "score": 0.7}],
        "total": 2,
    }


def test_ml_strategy_version_and_human_approval_are_owner_scoped() -> None:
    headers = trusted_agent_context("ml-api-owner", actor="ml-api-owner")
    task = client.post("/v1/research/tasks", headers=headers, json={
        "owner_principal": "ml-api-owner", "title": "ML API", "objective": "Train",
        "trace_id": "trace-ml-api", "idempotency_key": "task-ml-api",
    })
    assert task.status_code == 201, task.text
    task_id = task.json()["task_id"]
    version = client.post("/v1/research/ml/strategies/versions", headers=headers, json={
        "task_id": task_id, "strategy": valid_strategy(), "trace_id": "trace-ml-api",
        "idempotency_key": "version-ml-api",
    })
    assert version.status_code == 201, version.text
    artifact = version.json()["artifact"]
    assert artifact["kind"] == "ml_strategy_version" and artifact["status"] == "validated"
    approval = client.post("/v1/research/ml/strategies/approvals", headers=headers, json={
        "task_id": task_id, "ml_strategy_artifact_id": artifact["artifact_id"],
        "decision": "approved", "rationale": "reviewed", "trace_id": "trace-ml-api",
        "idempotency_key": "approval-ml-api",
    })
    assert approval.status_code == 201, approval.text
    assert approval.json()["approval"]["execution_authorized"] is True
    assert approval.json()["approval"]["reviewer_principal"] == "ml-api-owner"


def test_ml_strategy_endpoint_rejects_open_python_contract() -> None:
    headers = trusted_agent_context("ml-api-reject")
    task = client.post("/v1/research/tasks", headers=headers, json={
        "owner_principal": "ml-api-reject", "title": "ML reject", "objective": "Reject",
        "trace_id": "trace-ml-reject", "idempotency_key": "task-ml-reject",
    }).json()
    strategy = valid_strategy()
    strategy["python"] = "import lightgbm"
    response = client.post("/v1/research/ml/strategies/versions", headers=headers, json={
        "task_id": task["task_id"], "strategy": strategy, "trace_id": "trace-ml-reject",
        "idempotency_key": "version-ml-reject",
    })
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "unknown_fields"
    assert response.json()["detail"]["field"] == "strategy"
    assert "import lightgbm" not in response.text


def test_ml_v2_strategy_version_and_approval_use_qualified_capability_lock() -> None:
    headers = trusted_agent_context("ml-v2-api-owner", actor="ml-v2-api-owner")
    task = client.post("/v1/research/tasks", headers=headers, json={
        "owner_principal": "ml-v2-api-owner", "title": "ML v2 API", "objective": "Walk forward",
        "trace_id": "trace-ml-v2-api", "idempotency_key": "task-ml-v2-api",
    }).json()
    version = client.post("/v1/research/ml/strategies/versions", headers=headers, json={
        "task_id": task["task_id"], "strategy": valid_strategy_v2(),
        "trace_id": "trace-ml-v2-api", "idempotency_key": "version-ml-v2-api",
    })
    assert version.status_code == 201, version.text
    content = version.json()["ml_strategy_version"]
    assert content["schema_version"] == "ml-strategy-version.v2"
    assert content["capability_lock"]["content_sha256"]
    approval = client.post("/v1/research/ml/strategies/approvals", headers=headers, json={
        "task_id": task["task_id"],
        "ml_strategy_artifact_id": version.json()["artifact"]["artifact_id"],
        "decision": "approved", "rationale": "qualified baseline",
        "trace_id": "trace-ml-v2-api", "idempotency_key": "approval-ml-v2-api",
    })
    assert approval.status_code == 201, approval.text
    assert approval.json()["approval"]["ml_strategy_version_id"] == content["version_id"]


def test_ml_study_catalog_is_paged_and_detail_is_lazy_safe() -> None:
    headers = trusted_agent_context("ml-catalog-owner", actor="ml-catalog-owner")
    task = client.post("/v1/research/tasks", headers=headers, json={
        "owner_principal": "ml-catalog-owner", "title": "状态模型目录",
        "objective": "Paged study detail", "trace_id": "trace-ml-catalog",
        "idempotency_key": "task-ml-catalog",
    }).json()
    version = client.post("/v1/research/ml/strategies/versions", headers=headers, json={
        "task_id": task["task_id"], "strategy": valid_strategy_v2(),
        "trace_id": "trace-ml-catalog", "idempotency_key": "version-ml-catalog",
    })
    assert version.status_code == 201, version.text
    artifact_id = version.json()["artifact"]["artifact_id"]

    options = client.get("/v1/research/ml/options", headers=headers)
    assert options.status_code == 200
    assert options.json()["tasks"][0]["task_id"] == task["task_id"]
    assert "artifacts" not in options.json()

    page = client.get(
        "/v1/research/ml/studies?query=状态&status=active&limit=1&offset=0",
        headers=headers,
    )
    assert page.status_code == 200, page.text
    assert page.json()["total"] == 1 and len(page.json()["studies"]) == 1
    summary = page.json()["studies"][0]
    assert summary["artifact_id"] == artifact_id
    assert summary["stage"] == "definition"
    assert "content" not in summary and "capability_lock" not in page.text

    detail = client.get(f"/v1/research/ml/studies/{artifact_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["study"]["content"]["schema_version"] == "ml-strategy-version.v2"
    assert body["training_runs"]["total"] == 0
    assert body["prediction_runs"]["total"] == 0
    assert body["backtests"]["total"] == 0
    assert "object_reference" not in detail.text and '"rows"' not in detail.text


def test_never_executed_ml_study_can_be_soft_deleted_with_approvals() -> None:
    headers = trusted_agent_context("ml-delete-owner", actor="ml-delete-owner")
    task = client.post("/v1/research/tasks", headers=headers, json={
        "owner_principal": "ml-delete-owner", "title": "Delete pending ML",
        "objective": "Discard an unexecuted study", "trace_id": "trace-ml-delete",
        "idempotency_key": "task-ml-delete",
    }).json()
    version = client.post("/v1/research/ml/strategies/versions", headers=headers, json={
        "task_id": task["task_id"], "strategy": valid_strategy_v2(),
        "trace_id": "trace-ml-delete", "idempotency_key": "version-ml-delete",
    }).json()
    artifact_id = version["artifact"]["artifact_id"]
    approval = client.post("/v1/research/ml/strategies/approvals", headers=headers, json={
        "task_id": task["task_id"], "ml_strategy_artifact_id": artifact_id,
        "decision": "approved", "rationale": "approved before browser failure",
        "trace_id": "trace-ml-delete", "idempotency_key": "approval-ml-delete",
    }).json()["artifact"]

    deleted = client.delete(f"/v1/research/ml/studies/{artifact_id}", headers=headers)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["study"]["status"] == "superseded"
    assert deleted.json()["invalidated_approval_ids"] == [approval["artifact_id"]]
    assert backend_main.research_store.get_artifact(approval["artifact_id"])["status"] == "superseded"
    assert client.get(f"/v1/research/ml/studies/{artifact_id}", headers=headers).status_code == 404
    catalog = client.get("/v1/research/ml/studies", headers=headers).json()
    assert artifact_id not in {item["artifact_id"] for item in catalog["studies"]}

    repeated = client.delete(f"/v1/research/ml/studies/{artifact_id}", headers=headers)
    assert repeated.status_code == 200
    assert repeated.json()["study"]["status"] == "superseded"


def test_ml_study_with_execution_history_cannot_be_deleted() -> None:
    headers = trusted_agent_context("ml-delete-blocked", actor="ml-delete-blocked")
    task = client.post("/v1/research/tasks", headers=headers, json={
        "owner_principal": "ml-delete-blocked", "title": "Keep executed ML",
        "objective": "Preserve execution evidence", "trace_id": "trace-ml-delete-blocked",
        "idempotency_key": "task-ml-delete-blocked",
    }).json()
    version = client.post("/v1/research/ml/strategies/versions", headers=headers, json={
        "task_id": task["task_id"], "strategy": valid_strategy_v2(),
        "trace_id": "trace-ml-delete-blocked", "idempotency_key": "version-ml-delete-blocked",
    }).json()
    artifact_id = version["artifact"]["artifact_id"]
    backend_main.ml_training_store.create_waiting(
        workspace_id=headers["x-byq-workspace-id"], owner_principal="ml-delete-blocked",
        task_id=task["task_id"], experiment_id=None,
        ml_strategy_artifact_id=artifact_id,
        stock_pool_snapshot_id="snapshot_" + "a" * 32,
        preparation={"schema_version": "test"},
        requirement={"requirement_sha256": "b" * 64}, readiness={"state": "waiting_for_data"},
        trace_id="trace-ml-delete-blocked", idempotency_key="training-ml-delete-blocked",
    )

    response = client.delete(f"/v1/research/ml/studies/{artifact_id}", headers=headers)
    assert response.status_code == 409
    assert "cannot be deleted" in response.text
    assert backend_main.research_store.get_artifact(artifact_id)["status"] == "validated"


def test_executed_ml_study_can_be_archived_and_restored_without_losing_evidence() -> None:
    headers = trusted_agent_context("ml-archive-owner", actor="ml-archive-owner")
    task = client.post("/v1/research/tasks", headers=headers, json={
        "owner_principal": "ml-archive-owner", "title": "Archive completed ML",
        "objective": "Keep execution evidence", "trace_id": "trace-ml-archive",
        "idempotency_key": "task-ml-archive",
    }).json()
    version = client.post("/v1/research/ml/strategies/versions", headers=headers, json={
        "task_id": task["task_id"], "strategy": valid_strategy_v2(),
        "trace_id": "trace-ml-archive", "idempotency_key": "version-ml-archive",
    }).json()
    artifact_id = version["artifact"]["artifact_id"]
    run = backend_main.ml_training_store.create_waiting(
        workspace_id=headers["x-byq-workspace-id"], owner_principal="ml-archive-owner",
        task_id=task["task_id"], experiment_id=None,
        ml_strategy_artifact_id=artifact_id,
        stock_pool_snapshot_id="snapshot_" + "c" * 32,
        preparation={"schema_version": "test"},
        requirement={"requirement_sha256": "d" * 64}, readiness={"state": "waiting_for_data"},
        trace_id="trace-ml-archive", idempotency_key="training-ml-archive",
    )

    blocked = client.post(
        f"/v1/research/ml/studies/{artifact_id}/lifecycle", headers=headers,
        json={"status": "archived", "idempotency_key": "archive-while-active"},
    )
    assert blocked.status_code == 409
    assert "进行中" in blocked.text

    backend_main.ml_training_store.cancel(
        run["training_run_id"], trusted_workspace=headers["x-byq-workspace-id"],
        trusted_owner="ml-archive-owner",
    )
    archived = client.post(
        f"/v1/research/ml/studies/{artifact_id}/lifecycle", headers=headers,
        json={"status": "archived", "idempotency_key": "archive-terminal-study"},
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["study"]["status"] == "archived"
    assert archived.json()["management"]["can_restore"] is True

    detail = client.get(f"/v1/research/ml/studies/{artifact_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["training_runs"]["total"] == 1
    assert detail.json()["management"]["lifecycle_status"] == "archived"
    assert artifact_id not in {
        item["artifact_id"] for item in client.get("/v1/research/ml/studies", headers=headers).json()["studies"]
    }
    archived_page = client.get(
        "/v1/research/ml/studies?status=archived", headers=headers,
    ).json()
    assert archived_page["studies"][0]["artifact_id"] == artifact_id
    assert archived_page["studies"][0]["lifecycle_status"] == "archived"

    restored = client.post(
        f"/v1/research/ml/studies/{artifact_id}/lifecycle", headers=headers,
        json={"status": "active", "idempotency_key": "restore-terminal-study"},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["study"]["status"] == "validated"
    assert restored.json()["management"]["can_archive"] is True
    assert backend_main.ml_training_store.get(
        run["training_run_id"], trusted_workspace=headers["x-byq-workspace-id"],
        trusted_owner="ml-archive-owner",
    )["status"] == "cancelled"


def test_ml_training_requires_separate_human_strategy_approval() -> None:
    headers = trusted_agent_context("ml-training-approval-owner")
    task = client.post("/v1/research/tasks", headers=headers, json={
        "owner_principal": "ml-training-approval-owner", "title": "ML approval",
        "objective": "Require approval", "trace_id": "trace-ml-training-approval",
        "idempotency_key": "task-ml-training-approval",
    }).json()
    version = client.post("/v1/research/ml/strategies/versions", headers=headers, json={
        "task_id": task["task_id"], "strategy": valid_strategy(),
        "trace_id": "trace-ml-training-approval", "idempotency_key": "version-ml-training-approval",
    }).json()
    response = client.post("/v1/research/ml/training-runs", headers=headers, json={
        "task_id": task["task_id"],
        "ml_strategy_artifact_id": version["artifact"]["artifact_id"],
        "stock_pool_snapshot_id": "snapshot_not_reached",
        "trace_id": "trace-ml-training-approval",
        "idempotency_key": "training-ml-training-approval",
    })
    assert response.status_code == 422
    assert "explicit human approval" in response.text


def test_ml_training_read_is_workspace_scoped_and_returns_safe_not_found() -> None:
    response = client.get(
        "/v1/research/ml/training-runs/mlrun_missing",
        headers=trusted_agent_context("ml-api-reader"),
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "ML training run not found"}
