"""Offline acceptance contracts for the assigned current-head F6 CI driver."""
from __future__ import annotations

import ast
import copy
import hashlib
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
from packages.contracts.conversation_rehydration import normalize_conversation_context, rehydrated_prompt
from packages.contracts.continuation_request import profile_binding, request_limits
from tests.f6_synthetic_runtime import (
    AGENT_RUN_PATTERN,
    AUDIT_PATTERN,
    BG_SEQUENCE,
    FG1_SEQUENCE,
    FG2_SEQUENCE,
    F6FixtureRejected,
    _authorize,
    _normalize_tool_result,
    _selected_instruction,
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
              "_read_structured_agent_audit", "_validate_settlement_identity",
              "_body_text", "_messages", "_answer_after", "_session_call", "_wait_answer",
              "_failure_readonly_window", "_permission_view", "_assert_task_ready_read_profile",
              "_audit_closes_root", "_failure_reconciliation_mode", "_remaining_timeout",
              "_failure_observation_summary", "_is_untrusted_identity",
              "_request_state_identity_mismatch", "_stop_owned_signal_worker", "_revoke_exact_grant"}
    nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
             and node.name in wanted]
    if {node.name for node in nodes} != wanted:
        raise AssertionError("current F6 driver audit contract helpers are missing")
    category_names = {"SESSION_IDENTITY_FAILURES", "UNTRUSTED_IDENTITY_FAILURES"}
    category_nodes = [node for node in tree.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id in category_names
                              for target in node.targets)]
    found_categories = {target.id for node in category_nodes for target in node.targets
                        if isinstance(target, ast.Name) and target.id in category_names}
    if found_categories != category_names:
        raise AssertionError("current F6 driver failure classification sets are missing")

    def require(condition: object, category: str) -> None:
        if not condition:
            raise DriverContractRejected(category)

    namespace = {
        "re": re, "require": require, "hashlib": hashlib,
        "json": json, "os": os, "subprocess": types.SimpleNamespace(), "time": time,
        "state": {"checks": {}, "identities": {}, "audit_summaries": {},
                  "mutation_attempts": [], "uncertain_actions": [],
                  "grant_idempotency_key": None, "revoke_attempted": False,
                  "worker_cleanup_attempted": False, "failure_category": None},
        "PROJECT_PATTERN": re.compile(r"byq-ci-stack-[A-Za-z0-9][A-Za-z0-9_-]{0,80}\Z"),
        "RUNTIME_ROOT_PATTERN": re.compile(r"[0-9a-f]{32}\Z"),
        "RESERVATION_PATTERN": re.compile(r"continuation_[0-9a-f]{32}\Z"),
        "SESSION_PATTERN": re.compile(r"byq-session-[0-9a-f]{32}\Z"),
        "TRACE_PATTERN": re.compile(r"byq-trace-[0-9a-f]{32}\Z"),
        "AGENT_RUN_PATTERN": AGENT_RUN_PATTERN,
        "AUDIT_PATTERN": AUDIT_PATTERN,
        "SHA256_PATTERN": re.compile(r"[0-9a-f]{64}\Z"),
        "PROFILE_BINDING": profile_binding(), "PROFILE_REQUEST_LIMITS": request_limits(),
        "SESSION_IDENTITY_FAILURES": frozenset({
            "original_agent_session_identity_changed", "original_agent_session_trace_changed"}),
        "EvidenceError": DriverContractRejected,
    }
    exec(compile(ast.Module(body=category_nodes, type_ignores=[]), path, "exec"), namespace)
    module = ast.Module(body=nodes, type_ignores=[])
    exec(compile(module, path, "exec"), namespace)
    return namespace


def _base_failure_state(**identity_overrides):
    identities = {
        "conversation_id": "conversation_" + "7" * 32,
        "trace_id": "byq-trace-" + "8" * 32,
        "task_id": "task_" + "9" * 32,
        "workspace_id": "workspace_" + "a" * 32,
        "strategy_version_artifact_id": "artifact_" + "b" * 32,
        "stock_pool_snapshot_id": "stock_pool_snapshot_" + "c" * 64,
        "signal_job_id": "signaljob_" + "d" * 32,
        "grant_version": 1,
    }
    identities.update(identity_overrides)
    return {"checks": {}, "identities": identities, "audit_summaries": {},
            "mutation_attempts": [], "uncertain_actions": [],
            "grant_idempotency_key": "f6-ci-read-grant-byq-ci-stack-test",
            "revoke_attempted": False, "worker_cleanup_attempted": False,
            "failure_category": None}


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
        # Direct root close is the normal Gateway terminal path. A lifecycle
        # audit binding may be appended separately by the test that covers it.
        "events": [binding, *audit_events],
        "settlement": {"reservation_id": reservation_id, "grant_version": 1, "run_id": root,
                       "status": "settled", "outcome": "completed", "event_key": event_key,
                       "dispatch_attempts": 1, "settlement_sha256": digest},
    }
    settlement = {"reservation_id": reservation_id, "run_id": root,
                  "status": "settled", "outcome": "completed", "event_key": event_key,
                  "dispatch_attempts": 1, "settlement_sha256": digest,
                  "grant_version": 1}
    return document, settlement, expected_events


def _gateway_session_projection(session_id: str, trace_id: str, prompt: str, answer: str):
    return {
        "conversation": {"session_id": session_id, "trace_id": trace_id, "status": "active"},
        "messages": [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": answer},
        ],
        "events": [], "containment": {"status": "active"},
    }


@pytest.mark.parametrize("stage,required,answer", [
    ("fg1", ("ResearchTask ", "StrategyVersion "), "ResearchTask task_1 StrategyVersion artifact_1"),
    ("fg2", ("BacktestTask ", "SignalJob "), "BacktestTask backtesttask_1 SignalJob signaljob_1"),
])
def test_foreground_session_wait_uses_exact_gateway_public_session_and_trace(stage, required, answer):
    functions = _driver_functions()
    session_call, wait_answer = functions["_session_call"], functions["_wait_answer"]
    session_id = "conversation_" + "1" * 32
    trace_id = "byq-trace-" + "2" * 32
    prompt = "\n".join((
        "F6-CI:" + stage.upper(),
        "owner_principal=f6-chain-user",
        "instruction=match the exact normalized catalog user message",
    ))
    catalog_prompt = " ".join(prompt.split())
    requests = []

    def product_api(method, path, *, timeout):
        requests.append((method, path, timeout))
        return _gateway_session_projection(session_id, trace_id, catalog_prompt, answer)

    body = session_call(product_api, session_id, trace_id)
    assert body["conversation"]["session_id"] == session_id
    assert wait_answer(product_api, session_id, trace_id, prompt, required, timeout=1) == (body, answer)
    observation = functions["state"]["answer_wait_observation"]
    assert observation == {
        "foreground_step": stage,
        "session_status": "active",
        "session_message_count": 2,
        "prompt_matched": True,
        "assistant_answer_present": True,
        "required_answer_present": True,
    }
    assert prompt not in repr(observation) and answer not in repr(observation)
    assert [request[0:2] for request in requests] == [
        ("GET", f"/v1/agent/sessions/{session_id}"),
        ("GET", f"/v1/agent/sessions/{session_id}"),
    ]
    assert requests[0][2] == 12
    assert 0 < requests[1][2] <= 1


