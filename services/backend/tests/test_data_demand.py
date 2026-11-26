from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Event

import pytest
from fastapi.testclient import TestClient

from app import main
from app.conversation_catalog import ConversationCatalogStore
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


def _context(role="admin") -> dict[str, str]:
    users = UserAuthStore()
    user = users.create_user({
        "username": "alice", "password": "password-123", "display_name": "Alice", "role": role,
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


class ConversationPreparationReadiness:
    state = "missing"
    bulk_dates = ["20241118"]

    def requirement(self, **values):
        return {
            **values, "requirement_sha256": f"{values['start_date']}-{values['end_date']}",
            "declared": {},
        }

    def assess(self, _requirement):
        return {
            "state": self.state, "calendar_complete": True,
            "required_session_count": 1, "required_cell_count": 1,
            "missing_count": int(self.state != "ready"),
            "repair_plan": {"full_sessions": self.bulk_dates},
        }


def test_conversation_preparation_shares_repair_and_recovers_in_original_session(monkeypatch):
    readiness = ConversationPreparationReadiness()
    monkeypatch.setattr(main, "market_readiness_store", readiness)
    monkeypatch.setattr(main, "security_master_store", FakeSecurityMaster())
    context = _context("user")
    catalog = ConversationCatalogStore()
    first = catalog.create("alice", context["session_id"], context["trace_id"])
    second = catalog.create("alice", "session-demand-2", "trace-demand-2")
    headers = {f"x-byq-{key.replace('_', '-')}": value for key, value in context.items()}
    path = f"/v1/data-center/conversations/{first['conversation_id']}/research-preparations"
    other = f"/v1/data-center/conversations/{second['conversation_id']}/research-preparations"
    payload = {"symbols": ["600036.SH"], "start_date": "20241118", "end_date": "20241118"}
    client = TestClient(main.app)
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: client.post(path, json=payload, headers=headers), range(2)))
    assert all(response.status_code == 200 for response in responses)
    receipt = responses[0].json()
    assert receipt == responses[1].json()
    assert receipt["status"] == "queued"
    demand_id = receipt["request_id"]
    assert client.get(path, headers=headers).json()["preparations"] == [receipt]
    assert client.get(f"{other}/{demand_id}", headers=headers).status_code == 404
    assert client.get(f"{other}/{demand_id}", headers={**headers, "x-byq-owner-principal": "bob"}).status_code == 401
    assert client.post(other, json={**payload, "start_date": "20241117"}, headers=headers).status_code == 409

    agent_path = "/v1/agent/data-demands"
    agent_command = {**payload, "start_date": "2024-11-18", "end_date": "2024-11-18", "scope_kind": "conversation_research", "purpose": "research",
                     "idempotency_key": "known-agent-command"}
    agent = client.post(agent_path, json=agent_command, headers=headers)
    assert agent.status_code == 202
    assert agent.json()["demand"]["demand_id"] == demand_id
    reconcile_path = f"{agent_path}/by-key/known-agent-command"
    assert client.get(reconcile_path, headers=headers).json()["state"] == "confirmed"
    other_headers = {**headers, "x-byq-session-id": "session-demand-2"}
    assert client.get(reconcile_path, headers=other_headers).json()["state"] == "not_found"
    assert client.get(f"{agent_path}/{demand_id}", headers=other_headers).status_code == 404

    automation = main.market_automation_store
    job = automation.claim_data_repair()
    automation.complete_data_repair(job["request_id"], error="ProviderUnavailable")
    failed = client.get(f"{path}/{demand_id}", headers=headers).json()
    assert failed["status"] == "failed"
    assert "retry_token" not in failed
    automation._execute("""UPDATE market_data_repair_requests SET completed_at=now()-interval '6 minutes'
        WHERE request_id=:id""", {"id": job["request_id"]})
    failed = client.get(f"{path}/{demand_id}", headers=headers).json()
    assert "数据源暂时不可用" in failed["error"]
    retry_path = f"{path}/{demand_id}/retry"
    retry = {"retry_token": failed["retry_token"]}
    assert client.post(retry_path, json=retry, headers=headers).json()["status"] == "queued"
    assert client.post(retry_path, json=retry, headers=headers).status_code == 409
    record = automation.get_data_repair(job["request_id"])
    assert record["self_service_retry_evidence"]["error"] == "ProviderUnavailable"
    readiness.state = "ready"
    automation.complete_data_repair(job["request_id"])
    main.data_demand_store.settle_conversation_preparations(
        readiness_store=readiness, automation_store=automation,
    )
    assert main.data_demand_store.get(
        demand_id, trusted_owner=context["owner_principal"], trusted_workspace=context["workspace_id"],
        trusted_session=context["session_id"],
    )["status"] == "ready"
    assert client.get(f"{path}/{demand_id}", headers=headers).json()["status"] == "completed"


