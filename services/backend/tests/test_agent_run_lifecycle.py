from __future__ import annotations

import hashlib
import json
import os

import pytest

from app.agent_research import AgentConflict, AgentForbidden, AgentResearchStore, AgentUnauthorized
from tests.workspace_helpers import trusted_agent_context

pytestmark = pytest.mark.skipif(not os.environ.get("BYQ_DATABASE_URL"), reason="requires isolated PostgreSQL")


def context():
    return trusted_agent_context("alice", actor="byq-product-agent-test", dsh_run_id="generation-test")


def fingerprint(ctx, key):
    values = ["agent-run-registration.v1", *[ctx[f"x-byq-{field}"] for field in (
        "owner-principal", "workspace-id", "actor-principal", "trace-id", "session-id", "dsh-run-id",
    )], key]
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def start(store, ctx, key, **overrides):
    payload = {"role_id": "quant_orchestrator", "trace_id": ctx["x-byq-trace-id"],
               "session_id": ctx["x-byq-session-id"], "dsh_run_id": ctx["x-byq-dsh-run-id"],
               "idempotency_key": key, **overrides}
    return store.start_run(payload, trusted_owner=ctx["x-byq-owner-principal"],
                           trusted_actor=ctx["x-byq-actor-principal"],
                           trusted_workspace=ctx["x-byq-workspace-id"], require_runtime_binding=True)


def apply(store, ctx, root, *, key=None, outcome="active", sequence=1):
    return store.apply_runtime_lifecycle_event({
        "schema_version": "agent-run-lifecycle.v1", "root_run_id": root, "sequence": sequence,
        "outcome": outcome, **({"registration_fingerprint": fingerprint(ctx, key)} if key else {}),
    }, trusted_owner=ctx["x-byq-owner-principal"], trusted_workspace=ctx["x-byq-workspace-id"],
        trusted_session_id=ctx["x-byq-session-id"], trusted_trace_id=ctx["x-byq-trace-id"])


@pytest.mark.parametrize("outcome", ["completed", "failed", "cancelled", "interrupted"])
def test_exact_turn_closes_bound_runs_but_not_next_turn_or_business_approval(outcome):
    ctx = context()
    store = AgentResearchStore()
    try:
        apply(store, ctx, "a" * 32, key="first")
        first = start(store, ctx, "first")
        approval = store.create_approval({"run_id": first["run_id"], "action": "byq_backtest_task_execute",
            "reason": "Synthetic", "resource_type": "backtest_task", "resource_id": "backtesttask_synthetic",
            "idempotency_key": "synthetic-approval"})
        apply(store, ctx, "b" * 32, key="second", sequence=3)
        second = start(store, ctx, "second")
        apply(store, ctx, "a" * 32, outcome=outcome, sequence=2)
        assert start(store, ctx, "first")["status"] == outcome
        assert start(store, ctx, "second")["status"] == "active"
        assert store.authorize({"run_id": second["run_id"], "action": "byq_factor_compute"})["authorized"]
        with pytest.raises(AgentForbidden):
            store.authorize({"run_id": first["run_id"], "action": "byq_factor_compute"})
        persisted = store._fetch_one("SELECT * FROM agent_approvals WHERE approval_id=:id", {"id": approval["approval_id"]})
        assert persisted["status"] == "pending"
        assert persisted["execution_outcome"] == approval["execution_outcome"]
        audit_count = len(store.list_audit(first["run_id"], trusted_owner="alice")["events"])
        apply(store, ctx, "a" * 32, outcome=outcome, sequence=2)
        assert len(store.list_audit(first["run_id"], trusted_owner="alice")["events"]) == audit_count
    finally:
        store.close()


def test_missing_binding_is_not_authorized_and_late_binding_obeys_durable_terminal():
    ctx = context()
    store = AgentResearchStore()
    pending = start(store, ctx, "delayed")
    assert pending["status"] == "pending_binding"
    with pytest.raises(AgentForbidden):
        store.authorize({"run_id": pending["run_id"], "action": "byq_factor_compute"})
    apply(store, ctx, "c" * 32, outcome="failed", sequence=9)
    store.close()
    store = AgentResearchStore()
    try:
        apply(store, ctx, "c" * 32, key="delayed", sequence=2)
        assert start(store, ctx, "delayed")["status"] == "failed"
        apply(store, ctx, "c" * 32, key="late-write", sequence=3)
        assert start(store, ctx, "late-write")["status"] == "failed"
        with pytest.raises(AgentConflict):
            apply(store, ctx, "d" * 32, key="delayed", sequence=10)
        with pytest.raises(AgentConflict):
            apply(store, ctx, "c" * 32, outcome="completed", sequence=11)
    finally:
        store.close()