@pytest.mark.parametrize("stage", ["fg1", "fg2"])
def test_answer_after_rejects_changed_prompt_content_after_catalog_normalization(stage):
    answer_after = _driver_functions()["_answer_after"]
    session_id = "conversation_" + "3" * 32
    trace_id = "byq-trace-" + "4" * 32
    prompt = "\n".join(("F6-CI:" + stage.upper(), "exact instruction=preserve this token"))
    changed_prompt = prompt.replace("preserve", "altered")
    body = _gateway_session_projection(
        session_id, trace_id, " ".join(changed_prompt.split()), "ResearchTask task_1 SignalJob signaljob_1")
    assert answer_after(body, prompt) is None


def test_answer_after_rejects_duplicate_canonicalized_user_turns():
    answer_after = _driver_functions()["_answer_after"]
    session_id = "conversation_" + "5" * 32
    trace_id = "byq-trace-" + "6" * 32
    prompt = "F6-CI:FG1\ncreate one exact task"
    body = _gateway_session_projection(
        session_id, trace_id, " ".join(prompt.split()), "ResearchTask task_1 StrategyVersion artifact_1")
    body["messages"].insert(1, {"role": "user", "content": " ".join(prompt.split())})
    with pytest.raises(DriverContractRejected, match="agent_user_turn_duplicate"):
        answer_after(body, prompt)


def test_wait_answer_clamps_each_session_read_and_sleep_to_deadline_and_saves_safe_observation():
    functions = _driver_functions()
    clock = _install_fake_deadline(functions)
    session_id = "conversation_" + "7" * 32
    trace_id = "byq-trace-" + "8" * 32
    prompt = "\n".join(("F6-CI:FG1", "owner_principal=f6-chain-user", "private marker must not be saved"))
    body = _gateway_session_projection(
        session_id, trace_id, " ".join(prompt.split()), "")
    body["messages"] = body["messages"][:1]
    calls = []

    def slow_product_api(method, path, *, timeout):
        calls.append((method, path, timeout))
        clock.now += 0.75
        return body

    with pytest.raises(DriverContractRejected, match="agent_answer_not_persisted_before_deadline"):
        functions["_wait_answer"](slow_product_api, session_id, trace_id, prompt,
                                  ("ResearchTask ",), timeout=1)
    assert len(calls) == 1
    assert calls[0][0:2] == ("GET", f"/v1/agent/sessions/{session_id}")
    assert 0 < calls[0][2] <= 1
    assert clock.now == 1
    observation = functions["state"]["answer_wait_observation"]
    assert observation == {
        "foreground_step": "fg1",
        "session_status": "active",
        "session_message_count": 1,
        "prompt_matched": True,
        "assistant_answer_present": False,
        "required_answer_present": False,
    }
    assert "private marker" not in repr(observation)


def test_session_observer_rejects_wrong_or_missing_projected_identity_and_trace():
    session_call = _driver_functions()["_session_call"]
    session_id = "conversation_" + "3" * 32
    trace_id = "byq-trace-" + "4" * 32

    def read(body):
        return session_call(lambda *_args, **_kwargs: body, session_id, trace_id)

    valid = _gateway_session_projection(session_id, trace_id, "prompt", "answer")
    assert read(valid) == valid
    invalid = [
        {**valid, "conversation": {"conversation_id": session_id, "trace_id": trace_id}},
        {**valid, "conversation": {"session_id": "conversation_" + "5" * 32,
                                    "trace_id": trace_id}},
        {**valid, "conversation": {"session_id": session_id,
                                    "trace_id": "byq-trace-" + "6" * 32}},
        {"session_id": session_id, "conversation": {"conversation_id": session_id,
                                                       "trace_id": trace_id}},
        {**valid, "conversation": None},
    ]
    for body in invalid:
        with pytest.raises(DriverContractRejected):
            read(body)


class _FakeDeadline:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def _install_fake_deadline(functions):
    clock = _FakeDeadline()
    functions["time"] = SimpleNamespace(monotonic=clock.monotonic, sleep=clock.sleep)
    return clock


def _failure_projection(functions, *, status="completed", revoked=True):
    identities = functions["state"]["identities"]
    session_id, trace_id, task_id = (identities[key] for key in (
        "conversation_id", "trace_id", "task_id"))
    response = {
        f"/v1/agent/sessions/{session_id}": _gateway_session_projection(
            session_id, trace_id, "failure observer exact session", "persisted answer"),
        f"/api/product/research/tasks/{task_id}": {
            "task_id": task_id, "owner_principal": "f6-chain-user",
            "conversation_id": session_id, "trace_id": trace_id,
            "workspace_id": identities["workspace_id"], "status": "running",
        },
    }
    grant_id = functions["state"]["grant_idempotency_key"]
    permission = {
        "confirmation_id": grant_id,
        "confirmed_artifact_ids": [identities["strategy_version_artifact_id"]],
        "grant_version": identities["grant_version"],
        "revoked_at": "2026-10-02T00:00:00Z" if revoked else None,
        "execution_profile": profile_binding(), "request_limits": request_limits(),
    }
    request_identity = None
    request_usage = None
    if status == "settled":
        root_id = "e" * 32
        identities["signal_snapshot_artifact_id"] = "artifact_" + "a" * 32
        identities["background_reservation_id"] = "continuation_" + "f" * 32
        identities["background_event_key"] = "ready-v1:" + "1" * 64
        identities["background_runtime_root_id"] = root_id
        functions["state"]["audit_summaries"]["background"] = {
            "runtime_root_id": root_id, "terminal": "completed/closed"}
        request_identity = {
            "reservation_id": "continuation_" + "f" * 32, "status": "settled",
            "run_id": root_id, "event_key": "ready-v1:" + "1" * 64,
            "grant_version": identities["grant_version"], "outcome": "completed",
            "settlement_sha256": "2" * 64, "dispatch_attempts": 1,
        }
        request_usage = {"schema_version": "continuation-request-usage.v1",
                         "actual_usage": {"input_tokens": "unknown", "completeness": "unknown"}}
    response[f"/api/product/research/tasks/{task_id}/continuation-permission"] = {
        "task_id": task_id, "schema_version": "task-continuation-permission.v2",
        "permission": permission,
        "request_state": {
            "requests_reserved": 1 if status == "settled" else 0,
            "requests_remaining": 0 if status == "settled" else 1,
            "unconfirmed_requests": 0, "request_identity": request_identity,
            "request_usage": request_usage,
        },
    }
    job_id = identities.get("signal_job_id")
    if isinstance(job_id, str):
        response[f"/api/product/signal-producer/jobs/{job_id}"] = {
            "job": {
            "job_id": job_id, "task_id": task_id, "owner_principal": "f6-chain-user",
            "strategy_version_artifact_id": identities["strategy_version_artifact_id"],
            "stock_pool_snapshot_id": identities["stock_pool_snapshot_id"], "status": "completed",
            "result_artifact_id": identities.get("signal_snapshot_artifact_id"),
            },
        }
    return response


