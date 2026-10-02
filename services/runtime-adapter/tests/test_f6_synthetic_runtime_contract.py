"""Offline acceptance contracts for the assigned current-head F6 CI driver."""
from __future__ import annotations

import ast
import copy
import json
import os
import re
import sys
import time
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.research_request_gate import parse_response_usage
from tests.f6_synthetic_runtime import (
    AGENT_RUN_PATTERN,
    AUDIT_PATTERN,
    BG_SEQUENCE,
    FG1_SEQUENCE,
    FG2_SEQUENCE,
    F6FixtureRejected,
    _authorize,
    _normalize_tool_result,
    _sse_completion,
    _verify_agent_audit_result,
    _verify_result,
    _install_f6_provider_routes,
    _sequence_for,
    next_action,
    validate_environment,
)


class DriverContractRejected(AssertionError):
    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


def _driver_functions():
    path = os.environ.get("BYQ_F6_DRIVER_PATH")
    if not path:
        pytest.skip("driver-specific audit contract is run by check_f6_chain")
    source = Path(path).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=path)
    wanted = {"_assert_structured_agent_audit", "_assert_validated_signal_artifact",
              "_read_structured_agent_audit", "_validate_settlement_identity"}
    nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
             and node.name in wanted]
    if {node.name for node in nodes} != wanted:
        raise AssertionError("current F6 driver audit contract helpers are missing")

    def require(condition: object, category: str) -> None:
        if not condition:
            raise DriverContractRejected(category)

    namespace = {
        "re": re, "require": require,
        "json": json, "os": os, "subprocess": types.SimpleNamespace(), "time": time,
        "state": {"checks": {}},
        "PROJECT_PATTERN": re.compile(r"byq-ci-stack-[A-Za-z0-9][A-Za-z0-9_-]{0,80}\Z"),
        "RUNTIME_ROOT_PATTERN": re.compile(r"[0-9a-f]{32}\Z"),
        "RESERVATION_PATTERN": re.compile(r"continuation_[0-9a-f]{32}\Z"),
        "SESSION_PATTERN": re.compile(r"byq-session-[0-9a-f]{32}\Z"),
        "AGENT_RUN_PATTERN": AGENT_RUN_PATTERN,
        "AUDIT_PATTERN": AUDIT_PATTERN,
        "SHA256_PATTERN": re.compile(r"[0-9a-f]{64}\Z"),
        "EvidenceError": DriverContractRejected,
    }
    module = ast.Module(body=nodes, type_ignores=[])
    exec(compile(module, path, "exec"), namespace)
    return namespace


def _audit_fixture():
    root = "a" * 32
    runtime_session = "byq-session-" + "b" * 32
    trace = "byq-trace-" + "c" * 32
    task_id = "task_" + "d" * 32
    backtest_task_id = "backtesttask_" + "e" * 32
    run_id = "agent_run_" + "f" * 32
    digest = "1" * 64
    reservation_id = "continuation_" + "2" * 32
    event_key = "ready-v1:" + "3" * 64
    expected_events = [
        ("byq_research_get", "authorized", "research_task", task_id),
        ("byq_research_get", "success", "research_task", task_id),
        ("byq_backtest_task_get", "authorized", "backtest_task", backtest_task_id),
        ("byq_backtest_task_get", "success", "backtest_task", backtest_task_id),
    ]
    audit_events = [{
        "audit_id": "agent_audit_" + str(index) * 32,
        "run_id": run_id,
        "owner_principal": "f6-chain-user",
        "actor_principal": "byq-product-agent-" + runtime_session,
        "action": action,
        "outcome": outcome,
        "resource_type": resource_type,
        "resource_id": resource_id,
    } for index, (action, outcome, resource_type, resource_id) in enumerate(expected_events, start=1)]
    binding = {
        "audit_id": "agent_audit_" + "0" * 32,
        "run_id": run_id,
        "owner_principal": "f6-chain-user",
        "actor_principal": "byq-product-agent-" + runtime_session,
        "action": "runtime_turn_binding", "outcome": "active",
        "resource_type": "runtime_turn", "resource_id": root,
    }
    terminal_binding = {
        "audit_id": "agent_audit_" + "9" * 32,
        "run_id": run_id,
        "owner_principal": "f6-chain-user",
        "actor_principal": "byq-product-agent-" + runtime_session,
        "action": "runtime_turn_binding", "outcome": "completed",
        "resource_type": "runtime_turn", "resource_id": root,
    }
    document = {
        "schema_version": "f6-agent-run-audit.v1", "stage": "background",
        "task": {"task_id": task_id, "owner_principal": "f6-chain-user",
                 "workspace_id": "workspace_" + "4" * 32,
                 "conversation_id": "conversation_" + "5" * 32, "trace_id": trace,
                 "task_status": "running"},
        "runtime_session_id": runtime_session,
        "runtime_root": {"root_run_id": root, "owner_principal": "f6-chain-user",
                         "workspace_id": "workspace_" + "4" * 32,
                         "session_id": runtime_session, "trace_id": trace,
                         "status": "completed", "authority_status": "closed",
                         "terminal_sequence": 4, "terminal_event_sha256": digest},
        "agent_run": {"run_id": run_id, "owner_principal": "f6-chain-user",
                      "actor_principal": "byq-product-agent-" + runtime_session,
                      "role_id": "quant_orchestrator", "role_version": "2.5.0",
                      "session_id": runtime_session, "trace_id": trace,
                      "root_run_id": root, "status": "completed", "authority_status": "closed"},
        "events": [binding, *audit_events, terminal_binding],
        "settlement": {"reservation_id": reservation_id, "grant_version": 1, "run_id": root,
                       "status": "settled", "outcome": "completed", "event_key": event_key,
                       "dispatch_attempts": 1, "settlement_sha256": digest},
    }
    settlement = {"reservation_id": reservation_id, "run_id": root,
                  "status": "settled", "outcome": "completed", "event_key": event_key,
                  "dispatch_attempts": 1, "settlement_sha256": digest,
                  "grant_version": 1}
    return document, settlement, expected_events


