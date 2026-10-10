"""ADR-0097 Backend root admission and private AgentRun binding checks."""
from __future__ import annotations

import hashlib
import json
import os
import time
from uuid import uuid4

import pytest

from app.agent_research import AgentConflict, AgentForbidden, AgentResearchStore, AgentUnauthorized, role_catalog
from app.conversation_catalog import ConversationCatalogStore
from app.research import InvalidTransition, ResearchNotFound, ResearchStore
from packages.contracts.research_execution_plan import plan_at_stage
from packages.contracts.research_judgment import attempt_binding
from tests.workspace_helpers import trusted_product_agent_context


pytestmark = pytest.mark.skipif(not os.environ.get("BYQ_DATABASE_URL"), reason="isolated PostgreSQL required")


def _setup(stage: str = "strategy_draft"):
    suffix = uuid4().hex[:12]
    owner = f"judgment-acp-{suffix}"
    session = f"session-judgment-acp-{suffix}"
    trace = f"trace-judgment-acp-{suffix}"
    headers = trusted_product_agent_context(
        owner, actor=f"byq-product-agent-{session}", session_id=session,
        trace_id=trace, dsh_run_id=f"generation-judgment-acp-{suffix}")
    context = {
        "owner_principal": headers["x-byq-owner-principal"],
        "workspace_id": headers["x-byq-workspace-id"],
        "actor_principal": headers["x-byq-actor-principal"],
        "trace_id": headers["x-byq-trace-id"],
        "session_id": headers["x-byq-session-id"],
    }
    catalog = ConversationCatalogStore()
    research = ResearchStore()
    agents = AgentResearchStore()
    catalog.create(owner, session, trace)
    task = research.create_task({
        "owner_principal": owner, "title": "ACP judgment root",
        "objective": "Keep a judgment root bound to the exact stage call",
        "trace_id": trace, "idempotency_key": f"judgment-acp-task-{suffix}",
    }, trusted_context=context)
    task_row = research._fetch_one("SELECT * FROM research_tasks WHERE task_id=:task",
                                   {"task": task["task_id"]})
    plan = plan_at_stage(
        task_id=task["task_id"], owner_principal=owner,
        workspace_id=task_row["workspace_id"], conversation_id=task_row["conversation_id"],
        task_version=task_row["version"], stage=stage,
        idempotency_key=f"judgment-acp-plan-{suffix}", iteration=1)
    research._execute("""INSERT INTO research_execution_plans
        (task_id,owner_principal,workspace_id,conversation_id,plan_version,task_version,
         stage,iteration,status,next_action,plan,idempotency_key,request_hash,created_at,updated_at)
        VALUES (:task,:owner,:workspace,:conversation,:plan_version,:task_version,
         :stage,:iteration,:status,:next_action,:plan,:key,'test',now(),now())""",
        {"task": task["task_id"], "owner": owner, "workspace": task_row["workspace_id"],
         "conversation": task_row["conversation_id"], "plan_version": plan["plan_version"],
         "task_version": plan["task_version"], "stage": plan["stage"],
         "iteration": plan["iteration"], "status": plan["status"],
         "next_action": plan["next_action"], "plan": plan, "key": plan["idempotency_key"]})
    headers["x-byq-runtime-boot-id"] = agents.current_runtime_authority()["boot_id"]
    return catalog, research, agents, task["task_id"], context, headers, plan


def _begin_request(task_id: str, plan: dict) -> dict:
    binding = attempt_binding(plan["plan_version"], plan["stage"], plan["iteration"])
    call_identity = "byq-judgment-" + hashlib.sha256(f"{task_id}:{binding}".encode()).hexdigest()[:32]
    return {"schema_version": "byq-research-judgment-acp-root-begin.v1",
            "call_identity": call_identity, "attempt_binding": binding}


def _settlement_request(task_id: str, begin: dict, headers: dict, *,
                        settlement_kind: str = "never_dispatched",
                        terminal_outcome: str = "failed",
                        cancellation_intent_receipt: dict | None = None,
                        process_fence: str = "stopped") -> dict:
    if settlement_kind == "never_dispatched":
        journal_status, journal_digest = "available", "sha256:" + "1" * 64
        prompt_dispatch, provider_attempt = "not_dispatched", "not_started"
    elif settlement_kind == "cancelled_after_dispatch":
        journal_status, journal_digest = "available", "sha256:" + "2" * 64
        prompt_dispatch, provider_attempt = "may_have_dispatched", "may_have_started"
    else:
        journal_status, journal_digest = "unavailable", None
        prompt_dispatch, provider_attempt = "may_have_dispatched", "may_have_started"
    return {
        "schema_version": "byq-research-judgment-acp-settlement-request.v1",
        "call_identity": begin["call_identity"],
        "attempt_binding": begin["attempt_binding"],
        "root_run_id": begin["root"]["root_run_id"],
        "runtime_boot_id": headers["x-byq-runtime-boot-id"],
        "authority_epoch": begin["root"]["authority_epoch"],
        "dsh_run_id": begin["root"]["dsh_run_id"],
        "settlement_kind": settlement_kind,
        "terminal_outcome": terminal_outcome,
        "evidence": {
            "schema_version": "byq-research-judgment-acp-settlement-evidence.v1",
            "journal_status": journal_status,
            "journal_sha256": journal_digest,
            "prompt_dispatch": prompt_dispatch,
            "prompt_sha256": None,
            "provider_attempt": provider_attempt,
            "provider_attempt_sha256": None,
            "process_fence": process_fence,
            "process_fence_sha256": "sha256:" + "3" * 64 if process_fence == "stopped" else None,
            "known_usage": {"status": "unknown"},
            "cancellation_intent_receipt": cancellation_intent_receipt,
        },
    }


def _status_request(begin: dict) -> dict:
    return {"schema_version": "byq-research-judgment-acp-status.v1",
            "call_identity": begin["call_identity"],
            "attempt_binding": begin["attempt_binding"]}


def _cancel_intent_request(key: str = "cancel-" + "1" * 24) -> dict:
    return {"schema_version": "byq-research-judgment-acp-cancel-intent-request.v1",
            "idempotency_key": key}


def _close(*stores):
    for store in stores:
        store.close()


def _route_inputs(route: str):
    task_id = "task_" + "a" * 32
    root_id = "b" * 32
    if route == "begin":
        path = f"/internal/research-judgment/{task_id}/acp-root/begin"
        body = {"schema_version": "byq-research-judgment-acp-root-begin.v1",
                "call_identity": "byq-judgment-" + "c" * 32,
                "attempt_binding": "1:strategy_draft:1"}
    elif route == "register":
        path = f"/internal/research-judgment/{task_id}/acp-root/register-agent"
        body = {"schema_version": "byq-research-judgment-acp-agent-register.v1",
                "call_identity": "byq-judgment-" + "c" * 32, "root_run_id": root_id,
                "runtime_boot_id": "d" * 32,
                "native_root_session_id": str(uuid4())}
    elif route == "result":
        path = f"/internal/research-judgment/{task_id}/acp-root/result"
        body = {"schema_version": "byq-research-judgment-acp-result.v1",
                "call_identity": "byq-judgment-" + "c" * 32,
                "attempt_binding": "1:strategy_draft:1", "root_run_id": root_id,
                "runtime_boot_id": "d" * 32, "authority_epoch": 1,
                "dsh_run_id": "byqjudg-" + "e" * 32,
                "agent_run_id": "agent_run_" + "f" * 32,
                "native_root_session_id": str(uuid4()),
                "durable_evidence": {"kind": "none"}}
    elif route == "settle":
        path = f"/internal/research-judgment/{task_id}/acp-root/settle"
        body = {"schema_version": "byq-research-judgment-acp-settlement-request.v1",
                "call_identity": "byq-judgment-" + "c" * 32,
                "attempt_binding": "1:strategy_draft:1", "root_run_id": root_id,
                "runtime_boot_id": "d" * 32, "authority_epoch": 1,
                "dsh_run_id": "byqjudg-" + "e" * 32,
                "settlement_kind": "never_dispatched", "terminal_outcome": "failed",
                "evidence": {"schema_version": "byq-research-judgment-acp-settlement-evidence.v1",
                    "journal_status": "available", "journal_sha256": "sha256:" + "1" * 64,
                    "prompt_dispatch": "not_dispatched", "prompt_sha256": None,
                    "provider_attempt": "not_started", "provider_attempt_sha256": None,
                    "process_fence": "stopped", "process_fence_sha256": "sha256:" + "2" * 64,
                    "known_usage": {"status": "unknown"}, "cancellation_intent_receipt": None}}
    elif route == "cancel_intent":
        path = f"/internal/research-judgment/{task_id}/acp-root/cancel-intent"
        body = _cancel_intent_request()
    else:
        path = f"/internal/research-judgment/{task_id}/acp-root/status"
        body = {"schema_version": "byq-research-judgment-acp-status.v1",
                "call_identity": "byq-judgment-" + "c" * 32,
                "attempt_binding": "1:strategy_draft:1"}
    headers = {"Authorization": "Bearer test-runtime-authority-token",
        "x-byq-owner-principal": "route-test-user", "x-byq-workspace-id": "workspace-route-test",
        "x-byq-runtime-boot-id": "d" * 32}
    if route == "cancel_intent":
        headers = {"Authorization": "Bearer test-gateway-service-token-0123456789",
            "x-byq-owner-principal": "route-test-user", "x-byq-workspace-id": "workspace-route-test",
            "x-byq-actor-principal": "route-test-user"}
    return path, body, headers