def _api_for_projection(response, calls):
    def product_api(method, path, *, timeout):
        calls.append((method, path, timeout))
        assert method == "GET"
        if path not in response:
            raise AssertionError("unexpected observation path")
        return response[path]
    return product_api


def test_failure_reconcile_confirms_only_complete_closed_scope_and_keeps_usage_unknown():
    functions = _driver_functions()
    functions["state"] = _base_failure_state(
        foreground_1_runtime_root_id="3" * 32,
        foreground_2_runtime_root_id="4" * 32,
        background_runtime_root_id="e" * 32,
    )
    functions["state"]["mutation_attempts"] = ["foreground_agent_turn_1", "foreground_agent_turn_2"]
    functions["state"]["audit_summaries"] = {
        stage: {"runtime_root_id": root, "terminal": "completed/closed"}
        for stage, root in (("fg1", "3" * 32), ("fg2", "4" * 32), ("background", "e" * 32))
    }
    functions["state"]["answer_wait_observation"] = {
        "foreground_step": "fg1", "session_status": "active", "session_message_count": 2,
        "prompt_matched": False, "assistant_answer_present": False,
        "required_answer_present": False,
    }
    _install_fake_deadline(functions)
    response = _failure_projection(functions, status="settled", revoked=True)
    calls = []
    functions["_failure_readonly_window"](_api_for_projection(response, calls), seconds=4)
    observed = functions["state"]["failure_observation"]
    assert observed["classification"] == "healthy_observer_confirmed"
    assert observed["side_effects_resolved"] is True
    assert observed["resource_cleanup_is_terminal_proof"] is False
    assert observed["request_state"]["request_usage"]["actual_usage"]["input_tokens"] == "unknown"
    summary = functions["_failure_observation_summary"](observed)
    assert summary["classification"] == "healthy_observer_confirmed"
    assert "request_state" not in summary
    assert summary["session_status"] == "active" and summary["session_messages_observed"] == 2
    assert summary["answer_wait_observation"]["prompt_matched"] is False
    assert summary["answer_wait_observation"]["assistant_answer_present"] is False
    assert [call[:2] for call in calls] == [
        ("GET", "/v1/agent/sessions/" + functions["state"]["identities"]["conversation_id"]),
        ("GET", "/api/product/research/tasks/" + functions["state"]["identities"]["task_id"]),
        ("GET", "/api/product/research/tasks/" + functions["state"]["identities"]["task_id"]
         + "/continuation-permission"),
        ("GET", "/api/product/signal-producer/jobs/" + functions["state"]["identities"]["signal_job_id"]),
    ]
    assert all(0 < call[2] <= 4 for call in calls)


def test_unknown_post_remains_unknown_even_with_closed_known_roots_and_terminal_job():
    functions = _driver_functions()
    functions["state"] = _base_failure_state(
        foreground_1_runtime_root_id="3" * 32,
        foreground_2_runtime_root_id="4" * 32,
        background_runtime_root_id="e" * 32,
    )
    functions["state"]["mutation_attempts"] = ["foreground_agent_turn_1", "foreground_agent_turn_2"]
    functions["state"]["uncertain_actions"] = ["product_stock_pool"]
    functions["state"]["audit_summaries"] = {
        stage: {"runtime_root_id": root, "terminal": "completed/closed"}
        for stage, root in (("fg1", "3" * 32), ("fg2", "4" * 32), ("background", "e" * 32))
    }
    _install_fake_deadline(functions)
    response = _failure_projection(functions, status="settled", revoked=True)
    calls = []
    functions["_failure_readonly_window"](_api_for_projection(response, calls), seconds=1)
    observed = functions["state"]["failure_observation"]
    assert observed["reconcile_mode"] == "unknown_mutation_unresolved"
    assert observed["classification"] == "bounded_reconcile_incomplete_unknown"
    assert observed["side_effects_resolved"] is False
    assert observed["request_state"]["request_usage"]["actual_usage"]["input_tokens"] == "unknown"
    assert len(calls) == 4 and all(call[0] == "GET" for call in calls)


def test_accepted_root_without_terminal_proof_stays_unknown_after_exact_reads():
    functions = _driver_functions()
    functions["state"] = _base_failure_state(signal_job_id=None)
    functions["state"]["identities"]["foreground_1_runtime_root_id"] = "3" * 32
    functions["state"]["mutation_attempts"] = ["foreground_agent_turn_1"]
    _install_fake_deadline(functions)
    response = _failure_projection(functions, status="absent", revoked=True)
    calls = []
    functions["_failure_readonly_window"](_api_for_projection(response, calls), seconds=1)
    observed = functions["state"]["failure_observation"]
    assert observed["reconcile_mode"] == "accepted_root_terminal_unobserved"
    assert observed["classification"] == "bounded_reconcile_incomplete_unknown"
    assert observed["side_effects_resolved"] is False
    assert [call[1] for call in calls] == [
        "/v1/agent/sessions/" + functions["state"]["identities"]["conversation_id"],
        "/api/product/research/tasks/" + functions["state"]["identities"]["task_id"],
        "/api/product/research/tasks/" + functions["state"]["identities"]["task_id"]
        + "/continuation-permission",
    ]


def test_active_exact_grant_does_not_count_as_side_effects_resolved():
    functions = _driver_functions()
    functions["state"] = _base_failure_state(signal_job_id=None)
    _install_fake_deadline(functions)
    response = _failure_projection(functions, status="absent", revoked=False)
    calls = []
    functions["_failure_readonly_window"](_api_for_projection(response, calls), seconds=1)
    observed = functions["state"]["failure_observation"]
    assert observed["grant_status"] == "active"
    assert observed["classification"] == "bounded_reconcile_incomplete_unknown"
    assert observed["side_effects_resolved"] is False


