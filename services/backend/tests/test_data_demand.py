from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Event

import pytest
from fastapi.testclient import TestClient

from app import main
from app.data_demand import DataDemandConflict, DataDemandNotFound, DataDemandStore
from app.market_plan import partition_market_requirements
from app.paper_trading import PaperTradingStore
from app.research import InvalidTransition, ResearchStore
from app.user_auth import UserAuthStore
from app.workspace_tenancy import WorkspaceTenancyStore
from workers.data.worker import process_one_data_import_job


pytestmark = pytest.mark.skipif(
    not os.environ.get("BYQ_DATABASE_URL"), reason="BYQ_DATABASE_URL is not set",
)


class FakeReadiness:
    def __init__(self, states: list[str]) -> None:
        self.states = states

    def assess(self, requirement: dict[str, object]) -> dict[str, object]:
        index = int(requirement["partition"])
        state = self.states[index]
        return {
            "state": state,
            "required_cell_count": 10,
            "missing_count": 0 if state == "ready" else 10,
            "missing_trade_dates": [] if state == "ready" else [f"20260{index + 1}02"],
        }


class FakeAutomation:
    def __init__(self, repair_status: str = "completed", failed_jobs: int = 0) -> None:
        self.repair_status = repair_status
        self.failed_jobs = failed_jobs

    def get_data_repairs(self, request_ids: list[str]) -> list[dict[str, object]]:
        return [{"request_id": value, "status": self.repair_status} for value in request_ids]

    def session_job_counts(self, trade_dates: list[str]) -> dict[str, int]:
        return {"queued": 0, "running": 0, "completed": 0, "failed": self.failed_jobs}


class FakeDemandAutomation(FakeAutomation):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[dict[str, object]] = []

    def request_data_repair(self, *, requirement: dict[str, object], requested_by: str, _connection=None) -> dict[str, object]:
        self.requests.append(requirement)
        return {"request_id": f"repair_{len(self.requests)}", "status": "completed"}


class FakeDemandReadiness:
    def requirement(self, **values: object) -> dict[str, object]:
        return {**values, "datasets": ["stock_daily"], "partition": 0}

    def assess(self, requirement: dict[str, object]) -> dict[str, object]:
        return {"state": "ready", "required_cell_count": 1, "missing_count": 0, "missing_trade_dates": []}


class FakePendingDemandReadiness(FakeDemandReadiness):
    def assess(self, requirement: dict[str, object]) -> dict[str, object]:
        return {"state": "missing", "required_cell_count": 1, "missing_count": 1,
                "missing_trade_dates": ["20260105"]}


class FakeSecurityMaster:
    def latest_snapshot(self) -> dict[str, str]:
        return {"snapshot_id": "security_snapshot_test"}


def _context() -> dict[str, str]:
    users = UserAuthStore()
    user = users.create_user({
        "username": "alice", "password": "password-123", "display_name": "Alice", "role": "admin",
    }, actor_role="admin")
    tenancy = WorkspaceTenancyStore()
    workspace = tenancy.public_workspace(str(user["user_id"]))
    context = {
        "owner_principal": "alice", "actor_principal": "byq-agent-alice",
        "workspace_id": workspace["workspace_id"], "trace_id": "trace-demand-1",
        "session_id": "session-demand-1", "dsh_run_id": "dsh-demand-1",
    }
    tenancy.close()
    users.close()
    return context


def _payload() -> dict[str, object]:
    return {
        "purpose": "machine_learning", "stock_pool_snapshot_id": "snapshot_1",
        "start_date": "2023-01-01", "end_date": "2023-10-01",
        "data_requirements": {}, "idempotency_key": "demand-1",
    }