def _prompt_for(stage: str) -> str:
    task_id = "task_" + "1" * 32
    version_id = "artifact_" + "2" * 32
    approval_id = "artifact_" + "3" * 32
    pool_snapshot_id = "stock_pool_snapshot_" + "4" * 64
    job_suffix = "5" * 32
    backtest_task_id = "backtesttask_" + job_suffix
    signal_job_id = "signaljob_" + job_suffix
    signal_snapshot_id = "artifact_" + "6" * 32
    if stage == "fg1":
        strategy = {"strategy_id": "F6SyntheticSignal", "category": "momentum",
                    "data_requirements": {}}
        return "\n".join((
            "F6-CI:FG1", "owner_principal=f6-chain-user",
            "conversation_id=conversation_" + "7" * 32,
            "session_trace_id=byq-trace-" + "8" * 32,
            "task_title=F6 synthetic current-chain acceptance",
            "task_objective=Validate the scripted current F6 MCP contract.",
            "task_create_idempotency_key=f6-task-key",
            "strategy_validate_idempotency_key=f6-draft-key",
            "strategy_version_idempotency_key=f6-version-key",
            "strategy_json=" + json.dumps(strategy, sort_keys=True, separators=(",", ":")),
        ))
    if stage == "fg2":
        return "\n".join((
            "F6-CI:FG2", f"task_id={task_id}",
            f"strategy_version_artifact_id={version_id}", f"approval_artifact_id={approval_id}",
            f"stock_pool_snapshot_id={pool_snapshot_id}", "start_date=2026-03-12",
            "end_date=2026-03-30", "parameters={}",
            'execution={"initial_capital":100000,"commission_rate":0.0003}',
            "order_quantity=100", "backtest_task_idempotency_key=f6-backtest-key",
        ))
    ready = {"identity": signal_job_id, "kind": "signal_producer_jobs", "status": "completed",
             "result_artifact_id": signal_snapshot_id}
    return "\n".join((
        f"BYQ trusted read-only task-ready follow-up for exact task {task_id}",
        f"Exact BacktestTask ID: {backtest_task_id}",
        "Ready signal: " + json.dumps(ready, sort_keys=True, separators=(",", ":")),
    ))


def _provider_tools():
    names = sorted(set(FG1_SEQUENCE + FG2_SEQUENCE + BG_SEQUENCE))
    return [{"type": "function", "function": {"name": "mcp__byq__" + name}}
            for name in names]