@pytest.mark.parametrize("bad_identity,expected_calls", [
    ("session_trace", 1), ("task_workspace", 2), ("permission_artifact", 3),
    ("settlement_event", 3), ("job_owner", 4),
])
def test_observer_stops_immediately_on_proven_session_task_grant_or_job_identity_mismatch(
        bad_identity, expected_calls):
    functions = _driver_functions()
    functions["state"] = _base_failure_state()
    _install_fake_deadline(functions)
    response = _failure_projection(
        functions, status="settled" if bad_identity == "settlement_event" else "absent", revoked=True)
    identities = functions["state"]["identities"]
    if bad_identity == "session_trace":
        response[f"/v1/agent/sessions/{identities['conversation_id']}"]["conversation"]["trace_id"] = (
            "byq-trace-" + "f" * 32)
    elif bad_identity == "task_workspace":
        response[f"/api/product/research/tasks/{identities['task_id']}"]["workspace_id"] = (
            "workspace_" + "f" * 32)
    elif bad_identity == "permission_artifact":
        path = f"/api/product/research/tasks/{identities['task_id']}/continuation-permission"
        response[path]["permission"]["confirmed_artifact_ids"] = ["artifact_" + "f" * 32]
    elif bad_identity == "settlement_event":
        path = f"/api/product/research/tasks/{identities['task_id']}/continuation-permission"
        response[path]["request_state"]["request_identity"]["event_key"] = "ready-v1:" + "9" * 64
    else:
        response[f"/api/product/signal-producer/jobs/{identities['signal_job_id']}" ]["job"]["owner_principal"] = "other-user"
    calls = []
    functions["_failure_readonly_window"](_api_for_projection(response, calls), seconds=1)
    observed = functions["state"]["failure_observation"]
    assert observed["classification"] == "untrusted_identity"
    assert observed["side_effects_resolved"] is False
    assert len(calls) == expected_calls
    assert all(call[0] == "GET" for call in calls)


def test_readonly_reconcile_clamps_each_get_to_one_total_deadline(monkeypatch):
    functions = _driver_functions()
    functions["state"] = _base_failure_state(signal_job_id=None)
    clock = _install_fake_deadline(functions)
    session_id = functions["state"]["identities"]["conversation_id"]
    trace_id = functions["state"]["identities"]["trace_id"]
    calls = []

    def slow_session(method, path, *, timeout):
        calls.append((method, path, timeout))
        clock.now += 1.1
        return _gateway_session_projection(session_id, trace_id, "prompt", "answer")

    functions["_failure_readonly_window"](slow_session, seconds=1)
    assert calls == [("GET", f"/v1/agent/sessions/{session_id}", 1)]
    assert functions["state"]["failure_observation"]["classification"] == "bounded_reconcile_incomplete_unknown"
    assert functions["state"]["failure_observation"]["task_reads"] == 0


def test_each_read_get_uses_only_remaining_total_deadline():
    functions = _driver_functions()
    functions["state"] = _base_failure_state()
    clock = _install_fake_deadline(functions)
    response = _failure_projection(functions, status="absent", revoked=True)
    calls = []

    def delayed_api(method, path, *, timeout):
        calls.append((method, path, timeout))
        clock.now += 0.2
        return response[path]

    functions["_failure_readonly_window"](delayed_api, seconds=1)
    assert len(calls) == 4
    assert [round(call[2], 1) for call in calls] == [1.0, 0.8, 0.6, 0.4]
    assert all(call[0] == "GET" for call in calls)