def test_conversation_preparation_distinguishes_unpublished_and_unsupported(monkeypatch):
    readiness = ConversationPreparationReadiness()
    monkeypatch.setattr(main, "market_readiness_store", readiness)
    monkeypatch.setattr(main, "security_master_store", FakeSecurityMaster())
    context = _context("user")
    conversation = ConversationCatalogStore().create("alice", context["session_id"], context["trace_id"])
    headers = {f"x-byq-{key.replace('_', '-')}": value for key, value in context.items()}
    path = f"/v1/data-center/conversations/{conversation['conversation_id']}/research-preparations"
    payload = {"symbols": ["600036.SH"], "start_date": "20991118", "end_date": "20991118"}
    client = TestClient(main.app)

    pending = client.post(path, json=payload, headers=headers)
    assert pending.status_code == 200
    assert pending.json()["status"] == "not_published"
    assert pending.json()["request_id"] is None
    assert client.post(path, json={**payload, "symbols": ["AAPL"]}, headers=headers).status_code == 422
    readiness.bulk_dates = [f"202411{value:02d}" for value in range(16, 22)]
    too_wide = client.post(path, json={**payload, "start_date": "20241116", "end_date": "20241121"}, headers=headers)
    assert too_wide.status_code == 422
    assert "5 个" in too_wide.json()["detail"]
    assert client.get(path, headers=headers).json() == {"preparations": []}
    assert main.market_automation_store.claim_data_repair() is None