def test_data_demand_is_owner_scoped_idempotent_and_readiness_derived() -> None:
    store = DataDemandStore()
    context = _context()
    requirements = [{"partition": 0}, {"partition": 1}]
    scope = {
        "stock_pool_snapshot_id": "snapshot_1", "pool_id": "pool_1", "symbol_count": 300,
        "start_date": "20230101", "end_date": "20231001", "partition_count": 2,
        "datasets": ["stock_daily"],
    }
    demand, created = store.create(
        _payload(), context=context, scope=scope, requirements=requirements,
        repair_request_ids=["datarepair_1", "datarepair_2"],
    )
    same, created_again = store.create(
        _payload(), context=context, scope=scope, requirements=requirements,
        repair_request_ids=["datarepair_1", "datarepair_2"],
    )
    assert created is True and created_again is False
    assert same["demand_id"] == demand["demand_id"]

    syncing = store.refresh(
        demand["demand_id"], trusted_owner="alice", readiness_store=FakeReadiness(["ready", "missing"]),
        automation_store=FakeAutomation(repair_status="running"),
    )
    assert syncing["status"] == "syncing"
    assert syncing["progress"]["ready_partitions"] == 1

    waiting_for_sessions = store.refresh(
        demand["demand_id"], trusted_owner="alice",
        readiness_store=FakeReadiness(["ready", "missing"]),
        automation_store=FakeAutomation(repair_status="waiting_for_sessions"),
    )
    assert waiting_for_sessions["status"] == "syncing"

    ready = store.refresh(
        demand["demand_id"], trusted_owner="alice", readiness_store=FakeReadiness(["ready", "ready"]),
        automation_store=FakeAutomation(),
    )
    assert ready["status"] == "ready"
    assert ready["notification"] == "数据已准备妥当，可以继续研究"
    assert store.list_for_session(trusted_owner="alice", session_id="session-demand-1")[0]["status"] == "ready"
    with pytest.raises(DataDemandNotFound):
        store.get(demand["demand_id"], trusted_owner="bob")
    store.close()


def test_five_year_300_symbol_scope_is_partitioned_below_atomic_cell_bound(monkeypatch) -> None:
    class PartitionReadiness:
        def requirement(self, **values):
            start = datetime.strptime(values["start_date"], "%Y%m%d")
            end = datetime.strptime(values["end_date"], "%Y%m%d")
            weekdays = sum(
                (start + timedelta(days=offset)).weekday() < 5
                for offset in range((end - start).days + 1)
            )
            return {**values, "projected_cells": weekdays * len(values["symbols"])}

    monkeypatch.setattr(main, "market_readiness_store", PartitionReadiness())
    partitions = partition_market_requirements(
        main.market_readiness_store,
        symbols=[f"{index:06d}.SZ" for index in range(1, 301)],
        start=datetime(2022, 1, 1), end=datetime(2026, 12, 31),
        membership_fingerprint_value="membership-test",
        security_master_snapshot_id="security-test", declared={},
    )

    assert 1 < len(partitions) <= 32
    assert all(int(item["projected_cells"]) <= 50_000 for item in partitions)
    assert partitions[0]["start_date"] == "20220101"
    assert partitions[-1]["end_date"] == "20261231"
    for previous, current in zip(partitions, partitions[1:]):
        assert datetime.strptime(current["start_date"], "%Y%m%d") == datetime.strptime(
            previous["end_date"], "%Y%m%d"
        ) + timedelta(days=1)


def test_data_demand_rejects_same_key_for_different_scope() -> None:
    store = DataDemandStore()
    context = _context()
    requirements = [{"partition": 0}]
    scope = {"stock_pool_snapshot_id": "snapshot_1", "symbol_count": 1}
    store.create(_payload(), context=context, scope=scope, requirements=requirements, repair_request_ids=["repair_1"])
    changed = {**_payload(), "end_date": "2024-01-01"}
    with pytest.raises(DataDemandConflict, match="reused"):
        store.find_idempotent(changed, context=context, scope=scope, requirements=requirements)
    store.close()


def test_data_demand_preflight_rejects_invalid_request_before_repairs() -> None:
    store = DataDemandStore()
    context = _context()
    with pytest.raises(ValueError, match="purpose"):
        store.find_idempotent(
            {**_payload(), "purpose": "provider_sync"}, context=context,
            scope={"stock_pool_snapshot_id": "snapshot_1"}, requirements=[{"partition": 0}],
        )
    with pytest.raises(ValueError, match="unknown fields"):
        store.find_idempotent(
            {**_payload(), "provider_token": "forbidden"}, context=context,
            scope={"stock_pool_snapshot_id": "snapshot_1"}, requirements=[{"partition": 0}],
        )
    store.close()