def test_untrusted_primary_identity_failure_skips_all_observer_reads():
    functions = _driver_functions()
    functions["state"] = _base_failure_state()
    functions["state"]["failure_category"] = "structured_runtime_root_scope_invalid"
    calls = []

    def must_not_read(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("untrusted identity must stop reconciliation")

    functions["_failure_readonly_window"](must_not_read, seconds=20)
    observed = functions["state"]["failure_observation"]
    assert observed["reconcile_mode"] == "untrusted_identity"
    assert observed["classification"] == "untrusted_identity"
    assert observed["stop_category"] == "structured_runtime_root_scope_invalid"
    assert calls == []


def test_task_ready_read_profile_matches_source_closed_binding_and_all_limits():
    functions = _driver_functions()
    driver_source = Path(os.environ["BYQ_F6_DRIVER_PATH"]).read_text(encoding="utf-8")
    assert 'runpy.run_path(str(_continuation_contract_path))' in driver_source
    assert '"packages/contracts/continuation_request.py"' in driver_source
    permission = {"execution_profile": profile_binding(), "request_limits": request_limits()}
    assert functions["_assert_task_ready_read_profile"](permission) == request_limits()
    assert len(request_limits()) == 11


@pytest.mark.parametrize("change,category", [
    (lambda p: p["execution_profile"].update(profile_sha256="0" * 64),
     "single_request_profile_binding_invalid"),
    (lambda p: p["execution_profile"].update(unexpected="extra"),
     "single_request_profile_binding_invalid"),
    (lambda p: p["execution_profile"].update(profile_version=True),
     "single_request_profile_binding_invalid"),
    (lambda p: p["request_limits"].pop("max_total_input_bytes"),
     "single_request_profile_limits_invalid"),
    (lambda p: p["request_limits"].update(unexpected=1),
     "single_request_profile_limits_invalid"),
    (lambda p: p["request_limits"].update(max_provider_calls=15),
     "single_request_profile_limits_invalid"),
    (lambda p: p["request_limits"].update(max_tool_calls=True),
     "single_request_profile_limits_invalid"),
])
def test_task_ready_read_profile_rejects_nonexact_binding_or_any_limit(change, category):
    functions = _driver_functions()
    permission = {"execution_profile": profile_binding(), "request_limits": request_limits()}
    change(permission)
    with pytest.raises(DriverContractRejected) as rejected:
        functions["_assert_task_ready_read_profile"](permission)
    assert rejected.value.category == category


def test_one_exact_grant_revoke_preserves_unknown_request_state():
    functions = _driver_functions()
    state = functions["state"] = _base_failure_state()
    state["grant_idempotency_key"] = "f6-ci-read-grant-byq-ci-stack-test"
    state["uncertain_actions"] = ["foreground_agent_turn_1", "continuation_permission_revoke"]
    task_id = state["identities"]["task_id"]
    permission_path = f"/api/product/research/tasks/{task_id}/continuation-permission"
    request_state = {
        "requests_reserved": 1, "requests_remaining": 0, "unconfirmed_requests": 1,
        "request_identity": {"status": "outcome_unknown", "run_id": None,
                             "reservation_id": "continuation_" + "f" * 32,
                             "dispatch_attempts": 1, "grant_version": 1},
        "request_usage": {"actual_usage": {"input_tokens": "unknown", "completeness": "unknown"}},
    }
    active_permission = {
        "confirmation_id": state["grant_idempotency_key"],
        "confirmed_artifact_ids": [state["identities"]["strategy_version_artifact_id"]],
        "grant_version": 1, "revoked_at": None,
    }
    revoked_permission = {**active_permission, "revoked_at": "2026-10-02T00:00:00Z"}
    snapshots = [
        {"task_id": task_id, "schema_version": "task-continuation-permission.v2",
         "permission": active_permission, "request_state": copy.deepcopy(request_state)},
        {"task_id": task_id, "schema_version": "task-continuation-permission.v2",
         "permission": revoked_permission, "request_state": copy.deepcopy(request_state)},
    ]
    calls = []

    def product_api(method, path, payload=None, *, expected=200, headers=None, timeout=45):
        calls.append((method, path, payload, expected, headers))
        if path == permission_path and method == "GET":
            return snapshots.pop(0)
        if path == permission_path + "/revoke" and method == "POST":
            return {"permission": revoked_permission}
        raise AssertionError("unexpected revoke call")

    def post_once(api_call, label, path, payload, *, expected=200, headers=None, timeout=45):
        state["mutation_attempts"].append(label)
        return api_call("POST", path, payload, expected=expected, headers=headers, timeout=timeout)

    functions["_post_once"] = post_once
    functions["_revoke_exact_grant"](product_api)
    assert [call[0] for call in calls] == ["GET", "POST", "GET"]
    assert [call[1] for call in calls].count(permission_path + "/revoke") == 1
    assert state["checks"]["revoke"] == "one_exact_post_and_get_confirmed_no_second_request"
    assert state["uncertain_actions"] == ["foreground_agent_turn_1"]
    assert request_state["request_identity"]["status"] == "outcome_unknown"
    assert request_state["request_usage"]["actual_usage"]["input_tokens"] == "unknown"
    assert calls[0][2] is None and calls[2][2] is None
    assert state["revoke_attempted"] is True


def test_worker_cleanup_is_exact_owned_once_and_never_terminal_proof(monkeypatch):
    functions = _driver_functions()
    state = functions["state"] = _base_failure_state()
    project = "byq-ci-stack-f6-worker-test"
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", project)
    calls = []
    functions["_stop_owned_signal_worker"](
        lambda *args: calls.append(args), attempted=True, project=project)
    assert calls == [("signal_worker_stop_after_chain", "stop", "signal-worker")]
    audit = state["checks"]["worker_final_cleanup"]
    assert audit == {
        "status": "dedicated_signal_worker_stopped", "project": project,
        "service": "signal-worker", "worker_start_attempted": True,
        "purpose": "ci_resource_cleanup_only",
        "terminal_proof": False,
    }
    with pytest.raises(DriverContractRejected) as rejected:
        functions["_stop_owned_signal_worker"](
            lambda *args: calls.append(args), attempted=True, project=project)
    assert rejected.value.category == "signal_worker_cleanup_duplicate_attempt"
    assert len(calls) == 1


def test_worker_cleanup_failure_does_not_upgrade_unknown_or_claim_terminal(monkeypatch):
    functions = _driver_functions()
    state = functions["state"] = _base_failure_state()
    state["failure_observation"] = {
        "classification": "healthy_observer_confirmed", "side_effects_resolved": True,
        "resource_cleanup_is_terminal_proof": False,
    }
    project = "byq-ci-stack-f6-worker-failure"
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", project)

    def failed_stop(*_args):
        raise DriverContractRejected("dedicated_compose_action_outcome_unknown")

    with pytest.raises(DriverContractRejected):
        functions["_stop_owned_signal_worker"](failed_stop, attempted=True, project=project)
    assert state["failure_observation"]["classification"] == "bounded_reconcile_incomplete_unknown"
    assert state["failure_observation"]["side_effects_resolved"] is False
    assert state["checks"]["worker_final_cleanup"]["terminal_proof"] is False
    assert state["uncertain_actions"] == ["signal_worker_stop_after_chain"]


def test_foreground_background_and_failure_handlers_use_product_api_callable():
    path = os.environ.get("BYQ_F6_DRIVER_PATH")
    if not path:
        pytest.skip("driver call-site contract is run by check_f6_chain")
    tree = ast.parse(Path(path).read_text(encoding="utf-8"), filename=path)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name)]

    def args_for(name):
        return [node.args for node in calls if node.func.id == name]

    wait_args = args_for("_wait_answer")
    assert len(wait_args) == 2 and all(isinstance(args[0], ast.Name) and args[0].id == "call"
                                       for args in wait_args)
    readonly_args = args_for("_failure_readonly_window")
    assert len(readonly_args) == 2 and all(isinstance(args[0], ast.Name) and args[0].id == "call"
                                           for args in readonly_args)
    session_args = args_for("_session_call")
    assert sorted(args[0].id for args in session_args if isinstance(args[0], ast.Name)) == [
        "api_call", "api_call", "call", "call"]
    assert all(args and isinstance(args[0], ast.Name) and args[0].id != "client"
               for name in ("_wait_answer", "_failure_readonly_window", "_session_call", "_permission_view")
               for args in args_for(name))


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


def _drive_provider_turn(stage: str, public_history: list[dict[str, str]] | None = None,
                         provider_messages: list[dict[str, Any]] | None = None
                         ) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    prompt = _prompt_for(stage)
    history = normalize_conversation_context(public_history or [])
    effective_prompt = rehydrated_prompt(history, prompt)
    messages = list(provider_messages or [
        {"role": "system", "content": "F6 offline contract test system message."},
    ])
    messages.append({"role": "user", "content": effective_prompt})
    instruction_index = len(messages) - 1
    sequence = _sequence_for(stage)
    for step in range(len(sequence) + 1):
        body = {"messages": messages, "tools": _provider_tools()}
        assert _selected_instruction(messages) == (stage, prompt, instruction_index)
        action = next_action(body)
        if step == len(sequence):
            assert action is None
            chunks = [json.loads(line[6:]) for line in _sse_completion(body, None).decode().splitlines()
                      if line.startswith("data: ") and line != "data: [DONE]"]
            assert chunks[0]["choices"][0]["delta"]["content"]
            assert all("usage" not in chunk for chunk in chunks)
            answer = chunks[0]["choices"][0]["delta"]["content"]
            messages.append({"role": "assistant", "content": answer})
            return ([{"role": "user", "content": prompt},
                     {"role": "assistant", "content": answer}], messages)
        assert action is not None
        assert action[0] == "mcp__byq__" + sequence[step]
        if step == 0:
            expected_key = {
                "fg1": "f6-ci-fg1-agent-run",
                "fg2": "f6-ci-fg2-agent-run",
                "background": "f6-ci-bg-agent-run",
            }[stage]
            assert action[1].get("idempotency_key") == expected_key
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