@pytest.mark.parametrize("action", [
    "stop", "disable_auto_continue", "resume", "resume_index", "resume_index_stale", "resume_index_delivery_lost",
])
def test_conversation_preparation_watches_only_exact_acp_ingress(monkeypatch, action):
    import json
    import re
    from uuid import uuid4

    from tests.test_acp_domain_call_proof import (
        _bind, _independent_cursor_digest, _observe_tool, _open_root, _settle_tool,
    )
    from tests.workspace_helpers import trusted_product_agent_context

    index_history = action.startswith("resume_index")

    class ReadyAfterVerifiedRepair(ConversationPreparationReadiness):
        def assess(self, requirement):
            result = super().assess(requirement)
            return {**result, "ready_input_sha256": "d" * 64 if self.state == "ready" else None}

        def index_history_query(self, requirement, *, offset, limit, data_version):
            assert requirement["kind"] == "index_history"
            assert requirement["symbols"] == ["000300.SH", "000905.SH"]
            assert (requirement["start_date"], requirement["end_date"]) == ("20141118", "20241117")
            assert data_version == "d" * 64 and offset == 0 and 1 <= limit <= 200
            if action == "resume_index_stale":
                return {"state": "version_changed", "data_version": None, "rows": []}
            return {"state": "ready", "data_version": data_version, "rows": [{"symbol": "000300.SH"}]}

    readiness = ReadyAfterVerifiedRepair()
    monkeypatch.setattr(main, "RUNTIME_AUTHORITY_TOKEN", "synthetic-runtime-authority")
    monkeypatch.setattr(main, "market_readiness_store", readiness)
    monkeypatch.setattr(main, "security_master_store", FakeSecurityMaster())
    monkeypatch.setattr(main, "MCP_BACKEND_PROOF_TOKEN", "synthetic-data-preparation-proof")
    session_id = "session-agent-preparation"
    context = trusted_product_agent_context(
        "research-user", actor=f"byq-product-agent-{session_id}", session_id=session_id,
        trace_id="trace-agent-preparation", dsh_run_id="generation-agent-preparation",
    )
    catalog = ConversationCatalogStore()
    conversation = catalog.create("research-user", session_id, context["x-byq-trace-id"])
    catalog.append_user_message("research-user", conversation["conversation_id"], "研究招商银行日线")
    root, identity = _open_root(main.agent_store, context, "research-preparation-run", str(uuid4()))
    delivery_headers = {"x-byq-owner-principal": "research-user", "x-byq-actor-principal": "research-user",
                        "x-byq-workspace-id": context["x-byq-workspace-id"]}
    delivery_path = f"/internal/task-continuation/{conversation['conversation_id']}/peek"
    client = TestClient(main.app)
    assert client.post(delivery_path, headers=delivery_headers).json() == {
        "status": "waiting", "background_pending": True,
    }
    _bind(main.agent_store, context, identity)
    arguments = {
        "symbols": ["600036.SH"], "start_date": "2024-11-18", "end_date": "2024-11-18",
        "purpose": "research", "scope_kind": "conversation_research", "idempotency_key": "research-preparation-acp",
    }
    if index_history:
        arguments.update(symbols=["000300.SH", "000905.SH"], start_date="2014-11-18",
                         end_date="2024-11-17", scope_kind="conversation_index_history")
    ingress = _observe_tool(main.agent_store, context, identity, "byq_data_demand_create", arguments)
    headers = {
        **context, "authorization": "Bearer synthetic-data-preparation-proof", "x-byq-root-run-id": root,
        "x-byq-acp-origin": "root", "x-byq-acp-observation-id": ingress["mcp_request_id"],
    }
    changed = client.post("/v1/agent/data-demands", headers=headers,
                          json={**arguments, "end_date": "2024-11-19"})
    assert changed.status_code in {403, 404, 409, 422}
    prepared = client.post("/v1/agent/data-demands", headers=headers, json=arguments)
    assert prepared.status_code == 202, prepared.json()
    data = prepared.json()
    assert data["auto_continuation"]["status"] == "waiting"
    demand = data["demand"]["demand_id"]
    path = f"/v1/data-center/conversations/{conversation['conversation_id']}/research-preparations/{demand}"
    assert client.get(path, headers=context).json()["auto_continuation"]["status"] == "waiting"
    if action == "stop":
        stopped = client.post(f"{path}/stop-continuation", headers=context)
        assert stopped.status_code == 200
        assert stopped.json()["auto_continuation"]["status"] == "cancelled"
        main.agent_store._execute("""UPDATE agent_runtime_turns SET authority_status='authority_revoked_unconfirmed'
            WHERE root_run_id=:root""", {"root": root})
        assert client.post(delivery_path, headers=delivery_headers).json() == {
            "status": "waiting", "background_pending": False,
        }
        return

    boot = context["x-byq-runtime-boot-id"]
    trusted = {"owner_principal": "research-user", "workspace_id": context["x-byq-workspace-id"],
               "session_id": session_id, "trace_id": context["x-byq-trace-id"]}
    private = {"authorization": "Bearer synthetic-runtime-authority"}
    base = f"/internal/research-data-continuation/{conversation['conversation_id']}"
    assert client.post(f"{base}/peek", headers=private, json=trusted).json() == {"continuation": None}
    _settle_tool(main.agent_store, context, identity, ingress)
    cursor, cursor_sha256, _ = _independent_cursor_digest(main.agent_store, root)
    main.agent_store._execute(
        """UPDATE agent_runtime_turns SET status='completed',authority_status='closed',terminal_sequence=8,
            terminal_event_sha256=:sha,terminal_unknown_claim_count=0,terminal_acp_ingress_sequence=:sequence,
            terminal_acp_ingress_sha256=:cursor_sha256 WHERE root_run_id=:root""",
        {"root": root, "sha": "1" * 64, "sequence": cursor, "cursor_sha256": cursor_sha256},
    )
    assert client.post(f"{base}/peek", headers=private, json=trusted).json() == {"continuation": None}
    auto = main.market_automation_store
    repair = auto.claim_data_repair()
    assert repair is not None
    readiness.state = "ready"
    auto.complete_data_repair(repair["request_id"])
    main.data_demand_store.settle_conversation_preparations(readiness_store=readiness, automation_store=auto)
    if action == "disable_auto_continue":
        from packages.contracts.agent_execution_options import default_agent_execution_options

        user = main.user_store._fetch_one("SELECT user_id FROM users WHERE username='research-user'")
        main.user_store.update_agent_execution_options(user["user_id"], {
            "schema_version": "agent-execution-options.v1",
            "expected_revision": 0,
            "options": {**default_agent_execution_options(), "auto_continue": False},
        })
        assert client.post(f"{base}/peek", headers=private, json=trusted).json() == {"continuation": None}
        assert client.get(path, headers=context).json()["auto_continuation"]["status"] == "cancelled"
        return

    ready = client.post(f"{base}/peek", headers=private, json=trusted)
    assert ready.status_code == 200, ready.json()
    offer = ready.json()["continuation"]
    assert offer["ready_input_sha256"] == "d" * 64
    continuation = offer["continuation_id"]
    payload = {**trusted, "continuation_id": continuation, "boot_id": boot}
    claimed = client.post(f"{base}/claim", headers=private, json=payload).json()["continuation"]
    assert claimed["continuation_id"] == continuation
    argument_blocks = re.findall(r"\{[^{}]+\}", claimed["instruction"])
    assert json.loads(argument_blocks[0]) == {
        "role_id": "quant_orchestrator", "idempotency_key": continuation,
    }
    assert client.post(f"{base}/claim", headers=private, json=payload).json() == {"continuation": None}

    new_root = uuid4().hex
    binding = {**trusted, "root_run_id": new_root, "boot_id": boot,
               "content_sha256": claimed["content_sha256"]}
    bind_path = f"/internal/research-data-continuation/{continuation}/bind"
    bound = client.post(bind_path, headers=private, json=binding)
    assert bound.status_code == 200, bound.json()
    assert bound.json() == {"continuation_id": continuation, "root_run_id": new_root}
    assert main.agent_store._fetch_one("SELECT root_run_id FROM agent_runtime_turns WHERE root_run_id=:root",
                                      {"root": new_root}) is None

    from app.agent_research import AgentUnauthorized
    _, new_identity = _open_root(main.agent_store, context, "research-continuation-run", str(uuid4()),
                                 sequence=10, root_run_id=new_root)
    _bind(main.agent_store, context, new_identity)
    with pytest.raises(AgentUnauthorized):
        _observe_tool(main.agent_store, context, new_identity, "byq_data_demand_create", arguments)
    if index_history:
        _, read_block = argument_blocks
        read_args = json.loads(read_block)
        read = _observe_tool(main.agent_store, context, new_identity, "byq_market_index_daily", read_args)
        read_headers = {**headers, "x-byq-root-run-id": new_root, "x-byq-acp-observation-id": read["mcp_request_id"]}
        mismatched = client.post("/v1/data/research/index-daily", headers=read_headers,
                                 json={**read_args, "data_version": "a" * 64})
        assert mismatched.status_code == 409
        response = client.post("/v1/data/research/index-daily", headers=read_headers, json=read_args)
        assert response.status_code == 200, response.json()
        assert response.json()["state"] == ("version_changed" if action == "resume_index_stale" else "ready")
    else:
        read = _observe_tool(main.agent_store, context, new_identity, "byq_market_daily",
                             {"ts_code": "600036.SH", "trade_date": "20241118"})
    version_read = "d" * 64 if action == "resume_index" else None
    _settle_tool(main.agent_store, context, new_identity, read, index_data_version=version_read)
    main.agent_store._execute(
        """UPDATE agent_runtime_turns SET status='completed',authority_status='closed',terminal_sequence=14,
            terminal_event_sha256=:sha,terminal_unknown_claim_count=0,terminal_acp_ingress_sequence=:sequence
            WHERE root_run_id=:root""",
        {"root": new_root, "sha": "2" * 64, "sequence": read["sequence"]},
    )
    if action in {"resume_index_stale", "resume_index_delivery_lost"}:
        catalog.append_assistant_message("research-user", conversation["conversation_id"], "指数数据待复核。", 12)
        assert client.get(path, headers=context).json()["auto_continuation"]["status"] == "failed"
        return
    assert client.get(path, headers=context).json()["auto_continuation"]["status"] == "bound"
    catalog.append_assistant_message("research-user", conversation["conversation_id"], "已复查行情。", 12)
    assert client.get(path, headers=context).json()["auto_continuation"]["status"] == "succeeded"