def _mcp_payload(stage: str, name: str, arguments: dict, prompt: str, index: int) -> dict:
    ids = {
        "task_id": "task_" + "1" * 32,
        "draft_id": "artifact_" + "9" * 32,
        "version_id": "artifact_" + "2" * 32,
        "approval_id": "artifact_" + "3" * 32,
        "pool_snapshot_id": "stock_pool_snapshot_" + "4" * 64,
        "signal_job_id": "signaljob_" + "5" * 32,
        "backtest_task_id": "backtesttask_" + "5" * 32,
        "signal_snapshot_id": "artifact_" + "6" * 32,
        "run_id": {"fg1": "agent_run_" + "a" * 32,
                   "fg2": "agent_run_" + "b" * 32,
                   "background": "agent_run_" + "c" * 32}[stage],
        "runtime_session_id": "byq-session-" + "d" * 32,
    }
    if name == "byq_agent_run_start":
        return {"run": {"run_id": ids["run_id"], "status": "active"}}
    if name == "byq_agent_authorize":
        return {"authorization": {"authorized": True, "decision": "allowed",
                                   "run_id": arguments["run_id"], "action": arguments["action"]}}
    if name == "byq_agent_audit":
        return {"audit": {"audit_id": "agent_audit_" + f"{index + 1:032x}",
                           "run_id": arguments["run_id"], "owner_principal": "f6-chain-user",
                           "actor_principal": "byq-product-agent-" + ids["runtime_session_id"],
                           "action": arguments["action"], "outcome": arguments["outcome"],
                           "resource_type": arguments.get("resource_type"),
                           "resource_id": arguments.get("resource_id")}}
    if name == "byq_research_task_create":
        return {"task_id": ids["task_id"], "owner_principal": "f6-chain-user",
                "conversation_id": re.search(r"(?m)^conversation_id=(.+)$", prompt).group(1),
                "trace_id": re.search(r"(?m)^session_trace_id=(.+)$", prompt).group(1),
                "status": "planned"}
    if name == "byq_strategy_validate":
        return {"artifact": {"artifact_id": ids["draft_id"], "kind": "strategy_draft",
                              "status": "validated", "task_id": ids["task_id"]}}
    if name == "byq_strategy_version_create":
        return {"artifact": {"artifact_id": ids["version_id"], "kind": "strategy_version",
                              "status": "validated", "task_id": ids["task_id"],
                              "lineage": [{"kind": "artifact", "id": ids["draft_id"]}]}}
    if name == "byq_backtest_task_create":
        return {"backtest_task_id": ids["backtest_task_id"],
                "signal_producer_job_id": ids["signal_job_id"],
                "references": {"research_task_id": ids["task_id"],
                               "strategy_version_artifact_id": ids["version_id"],
                               "approval_artifact_id": ids["approval_id"],
                               "stock_pool_snapshot_id": ids["pool_snapshot_id"],
                               "signal_producer_job_id": ids["signal_job_id"]}}
    if name == "byq_research_get":
        # requestResearch spreads the raw Backend ResearchTask after its own
        # status key, so the domain status occupies the MCP envelope field.
        return {"task_id": ids["task_id"], "status": "running",
                "owner_principal": "f6-chain-user"}
    if name == "byq_backtest_task_get":
        return {"task": {"backtest_task_id": ids["backtest_task_id"],
                          "references": {"research_task_id": ids["task_id"],
                                         "signal_producer_job_id": ids["signal_job_id"],
                                         "signal_snapshot_artifact_id": ids["signal_snapshot_id"]}}}
    raise AssertionError("unexpected scripted MCP action")


def _append_provider_tool_result(messages: list, stage: str, prompt: str,
                                 action: tuple[str, dict], step: int,
                                 result_override: dict | None = None) -> None:
    body = {"messages": messages, "tools": _provider_tools()}
    response = _sse_completion(body, action)
    chunks = [json.loads(line[6:]) for line in response.decode().splitlines()
              if line.startswith("data: ") and line != "data: [DONE]"]
    assert len(chunks) == 2 and all("usage" not in chunk for chunk in chunks)
    tool_call = chunks[0]["choices"][0]["delta"]["tool_calls"][0]
    name = action[0].removeprefix("mcp__byq__")
    call_id = tool_call["id"]
    messages.append({"role": "assistant", "tool_calls": [tool_call]})
    payload = result_override if result_override is not None else _mcp_payload(
        stage, name, action[1], prompt, step)
    wrapped = {"service": "beyondquant-mcp", "status": "ok", **payload}
    messages.append({"role": "tool", "tool_call_id": call_id,
                     "content": [{"type": "text", "text": json.dumps(wrapped, sort_keys=True)}]})