def test_agent_data_demand_route_freezes_scope_is_idempotent_and_notifies(monkeypatch) -> None:
    context = _context()
    paper = PaperTradingStore()
    pool = paper.create_pool(
        {"name": "Demand pool", "symbols": ["000001.SZ", "600000.SH"]}, trusted_owner="alice",
    )
    demands = DataDemandStore()
    automation = FakeDemandAutomation()
    monkeypatch.setattr(main, "paper_store", paper)
    monkeypatch.setattr(main, "data_demand_store", demands)
    monkeypatch.setattr(main, "market_automation_store", automation)
    monkeypatch.setattr(main, "market_readiness_store", FakeDemandReadiness())
    monkeypatch.setattr(main, "security_master_store", FakeSecurityMaster())
    client = TestClient(main.app)
    client.headers.update({
        "x-byq-owner-principal": context["owner_principal"],
        "x-byq-actor-principal": context["actor_principal"],
        "x-byq-workspace-id": context["workspace_id"],
        "x-byq-trace-id": context["trace_id"],
        "x-byq-session-id": context["session_id"],
        "x-byq-dsh-run-id": context["dsh_run_id"],
    })
    payload = {
        **_payload(), "stock_pool_snapshot_id": pool["current_snapshot_id"],
        "start_date": "2026-01-01", "end_date": "2026-01-31",
    }

    created = client.post("/v1/agent/data-demands", json=payload)
    repeated = client.post("/v1/agent/data-demands", json=payload)
    notifications = client.get("/v1/agent/data-demand-notifications")

    assert created.status_code == 202, created.text
    assert created.json()["created"] is True
    assert created.json()["demand"]["status"] == "ready"
    assert created.json()["demand"]["scope"]["symbol_count"] == 2
    assert repeated.status_code == 202 and repeated.json()["created"] is False
    assert len(automation.requests) == 1
    assert notifications.status_code == 200
    assert notifications.json()["notifications"][0]["notification"] == "数据已准备妥当，可以继续研究"
    demands.close()
    paper.close()