def test_provider_uses_current_user_block_for_full_rehydrated_fg2_and_background_turns():
    fg1_history, live_provider_messages = _drive_provider_turn("fg1")
    fg2_prompt = _prompt_for("fg2")
    fg2_context = normalize_conversation_context(fg1_history)
    fg2_message = rehydrated_prompt(fg2_context, fg2_prompt)
    fresh_fg2_root = [
        {"role": "system", "content": "F6 offline contract test system message."},
        {"role": "user", "content": fg2_message},
    ]
    assert _selected_instruction(fresh_fg2_root) == ("fg2", fg2_prompt, 1)
    fg2_message_index = len(live_provider_messages)
    assert _selected_instruction([
        *live_provider_messages,
        {"role": "user", "content": fg2_message},
    ]) == ("fg2", fg2_prompt, fg2_message_index)

    fg2_history, live_provider_messages = _drive_provider_turn(
        "fg2", public_history=fg1_history, provider_messages=live_provider_messages)
    bg_prompt = _prompt_for("background")
    bg_context = normalize_conversation_context(fg1_history + fg2_history)
    bg_message = rehydrated_prompt(bg_context, bg_prompt)
    fresh_bg_root = [
        {"role": "system", "content": "F6 offline contract test system message."},
        {"role": "user", "content": bg_message},
    ]
    assert _selected_instruction(fresh_bg_root) == ("background", bg_prompt, 1)
    bg_message_index = len(live_provider_messages)
    assert _selected_instruction([
        *live_provider_messages,
        {"role": "user", "content": bg_message},
    ]) == ("background", bg_prompt, bg_message_index)

    _drive_provider_turn("background", public_history=fg1_history + fg2_history,
                         provider_messages=live_provider_messages)


def test_provider_ignores_historical_assistant_and_tool_markers_when_current_user_is_valid():
    fg1 = _prompt_for("fg1")
    fg2 = _prompt_for("fg2")
    current = rehydrated_prompt(normalize_conversation_context([
        {"role": "user", "content": fg1},
        {"role": "assistant", "content": "Completed prior turn."},
    ]), fg2)
    messages = [
        {"role": "system", "content": "F6 offline contract test system message."},
        {"role": "user", "content": fg1},
        {"role": "assistant", "content": fg1},
        {"role": "tool", "content": _prompt_for("background")},
        {"role": "user", "content": current},
    ]
    assert _selected_instruction(messages) == ("fg2", fg2, 4)


@pytest.mark.parametrize("malformation", [
    "missing_current_block", "missing_current_open", "missing_current_close",
    "duplicate_current_block", "missing_rehydration_close", "missing_all_wrapper_tags",
])
def test_provider_rejects_malformed_rehydrated_current_message_without_history_fallback(malformation):
    history = normalize_conversation_context([
        {"role": "user", "content": _prompt_for("fg1")},
        {"role": "assistant", "content": "Completed prior public turn."},
    ])
    prompt = _prompt_for("fg2")
    content = rehydrated_prompt(history, prompt)
    if malformation == "missing_current_block":
        content = content.replace(
            "[CURRENT_USER_MESSAGE]\n" + prompt + "\n[/CURRENT_USER_MESSAGE]", "", 1)
    elif malformation == "missing_current_open":
        content = content.replace("[CURRENT_USER_MESSAGE]", "[CURRENT_MESSAGE]", 1)
    elif malformation == "missing_current_close":
        content = content.replace("[/CURRENT_USER_MESSAGE]", "[/CURRENT_MESSAGE]", 1)
    elif malformation == "duplicate_current_block":
        content += "\n[CURRENT_USER_MESSAGE]\n" + prompt + "\n[/CURRENT_USER_MESSAGE]"
    elif malformation == "missing_all_wrapper_tags":
        for marker in (
            "[BYQ_CONVERSATION_REHYDRATION]", "[/BYQ_CONVERSATION_REHYDRATION]",
            "[CURRENT_USER_MESSAGE]", "[/CURRENT_USER_MESSAGE]",
        ):
            content = content.replace(marker, "")
    else:
        content = content.replace(
            "[/BYQ_CONVERSATION_REHYDRATION]", "[/BYQ_CONVERSATION_REHYDRATION", 1)
    with pytest.raises(F6FixtureRejected, match="rehydrated_current_message_malformed"):
        _selected_instruction([{"role": "user", "content": content}])


def test_provider_does_not_fall_back_to_earlier_user_stage_when_current_message_has_none():
    fg1_history = [
        {"role": "user", "content": _prompt_for("fg1")},
        {"role": "assistant", "content": "Completed prior public turn."},
    ]
    wrapped_without_stage = rehydrated_prompt(
        normalize_conversation_context(fg1_history), "Continue using only the current instruction.")
    with pytest.raises(F6FixtureRejected, match="provider_current_user_instruction_missing"):
        _selected_instruction([{"role": "user", "content": wrapped_without_stage}])
    with pytest.raises(F6FixtureRejected, match="provider_current_user_instruction_missing"):
        _selected_instruction([
            {"role": "user", "content": _prompt_for("fg1")},
            {"role": "user", "content": "Continue using only the current instruction."},
        ])


@pytest.mark.parametrize("messages", [
    [{"role": "user", "content": _prompt_for("fg1") + "\n" + _prompt_for("fg2")}],
    [{"role": "user", "content": _prompt_for("fg2") + "\n" + _prompt_for("fg2")}],
])
def test_provider_rejects_ambiguous_ordinary_user_stage_instructions(messages):
    with pytest.raises(F6FixtureRejected, match="f6_stage_instruction_ambiguous"):
        _selected_instruction(messages)


def test_provider_selects_latest_ordinary_user_instruction_without_historical_stage_ambiguity():
    fg2 = _prompt_for("fg2")
    assert _selected_instruction([
        {"role": "user", "content": _prompt_for("fg1")},
        {"role": "user", "content": fg2},
    ]) == ("fg2", fg2, 1)