def _drive_provider_turn(stage: str) -> None:
    prompt = _prompt_for(stage)
    messages = [{"role": "user", "content": prompt}]
    sequence = _sequence_for(stage)
    for step in range(len(sequence) + 1):
        body = {"messages": messages, "tools": _provider_tools()}
        action = next_action(body)
        if step == len(sequence):
            assert action is None
            chunks = [json.loads(line[6:]) for line in _sse_completion(body, None).decode().splitlines()
                      if line.startswith("data: ") and line != "data: [DONE]"]
            assert chunks[0]["choices"][0]["delta"]["content"]
            assert all("usage" not in chunk for chunk in chunks)
            return
        assert action is not None
        assert action[0] == "mcp__byq__" + sequence[step]
        _append_provider_tool_result(messages, stage, prompt, action, step)
    raise AssertionError("provider sequence did not close")


def test_synthetic_runtime_requires_all_three_ci_only_guard_values():
    expected_project = "byq-ci-stack-f6-test"
    assert validate_environment({
        "COMPOSE_PROJECT_NAME": expected_project,
        "BYQ_F6_CI_PROJECT": expected_project,
        "BYQ_F6_SYNTHETIC_RUNTIME": "1",
        "DEEPSEEK_API_KEY": "f6-synthetic-only",
    }) == expected_project
    for invalid in (
        {"COMPOSE_PROJECT_NAME": expected_project, "BYQ_F6_CI_PROJECT": expected_project,
         "BYQ_F6_SYNTHETIC_RUNTIME": "1"},
        {"COMPOSE_PROJECT_NAME": expected_project, "BYQ_F6_CI_PROJECT": "other-project",
         "BYQ_F6_SYNTHETIC_RUNTIME": "1", "DEEPSEEK_API_KEY": "f6-synthetic-only"},
        {"COMPOSE_PROJECT_NAME": "production", "BYQ_F6_CI_PROJECT": "production",
         "BYQ_F6_SYNTHETIC_RUNTIME": "1", "DEEPSEEK_API_KEY": "f6-synthetic-only"},
    ):
        with pytest.raises(F6FixtureRejected):
            validate_environment(invalid)


def test_fixed_provider_tool_sequences_are_exact_two_foreground_and_two_read_only_bg_calls():
    assert len(FG1_SEQUENCE) == 10
    assert len(FG2_SEQUENCE) == 4
    assert BG_SEQUENCE == (
        "byq_agent_run_start", "byq_agent_authorize", "byq_research_get", "byq_agent_audit",
        "byq_agent_authorize", "byq_backtest_task_get", "byq_agent_audit",
    )
    assert not any(name.endswith(("_create", "_execute", "_transition")) for name in BG_SEQUENCE)


@pytest.mark.parametrize("stage", ["fg1", "fg2", "background"])
def test_provider_next_action_accepts_full_stage_with_current_mcp_result_shapes(stage):
    _drive_provider_turn(stage)


@pytest.mark.parametrize("malformation", ["wrong_action", "wrong_run", "unknown_result"])
def test_provider_rejects_wrong_authorization_identity_and_unknown_result(malformation):
    prompt = _prompt_for("fg1")
    messages = [{"role": "user", "content": prompt}]
    tools = _provider_tools()
    first = next_action({"messages": messages, "tools": tools})
    assert first[0] == "mcp__byq__byq_agent_run_start"
    if malformation == "unknown_result":
        _append_provider_tool_result(messages, "fg1", prompt, first, 0,
                                     result_override={"unexpected": "unknown"})
        with pytest.raises(F6FixtureRejected):
            next_action({"messages": messages, "tools": tools})
        return
    _append_provider_tool_result(messages, "fg1", prompt, first, 0)
    authorization = next_action({"messages": messages, "tools": tools})
    assert authorization[0] == "mcp__byq__byq_agent_authorize"
    run_id = "agent_run_" + "a" * 32
    approved_action = "byq_research_task_create"
    if malformation == "wrong_action":
        approved_action = "byq_backtest_task_get"
    if malformation == "wrong_run":
        run_id = "agent_run_" + "b" * 32
    bad_result = {"authorization": {"authorized": True, "decision": "allowed",
                                    "run_id": run_id, "action": approved_action}}
    _append_provider_tool_result(messages, "fg1", prompt, authorization, 1,
                                 result_override=bad_result)
    with pytest.raises(F6FixtureRejected):
        next_action({"messages": messages, "tools": tools})