def test_task_bound_data_import_is_worker_owned_atomic_and_readable_by_new_session(monkeypatch) -> None:
    context = _context()
    research = ResearchStore()
    task = research.create_task({
        "owner_principal": context["owner_principal"], "title": "Data import task",
        "objective": "Prepare verified market data.", "trace_id": context["trace_id"],
        "idempotency_key": "data-import-task-1",
    }, trusted_context=context)
    paper = PaperTradingStore()
    pool = paper.create_pool(
        {"name": "Data import pool", "symbols": ["000001.SZ", "600000.SH"]},
        trusted_owner=context["owner_principal"],
    )
    demands = DataDemandStore()
    automation = FakeDemandAutomation()
    readiness = FakeDemandReadiness()
    monkeypatch.setattr(main, "paper_store", paper)
    monkeypatch.setattr(main, "data_demand_store", demands)
    monkeypatch.setattr(main, "market_automation_store", automation)
    monkeypatch.setattr(main, "market_readiness_store", readiness)
    monkeypatch.setattr(main, "security_master_store", FakeSecurityMaster())
    client = TestClient(main.app)
    headers = {
        "x-byq-owner-principal": context["owner_principal"],
        "x-byq-actor-principal": context["actor_principal"],
        "x-byq-workspace-id": context["workspace_id"],
        "x-byq-trace-id": context["trace_id"],
        "x-byq-session-id": context["session_id"],
        "x-byq-dsh-run-id": context["dsh_run_id"],
    }
    client.headers.update(headers)
    payload = {
        **_payload(), "task_id": task["task_id"],
        "stock_pool_snapshot_id": pool["current_snapshot_id"],
        "start_date": "2026-01-01", "end_date": "2026-01-31",
    }

    submitted = client.post("/v1/agent/data-demands", json=payload)
    assert submitted.status_code == 202, submitted.text
    demand = submitted.json()["demand"]
    job_id = demand["job"]["job_id"]
    assert demand["status"] == "queued"
    assert demand["job"]["type"] == "DATA_IMPORT"
    assert demand["job"]["status"] == "QUEUED"
    assert demand["job"]["input_ref"]
    assert submitted.json()["business_job"] == demand["job"]

    # A routine Agent read cannot finalize readiness, even if it could observe
    # ready market data. Only the Worker cycle below creates the Artifact.
    observed = client.get(f"/v1/agent/data-demands/{job_id}")
    assert observed.status_code == 200
    assert observed.json()["demand"]["job"]["status"] == "QUEUED"
    assert research._fetch_one("SELECT COUNT(*) AS n FROM artifacts")["n"] == 0

    syncing = process_one_data_import_job(
        demands, research, FakePendingDemandReadiness(), FakeAutomation(repair_status="running"),
    )
    assert syncing is not None
    assert syncing["status"] == "syncing"
    assert syncing["job"]["status"] == "RUNNING"

    report = research.create_artifact({
        "task_id": task["task_id"], "kind": "research_report", "content": {"summary": "ready"},
        "lineage": [], "trace_id": context["trace_id"], "idempotency_key": "data-import-guard-proof",
    }, trusted_owner=context["owner_principal"], trusted_workspace=context["workspace_id"])
    research.transition("artifact", report["artifact_id"], "validated", "data-import-guard-proof-valid")
    research.transition("research_task", task["task_id"], "running", "data-import-task-start")
    completion = {
        "schema_version": "research-progress.v1", "stage": "completed",
        "next_action": None, "blocked_reason": None, "linked_objects": [],
        "completion_evidence": [report["artifact_id"]],
    }
    with pytest.raises(InvalidTransition, match="unfinished domain work"):
        research.transition("research_task", task["task_id"], "completed", "data-import-guard-active",
            progress=completion, require_completion_evidence=True)

    original_create_artifact = research.create_artifact
    def fail_artifact(*args, **kwargs):
        raise RuntimeError("synthetic Artifact write interruption")
    research.create_artifact = fail_artifact
    with pytest.raises(RuntimeError, match="interruption"):
        process_one_data_import_job(demands, research, readiness, automation)
    research.create_artifact = original_create_artifact
    rolled_back = demands.get(job_id, trusted_owner=context["owner_principal"], trusted_workspace=context["workspace_id"])
    assert rolled_back["job"]["status"] == "RUNNING"
    assert rolled_back.get("result_artifact_id") is None
    assert research._fetch_one("SELECT COUNT(*) AS n FROM artifacts WHERE kind='data_readiness'")["n"] == 0

    finalized = process_one_data_import_job(demands, research, readiness, automation)
    assert finalized is not None
    assert finalized["job"]["job_id"] == job_id
    assert finalized["job"]["status"] == "SUCCEEDED"
    artifact_id = finalized["job"]["result_ref"]
    artifact = research.get_artifact(artifact_id)
    assert artifact["status"] == "validated"
    assert artifact["kind"] == "data_readiness"
    assert artifact["task_id"] == task["task_id"]
    assert artifact["owner_principal"] == context["owner_principal"]
    assert artifact["workspace_id"] == context["workspace_id"]
    assert artifact["content"]["demand_id"] == job_id
    assert artifact["content"]["coverage"][0]["ready_identity"] is None
    assert artifact["content"]["provenance"]["store"] == "BYQ Data Plane"
    assert {"kind": "stock_pool_snapshot", "id": pool["current_snapshot_id"]} in artifact["lineage"]

    # The same ID is readable from a fresh Agent session and submission replay
    # resolves to the same Job/Artifact without creating another repair.
    client.headers.update({
        "x-byq-session-id": "session-demand-new-agent",
        "x-byq-dsh-run-id": "dsh-demand-new-agent",
    })
    new_session = client.get(f"/v1/agent/data-demands/{job_id}")
    assert new_session.status_code == 200
    assert new_session.json()["demand"]["job"]["job_id"] == job_id
    assert new_session.json()["demand"]["job"]["result_ref"] == artifact_id
    assert new_session.json()["business_job"] == new_session.json()["demand"]["job"]
    replay = client.post("/v1/agent/data-demands", json=payload)
    assert replay.status_code == 202, replay.text
    assert replay.json()["created"] is False
    assert replay.json()["demand"]["job"]["job_id"] == job_id
    assert replay.json()["demand"]["job"]["result_ref"] == artifact_id
    assert replay.json()["business_job"] == replay.json()["demand"]["job"]
    assert len(automation.requests) == 1
    with pytest.raises(DataDemandNotFound):
        demands.get(job_id, trusted_owner=context["owner_principal"], trusted_workspace="workspace_other")
    with pytest.raises(DataDemandNotFound):
        demands.get(job_id, trusted_owner=context["owner_principal"])
    foreign_context = {**context, "workspace_id": "workspace_other"}
    with pytest.raises(DataDemandNotFound):
        demands.submit(
            {**payload, "idempotency_key": "foreign-workspace-demand"},
            context=foreign_context,
            planner=lambda *_args: (_ for _ in ()).throw(AssertionError("foreign task reached planner")),
            automation_store=automation,
        )
    assert len(automation.requests) == 1

    completed = research.transition("research_task", task["task_id"], "completed", "data-import-guard-active",
        progress=completion, require_completion_evidence=True)
    assert completed["status"] == "completed"
    demands.close()
    paper.close()
    research.close()


