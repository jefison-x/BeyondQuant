from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app import main
from app.data_demand import DataDemandConflict, DataDemandNotFound, DataDemandStore
from app.paper_trading import PaperTradingStore
from app.user_auth import UserAuthStore
from app.workspace_tenancy import WorkspaceTenancyStore


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

    def request_data_repair(self, *, requirement: dict[str, object], requested_by: str) -> dict[str, object]:
        self.requests.append(requirement)
        return {"request_id": f"repair_{len(self.requests)}", "status": "completed"}


class FakeDemandReadiness:
    def requirement(self, **values: object) -> dict[str, object]:
        return {**values, "datasets": ["stock_daily"], "partition": 0}

    def assess(self, requirement: dict[str, object]) -> dict[str, object]:
        return {"state": "ready", "required_cell_count": 1, "missing_count": 0, "missing_trade_dates": []}


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