def _route_client(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main

    class NeverStore:
        def __getattr__(self, name):
            raise AssertionError(f"route reached Backend storage method {name}")

    monkeypatch.setattr(main, "RUNTIME_AUTHORITY_TOKEN", "test-runtime-authority-token")
    monkeypatch.setattr(main, "GATEWAY_SERVICE_TOKEN", "test-gateway-service-token-0123456789")
    monkeypatch.setattr(main, "research_store", NeverStore())
    monkeypatch.setattr(main, "agent_store", NeverStore())
    return TestClient(main.app)


def test_acp_judgment_begin_is_exact_retry_and_creates_one_bound_root():
    catalog, research, agents, task, context, headers, plan = _setup()
    try:
        request = _begin_request(task, plan)
        first = research.begin_acp_judgment_root(
            task, request, trusted_context=context,
            runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        replay = research.begin_acp_judgment_root(
            task, request, trusted_context=context,
            runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        assert first["created"] is True
        assert replay["created"] is False
        assert {key: value for key, value in replay.items() if key != "created"} == {
            key: value for key, value in first.items() if key != "created"}
        assert first["status"] == "admitted"
        assert first["attempt_binding"] == request["attempt_binding"]
        assert first["root"]["runtime_boot_id"] == headers["x-byq-runtime-boot-id"]
        assert first["root"]["authority_epoch"] == agents.current_runtime_authority()["authority_epoch"]
        assert first["root"]["actor_principal"] == "byq-product-agent-" + first["root"]["session_id"]
        assert research._fetch_one("""SELECT COUNT(*) AS n FROM research_judgment_stage_calls
            WHERE task_id=:task""", {"task": task})["n"] == 1
        assert research._fetch_one("""SELECT COUNT(*) AS n FROM research_judgment_acp_roots
            WHERE task_id=:task""", {"task": task})["n"] == 1
        wrong = dict(request, attempt_binding="1:backtest_analysis:1")
        with pytest.raises(ValueError, match="call_identity"):
            research.begin_acp_judgment_root(task, wrong, trusted_context=context,
                runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
    finally:
        _close(catalog, research, agents)


def test_acp_bound_completed_result_fails_closed_until_terminal_reconciliation():
    catalog, research, agents, task, context, headers, plan = _setup("backtest_analysis")
    try:
        request = _begin_request(task, plan)
        begin = research.begin_acp_judgment_root(
            task, request, trusted_context=context,
            runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        research.register_acp_judgment_root_agent(task, {
            "schema_version": "byq-research-judgment-acp-agent-register.v1",
            "call_identity": begin["call_identity"],
            "root_run_id": begin["root"]["root_run_id"],
            "runtime_boot_id": headers["x-byq-runtime-boot-id"],
            "native_root_session_id": str(uuid4()),
        }, trusted_context=context, runtime_boot_id=headers["x-byq-runtime-boot-id"],
            agent_store=agents)
        result = {"schema_version": "byq-research-judgment-result.v1", "outcome": "accepted"}
        research._execute("""UPDATE research_judgment_stage_calls
            SET status='completed',completed_at=now(),outcome='accepted',
                result_json=CAST(:result AS jsonb)
            WHERE task_id=:task AND call_identity=:identity""",
            {"result": result, "task": task, "identity": begin["call_identity"]})

        with pytest.raises(AgentConflict, match="committed result but no terminal root reconciliation"):
            research.begin_acp_judgment_root(task, request, trusted_context=context,
                runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        binding = research._fetch_one("""SELECT status,root_run_id FROM research_judgment_acp_roots
            WHERE task_id=:task AND call_identity=:identity""",
            {"task": task, "identity": begin["call_identity"]})
        assert binding == {"status": "agent_bound", "root_run_id": begin["root"]["root_run_id"]}
    finally:
        _close(catalog, research, agents)


def test_judgment_root_cannot_close_before_exact_result_commit():
    catalog, research, agents, task, context, headers, plan = _setup("backtest_analysis")
    try:
        begin = research.begin_acp_judgment_root(
            task, _begin_request(task, plan), trusted_context=context,
            runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        root = begin["root"]["root_run_id"]
        digest = "a" * 64
        with pytest.raises(AgentConflict, match="completed result and bound Agent"):
            agents.close_runtime_root(root, boot_id=headers["x-byq-runtime-boot-id"],
                sequence=2, outcome="completed", event_sha256=digest)
        research.register_acp_judgment_root_agent(task, {
            "schema_version": "byq-research-judgment-acp-agent-register.v1",
            "call_identity": begin["call_identity"], "root_run_id": root,
            "runtime_boot_id": headers["x-byq-runtime-boot-id"],
            "native_root_session_id": str(uuid4()),
        }, trusted_context=context, runtime_boot_id=headers["x-byq-runtime-boot-id"],
            agent_store=agents)
        with pytest.raises(AgentConflict, match="result is not durably committed"):
            agents.close_runtime_root(root, boot_id=headers["x-byq-runtime-boot-id"],
                sequence=2, outcome="completed", event_sha256=digest)
        with pytest.raises(AgentConflict, match="matching durable pre-result settlement"):
            agents.close_runtime_root(root, boot_id=headers["x-byq-runtime-boot-id"],
                sequence=2, outcome="cancelled", event_sha256=digest)
        stored = research._fetch_one("SELECT status FROM agent_runtime_turns WHERE root_run_id=:root",
                                     {"root": root})
        assert stored["status"] == "active"
    finally:
        _close(catalog, research, agents)


def test_acp_judgment_result_commits_once_then_allows_exact_root_close():
    catalog, research, agents, task, context, headers, plan = _setup("backtest_analysis")
    try:
        begin = research.begin_acp_judgment_root(
            task, _begin_request(task, plan), trusted_context=context,
            runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        native = str(uuid4())
        research.register_acp_judgment_root_agent(task, {
            "schema_version": "byq-research-judgment-acp-agent-register.v1",
            "call_identity": begin["call_identity"],
            "root_run_id": begin["root"]["root_run_id"],
            "runtime_boot_id": headers["x-byq-runtime-boot-id"],
            "native_root_session_id": native,
        }, trusted_context=context, runtime_boot_id=headers["x-byq-runtime-boot-id"],
            agent_store=agents)
        binding = research._fetch_one("""SELECT * FROM research_judgment_acp_roots
            WHERE task_id=:task AND call_identity=:identity""",
            {"task": task, "identity": begin["call_identity"]})
        status_request = {"schema_version": "byq-research-judgment-acp-status.v1",
                          "call_identity": begin["call_identity"],
                          "attempt_binding": begin["attempt_binding"]}
        pending = research.get_acp_judgment_root_status(
            task, status_request, trusted_context=context,
            runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        assert pending["binding_status"] == "agent_bound"
        assert pending["stage_call_status"] == "admitted"
        assert pending["result_receipt"] is None
        with pytest.raises(ResearchNotFound, match="research task not found"):
            research.get_acp_judgment_root_status(
                task, status_request,
                trusted_context={**context, "owner_principal": "another-owner"},
                runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        request = {
            "schema_version": "byq-research-judgment-acp-result.v1",
            "call_identity": begin["call_identity"],
            "attempt_binding": begin["attempt_binding"],
            "root_run_id": begin["root"]["root_run_id"],
            "runtime_boot_id": headers["x-byq-runtime-boot-id"],
            "authority_epoch": begin["root"]["authority_epoch"],
            "dsh_run_id": begin["root"]["dsh_run_id"],
            "agent_run_id": binding["agent_run_id"],
            "native_root_session_id": native,
            "durable_evidence": {"kind": "none"},
            "proposal": {"schema_version": "research-proposal.v1", "task_id": task,
                         "plan_version": plan["plan_version"],
                         "task_version": plan["task_version"],
                         "stage": plan["stage"], "iteration": plan["iteration"],
                         "proposal_kind": "backtest_analysis",
                         "evidence_sufficient": True, "escalate": False,
                         "summary": "bounded ACP judgment"},
        }
        with pytest.raises(AgentConflict, match="exact root binding"):
            research.record_acp_judgment_root_result(
                task, dict(request, dsh_run_id="byqjudg-" + "f" * 32),
                trusted_context=context, runtime_boot_id=headers["x-byq-runtime-boot-id"],
                agent_store=agents)
        with pytest.raises(AgentConflict, match="exact root binding"):
            research.record_acp_judgment_root_result(
                task, dict(request, native_root_session_id=str(uuid4())),
                trusted_context=context, runtime_boot_id=headers["x-byq-runtime-boot-id"],
                agent_store=agents)
        with pytest.raises(ResearchNotFound, match="research task not found"):
            research.record_acp_judgment_root_result(
                task, request, trusted_context={**context, "owner_principal": "another-owner"},
                runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        result = research.record_acp_judgment_root_result(
            task, request, trusted_context=context,
            runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        replay = research.record_acp_judgment_root_result(
            task, request, trusted_context=context,
            runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        assert result["schema_version"] == "research-judgment-result-receipt.v1"
        assert not result["replayed"] and replay == {**result, "replayed": True}
        assert result["proposal"]["stage"] == "iteration_comparison"
        committed = research.get_acp_judgment_root_status(
            task, status_request, trusted_context=context,
            runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        assert committed["stage_call_status"] == "completed"
        assert committed["root_status"] == "active"
        assert committed["result_receipt"] == {key: value for key, value in result.items()
                                               if key != "replayed"}
        assert committed["terminal_sequence"] is None
        assert research._fetch_one("""SELECT status FROM research_judgment_stage_calls
            WHERE task_id=:task AND call_identity=:identity""",
            {"task": task, "identity": begin["call_identity"]})["status"] == "completed"
        with pytest.raises(AgentConflict, match="retry differs"):
            research.record_acp_judgment_root_result(
                task, dict(request, durable_evidence={"kind": "plan_advance"}),
                trusted_context=context, runtime_boot_id=headers["x-byq-runtime-boot-id"],
                agent_store=agents)
        with pytest.raises(AgentConflict, match="exact root binding"):
            research.record_acp_judgment_root_result(
                task, dict(request, root_run_id=uuid4().hex), trusted_context=context,
                runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        with pytest.raises(AgentConflict, match="matching durable pre-result settlement"):
            agents.close_runtime_root(begin["root"]["root_run_id"],
                boot_id=headers["x-byq-runtime-boot-id"], sequence=2,
                outcome="failed", event_sha256="a" * 64)
        receipt = agents.close_runtime_root(begin["root"]["root_run_id"],
            boot_id=headers["x-byq-runtime-boot-id"], sequence=2,
            outcome="completed", event_sha256="a" * 64)
        assert receipt["root_run_id"] == begin["root"]["root_run_id"]
        assert agents.close_runtime_root(begin["root"]["root_run_id"],
            boot_id=headers["x-byq-runtime-boot-id"], sequence=2,
            outcome="completed", event_sha256="a" * 64) == receipt
        closed = research.get_acp_judgment_root_status(
            task, status_request, trusted_context=context,
            runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        assert closed["root_status"] == "completed"
        assert closed["terminal_sequence"] == receipt["sequence"]
        assert closed["terminal_event_sha256"] == receipt["event_sha256"]
        assert "terminal_ack" not in closed
        assert research.record_acp_judgment_root_result(
            task, request, trusted_context=context,
            runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents) == replay
        new_boot = uuid4().hex
        agents.rotate_runtime_authority(new_boot)
        with pytest.raises(AgentUnauthorized, match="current Backend authority"):
            research.record_acp_judgment_root_result(
                task, request, trusted_context=context,
                runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        assert research.get_acp_judgment_root_status(
            task, status_request, trusted_context=context,
            runtime_boot_id=new_boot, agent_store=agents)["root_status"] == "completed"
        with pytest.raises(AgentUnauthorized, match="current Backend authority"):
            research.get_acp_judgment_root_status(
                task, status_request, trusted_context=context,
                runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
    finally:
        _close(catalog, research, agents)


def test_never_dispatched_settlement_is_idempotent_consumes_call_and_closes_exact_root():
    catalog, research, agents, task, context, headers, plan = _setup("strategy_draft")
    try:
        begin = research.begin_acp_judgment_root(
            task, _begin_request(task, plan), trusted_context=context,
            runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        request = _settlement_request(task, begin, headers)
        first = research.settle_acp_judgment_root(
            task, request, trusted_context=context,
            runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        replay = research.settle_acp_judgment_root(
            task, request, trusted_context=context,
            runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        assert first["status"] == "settled" and first["settlement_kind"] == "never_dispatched"
        assert first["terminal_outcome"] == "failed" and first["settlement_digest"].startswith("sha256:")
        assert replay == {**first, "replayed": True}
        assert first["attention"]["state"] == "needs_attention"
        assert first["attention"]["reason"].find(begin["call_identity"]) >= 0
        call = research._fetch_one("""SELECT status,outcome,result_json FROM research_judgment_stage_calls
            WHERE task_id=:task AND call_identity=:identity""",
            {"task": task, "identity": begin["call_identity"]})
        assert call == {"status": "settled", "outcome": "failed", "result_json": None}
        current_plan = research.get_execution_plan(task, trusted_context=context)
        assert current_plan["stage"] == "needs_attention"
        pending = research.get_acp_judgment_root_status(
            task, _status_request(begin), trusted_context=context,
            runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        assert pending["stage_call_status"] == "settled"
        assert pending["result_receipt"] is None
        assert pending["settlement_digest"] == first["settlement_digest"]
        assert pending["terminal_outcome"] == pending["stage_call_outcome"] == "failed"
        assert pending["settlement_receipt"] == {key: value for key, value in first.items()
                                                  if key != "replayed"}
        assert pending["terminal_sequence"] is None

        changed = dict(request)
        changed["evidence"] = {**request["evidence"], "prompt_sha256": "sha256:" + "4" * 64}
        with pytest.raises(AgentConflict, match="different terminal settlement"):
            research.settle_acp_judgment_root(
                task, changed, trusted_context=context,
                runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        with pytest.raises(AgentConflict, match="settled ACP judgment call"):
            research.begin_acp_judgment_root(task, _begin_request(task, plan), trusted_context=context,
                runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)

        with pytest.raises(AgentConflict, match="matching durable pre-result settlement"):
            agents.close_runtime_root(begin["root"]["root_run_id"],
                boot_id=headers["x-byq-runtime-boot-id"], sequence=2,
                outcome="interrupted", event_sha256="a" * 64)
        terminal = agents.close_runtime_root(begin["root"]["root_run_id"],
            boot_id=headers["x-byq-runtime-boot-id"], sequence=2,
            outcome="failed", event_sha256="a" * 64)
        assert terminal["root_run_id"] == begin["root"]["root_run_id"]
        closed = research.get_acp_judgment_root_status(
            task, _status_request(begin), trusted_context=context,
            runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        assert closed["root_status"] == "failed"
        assert closed["settlement_digest"] == first["settlement_digest"]
        assert closed["terminal_sequence"] == 2
        assert closed["terminal_event_sha256"] == "a" * 64
        assert closed["terminal_acp_ingress_sequence"] == 0
        assert closed["terminal_unknown_claim_count"] == 0
    finally:
        _close(catalog, research, agents)


def test_never_dispatched_settlement_rejects_late_resolved_ingress_before_close():
    from app.db import execute

    catalog, research, agents, task, context, headers, plan = _setup("strategy_draft")
    try:
        begin = research.begin_acp_judgment_root(
            task, _begin_request(task, plan), trusted_context=context,
            runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        settled = research.settle_acp_judgment_root(
            task, _settlement_request(task, begin, headers), trusted_context=context,
            runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        root_id = begin["root"]["root_run_id"]
        late_id = uuid4().hex
        late_event_sha256 = "d" * 64
        late_settlement_sha256 = "e" * 64
        root = agents._fetch_one("""SELECT * FROM agent_runtime_turns WHERE root_run_id=:root""",
                                 {"root": root_id})

        # Model an already observed and resolved callback arriving after the
        # pre-result settlement but before root close. Keep it under the same
        # root transaction lock used by real ACP ingress writes.
        with agents._transaction() as connection:
            agents._lifecycle_lock(connection, "runtime-authority:current")
            agents._lifecycle_lock(connection, "root:" + root_id)
            execute(connection, """INSERT INTO agent_acp_tool_ingress_observations
                (mcp_request_id,owner_principal,workspace_id,actor_principal,session_id,trace_id,dsh_run_id,
                 runtime_boot_id,root_run_id,native_root_session_id,native_agent_session_id,
                 native_parent_session_id,origin,depth,agent_run_id,tool_name,arguments_sha256,
                 sequence,event_sha256,status,settlement_json,settled_at,receipt_json)
                VALUES (:request_id,:owner,:workspace,:actor,:session,:trace,:generation,
                 :boot,:root,:native,:native,NULL,'root',0,NULL,'byq_agent_context',:arguments_sha256,
                 1,:event_sha256,'settled',CAST(:settlement AS jsonb),CURRENT_TIMESTAMP,
                 CAST(:receipt AS jsonb))""", {
                    "request_id": late_id, "owner": root["owner_principal"],
                    "workspace": root["workspace_id"], "actor": context["actor_principal"],
                    "session": root["session_id"], "trace": root["trace_id"],
                    "generation": begin["root"]["dsh_run_id"],
                    "boot": headers["x-byq-runtime-boot-id"],
                    "root": root_id, "native": str(uuid4()),
                    "arguments_sha256": "f" * 64, "event_sha256": late_event_sha256,
                    "settlement": json.dumps({"outcome": "settled",
                        "settlement_sha256": late_settlement_sha256}),
                    "receipt": json.dumps({"mcp_request_id": late_id}),
                })

        with pytest.raises(AgentConflict, match="ingress snapshot changed before root close"):
            agents.close_runtime_root(root_id,
                boot_id=headers["x-byq-runtime-boot-id"], sequence=2,
                outcome="failed", event_sha256="a" * 64)
        status = research.get_acp_judgment_root_status(
            task, _status_request(begin), trusted_context=context,
            runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        assert status["root_status"] == "active"
        assert status["terminal_sequence"] is None
        assert status["settlement_digest"] == settled["settlement_digest"]
        assert status["terminal_acp_ingress_sequence"] is None
    finally:
        _close(catalog, research, agents)


def test_cancelled_after_dispatch_requires_persisted_owner_intent_receipt():
    catalog, research, agents, task, context, headers, plan = _setup("backtest_analysis")
    try:
        begin = research.begin_acp_judgment_root(
            task, _begin_request(task, plan), trusted_context=context,
            runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        native = str(uuid4())
        research.register_acp_judgment_root_agent(task, {
            "schema_version": "byq-research-judgment-acp-agent-register.v1",
            "call_identity": begin["call_identity"], "root_run_id": begin["root"]["root_run_id"],
            "runtime_boot_id": headers["x-byq-runtime-boot-id"],
            "native_root_session_id": native,
        }, trusted_context=context, runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        request = _settlement_request(task, begin, headers,
            settlement_kind="cancelled_after_dispatch", terminal_outcome="cancelled")
        with pytest.raises(ValueError, match="cancel-intent receipt"):
            research.settle_acp_judgment_root(
                task, request, trusted_context=context,
                runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)

        owner_context = {**context, "actor_principal": context["owner_principal"]}
        intent_request = _cancel_intent_request()
        cancel_receipt = research.record_acp_judgment_cancel_intent(
            task, intent_request, trusted_context=owner_context, agent_store=agents)
        assert cancel_receipt["owner_principal"] == owner_context["owner_principal"]
        assert cancel_receipt["workspace_id"] == owner_context["workspace_id"]
        assert cancel_receipt["call_identity"] == begin["call_identity"]
        assert cancel_receipt["root_run_id"] == begin["root"]["root_run_id"]
        assert cancel_receipt["intent_sha256"].startswith("sha256:")
        assert research.record_acp_judgment_cancel_intent(
            task, intent_request, trusted_context=owner_context, agent_store=agents
        ) == {**cancel_receipt, "replayed": True}

        binding = research._fetch_one("""SELECT agent_run_id FROM research_judgment_acp_roots
            WHERE task_id=:task AND call_identity=:identity""",
            {"task": task, "identity": begin["call_identity"]})
        result_request = {
            "schema_version": "byq-research-judgment-acp-result.v1",
            "call_identity": begin["call_identity"], "attempt_binding": begin["attempt_binding"],
            "root_run_id": begin["root"]["root_run_id"],
            "runtime_boot_id": headers["x-byq-runtime-boot-id"],
            "authority_epoch": begin["root"]["authority_epoch"],
            "dsh_run_id": begin["root"]["dsh_run_id"],
            "agent_run_id": binding["agent_run_id"], "native_root_session_id": native,
            "durable_evidence": {"kind": "none"},
        }
        with pytest.raises(AgentConflict, match="cancel intent already owns this call"):
            research.record_acp_judgment_root_result(
                task, result_request, trusted_context=context,
                runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)

        body_receipt = {key: value for key, value in cancel_receipt.items() if key != "replayed"}
        request["evidence"]["cancellation_intent_receipt"] = body_receipt
        forged = dict(request)
        forged["evidence"] = {**request["evidence"], "cancellation_intent_receipt": {
            **body_receipt, "intent_sha256": "sha256:" + "f" * 64}}
        with pytest.raises(AgentConflict, match="exact persisted owner cancel intent"):
            research.settle_acp_judgment_root(
                task, forged, trusted_context=context,
                runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        settled = research.settle_acp_judgment_root(
            task, request, trusted_context=context,
            runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        assert settled["settlement_kind"] == "cancelled_after_dispatch"
        assert settled["terminal_outcome"] == "cancelled"
        assert settled["evidence"]["cancellation_intent_receipt"] == body_receipt
        assert research.record_acp_judgment_cancel_intent(
            task, intent_request, trusted_context=owner_context, agent_store=agents
        ) == {**body_receipt, "replayed": True}
        terminal = agents.close_runtime_root(begin["root"]["root_run_id"],
            boot_id=headers["x-byq-runtime-boot-id"], sequence=2,
            outcome="cancelled", event_sha256="b" * 64)
        assert terminal["root_run_id"] == begin["root"]["root_run_id"]
        status = research.get_acp_judgment_root_status(
            task, _status_request(begin), trusted_context=context,
            runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        assert status["root_status"] == "cancelled"
        assert status["settlement_receipt"]["settlement_digest"] == settled["settlement_digest"]
        assert status["cancellation_intent_receipt"] == body_receipt
        research.transition("research_task", task, "cancelled", "cancel-after-acp-settlement")
        assert research.record_acp_judgment_cancel_intent(
            task, intent_request, trusted_context=owner_context, agent_store=agents
        ) == {**body_receipt, "replayed": True}
    finally:
        _close(catalog, research, agents)


def test_unknown_settlement_with_unproven_process_fence_cannot_close_or_ack():
    catalog, research, agents, task, context, headers, plan = _setup("iteration_comparison")
    try:
        begin = research.begin_acp_judgment_root(
            task, _begin_request(task, plan), trusted_context=context,
            runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        request = _settlement_request(task, begin, headers, settlement_kind="outcome_unknown",
            terminal_outcome="interrupted", process_fence="unproven")
        settled = research.settle_acp_judgment_root(
            task, request, trusted_context=context,
            runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        assert settled["status"] == "settled"
        assert settled["evidence"]["process_fence"] == "unproven"
        with pytest.raises(AgentConflict, match="matching durable pre-result settlement"):
            agents.close_runtime_root(begin["root"]["root_run_id"],
                boot_id=headers["x-byq-runtime-boot-id"], sequence=2,
                outcome="interrupted", event_sha256="c" * 64)
        status = research.get_acp_judgment_root_status(
            task, _status_request(begin), trusted_context=context,
            runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        assert status["root_status"] == "active"
        assert status["stage_call_status"] == "settled"
        assert status["terminal_sequence"] is None
        assert status["settlement_digest"] == settled["settlement_digest"]
    finally:
        _close(catalog, research, agents)


def test_terminal_task_settlement_preserves_task_and_plan_rows():
    catalog, research, agents, task, context, headers, plan = _setup("strategy_draft")
    try:
        begin = research.begin_acp_judgment_root(
            task, _begin_request(task, plan), trusted_context=context,
            runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        research.transition("research_task", task, "cancelled", "user-cancel-before-settlement")
        before_task = research._fetch_one("""SELECT status,version,progress,updated_at FROM research_tasks
            WHERE task_id=:task""", {"task": task})
        before_plan = research._fetch_one("""SELECT plan_version,task_version,stage,status,plan,
            idempotency_key,request_hash,updated_at FROM research_execution_plans WHERE task_id=:task""",
            {"task": task})
        request = _settlement_request(task, begin, headers, settlement_kind="outcome_unknown",
            terminal_outcome="interrupted", process_fence="stopped")
        receipt = research.settle_acp_judgment_root(
            task, request, trusted_context=context,
            runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        assert receipt["attention"]["state"] == "task_terminal_preserved"
        after_task = research._fetch_one("""SELECT status,version,progress,updated_at FROM research_tasks
            WHERE task_id=:task""", {"task": task})
        after_plan = research._fetch_one("""SELECT plan_version,task_version,stage,status,plan,
            idempotency_key,request_hash,updated_at FROM research_execution_plans WHERE task_id=:task""",
            {"task": task})
        assert after_task == before_task
        assert after_plan == before_plan
    finally:
        _close(catalog, research, agents)


def test_result_and_pre_result_settlement_race_has_one_winner():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    catalog, research, agents, task, context, headers, plan = _setup("strategy_draft")
    second_research = second_agents = None
    try:
        begin = research.begin_acp_judgment_root(
            task, _begin_request(task, plan), trusted_context=context,
            runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        native = str(uuid4())
        research.register_acp_judgment_root_agent(task, {
            "schema_version": "byq-research-judgment-acp-agent-register.v1",
            "call_identity": begin["call_identity"], "root_run_id": begin["root"]["root_run_id"],
            "runtime_boot_id": headers["x-byq-runtime-boot-id"], "native_root_session_id": native,
        }, trusted_context=context, runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        binding = research._fetch_one("""SELECT agent_run_id FROM research_judgment_acp_roots
            WHERE task_id=:task AND call_identity=:identity""",
            {"task": task, "identity": begin["call_identity"]})
        result_request = {
            "schema_version": "byq-research-judgment-acp-result.v1",
            "call_identity": begin["call_identity"], "attempt_binding": begin["attempt_binding"],
            "root_run_id": begin["root"]["root_run_id"],
            "runtime_boot_id": headers["x-byq-runtime-boot-id"],
            "authority_epoch": begin["root"]["authority_epoch"],
            "dsh_run_id": begin["root"]["dsh_run_id"],
            "agent_run_id": binding["agent_run_id"], "native_root_session_id": native,
            "durable_evidence": {"kind": "none"},
        }
        settlement_request = _settlement_request(task, begin, headers,
            settlement_kind="outcome_unknown", terminal_outcome="interrupted")
        second_research = ResearchStore()
        second_agents = AgentResearchStore()
        barrier = Barrier(2)

        def run_result():
            barrier.wait(timeout=10)
            try:
                return ("result", research.record_acp_judgment_root_result(
                    task, result_request, trusted_context=context,
                    runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents))
            except Exception as error:  # the competing transaction must lose cleanly
                return ("result_error", type(error).__name__, str(error))

        def run_settlement():
            barrier.wait(timeout=10)
            try:
                return ("settlement", second_research.settle_acp_judgment_root(
                    task, settlement_request, trusted_context=context,
                    runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=second_agents))
            except Exception as error:
                return ("settlement_error", type(error).__name__, str(error))

        with ThreadPoolExecutor(max_workers=2) as executor:
            result_future = executor.submit(run_result)
            settlement_future = executor.submit(run_settlement)
            outcomes = [result_future.result(timeout=30), settlement_future.result(timeout=30)]
        successes = [item for item in outcomes if item[0] in {"result", "settlement"}]
        errors = [item for item in outcomes if item[0].endswith("_error")]
        assert len(successes) == 1, outcomes
        assert len(errors) == 1, outcomes
        assert errors[0][1] in {"AgentConflict", "InvalidTransition"}, outcomes
        stored = research._fetch_one("""SELECT status,result_json,outcome FROM research_judgment_stage_calls
            WHERE task_id=:task AND call_identity=:identity""",
            {"task": task, "identity": begin["call_identity"]})
        assert stored["status"] in {"completed", "settled"}
        if stored["status"] == "completed":
            assert isinstance(stored["result_json"], dict) and stored["outcome"] is not None
        else:
            assert stored["result_json"] is None and stored["outcome"] == "interrupted"
    finally:
        _close(catalog, research, agents)
        _close(*(store for store in (second_research, second_agents) if store is not None))


def test_private_role_is_not_public_or_model_selectable_and_native_registration_is_idempotent():
    catalog, research, agents, task, context, headers, plan = _setup("backtest_analysis")
    try:
        from app.agent_research import RESEARCH_JUDGMENT_ROLE_ID
        from app.agent_research import RESEARCH_JUDGMENT_ROLE
        from packages.contracts.research_judgment import STAGE_ALLOWED_TOOLS

        assert RESEARCH_JUDGMENT_ROLE_ID not in {role["role_id"] for role in role_catalog()}
        assert set(RESEARCH_JUDGMENT_ROLE.allowed_tools) == set().union(*STAGE_ALLOWED_TOOLS.values())
        assert len(RESEARCH_JUDGMENT_ROLE.allowed_tools) == 5
        with pytest.raises(AgentForbidden, match="trusted Backend registration"):
            agents.start_run({"role_id": RESEARCH_JUDGMENT_ROLE_ID}, trusted_owner=context["owner_principal"])

        begin = research.begin_acp_judgment_root(task, _begin_request(task, plan),
            trusted_context=context, runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        native_id = str(uuid4())
        registration = {"schema_version": "byq-research-judgment-acp-agent-register.v1",
            "call_identity": begin["call_identity"], "root_run_id": begin["root"]["root_run_id"],
            "runtime_boot_id": headers["x-byq-runtime-boot-id"],
            "native_root_session_id": native_id}
        receipt = research.register_acp_judgment_root_agent(
            task, registration, trusted_context=context,
            runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        replay = research.register_acp_judgment_root_agent(
            task, registration, trusted_context=context,
            runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        assert replay == receipt
        assert receipt["schema_version"] == "byq-acp-agent-bind-receipt.v1"
        assert receipt["native_agent_session_id"] == native_id
        assert receipt["origin"] == "root" and receipt["depth"] == 0
        assert receipt["parent_run_id"] is None
        binding = research._fetch_one("""SELECT * FROM research_judgment_acp_roots
            WHERE task_id=:task AND call_identity=:identity""",
            {"task": task, "identity": begin["call_identity"]})
        run = agents._fetch_one("SELECT * FROM agent_runs WHERE run_id=:run",
                                {"run": binding["agent_run_id"]})
        assert binding["status"] == "agent_bound"
        assert run["role_id"] == RESEARCH_JUDGMENT_ROLE_ID
        assert binding["runtime_boot_id"] == run["authority_boot_id"]
        assert binding["dsh_run_id"] == run["dsh_run_id"]
        changed = dict(registration, native_root_session_id=str(uuid4()))
        with pytest.raises(AgentConflict, match="conflicts with its durable binding"):
            research.register_acp_judgment_root_agent(task, changed,
                trusted_context=context, runtime_boot_id=headers["x-byq-runtime-boot-id"],
                agent_store=agents)
    finally:
        _close(catalog, research, agents)


def test_bound_judgment_root_enforces_per_stage_mcp_ingress_and_blocks_legacy_admission():
    catalog, research, agents, task, context, headers, plan = _setup("strategy_draft")
    try:
        begin = research.begin_acp_judgment_root(task, _begin_request(task, plan),
            trusted_context=context, runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        native_id = str(uuid4())
        identity = {"root_run_id": begin["root"]["root_run_id"],
            "runtime_boot_id": headers["x-byq-runtime-boot-id"],
            "native_root_session_id": native_id, "native_agent_session_id": native_id,
            "native_parent_session_id": None, "origin": "root", "depth": 0}
        root = begin["root"]
        scope = {"owner": root["owner_principal"], "workspace": root["workspace_id"],
            "actor": root["actor_principal"], "session": root["session_id"],
            "trace": root["trace_id"], "generation": root["dsh_run_id"],
            "boot_id": headers["x-byq-runtime-boot-id"], "root": begin["root"]["root_run_id"]}
        judgment_scope = {**scope, "judgment_task_id": task,
                          "judgment_call_identity": begin["call_identity"]}
        before_bind = {"schema_version": "byq-acp-tool-ingress-observe.v1",
            "mcp_request_id": uuid4().hex, **identity,
            "tool_name": "byq_agent_context", "arguments": {}}
        with pytest.raises(AgentConflict, match="exact bound root"):
            agents.observe_acp_tool_ingress(before_bind, trusted_scope=judgment_scope)
        registration = {"schema_version": "byq-research-judgment-acp-agent-register.v1",
            "call_identity": begin["call_identity"], "root_run_id": begin["root"]["root_run_id"],
            "runtime_boot_id": headers["x-byq-runtime-boot-id"],
            "native_root_session_id": native_id}
        bind = research.register_acp_judgment_root_agent(task, registration,
            trusted_context=context, runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        with pytest.raises(AgentForbidden, match="Product ACP proof"):
            agents.observe_acp_tool_ingress(before_bind, trusted_scope=scope)
        observed = agents.observe_acp_tool_ingress({
            "schema_version": "byq-acp-tool-ingress-observe.v1", "mcp_request_id": uuid4().hex,
            **identity, "tool_name": "byq_agent_context", "arguments": {}},
            trusted_scope=judgment_scope)
        assert observed["agent_run_id"] == bind["agent_run_id"]
        assert len(observed["event_sha256"]) == 64
        before_count = research._fetch_one("""SELECT COUNT(*) AS n
            FROM agent_acp_tool_ingress_observations WHERE root_run_id=:root""",
            {"root": root["root_run_id"]})["n"]
        with pytest.raises(AgentForbidden, match="admitted task evidence"):
            agents.observe_acp_tool_ingress({
                "schema_version": "byq-acp-tool-ingress-observe.v1", "mcp_request_id": uuid4().hex,
                **identity, "tool_name": "byq_research_get",
                "arguments": {"entity_type": "research_task", "entity_id": "task_" + "f" * 32}},
                trusted_scope=judgment_scope)
        assert research._fetch_one("""SELECT COUNT(*) AS n
            FROM agent_acp_tool_ingress_observations WHERE root_run_id=:root""",
            {"root": root["root_run_id"]})["n"] == before_count
        exact_task = agents.observe_acp_tool_ingress({
            "schema_version": "byq-acp-tool-ingress-observe.v1", "mcp_request_id": uuid4().hex,
            **identity, "tool_name": "byq_research_get",
            "arguments": {"entity_type": "research_task", "entity_id": task}},
            trusted_scope=judgment_scope)
        assert exact_task["root_run_id"] == root["root_run_id"]
        with pytest.raises(AgentForbidden, match="stage is not authorized"):
            agents.observe_acp_tool_ingress({
                "schema_version": "byq-acp-tool-ingress-observe.v1", "mcp_request_id": uuid4().hex,
                **identity, "tool_name": "byq_backtest_analysis_get", "arguments": {}},
                trusted_scope=judgment_scope)
        with pytest.raises(InvalidTransition, match="ACP-bound judgment calls"):
            research.admit_research_stage_call(task, {
                "call_identity": begin["call_identity"],
                "attempt_binding": attempt_binding(plan["plan_version"], plan["stage"], plan["iteration"]),
            }, trusted_context=context)
    finally:
        _close(catalog, research, agents)


def test_judgment_ingress_http_to_db_rejects_wrong_task_and_old_boot(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main

    catalog, research, agents, task, context, headers, plan = _setup("strategy_draft")
    try:
        begin = research.begin_acp_judgment_root(task, _begin_request(task, plan),
            trusted_context=context, runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        native = str(uuid4())
        research.register_acp_judgment_root_agent(task, {
            "schema_version": "byq-research-judgment-acp-agent-register.v1",
            "call_identity": begin["call_identity"], "root_run_id": begin["root"]["root_run_id"],
            "runtime_boot_id": headers["x-byq-runtime-boot-id"], "native_root_session_id": native,
        }, trusted_context=context, runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        monkeypatch.setattr(main, "agent_store", agents)
        monkeypatch.setattr(main, "MCP_ACP_JUDGMENT_PROOF_TOKEN", "judgment-http-db-test-proof")
        monkeypatch.setattr(main, "MCP_BACKEND_PROOF_TOKEN", "product-http-db-test-proof")
        client = TestClient(main.app)
        root = begin["root"]["root_run_id"]
        ingress_headers = {**headers, "authorization": "Bearer judgment-http-db-test-proof",
            "x-byq-root-run-id": root, "x-byq-judgment-task-id": task,
            "x-byq-judgment-call-identity": begin["call_identity"],
            "x-byq-dsh-run-id": begin["root"]["dsh_run_id"],
            "x-byq-session-id": begin["root"]["session_id"],
            "x-byq-actor-principal": begin["root"]["actor_principal"]}
        identity = {"root_run_id": root, "runtime_boot_id": headers["x-byq-runtime-boot-id"],
            "native_root_session_id": native, "native_agent_session_id": native,
            "native_parent_session_id": None, "origin": "root", "depth": 0}
        payload = {"schema_version": "byq-acp-tool-ingress-observe.v1",
            "mcp_request_id": uuid4().hex, **identity,
            "tool_name": "byq_research_stage_input_get", "arguments": {"task_id": task}}
        path = "/internal/acp/judgment-tool-ingress-observe"
        wrong_task = client.post(path, headers=ingress_headers,
            json={**payload, "mcp_request_id": uuid4().hex,
                  "arguments": {"task_id": "task_" + "f" * 32}})
        assert wrong_task.status_code == 403, wrong_task.json()
        assert research._fetch_one("""SELECT COUNT(*) AS n FROM agent_acp_tool_ingress_observations
            WHERE root_run_id=:root""", {"root": root})["n"] == 0
        observed = client.post(path, headers=ingress_headers, json=payload)
        assert observed.status_code == 200
        receipt = observed.json()
        assert receipt["root_run_id"] == root and receipt["mcp_request_id"] == payload["mcp_request_id"]
        settled = client.post("/internal/acp/judgment-tool-ingress-settle", headers=ingress_headers,
            json={"schema_version": "byq-acp-tool-ingress-settle.v1",
                  "mcp_request_id": receipt["mcp_request_id"], **identity,
                  "tool_name": payload["tool_name"], "sequence": receipt["sequence"],
                  "event_sha256": receipt["event_sha256"], "outcome": "settled"})
        assert settled.status_code == 200 and settled.json()["outcome"] == "settled"
        assert research._fetch_one("""SELECT COUNT(*) AS n FROM agent_acp_tool_ingress_observations
            WHERE root_run_id=:root""", {"root": root})["n"] == 1
        agents.rotate_runtime_authority(uuid4().hex)
        late = client.post(path, headers=ingress_headers,
            json={**payload, "mcp_request_id": uuid4().hex})
        assert late.status_code == 401
    finally:
        _close(catalog, research, agents)


def test_legacy_admitted_call_is_never_automatically_adopted_by_acp():
    catalog, research, agents, task, context, headers, plan = _setup("iteration_comparison")
    try:
        request = _begin_request(task, plan)
        research.admit_research_stage_call(task, {
            "call_identity": request["call_identity"],
            "attempt_binding": request["attempt_binding"],
        }, trusted_context=context)
        with pytest.raises(AgentConflict, match="unknown outcome and cannot be adopted"):
            research.begin_acp_judgment_root(task, request, trusted_context=context,
                runtime_boot_id=headers["x-byq-runtime-boot-id"], agent_store=agents)
        assert research._fetch_one("""SELECT COUNT(*) AS n FROM research_judgment_acp_roots
            WHERE task_id=:task""", {"task": task})["n"] == 0
    finally:
        _close(catalog, research, agents)


@pytest.mark.parametrize("route", ["begin", "register", "result", "settle", "status"])
def test_acp_judgment_routes_reject_wrong_bearer_before_storage(route, monkeypatch):
    client = _route_client(monkeypatch)
    path, body, headers = _route_inputs(route)
    headers["Authorization"] = "Bearer wrong"
    response = client.post(path, headers=headers, json=body)
    assert response.status_code == 401
    assert "service credential" in response.json()["detail"]


@pytest.mark.parametrize("route", ["begin", "register", "result", "settle", "status"])
@pytest.mark.parametrize("missing_header", [
    "x-byq-owner-principal", "x-byq-workspace-id", "x-byq-runtime-boot-id",
])
def test_acp_judgment_routes_require_exact_trusted_scope_headers(route, missing_header, monkeypatch):
    client = _route_client(monkeypatch)
    path, body, headers = _route_inputs(route)
    headers.pop(missing_header)
    response = client.post(path, headers=headers, json=body)
    assert response.status_code == 401
    assert "owner, Workspace and runtime boot" in response.json()["detail"]


@pytest.mark.parametrize("route", ["begin", "register", "result", "settle", "status"])
def test_acp_judgment_routes_reject_open_body_before_storage(route, monkeypatch):
    client = _route_client(monkeypatch)
    path, body, headers = _route_inputs(route)
    body["unexpected"] = "not accepted"
    response = client.post(path, headers=headers, json=body)
    assert response.status_code == 422
    assert "exact ACP judgment" in response.json()["detail"]


@pytest.mark.parametrize("route", ["begin", "register", "result", "settle", "status"])
def test_acp_judgment_routes_validate_identity_fields_before_storage(route, monkeypatch):
    client = _route_client(monkeypatch)
    path, body, headers = _route_inputs(route)
    if route == "begin":
        body["call_identity"] = "not-a-call-identity"
    elif route == "register":
        body["native_root_session_id"] = "not-a-native-session-id"
    elif route == "result":
        body["agent_run_id"] = "not-an-AgentRun-id"
    else:
        body["call_identity"] = "not-a-call-identity"
    response = client.post(path, headers=headers, json=body)
    assert response.status_code == 422
    assert response.json()["detail"]


def test_acp_judgment_cancel_intent_route_is_gateway_only_and_owner_scoped(monkeypatch):
    client = _route_client(monkeypatch)
    path, body, headers = _route_inputs("cancel_intent")

    wrong_service = client.post(path, headers={**headers, "Authorization": "Bearer wrong"}, json=body)
    assert wrong_service.status_code == 401
    assert "Gateway Backend service credential" in wrong_service.json()["detail"]

    missing_scope = {**headers}
    missing_scope.pop("x-byq-workspace-id")
    response = client.post(path, headers=missing_scope, json=body)
    assert response.status_code == 401

    wrong_actor = {**headers, "x-byq-actor-principal": "another-user"}
    response = client.post(path, headers=wrong_actor, json=body)
    assert response.status_code == 403

    response = client.post(path, headers=headers, json={**body, "call_identity": "untrusted"})
    assert response.status_code == 422
    assert "exact ACP judgment cancel-intent request" in response.json()["detail"]


def test_acp_judgment_cancel_intent_route_requires_gateway_service_credential(monkeypatch):
    from app import main

    client = _route_client(monkeypatch)
    monkeypatch.setattr(main, "GATEWAY_SERVICE_TOKEN", None)
    path, body, headers = _route_inputs("cancel_intent")
    response = client.post(path, headers=headers, json=body)
    assert response.status_code == 503
    assert "Gateway Backend service credential is unavailable" in response.json()["detail"]

    monkeypatch.setattr(main, "GATEWAY_SERVICE_TOKEN", "short")
    response = client.post(path, headers={**headers, "Authorization": "Bearer short"}, json=body)
    assert response.status_code == 503
    assert "Gateway Backend service credential is too short" in response.json()["detail"]


@pytest.mark.parametrize("operation", ["observe", "abort", "settle"])
def test_judgment_ingress_routes_require_distinct_proof_and_exact_task_call(operation, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main

    seen = []

    class CaptureStore:
        def observe_acp_tool_ingress(self, payload, *, trusted_scope):
            seen.append(("observe", trusted_scope))
            return {"status": "observed"}

        def abort_acp_tool_ingress_before_dispatch(self, payload, *, trusted_scope):
            seen.append(("abort", trusted_scope))
            return {"status": "aborted"}

        def settle_acp_tool_ingress(self, payload, *, trusted_scope):
            seen.append(("settle", trusted_scope))
            return {"status": "settled"}

    monkeypatch.setattr(main, "agent_store", CaptureStore())
    monkeypatch.setattr(main, "MCP_ACP_JUDGMENT_PROOF_TOKEN", "judgment-proof-test-only")
    monkeypatch.setattr(main, "MCP_BACKEND_PROOF_TOKEN", "product-proof-test-only")
    class WorkspaceStub:
        def resolve_context(self, owner, workspace):
            assert owner == "judgment-route-owner" and workspace == "workspace-judgment-route"
            return {"workspace_id": workspace}
    monkeypatch.setattr(main, "workspace_tenancy_store", WorkspaceStub())
    client = TestClient(main.app)
    task = "task_" + "a" * 32
    call = "byq-judgment-" + "b" * 32
    authority_store = AgentResearchStore()
    try:
        boot = authority_store.rotate_runtime_authority(uuid4().hex)["boot_id"]
    finally:
        authority_store.close()
    root = "c" * 32
    session = "byqjdg-test-session"
    headers = {"authorization": "Bearer judgment-proof-test-only",
               "x-byq-owner-principal": "judgment-route-owner",
               "x-byq-workspace-id": "workspace-judgment-route",
               "x-byq-actor-principal": "byq-product-agent-" + session,
               "x-byq-session-id": session, "x-byq-trace-id": "trace-judgment-route",
               "x-byq-dsh-run-id": "byqjudg-" + "e" * 32,
               "x-byq-root-run-id": root, "x-byq-runtime-boot-id": boot,
               "x-byq-judgment-task-id": task, "x-byq-judgment-call-identity": call}
    schema = {"observe": "byq-acp-tool-ingress-observe.v1",
              "abort": "byq-acp-tool-ingress-abort.v1",
              "settle": "byq-acp-tool-ingress-settle.v1"}[operation]
    body = {"schema_version": schema, "root_run_id": root, "runtime_boot_id": boot}
    path = "/internal/acp/judgment-tool-ingress-" + operation
    assert client.post(path, headers={**headers, "authorization": "Bearer product-proof-test-only"},
                       json=body).status_code == 401
    assert client.post(path, headers={key: value for key, value in headers.items()
                                      if key != "x-byq-judgment-call-identity"},
                       json=body).status_code == 422
    assert seen == []
    response = client.post(path, headers=headers, json=body)
    assert response.status_code == 200
    assert seen == [(operation, {"owner": "judgment-route-owner",
                                 "workspace": "workspace-judgment-route",
                                 "actor": "byq-product-agent-" + session,
                                 "session": session, "trace": "trace-judgment-route",
                                 "generation": "byqjudg-" + "e" * 32,
                                 "boot_id": boot, "root": root,
                                 "judgment_task_id": task,
                                 "judgment_call_identity": call})]
    assert client.post("/internal/acp/tool-ingress-" + operation,
                       headers=headers, json=body).status_code == 401


def _insert_judgment_root(research, *, task, context, headers, plan, call_identity, status):
    research._execute(
        """INSERT INTO research_judgment_stage_calls
        (task_id, call_identity, plan_version, stage, call_index, status, admitted_at)
        VALUES (:task, :identity, :plan, :stage, 1, 'admitted', now())""",
        {"task": task, "identity": call_identity, "plan": plan["plan_version"],
         "stage": plan["stage"]})
    research._execute(
        """INSERT INTO research_judgment_acp_roots
        (task_id, call_identity, root_run_id, owner_principal, workspace_id, actor_principal,
         session_id, trace_id, runtime_boot_id, authority_epoch, dsh_run_id, plan_version,
         stage, call_index, iteration, status, native_root_session_id, agent_run_id,
         begin_receipt_json, created_at, updated_at)
        VALUES (:task,:identity,:root,:owner,:workspace,:actor,:session,:trace,:boot,1,
         :dsh,:plan,:stage,1,1,:status,:native,:run,'{}',now(),now())""",
        {"task": task, "identity": call_identity, "root": "a" * 32,
         "owner": context["owner_principal"], "workspace": context["workspace_id"],
         "actor": f"byq-product-agent-{headers['x-byq-session-id']}",
         "session": headers["x-byq-session-id"], "trace": headers["x-byq-trace-id"],
         "boot": headers["x-byq-runtime-boot-id"], "dsh": "byqjudg-" + "b" * 32,
         "plan": plan["plan_version"], "stage": plan["stage"], "status": status,
         "native": "00000000-0000-4000-8000-000000000001" if status == "agent_bound" else None,
         "run": ("agent_run_" + "c" * 32) if status == "agent_bound" else None})


def test_judgment_stage_claim_is_leased_and_unknown_safe():
    catalog, research, agents, task, context, headers, plan = _setup()
    try:
        request = _begin_request(task, plan)
        call_identity = request["call_identity"]

        def claim(owner: str, identity: str = call_identity) -> dict:
            return research.claim_judgment_stage_call(
                task, identity,
                {"schema_version": "byq-research-judgment-stage-claim.v1",
                 "claim_owner": owner, "lease_seconds": 300},
                trusted_context=context)

        # Pre-begin: the claim is keyed on the current plan attempt and persists once.
        first = claim("worker-a")
        assert first["claimed"] is True and first["reconcile_only"] is False
        assert first["claim_attempt"] == 1
        # a live lease cannot be stolen by a different owner
        assert claim("worker-b") == {"claimed": False, "reason": "lease_held"}
        # the same owner may renew (same attempt, persisted once, attempt counter bumped)
        renewed = claim("worker-a")
        assert renewed["claimed"] is True and renewed["claim_attempt"] == 2
        # a claim for a stale/forged attempt identity is refused
        with pytest.raises(InvalidTransition, match="current plan attempt"):
            claim("worker-a", "byq-judgment-" + "0" * 32)

        # ANY existing root (even root_created) is NOT affirmative no-dispatch
        # evidence -> read-only reconcile only, never re-run.
        _insert_judgment_root(research, task=task, context=context, headers=headers,
                              plan=plan, call_identity=call_identity, status="root_created")
        created = claim("worker-a")
        assert created == {"claimed": False, "reconcile_only": True,
                           "reason": "root_exists", "root_status": "root_created"}
        research._execute(
            "UPDATE research_judgment_acp_roots SET status='agent_bound' "
            "WHERE task_id=:t AND call_identity=:c", {"t": task, "c": call_identity})
        bound = claim("worker-a")
        assert bound["reconcile_only"] is True and bound["root_status"] == "agent_bound"
    finally:
        _close(research, agents, catalog)


def test_judgment_stage_claim_lease_expiry_is_reclaimable_but_never_after_a_root():
    catalog, research, agents, task, context, headers, plan = _setup()
    try:
        request = _begin_request(task, plan)
        call_identity = request["call_identity"]

        def claim(owner: str) -> dict:
            return research.claim_judgment_stage_call(
                task, call_identity,
                {"schema_version": "byq-research-judgment-stage-claim.v1",
                 "claim_owner": owner, "lease_seconds": 1},
                trusted_context=context)

        assert claim("worker-a")["claimed"] is True
        time.sleep(2)  # the lease expires
        # a free/expired lease with NO root is reclaimable by another owner
        assert claim("worker-b")["claimed"] is True
        # a lost begin response (root_created) after an expired lease -> reconcile only
        _insert_judgment_root(research, task=task, context=context, headers=headers,
                              plan=plan, call_identity=call_identity, status="root_created")
        late = claim("worker-c")
        assert late["claimed"] is False and late["reconcile_only"] is True
        assert late["reason"] == "root_exists"
    finally:
        _close(research, agents, catalog)


def test_dispatch_intent_requires_the_live_lease_owner():
    catalog, research, agents, task, context, headers, plan = _setup()
    try:
        request = _begin_request(task, plan)
        call_identity = request["call_identity"]

        def payload(owner: str, lease: int = 300) -> dict:
            return {"schema_version": "byq-research-judgment-stage-claim.v1",
                    "claim_owner": owner, "lease_seconds": lease}

        research.claim_judgment_stage_call(task, call_identity, payload("worker-a"),
                                           trusted_context=context)
        # a different owner cannot persist a dispatch-intent
        denied = research.record_judgment_dispatch_intent(
            task, call_identity, payload("worker-b"), trusted_context=context)
        assert denied == {"intent": False, "reason": "lease_not_held_or_intent_exists"}
        # the live owner can persist it once
        granted = research.record_judgment_dispatch_intent(
            task, call_identity, payload("worker-a"), trusted_context=context)
        assert granted["intent"] is True and granted["claim_owner"] == "worker-a"
        # the intent is ONCE: a repeated same-owner intent is refused
        again = research.record_judgment_dispatch_intent(
            task, call_identity, payload("worker-a"), trusted_context=context)
        assert again == {"intent": False, "reason": "lease_not_held_or_intent_exists"}
        # an existing intent makes a fresh claim reconcile-only, never re-run
        reclaimed = research.claim_judgment_stage_call(
            task, call_identity, payload("worker-a"), trusted_context=context)
        assert reclaimed["claimed"] is False and reclaimed["reconcile_only"] is True
        assert reclaimed["reason"] == "dispatch_intent_exists"
    finally:
        _close(research, agents, catalog)


def test_list_judgment_turn_tasks_selects_the_judgment_stage():
    catalog, research, agents, task, context, headers, plan = _setup()
    try:
        rows = research.list_judgment_turn_tasks()
        match = [row for row in rows if row["task_id"] == task]
        assert len(match) == 1
        assert match[0]["stage"] == "strategy_draft"
        assert match[0]["plan_version"] == plan["plan_version"]
        assert match[0]["owner_principal"] == context["owner_principal"]
    finally:
        _close(research, agents, catalog)


def test_dispatch_intent_is_refused_after_the_lease_expires():
    catalog, research, agents, task, context, headers, plan = _setup()
    try:
        request = _begin_request(task, plan)
        call_identity = request["call_identity"]

        def payload(owner: str, lease: int = 1) -> dict:
            return {"schema_version": "byq-research-judgment-stage-claim.v1",
                    "claim_owner": owner, "lease_seconds": lease}

        assert research.claim_judgment_stage_call(
            task, call_identity, payload("worker-a"), trusted_context=context)["claimed"] is True
        time.sleep(2)  # the lease expires
        # the expired same-owner intent is refused (claim_lease_until > now() fails)
        expired = research.record_judgment_dispatch_intent(
            task, call_identity, payload("worker-a"), trusted_context=context)
        assert expired == {"intent": False, "reason": "lease_not_held_or_intent_exists"}
        # a fresh owner can re-claim and then persist the intent once
        assert research.claim_judgment_stage_call(
            task, call_identity, payload("worker-b"), trusted_context=context)["claimed"] is True
        assert research.record_judgment_dispatch_intent(
            task, call_identity, payload("worker-b"), trusted_context=context)["intent"] is True
    finally:
        _close(research, agents, catalog)