def test_binding_cannot_cross_workspace_session_or_parent_turn():
    ctx = context()
    store = AgentResearchStore()
    try:
        apply(store, ctx, "a" * 32, key="parent")
        parent = start(store, ctx, "parent")
        for changed in ({"x-byq-session-id": "wrong-session"}, {"x-byq-trace-id": "wrong-trace"},
                        {"x-byq-workspace-id": "workspace_wrong"}):
            with pytest.raises(AgentUnauthorized):
                apply(store, {**ctx, **changed}, "a" * 32, outcome="failed", sequence=2)
        apply(store, ctx, "b" * 32, key="child")
        with pytest.raises(AgentForbidden):
            start(store, ctx, "child", role_id="market_researcher", parent_run_id=parent["run_id"])
        assert start(store, ctx, "parent")["status"] == "active"
    finally:
        store.close()


def test_terminal_audit_failure_rolls_back_receipt_and_run(monkeypatch):
    ctx = context()
    store = AgentResearchStore()
    try:
        apply(store, ctx, "a" * 32, key="atomic")
        run = start(store, ctx, "atomic")
        original = store._record_runtime_binding_audit
        def fail(*args):
            raise RuntimeError("synthetic audit write failure")
        monkeypatch.setattr(store, "_record_runtime_binding_audit", fail)
        with pytest.raises(RuntimeError, match="synthetic"):
            apply(store, ctx, "a" * 32, outcome="failed", sequence=2)
        assert start(store, ctx, "atomic")["status"] == "active"
        assert store._fetch_one("SELECT status FROM agent_runtime_turns WHERE root_run_id=:id", {"id": "a" * 32})["status"] == "active"
        monkeypatch.setattr(store, "_record_runtime_binding_audit", original)
        apply(store, ctx, "a" * 32, outcome="failed", sequence=2)
        assert start(store, ctx, "atomic")["status"] == "failed"
        assert len(store.list_audit(run["run_id"], trusted_owner="alice")["events"]) == 2
    finally:
        store.close()


def test_concurrent_registration_and_terminal_do_not_leave_an_active_run():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    ctx = context()
    first, second = AgentResearchStore(), AgentResearchStore()
    try:
        for index in range(4):
            root, key = f"{index:032x}", f"racing-{index}"
            apply(first, ctx, root, key=key)
            barrier = Barrier(2)
            def register():
                barrier.wait(timeout=5)
                return start(first, ctx, key)
            def finish():
                barrier.wait(timeout=5)
                return apply(second, ctx, root, outcome="failed", sequence=2)
            with ThreadPoolExecutor(max_workers=2) as pool:
                registered, finished = pool.submit(register), pool.submit(finish)
                registered.result(timeout=10)
                finished.result(timeout=10)
            assert start(first, ctx, key)["status"] == "failed"
    finally:
        first.close()
        second.close()


def test_pending_child_is_bound_only_to_its_original_parent_turn():
    ctx = context()
    store = AgentResearchStore()
    try:
        apply(store, ctx, "a" * 32, key="parent")
        parent = start(store, ctx, "parent")
        for key, root, expected in [("same-root", "a" * 32, "active"), ("other-root", "b" * 32, "failed")]:
            child = start(store, ctx, key, role_id="market_researcher", parent_run_id=parent["run_id"])
            assert child["status"] == "pending_binding"
            apply(store, ctx, root, key=key, sequence=2)
            assert start(store, ctx, key, role_id="market_researcher", parent_run_id=parent["run_id"])["status"] == expected
    finally:
        store.close()


def test_another_generation_does_not_inherit_a_registration():
    ctx = context()
    resumed = {**ctx, "x-byq-dsh-run-id": "generation-resumed"}
    store = AgentResearchStore()
    try:
        apply(store, ctx, "a" * 32, key="generation-key")
        assert start(store, resumed, "generation-key")["status"] == "pending_binding"
        apply(store, resumed, "b" * 32, key="generation-key", sequence=2)
        assert start(store, resumed, "generation-key")["status"] == "active"
        apply(store, ctx, "a" * 32, outcome="failed", sequence=3)
        assert start(store, resumed, "generation-key")["status"] == "active"
    finally:
        store.close()
