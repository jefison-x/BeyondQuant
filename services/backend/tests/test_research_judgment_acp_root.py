"""ADR-0097 Backend root admission and private AgentRun binding checks."""
from __future__ import annotations

import hashlib
import os
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
    else:
        path = f"/internal/research-judgment/{task_id}/acp-root/status"
        body = {"schema_version": "byq-research-judgment-acp-status.v1",
                "call_identity": "byq-judgment-" + "c" * 32,
                "attempt_binding": "1:strategy_draft:1"}
    headers = {"Authorization": "Bearer test-runtime-authority-token",
        "x-byq-owner-principal": "route-test-user", "x-byq-workspace-id": "workspace-route-test",
        "x-byq-runtime-boot-id": "d" * 32}
    return path, body, headers


def _route_client(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main

    class NeverStore:
        def __getattr__(self, name):
            raise AssertionError(f"route reached Backend storage method {name}")

    monkeypatch.setattr(main, "RUNTIME_AUTHORITY_TOKEN", "test-runtime-authority-token")
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
        assert replay == first
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
        with pytest.raises(AgentConflict, match="completed result and bound Agent"):
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
        with pytest.raises(AgentConflict, match="completed result and bound Agent"):
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


@pytest.mark.parametrize("route", ["begin", "register", "result", "status"])
def test_acp_judgment_routes_reject_wrong_bearer_before_storage(route, monkeypatch):
    client = _route_client(monkeypatch)
    path, body, headers = _route_inputs(route)
    headers["Authorization"] = "Bearer wrong"
    response = client.post(path, headers=headers, json=body)
    assert response.status_code == 401
    assert "service credential" in response.json()["detail"]


@pytest.mark.parametrize("route", ["begin", "register", "result", "status"])
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


@pytest.mark.parametrize("route", ["begin", "register", "result", "status"])
def test_acp_judgment_routes_reject_open_body_before_storage(route, monkeypatch):
    client = _route_client(monkeypatch)
    path, body, headers = _route_inputs(route)
    body["unexpected"] = "not accepted"
    response = client.post(path, headers=headers, json=body)
    assert response.status_code == 422
    assert "exact ACP judgment" in response.json()["detail"]


@pytest.mark.parametrize("route", ["begin", "register", "result", "status"])
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