def test_provider_does_not_accept_non_user_stage_as_current_instruction():
    with pytest.raises(F6FixtureRejected, match="f6_instruction_role_invalid"):
        _selected_instruction([{"role": "assistant", "content": _prompt_for("fg1")}])
    with pytest.raises(F6FixtureRejected, match="provider_current_user_instruction_missing"):
        _selected_instruction([
            {"role": "user", "content": "Current user has no stage marker."},
            {"role": "assistant", "content": _prompt_for("fg1")},
        ])


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
                     if not (event.get("action") == "byq_research_get"
                             and event.get("outcome") == "success")]
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

    duplicate_audit_id = copy.deepcopy(document)
    duplicate_audit_id["events"][2]["audit_id"] = duplicate_audit_id["events"][1]["audit_id"]
    with pytest.raises(DriverContractRejected, match="structured_agent_audit_event_invalid"):
        assert_structured(duplicate_audit_id, **args)

    for unknown in (None, {}, {**settlement, "run_id": "agent_run_" + "1" * 32},
                    {**settlement, "settlement_sha256": "not-a-digest"},
                    {**settlement, "dispatch_attempts": 0},
                    {**settlement, "event_key": "ready-v1:incomplete"},
                    {**settlement, "grant_version": 2}):
        with pytest.raises(DriverContractRejected):
            validate_settlement(unknown, 1)


def test_structured_audit_accepts_direct_close_or_one_exact_completed_binding_and_rejects_event_drift():
    functions = _driver_functions()
    validate = functions["_assert_structured_agent_audit"]
    document, settlement, expected_events = _audit_fixture()
    args = {
        "stage": "background", "task_id": document["task"]["task_id"],
        "conversation_id": document["task"]["conversation_id"],
        "trace_id": document["task"]["trace_id"],
        "runtime_root_id": document["runtime_root"]["root_run_id"],
        "expected_events": expected_events, "settlement": settlement,
    }

    direct_close = validate(document, **args)
    assert direct_close["active_binding_count"] == 1
    assert direct_close["completed_binding_count"] == 0

    lifecycle_close = copy.deepcopy(document)
    completed_binding = copy.deepcopy(lifecycle_close["events"][0])
    completed_binding.update(
        audit_id="agent_audit_" + "9" * 32,
        outcome="completed",
    )
    lifecycle_close["events"].append(completed_binding)
    lifecycle_summary = validate(lifecycle_close, **args)
    assert lifecycle_summary["active_binding_count"] == 1
    assert lifecycle_summary["completed_binding_count"] == 1

    missing_domain = copy.deepcopy(document)
    missing_domain["events"] = [event for event in missing_domain["events"]
                                if not (event.get("action") == "byq_research_get"
                                        and event.get("outcome") == "success")]
    with pytest.raises(DriverContractRejected) as rejected:
        validate(missing_domain, **args)
    assert rejected.value.category == "structured_agent_audit_events_incomplete"

    wrong_domain = copy.deepcopy(document)
    wrong_domain["events"][1]["resource_id"] = "task_" + "0" * 32
    with pytest.raises(DriverContractRejected) as rejected:
        validate(wrong_domain, **args)
    assert rejected.value.category == "structured_agent_audit_actions_or_resources_invalid"

    duplicate_domain = copy.deepcopy(document)
    duplicate = copy.deepcopy(duplicate_domain["events"][1])
    duplicate["audit_id"] = "agent_audit_" + "8" * 32
    duplicate_domain["events"].append(duplicate)
    with pytest.raises(DriverContractRejected) as rejected:
        validate(duplicate_domain, **args)
    assert rejected.value.category == "structured_agent_audit_actions_or_resources_invalid"

    wrong_completed_binding = copy.deepcopy(lifecycle_close)
    wrong_completed_binding["events"][-1]["resource_id"] = "b" * 32
    with pytest.raises(DriverContractRejected) as rejected:
        validate(wrong_completed_binding, **args)
    assert rejected.value.category == "structured_agent_audit_actions_or_resources_invalid"

    wrong_completed_outcome = copy.deepcopy(lifecycle_close)
    wrong_completed_outcome["events"][-1]["outcome"] = "failed"
    with pytest.raises(DriverContractRejected) as rejected:
        validate(wrong_completed_outcome, **args)
    assert rejected.value.category == "structured_agent_audit_actions_or_resources_invalid"

    duplicate_active_binding = copy.deepcopy(document)
    repeated_active = copy.deepcopy(duplicate_active_binding["events"][0])
    repeated_active["audit_id"] = "agent_audit_" + "7" * 32
    duplicate_active_binding["events"].append(repeated_active)
    with pytest.raises(DriverContractRejected) as rejected:
        validate(duplicate_active_binding, **args)
    assert rejected.value.category == "structured_agent_audit_actions_or_resources_invalid"

    duplicate_completed_binding = copy.deepcopy(lifecycle_close)
    repeated_completed = copy.deepcopy(duplicate_completed_binding["events"][-1])
    repeated_completed["audit_id"] = "agent_audit_" + "6" * 32
    duplicate_completed_binding["events"].append(repeated_completed)
    with pytest.raises(DriverContractRejected) as rejected:
        validate(duplicate_completed_binding, **args)
    assert rejected.value.category == "structured_agent_audit_actions_or_resources_invalid"

    wrong_active_binding = copy.deepcopy(document)
    wrong_active_binding["events"][0]["resource_id"] = "c" * 32
    with pytest.raises(DriverContractRejected) as rejected:
        validate(wrong_active_binding, **args)
    assert rejected.value.category == "structured_agent_audit_actions_or_resources_invalid"