def test_research_task_mcp_status_collision_is_normalized_only_for_current_shapes():
    task_id = "task_" + "a" * 32
    created = _normalize_tool_result("byq_research_task_create", {
        "service": "beyondquant-mcp", "status": "planned", "task_id": task_id,
        "owner_principal": "f6-chain-user", "conversation_id": "conversation_" + "b" * 32,
        "trace_id": "byq-trace-" + "c" * 32,
    })
    assert created["status"] == "ok" and created["task"]["status"] == "planned"
    read = _normalize_tool_result("byq_research_get", {
        "service": "beyondquant-mcp", "status": "running", "task_id": task_id,
        "owner_principal": "f6-chain-user",
    })
    assert read["status"] == "ok" and read["task"] == {
        "task_id": task_id, "owner_principal": "f6-chain-user", "status": "running"}
    nested = _normalize_tool_result("byq_research_get", {
        "service": "beyondquant-mcp", "status": "ok",
        "task": {"task_id": task_id, "status": "planned"},
    })
    assert nested["task"]["status"] == "planned"
    for name, result in (
        ("byq_research_task_create", {"service": "beyondquant-mcp", "status": "error",
                                       "task_id": task_id}),
        ("byq_research_task_create", {"service": "beyondquant-mcp", "status": "completed",
                                       "task_id": task_id}),
        ("byq_research_get", {"service": "beyondquant-mcp", "status": "completed",
                               "task_id": task_id}),
        ("byq_research_get", {"service": "beyondquant-mcp", "status": "ok",
                               "task": {"task_id": task_id, "status": "failed"}}),
    ):
        with pytest.raises(F6FixtureRejected):
            _normalize_tool_result(name, result)


def test_provider_audit_result_requires_exact_run_owner_action_and_resource():
    run_id = "agent_run_" + "a" * 32
    task_id = "task_" + "b" * 32
    args = {"run_id": run_id, "action": "byq_research_get", "outcome": "success",
            "resource_type": "research_task", "resource_id": task_id}
    result = {"audit": {
        "audit_id": "agent_audit_" + "c" * 32, "run_id": run_id,
        "owner_principal": "f6-chain-user", "actor_principal": "byq-product-agent-byq-session-" + "d" * 32,
        "action": args["action"], "outcome": args["outcome"],
        "resource_type": args["resource_type"], "resource_id": args["resource_id"],
    }}
    records = [{"name": "byq_agent_run_start", "result": {
        "run": {"run_id": run_id, "status": "active"}}}]
    valid_row = {"arguments": args, "result": result}
    _verify_agent_audit_result(valid_row, records)
    assert AUDIT_PATTERN.fullmatch(result["audit"]["audit_id"])

    for mutate in (
        lambda row: row["result"]["audit"].update(run_id="agent_run_" + "e" * 32),
        lambda row: row["result"]["audit"].update(owner_principal="another-user"),
        lambda row: row["result"]["audit"].update(action="byq_backtest_task_get"),
        lambda row: row["result"]["audit"].update(resource_id="task_" + "f" * 32),
        lambda row: row.update(result={"status": "unknown"}),
    ):
        row = copy.deepcopy(valid_row)
        mutate(row)
        with pytest.raises(F6FixtureRejected):
            _verify_agent_audit_result(row, records)


def test_authorization_result_requires_exact_allowed_action_and_run():
    run_id = "agent_run_" + "a" * 32
    records = [
        {"name": "byq_agent_run_start", "result": {"run": {"run_id": run_id, "status": "active"}}},
        {"name": "byq_agent_authorize", "result": {"authorization": {
            "authorized": True, "decision": "allowed", "run_id": run_id,
            "action": "byq_research_get"}}},
        {"name": "byq_agent_authorize", "result": {"authorization": {
            "authorized": True, "decision": "allowed", "run_id": run_id,
            "action": "byq_backtest_task_get"}}},
    ]
    # The current row must be checked directly despite an earlier call to the same tool.
    _authorize(records[2], records, "byq_backtest_task_get")
    for mutation in (
        {"authorized": True, "decision": "allowed", "run_id": "agent_run_" + "b" * 32,
         "action": "byq_backtest_task_get"},
        {"authorized": True, "decision": "allowed", "run_id": run_id,
         "action": "byq_research_get"},
        {"authorized": False, "decision": "approval_required", "run_id": run_id,
         "action": "byq_backtest_task_get"},
    ):
        bad_row = copy.deepcopy(records[2])
        bad_row["result"]["authorization"] = mutation
        with pytest.raises(F6FixtureRejected):
            _authorize(bad_row, records, "byq_backtest_task_get")