def test_task_bound_data_import_partial_and_failed_states_have_no_success_artifact() -> None:
    context = _context()
    research = ResearchStore()
    task = research.create_task({
        "owner_principal": context["owner_principal"], "title": "Partial data task",
        "objective": "Exercise bounded data failure.", "trace_id": context["trace_id"],
        "idempotency_key": "data-import-failure-task-1",
    }, trusted_context=context)
    demands = DataDemandStore()
    scope = {"stock_pool_snapshot_id": "snapshot-test", "symbol_count": 1}
    for key, status, readiness in (
        ("data-import-partial", "partial", FakeReadiness(["ready", "missing"])),
        ("data-import-failed", "failed", FakeReadiness(["missing"])),
    ):
        payload = {**_payload(), "task_id": task["task_id"], "idempotency_key": key}
        requirements = [{"partition": index} for index in range(len(readiness.states))]
        demand, created = demands.create(
            payload, context=context, scope=scope, requirements=requirements,
            repair_request_ids=[f"repair-{key}-{index}" for index in range(len(requirements))],
        )
        assert created is True
        result = demands.process_task_bound(
            demand["demand_id"], readiness_store=readiness,
            automation_store=FakeAutomation(repair_status="failed"), research_store=research,
        )
        assert result is not None
        assert result["status"] == status
        assert result["job"]["status"] == "FAILED"
        assert result["job"]["result_ref"] is None
        assert result["job"]["error"]["code"] == f"data_preparation_{status}"
    assert research._fetch_one("SELECT COUNT(*) AS n FROM artifacts WHERE kind='data_readiness'")["n"] == 0
    demands.close()
    research.close()


def test_task_bound_data_import_fails_when_frozen_pool_no_longer_accepts_reference() -> None:
    context = _context()
    research = ResearchStore()
    paper = PaperTradingStore()
    demands = DataDemandStore()
    task = research.create_task({
        "owner_principal": context["owner_principal"], "title": "Inactive source task",
        "objective": "Check unavailable frozen input.", "trace_id": context["trace_id"],
        "idempotency_key": "data-import-inactive-task",
    }, trusted_context=context)
    pool = paper.create_pool(
        {"name": "Inactive source pool", "symbols": ["000001.SZ"]},
        trusted_owner=context["owner_principal"],
    )
    snapshot_id = pool["current_snapshot_id"]
    demand, _ = demands.create(
        {**_payload(), "task_id": task["task_id"], "stock_pool_snapshot_id": snapshot_id,
         "idempotency_key": "data-import-inactive-pool"},
        context=context, scope={"stock_pool_snapshot_id": snapshot_id},
        requirements=[{"partition": 0}], repair_request_ids=["repair-inactive-pool"],
    )
    paper.set_pool_lifecycle(
        pool["pool_id"],
        {"status": "inactive", "reason": "source removed after submission",
         "idempotency_key": "data-import-inactive-pool-state"},
        trusted_owner=context["owner_principal"],
    )
    result = demands.process_task_bound(
        demand["demand_id"], readiness_store=FakeReadiness(["ready"]),
        automation_store=FakeAutomation(), research_store=research,
    )
    assert result is not None
    assert result["job"]["status"] == "FAILED"
    assert result["job"]["error"]["code"] == "data_source_unavailable"
    assert result["job"]["result_ref"] is None
    assert demand["demand_id"] not in demands.list_pending_task_bound()
    assert research._fetch_one("SELECT COUNT(*) AS n FROM artifacts WHERE kind='data_readiness'")["n"] == 0
    demands.close()
    paper.close()
    research.close()