def test_structured_audit_separates_identity_mismatch_from_missing_terminal_proof():
    functions = _driver_functions()
    validate = functions["_assert_structured_agent_audit"]
    is_untrusted = functions["_is_untrusted_identity"]
    document, settlement, expected_events = _audit_fixture()
    args = {
        "stage": "background", "task_id": document["task"]["task_id"],
        "conversation_id": document["task"]["conversation_id"],
        "trace_id": document["task"]["trace_id"],
        "runtime_root_id": document["runtime_root"]["root_run_id"],
        "expected_events": expected_events, "settlement": settlement,
    }

    wrong_root = copy.deepcopy(document)
    wrong_root["runtime_root"]["owner_principal"] = "another-user"
    with pytest.raises(DriverContractRejected) as rejected:
        validate(wrong_root, **args)
    assert rejected.value.category == "structured_runtime_root_scope_invalid"
    assert is_untrusted(rejected.value.category)

    nonterminal_root = copy.deepcopy(document)
    nonterminal_root["runtime_root"].update(
        status="active", authority_status="active", terminal_sequence=None,
        terminal_event_sha256=None)
    with pytest.raises(DriverContractRejected) as rejected:
        validate(nonterminal_root, **args)
    assert rejected.value.category == "structured_runtime_root_terminal_not_confirmed"
    assert not is_untrusted(rejected.value.category)

    forged_root_identity = copy.deepcopy(document)
    forged_root_identity["runtime_root"]["root_run_id"] = "9" * 32
    with pytest.raises(DriverContractRejected) as rejected:
        validate(forged_root_identity, **args)
    assert rejected.value.category == "structured_runtime_root_identity_invalid"
    assert is_untrusted(rejected.value.category)

    forged_terminal_sequence = copy.deepcopy(document)
    forged_terminal_sequence["runtime_root"]["terminal_sequence"] = True
    with pytest.raises(DriverContractRejected) as rejected:
        validate(forged_terminal_sequence, **args)
    assert rejected.value.category == "structured_runtime_root_terminal_not_confirmed"

    wrong_run = copy.deepcopy(document)
    wrong_run["agent_run"]["root_run_id"] = "9" * 32
    with pytest.raises(DriverContractRejected) as rejected:
        validate(wrong_run, **args)
    assert rejected.value.category == "structured_agent_run_identity_invalid"
    assert is_untrusted(rejected.value.category)

    missing_event = copy.deepcopy(document)
    missing_event["events"] = [event for event in missing_event["events"]
                               if not (event.get("action") == "byq_backtest_task_get"
                                       and event.get("outcome") == "success")]
    with pytest.raises(DriverContractRejected) as rejected:
        validate(missing_event, **args)
    assert rejected.value.category == "structured_agent_audit_events_incomplete"
    assert not is_untrusted(rejected.value.category)

    wrong_event_identity = copy.deepcopy(document)
    wrong_event_identity["events"][1]["owner_principal"] = "another-user"
    with pytest.raises(DriverContractRejected) as rejected:
        validate(wrong_event_identity, **args)
    assert rejected.value.category == "structured_agent_audit_event_identity_invalid"
    assert is_untrusted(rejected.value.category)


def test_structured_audit_safe_summary_is_saved_before_incomplete_event_failure(monkeypatch):
    functions = _driver_functions()
    document, settlement, expected_events = _audit_fixture()
    incomplete = copy.deepcopy(document)
    incomplete["events"] = [event for event in incomplete["events"]
                            if not (event.get("action") == "byq_research_get"
                                    and event.get("outcome") == "success")]

    functions["subprocess"].run = lambda *_args, **_kwargs: SimpleNamespace(
        returncode=0, stdout=json.dumps(incomplete))
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "byq-ci-stack-f6-offline")
    with pytest.raises(DriverContractRejected) as rejected:
        functions["_read_structured_agent_audit"](
            "background", task_id=document["task"]["task_id"],
            conversation_id=document["task"]["conversation_id"],
            trace_id=document["task"]["trace_id"],
            runtime_root_id=document["runtime_root"]["root_run_id"],
            expected_events=expected_events, settlement=settlement, timeout=1,
        )
    assert rejected.value.category == "structured_agent_audit_events_incomplete"
    checks = functions["state"]["checks"]
    observation = checks["structured_audit_observed_background"]
    assert observation["qualification"] == "diagnostic_only_not_a_pass"
    assert observation["authority"]["root_status"] == "completed"
    assert observation["authority"]["root_authority_status"] == "closed"
    assert observation["authority"]["agent_run_status"] == "completed"
    assert observation["authority"]["agent_run_authority_status"] == "closed"
    assert observation["event_count"] == len(document["events"]) - 1
    assert observation["domain_event_multiset"]["status"] == "incomplete"
    assert observation["domain_event_multiset"]["missing"] == [{
        "action": "byq_research_get", "outcome": "success",
        "resource_type": "research_task", "resource_id": document["task"]["task_id"],
    }]
    assert functions["state"]["audit_summaries"] == {}
    assert not any("detail" in event for event in observation["events"])
    assert "prompt" not in repr(observation) and "answer" not in repr(observation)


def test_structured_audit_safe_summary_captures_extra_event_before_failure(monkeypatch):
    functions = _driver_functions()
    document, settlement, expected_events = _audit_fixture()
    unexpected = copy.deepcopy(document["events"][1])
    private_extra = "OBSERVER_PRIVATE_TEXT_" + "x" * 4096
    unexpected.update(
        audit_id="agent_audit_" + "8" * 32,
        action=private_extra,
        outcome="success",
        resource_id=private_extra,
    )
    extra = copy.deepcopy(document)
    extra["events"].append(unexpected)

    functions["subprocess"].run = lambda *_args, **_kwargs: SimpleNamespace(
        returncode=0, stdout=json.dumps(extra))
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "byq-ci-stack-f6-offline")
    with pytest.raises(DriverContractRejected) as rejected:
        functions["_read_structured_agent_audit"](
            "background", task_id=document["task"]["task_id"],
            conversation_id=document["task"]["conversation_id"],
            trace_id=document["task"]["trace_id"],
            runtime_root_id=document["runtime_root"]["root_run_id"],
            expected_events=expected_events, settlement=settlement, timeout=1,
        )
    assert rejected.value.category == "structured_agent_audit_actions_or_resources_invalid"
    observation = functions["state"]["checks"]["structured_audit_observed_background"]
    assert observation["qualification"] == "diagnostic_only_not_a_pass"
    assert observation["domain_event_multiset"]["status"] == "invalid"
    assert observation["domain_event_multiset"]["extra"] == [{
        "action": {"type": "string", "length": len(private_extra),
                   "sha256": hashlib.sha256(private_extra.encode("utf-8")).hexdigest()},
        "outcome": {"type": "string", "length": len("success"),
                    "sha256": hashlib.sha256(b"success").hexdigest()},
        "resource_type": {"type": "string", "length": len(unexpected["resource_type"]),
                          "sha256": hashlib.sha256(unexpected["resource_type"].encode("utf-8")).hexdigest()},
        "resource_id": {"type": "string", "length": len(private_extra),
                        "sha256": hashlib.sha256(private_extra.encode("utf-8")).hexdigest()},
    }]
    assert private_extra not in repr(observation)
    assert functions["state"]["audit_summaries"] == {}


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
    with pytest.raises(DriverContractRejected) as rejected:
        functions["_read_structured_agent_audit"](
            "background", task_id=document["task"]["task_id"],
            conversation_id=document["task"]["conversation_id"],
            trace_id=document["task"]["trace_id"],
            runtime_root_id=document["runtime_root"]["root_run_id"],
            expected_events=expected_events, settlement=settlement, timeout=1,
        )
    assert rejected.value.category == "structured_agent_audit_scope_mismatch"
    assert functions["_is_untrusted_identity"](rejected.value.category)
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