def test_synthetic_response_omits_usage_and_gate_parser_preserves_unknown():
    response = _sse_completion({"messages": []}, ("mcp__byq__byq_agent_context", {}))
    chunks = [json.loads(line[6:]) for line in response.decode().splitlines()
              if line.startswith("data: ") and line != "data: [DONE]"]
    assert chunks and all("usage" not in chunk for chunk in chunks)
    usage = parse_response_usage(response)
    assert usage == {
        "actual_input_tokens": "unknown", "actual_cache_read_tokens": "unknown",
        "actual_output_tokens": "unknown", "usage_source": "unknown",
    }


def test_synthetic_provider_changes_only_the_request_gate_proxy_upstream():
    source = Path(__file__).with_name("f6_synthetic_runtime.py").read_text(encoding="utf-8")
    assert 'os.environ["DEEPSEEK_BASE_URL"]' not in source
    assert "proxy_type.__init__ = init_with_local_upstream" in source
    assert "self._server.upstream = self._upstream" in source


def test_foreground_routes_only_its_child_to_provider_and_background_keeps_proxy(monkeypatch):
    import app

    provider_url = "http://127.0.0.1:41001"
    proxy_url = "http://127.0.0.1:41002"
    official_url = "https://api.deepseek.com"

    class FakeProxy:
        def __init__(self, gate, upstream):
            if upstream != official_url:
                raise ValueError("official upstream required")
            handler = object()
            self._upstream = upstream
            self._server = SimpleNamespace(upstream=upstream, handler=handler)

    class FakeCompatibility:
        def build_harness(self, *, provider, model, composition, session_root,
                          runtime_command, environment, max_tokens=None):
            return {"provider": provider, "model": model, "composition": composition,
                    "session_root": session_root, "runtime_command": runtime_command,
                    "environment": dict(environment), "max_tokens": max_tokens}

    class FakeRuntimeAdapter:
        def _build_harness(self, *, continuation_budget=None, continuation_proxy_url=None,
                           continuation_deadline_epoch_ms=None):
            environment = {"BYQ_MCP_URL": "http://mcp:8300"}
            max_tokens = None
            if continuation_budget is not None:
                environment["DEEPSEEK_BASE_URL"] = continuation_proxy_url
                max_tokens = 8192
            return self._compatibility.build_harness(
                provider="deepseek-official", model="deepseek-v4-flash", composition="patch",
                session_root="root", runtime_command=("dsh",), environment=environment,
                max_tokens=max_tokens)

    fake_runtime = types.ModuleType("app.runtime")
    fake_runtime.RequestGateProxy = FakeProxy
    fake_runtime.RuntimeAdapter = FakeRuntimeAdapter
    fake_runtime.compatibility_for_release = lambda _: FakeCompatibility()
    monkeypatch.setitem(sys.modules, "app.runtime", fake_runtime)
    monkeypatch.setattr(app, "runtime", fake_runtime, raising=False)
    monkeypatch.setenv("BYQ_DSH_COMPATIBILITY_RELEASE", "dsh-0.1.5rc1")

    _install_f6_provider_routes(provider_url)
    adapter = object.__new__(FakeRuntimeAdapter)
    adapter._compatibility = FakeCompatibility()
    foreground = adapter._build_harness()
    assert foreground["environment"]["DEEPSEEK_BASE_URL"] == provider_url
    assert foreground["environment"]["BYQ_MCP_URL"] == "http://mcp:8300"
    assert foreground["max_tokens"] is None

    background = adapter._build_harness(
        continuation_budget={"reservation_id": "continuation-exact"},
        continuation_proxy_url=proxy_url, continuation_deadline_epoch_ms=1000)
    assert background["environment"]["DEEPSEEK_BASE_URL"] == proxy_url
    assert background["environment"]["DEEPSEEK_BASE_URL"] != provider_url
    assert background["max_tokens"] == 8192

    with pytest.raises(F6FixtureRejected, match="background_request_gate_proxy_not_preserved"):
        adapter._build_harness(
            continuation_budget={"reservation_id": "continuation-exact"},
            continuation_proxy_url=provider_url, continuation_deadline_epoch_ms=1000)

    gate = object()
    proxy = FakeProxy(gate, official_url)
    original_handler = proxy._server.handler
    assert proxy._upstream == provider_url
    assert proxy._server.upstream == provider_url
    assert proxy._server.handler is original_handler
    with pytest.raises(ValueError, match="official upstream required"):
        FakeProxy(gate, "https://unapproved.example")