def test_task_bound_data_import_cancel_is_scoped_idempotent_and_fences_worker(monkeypatch) -> None:
    context = _context()
    research = ResearchStore()
    demands = DataDemandStore()
    task = research.create_task({
        "owner_principal": context["owner_principal"], "title": "Cancel data import",
        "objective": "Cancel the waiting demand.", "trace_id": context["trace_id"],
        "idempotency_key": "data-import-cancel-task",
    }, trusted_context=context)
    demand, _ = demands.create(
        {**_payload(), "task_id": task["task_id"], "idempotency_key": "data-import-cancel"},
        context=context, scope={"stock_pool_snapshot_id": "snapshot-test"},
        requirements=[{"partition": 0}], repair_request_ids=["repair-cancel"],
    )
    job_id = demand["demand_id"]
    with pytest.raises(DataDemandNotFound):
        demands.cancel(job_id, trusted_owner=context["owner_principal"], trusted_workspace="other-workspace")
    monkeypatch.setattr(main, "data_demand_store", demands)
    client = TestClient(main.app)
    client.headers.update({
        "x-byq-owner-principal": context["owner_principal"],
        "x-byq-actor-principal": context["actor_principal"],
        "x-byq-workspace-id": context["workspace_id"],
        "x-byq-trace-id": context["trace_id"],
        "x-byq-session-id": context["session_id"],
        "x-byq-dsh-run-id": context["dsh_run_id"],
    })
    response = client.post(f"/v1/agent/data-demands/{job_id}/cancel")
    assert response.status_code == 200, response.text
    cancelled = response.json()["demand"]
    assert response.json()["business_job"] == cancelled["job"]
    assert cancelled["job"]["status"] == "CANCELLED"
    assert cancelled["job"]["result_ref"] is None
    assert demands.cancel(
        job_id, trusted_owner=context["owner_principal"], trusted_workspace=context["workspace_id"],
    )["job"] == cancelled["job"]
    assert job_id not in demands.list_pending_task_bound()
    assert demands.process_task_bound(
        job_id, readiness_store=FakeReadiness(["ready"]),
        automation_store=FakeAutomation(), research_store=research,
    )["job"]["status"] == "CANCELLED"
    assert research._fetch_one("SELECT COUNT(*) AS n FROM artifacts WHERE kind='data_readiness'")["n"] == 0
    demands.close()
    research.close()


def test_data_import_worker_completion_wins_over_concurrent_cancel() -> None:
    context = _context()
    research = ResearchStore()
    paper = PaperTradingStore()
    demands = DataDemandStore()
    task = research.create_task({
        "owner_principal": context["owner_principal"], "title": "Data import race",
        "objective": "Confirm one terminal result.", "trace_id": context["trace_id"],
        "idempotency_key": "data-import-race-task",
    }, trusted_context=context)
    pool = paper.create_pool(
        {"name": "Data import race pool", "symbols": ["000001.SZ"]},
        trusted_owner=context["owner_principal"],
    )
    snapshot_id = pool["current_snapshot_id"]
    demand, _ = demands.create(
        {**_payload(), "task_id": task["task_id"], "stock_pool_snapshot_id": snapshot_id,
         "idempotency_key": "data-import-race"},
        context=context, scope={"stock_pool_snapshot_id": snapshot_id},
        requirements=[{"partition": 0}], repair_request_ids=["repair-race"],
    )
    started, release = Event(), Event()

    class BlockingReady(FakeReadiness):
        def assess(self, requirement):
            started.set()
            assert release.wait(5)
            return super().assess(requirement)

    with ThreadPoolExecutor(max_workers=2) as executor:
        worker = executor.submit(
            demands.process_task_bound, demand["demand_id"], readiness_store=BlockingReady(["ready"]),
            automation_store=FakeAutomation(), research_store=research,
        )
        try:
            assert started.wait(5)
            cancellation = executor.submit(
                demands.cancel, demand["demand_id"], trusted_owner=context["owner_principal"],
                trusted_workspace=context["workspace_id"],
            )
            assert not cancellation.done()
        finally:
            release.set()
        completed = worker.result(timeout=10)
        after_cancel = cancellation.result(timeout=10)
    assert completed["job"]["status"] == "SUCCEEDED"
    assert after_cancel["job"]["status"] == "SUCCEEDED"
    assert completed["job"]["result_ref"] == after_cancel["job"]["result_ref"]
    assert research._fetch_one("SELECT COUNT(*) AS n FROM artifacts WHERE kind='data_readiness'")["n"] == 1
    demands.close()
    paper.close()
    research.close()