def test_authoritative_audit_contract_rejects_mismatched_scope_and_unknown_receipts():
    functions = _driver_functions()
    assert_structured = functions["_assert_structured_agent_audit"]
    validate_settlement = functions["_validate_settlement_identity"]
    document, settlement, expected_events = _audit_fixture()
    task = document["task"]
    run_id = document["runtime_root"]["root_run_id"]
    args = {
        "stage": "background", "task_id": task["task_id"],
        "conversation_id": task["conversation_id"], "trace_id": task["trace_id"],
        "runtime_root_id": run_id, "expected_events": expected_events,
        "settlement": settlement,
    }
    summary = assert_structured(document, **args)
    assert summary["runtime_root_id"] == run_id
    assert summary["agent_run_id"] == document["agent_run"]["run_id"]
    assert summary["settlement_status"] == "settled"
    assert validate_settlement(settlement, 1)["run_id"] == run_id

    variants = []
    bad = copy.deepcopy(document)
    bad["agent_run"]["root_run_id"] = "9" * 32
    variants.append(bad)
    bad = copy.deepcopy(document)
    bad["agent_run"]["owner_principal"] = "another-user"
    variants.append(bad)
    bad = copy.deepcopy(document)
    bad["runtime_root"]["terminal_event_sha256"] = None
    variants.append(bad)
    bad = copy.deepcopy(document)
    bad["events"][1]["action"] = "byq_research_transition"
    variants.append(bad)
    bad = copy.deepcopy(document)
    bad["events"] = [event for event in bad["events"]
                     if not (event.get("action") == "runtime_turn_binding"
                             and event.get("outcome") == "completed")]
    variants.append(bad)
    bad = copy.deepcopy(document)
    bad["events"].append({
        **bad["events"][1], "audit_id": "agent_audit_" + "8" * 32,
        "action": "byq_unknown_unexpected", "outcome": "success",
    })
    variants.append(bad)
    bad = copy.deepcopy(document)
    bad["events"][1]["resource_id"] = "task_" + "9" * 32
    variants.append(bad)
    bad = copy.deepcopy(document)
    bad["events"][1]["owner_principal"] = "another-user"
    variants.append(bad)
    bad = copy.deepcopy(document)
    bad["settlement"]["run_id"] = "8" * 32
    variants.append(bad)
    for bad_document in variants:
        with pytest.raises(DriverContractRejected):
            assert_structured(bad_document, **args)

    bad_audit_id = copy.deepcopy(document)
    bad_audit_id["events"][1]["audit_id"] = "not-an-audit-id"
    with pytest.raises(DriverContractRejected):
        assert_structured(bad_audit_id, **args)

    for unknown in (None, {}, {**settlement, "run_id": "agent_run_" + "1" * 32},
                    {**settlement, "settlement_sha256": "not-a-digest"},
                    {**settlement, "dispatch_attempts": 0},
                    {**settlement, "event_key": "ready-v1:incomplete"},
                    {**settlement, "grant_version": 2}):
        with pytest.raises(DriverContractRejected):
            validate_settlement(unknown, 1)


def test_validated_signal_artifact_requires_exact_owner_strategy_job_snapshot_and_lineage():
    functions = _driver_functions()
    validate_artifact = functions["_assert_validated_signal_artifact"]
    artifact_id = "artifact_" + "a" * 32
    task_id = "task_" + "b" * 32
    owner = "f6-chain-user"
    workspace = "workspace_" + "c" * 32
    version_id = "artifact_" + "d" * 32
    pool_snapshot_id = "stock_pool_snapshot_" + "e" * 64
    signal_job_id = "signaljob_" + "f" * 32
    lineage = [
        {"kind": "research_task", "id": task_id},
        {"kind": "artifact", "id": version_id},
        {"kind": "stock_pool_snapshot", "id": pool_snapshot_id},
        {"kind": "signal_producer_job", "id": signal_job_id},
    ]
    artifact = {
        "artifact_id": artifact_id, "owner_principal": owner, "workspace_id": workspace,
        "task_id": task_id, "kind": "signal_snapshot", "status": "validated",
        "content": {"schema_version": "signal-snapshot-v2",
                    "strategy": {"strategy_version_artifact_id": version_id},
                    "universe": {"version_id": pool_snapshot_id}},
        "lineage": lineage,
    }
    kwargs = {"artifact_id": artifact_id, "task_id": task_id, "owner_principal": owner,
              "workspace_id": workspace, "strategy_version_artifact_id": version_id,
              "stock_pool_snapshot_id": pool_snapshot_id, "signal_job_id": signal_job_id}
    assert validate_artifact(artifact, **kwargs) == artifact
    mutations = (
        lambda row: row["content"]["strategy"].update(strategy_version_artifact_id="artifact_" + "0" * 32),
        lambda row: row["lineage"].pop(),
        lambda row: row["lineage"].pop(0),
        lambda row: row["lineage"][0].update(id="task_" + "0" * 32),
        lambda row: row.update(lineage=[*row["lineage"], {"kind": "artifact", "id": "artifact_" + "1" * 32}]),
        lambda row: row["content"]["universe"].update(version_id="stock_pool_snapshot_" + "2" * 64),
        lambda row: row["content"].update(schema_version="signal-snapshot-v1"),
        lambda row: row.update(owner_principal="another-user"),
    )
    for mutate in mutations:
        bad = copy.deepcopy(artifact)
        mutate(bad)
        with pytest.raises(DriverContractRejected):
            validate_artifact(bad, **kwargs)


def test_structured_audit_wait_retries_only_explicit_active_root_proof(monkeypatch):
    functions = _driver_functions()
    document, settlement, expected_events = _audit_fixture()
    root_id = document["runtime_root"]["root_run_id"]
    not_ready = {"schema_version": "f6-agent-audit-readiness.v1", "stage": "background",
                 "status": "not_ready", "category": "runtime_root_active"}
    results = [json.dumps(not_ready), json.dumps(document)]
    calls = []

    def read(*_args, **_kwargs):
        calls.append(None)
        return SimpleNamespace(returncode=0, stdout=results.pop(0))

    functions["subprocess"].run = read
    functions["time"] = SimpleNamespace(monotonic=time.monotonic, sleep=lambda _seconds: None)
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "byq-ci-stack-f6-offline")
    summary = functions["_read_structured_agent_audit"](
        "background", task_id=document["task"]["task_id"],
        conversation_id=document["task"]["conversation_id"],
        trace_id=document["task"]["trace_id"], runtime_root_id=root_id,
        expected_events=expected_events, settlement=settlement, timeout=1,
    )
    assert summary["runtime_root_id"] == root_id
    assert len(calls) == 2
    observation = functions["state"]["checks"]["structured_audit_wait_background"]
    assert observation == {"attempts": 2, "last_not_ready_category": "runtime_root_active",
                           "status": "terminal_proof_observed"}


def test_structured_audit_wait_does_not_retry_unknown_readiness_or_wrong_stage(monkeypatch):
    functions = _driver_functions()
    document, settlement, expected_events = _audit_fixture()
    unknown = {"schema_version": "f6-agent-audit-readiness.v1", "stage": "background",
               "status": "not_ready", "category": "scope_mismatch"}
    calls = []

    def read(*_args, **_kwargs):
        calls.append(None)
        return SimpleNamespace(returncode=0, stdout=json.dumps(unknown))

    functions["subprocess"].run = read
    functions["time"] = SimpleNamespace(monotonic=time.monotonic, sleep=lambda _seconds: None)
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "byq-ci-stack-f6-offline")
    with pytest.raises(DriverContractRejected):
        functions["_read_structured_agent_audit"](
            "background", task_id=document["task"]["task_id"],
            conversation_id=document["task"]["conversation_id"],
            trace_id=document["task"]["trace_id"],
            runtime_root_id=document["runtime_root"]["root_run_id"],
            expected_events=expected_events, settlement=settlement, timeout=1,
        )
    assert len(calls) == 1


def test_audit_fixture_is_a_select_only_readonly_observer():
    path = os.environ.get("BYQ_F6_FIXTURE_PATH")
    if not path:
        pytest.skip("fixture SQL boundary is run by check_f6_chain")
    source = Path(path).read_text(encoding="utf-8")
    assert 'SET TRANSACTION READ ONLY' in source
    assert 'FROM research_tasks' in source and 'FROM agent_runtime_turns' in source
    assert 'FROM agent_runs' in source and 'FROM agent_audit' in source
    assert 'ORDER BY created_at ASC, audit_id ASC LIMIT 33' in source
    assert 'len(audit_rows) > 32' in source
    assert "'grant_version'" in source and "'settlement_sha256'" in source
    assert 'INSERT INTO' not in source.upper()
    assert 'UPDATE ' not in source.upper()
