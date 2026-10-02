"""Strict loopback Provider for the current keyless F6 wiring contract.

The fixture scripts two foreground Agent turns and one ADR-0090 read-only
follow-up. Every domain result comes from the real BYQ MCP/Backend path; unknown
calls, malformed results, or failed writes stop the fixture without replay.
No model/provider credential or raw prompt/result is written to logs.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from contextvars import ContextVar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


PROJECT_PATTERN = re.compile(r"byq-ci-stack-[A-Za-z0-9][A-Za-z0-9_-]{0,80}\Z")
TASK_PATTERN = re.compile(r"task_[0-9a-f]{32}\Z")
ARTIFACT_PATTERN = re.compile(r"artifact_[0-9a-f]{32}\Z")
SIGNAL_JOB_PATTERN = re.compile(r"signaljob_([0-9a-f]{32})\Z")
BACKTEST_TASK_PATTERN = re.compile(r"backtesttask_([0-9a-f]{32})\Z")
AGENT_RUN_PATTERN = re.compile(r"agent_run_[0-9a-f]{32}\Z")
AUDIT_PATTERN = re.compile(r"agent_audit_[0-9a-f]{32}\Z")
MCP_PREFIX = "mcp__byq__"

FG1_SEQUENCE = (
    "byq_agent_run_start",
    "byq_agent_authorize",
    "byq_research_task_create",
    "byq_agent_audit",
    "byq_agent_authorize",
    "byq_strategy_validate",
    "byq_agent_audit",
    "byq_agent_authorize",
    "byq_strategy_version_create",
    "byq_agent_audit",
)
FG2_SEQUENCE = (
    "byq_agent_run_start",
    "byq_agent_authorize",
    "byq_backtest_task_create",
    "byq_agent_audit",
)
BG_SEQUENCE = (
    "byq_agent_run_start",
    "byq_agent_authorize",
    "byq_research_get",
    "byq_agent_audit",
    "byq_agent_authorize",
    "byq_backtest_task_get",
    "byq_agent_audit",
)


class F6FixtureRejected(RuntimeError):
    """A fixed, sanitized category; never include prompts or tool payloads."""


def validate_environment(environment: dict[str, str] | None = None) -> str:
    env = os.environ if environment is None else environment
    project = env.get("COMPOSE_PROJECT_NAME", "")
    fixture_project = env.get("BYQ_F6_CI_PROJECT", "")
    if not PROJECT_PATTERN.fullmatch(project) or fixture_project != project:
        raise F6FixtureRejected("isolated_ci_project_required")
    if env.get("BYQ_F6_SYNTHETIC_RUNTIME") != "1":
        raise F6FixtureRejected("synthetic_runtime_flag_required")
    if env.get("DEEPSEEK_API_KEY") != "f6-synthetic-only":
        raise F6FixtureRejected("synthetic_provider_marker_required")
    return project


def _content_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts)
    return ""


def _selected_instruction(messages: object) -> tuple[str, str, int]:
    if not isinstance(messages, list):
        raise F6FixtureRejected("provider_messages_invalid")
    candidates: list[tuple[str, str, int]] = []
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        text = _content_text(message.get("content"))
        if "F6-CI:FG1" in text:
            candidates.append(("fg1", text, index))
        if "F6-CI:FG2" in text:
            candidates.append(("fg2", text, index))
        if "BYQ trusted read-only task-ready follow-up for exact task " in text:
            candidates.append(("background", text, index))
    if not candidates:
        raise F6FixtureRejected("unsupported_foreground_or_background_prompt")
    return max(candidates, key=lambda item: item[2])


def _line(prompt: str, name: str) -> str:
    matches = re.findall(rf"(?m)^{re.escape(name)}=(.*)$", prompt)
    if len(matches) != 1 or not matches[0]:
        raise F6FixtureRejected("required_prompt_field_missing")
    return matches[0]


def _json_line(prompt: str, name: str) -> dict[str, Any]:
    try:
        result = json.loads(_line(prompt, name))
    except (ValueError, TypeError):
        raise F6FixtureRejected("required_prompt_json_invalid") from None
    if not isinstance(result, dict):
        raise F6FixtureRejected("required_prompt_json_invalid")
    return result


def _background_scope(prompt: str) -> dict[str, str]:
    task_matches = re.findall(r"BYQ trusted read-only task-ready follow-up for exact task (task_[0-9a-f]{32})", prompt)
    backtest_matches = re.findall(r"Exact BacktestTask ID: (backtesttask_[0-9a-f]{32})", prompt)
    ready_matches = re.findall(r"Ready signal: (\{[^\n]+\})", prompt)
    if len(task_matches) != 1 or len(backtest_matches) != 1 or len(ready_matches) != 1:
        raise F6FixtureRejected("background_scope_missing")
    task_id, backtest_task_id = task_matches[0], backtest_matches[0]
    try:
        event = json.loads(ready_matches[0])
    except (ValueError, TypeError):
        raise F6FixtureRejected("background_ready_event_invalid") from None
    if not isinstance(event, dict):
        raise F6FixtureRejected("background_ready_event_invalid")
    job_id = event.get("identity")
    job_match = SIGNAL_JOB_PATTERN.fullmatch(job_id) if isinstance(job_id, str) else None
    snapshot_id = event.get("result_artifact_id")
    derived = "backtesttask_" + job_match.group(1) if job_match else None
    if (not TASK_PATTERN.fullmatch(task_id)
            or not BACKTEST_TASK_PATTERN.fullmatch(backtest_task_id)
            or derived != backtest_task_id
            or event.get("kind") != "signal_producer_jobs"
            or event.get("status") != "completed"
            or not isinstance(snapshot_id, str)
            or not ARTIFACT_PATTERN.fullmatch(snapshot_id)):
        raise F6FixtureRejected("background_scope_invalid")
    return {"task_id": task_id, "backtest_task_id": backtest_task_id,
            "signal_job_id": job_id, "signal_snapshot_artifact_id": snapshot_id}


def _decode_json_text(value: str) -> object | None:
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return None


def _unwrap_tool_result(value: object, *, depth: int = 0) -> dict[str, Any]:
    if depth > 8:
        raise F6FixtureRejected("mcp_result_unrecognized")
    if isinstance(value, str):
        parsed = _decode_json_text(value)
        if parsed is None:
            raise F6FixtureRejected("mcp_result_unrecognized")
        return _unwrap_tool_result(parsed, depth=depth + 1)
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                return _unwrap_tool_result(item["text"], depth=depth + 1)
        raise F6FixtureRejected("mcp_result_unrecognized")
    if not isinstance(value, dict):
        raise F6FixtureRejected("mcp_result_unrecognized")
    if value.get("isError") is True:
        raise F6FixtureRejected("mcp_tool_error")
    if value.get("service") == "beyondquant-mcp":
        return value
    if "content" in value:
        return _unwrap_tool_result(value["content"], depth=depth + 1)
    if isinstance(value.get("text"), str):
        return _unwrap_tool_result(value["text"], depth=depth + 1)
    raise F6FixtureRejected("mcp_result_unrecognized")


def _normalize_tool_result(name: str, result: dict[str, Any]) -> dict[str, Any]:
    """Separate the MCP status envelope from the two raw ResearchTask projections.

    requestResearch spreads backend payload fields after ``status: "ok"``. A
    ResearchTask's own ``planned``/``running`` status therefore occupies the
    envelope's status key. Accept only those tool-specific current shapes and
    restore an explicit MCP success envelope around the exact task projection.
    """
    if result.get("service") != "beyondquant-mcp":
        raise F6FixtureRejected("mcp_result_unrecognized")
    status = result.get("status")
    if name == "byq_research_task_create":
        if status != "planned" or not TASK_PATTERN.fullmatch(str(result.get("task_id", ""))):
            raise F6FixtureRejected("mcp_tool_error")
        task = {key: value for key, value in result.items() if key not in {"service", "status"}}
        return {"service": "beyondquant-mcp", "status": "ok", "task": {**task, "status": status}}
    if name == "byq_research_get":
        if status == "ok":
            task = result.get("task")
            if (not isinstance(task, dict) or task.get("status") not in {"planned", "running"}
                    or not TASK_PATTERN.fullmatch(str(task.get("task_id", "")))):
                raise F6FixtureRejected("mcp_result_unrecognized")
            return result
        if status in {"planned", "running"} and TASK_PATTERN.fullmatch(str(result.get("task_id", ""))):
            task = {key: value for key, value in result.items() if key not in {"service", "status"}}
            return {"service": "beyondquant-mcp", "status": "ok", "task": {**task, "status": status}}
        raise F6FixtureRejected("mcp_tool_error")
    if status != "ok":
        raise F6FixtureRejected("mcp_tool_error")
    return result


def _field(value: object, key: str, *, depth: int = 0) -> object | None:
    if depth > 10:
        return None
    if isinstance(value, dict):
        if key in value:
            return value[key]
        for child in value.values():
            found = _field(child, key, depth=depth + 1)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _field(child, key, depth=depth + 1)
            if found is not None:
                return found
    return None


def _required_string(value: object, key: str, pattern: re.Pattern[str]) -> str:
    item = _field(value, key)
    if not isinstance(item, str) or not pattern.fullmatch(item):
        raise F6FixtureRejected("mcp_identity_missing_or_invalid")
    return item


def _mcp_records(messages: list[object], instruction_index: int) -> list[dict[str, Any]]:
    pending: dict[str, tuple[str, dict[str, Any]]] = {}
    records: list[dict[str, Any]] = []
    for message in messages[instruction_index + 1:]:
        if not isinstance(message, dict):
            continue
        if message.get("role") == "assistant":
            calls = message.get("tool_calls", [])
            if calls is None:
                calls = []
            if not isinstance(calls, list):
                raise F6FixtureRejected("provider_tool_history_invalid")
            for call in calls:
                if not isinstance(call, dict) or not isinstance(call.get("id"), str):
                    raise F6FixtureRejected("provider_tool_history_invalid")
                function = call.get("function")
                if not isinstance(function, dict) or not isinstance(function.get("name"), str):
                    raise F6FixtureRejected("provider_tool_history_invalid")
                name = function["name"]
                if not name.startswith(MCP_PREFIX):
                    raise F6FixtureRejected("non_mcp_tool_in_f6_turn")
                try:
                    arguments = json.loads(function.get("arguments", "{}"))
                except (TypeError, ValueError):
                    raise F6FixtureRejected("provider_tool_arguments_invalid") from None
                if not isinstance(arguments, dict) or call["id"] in pending:
                    raise F6FixtureRejected("provider_tool_arguments_invalid")
                pending[call["id"]] = (name.removeprefix(MCP_PREFIX), arguments)
        elif message.get("role") == "tool":
            call_id = message.get("tool_call_id")
            if not isinstance(call_id, str) or call_id not in pending:
                raise F6FixtureRejected("provider_tool_history_invalid")
            name, arguments = pending.pop(call_id)
            result = _normalize_tool_result(name, _unwrap_tool_result(message.get("content")))
            records.append({"name": name, "arguments": arguments, "result": result})
    if pending:
        # A lost/unknown MCP response is never permission to emit that call again.
        raise F6FixtureRejected("mcp_action_outcome_unconfirmed")
    return records


def _result(records: list[dict[str, Any]], name: str) -> dict[str, Any]:
    matches = [row["result"] for row in records if row["name"] == name]
    if len(matches) != 1:
        raise F6FixtureRejected("mcp_action_result_ambiguous")
    return matches[0]


def _run_id(records: list[dict[str, Any]]) -> str:
    run = _field(_result(records, "byq_agent_run_start"), "run")
    run_id = run.get("run_id") if isinstance(run, dict) else None
    if not isinstance(run_id, str) or not AGENT_RUN_PATTERN.fullmatch(run_id):
        raise F6FixtureRejected("agent_run_not_registered")
    if run.get("status") != "active":
        raise F6FixtureRejected("agent_run_not_active")
    return run_id


def _authorize(row: dict[str, Any], records: list[dict[str, Any]], action: str) -> None:
    if row.get("name") != "byq_agent_authorize":
        raise F6FixtureRejected("agent_authorization_sequence_invalid")
    result = row.get("result")
    authorization = _field(result, "authorization")
    if (not isinstance(authorization, dict) or authorization.get("decision") != "allowed"
            or authorization.get("authorized") is not True
            or authorization.get("action") != action
            or authorization.get("run_id") != _run_id(records)):
        raise F6FixtureRejected("agent_action_not_authorized")


def _verify_agent_audit_result(row: dict[str, Any], records: list[dict[str, Any]]) -> None:
    arguments = row.get("arguments")
    result = row.get("result")
    audit = result.get("audit") if isinstance(result, dict) else None
    if not isinstance(arguments, dict) or not isinstance(audit, dict):
        raise F6FixtureRejected("agent_audit_result_missing")
    expected = {
        "run_id": _run_id(records),
        "owner_principal": "f6-chain-user",
        "action": arguments.get("action"),
        "outcome": arguments.get("outcome"),
        "resource_type": arguments.get("resource_type"),
        "resource_id": arguments.get("resource_id"),
    }
    if (not isinstance(audit.get("audit_id"), str) or not AUDIT_PATTERN.fullmatch(audit["audit_id"])
            or not isinstance(audit.get("actor_principal"), str)
            or not audit["actor_principal"].startswith("byq-product-agent-byq-session-")
            or any(audit.get(key) != value for key, value in expected.items())):
        raise F6FixtureRejected("agent_audit_result_scope_mismatch")


def _strategy(prompt: str) -> dict[str, Any]:
    value = _json_line(prompt, "strategy_json")
    if (value.get("strategy_id") != "F6SyntheticSignal"
            or value.get("category") != "momentum"
            or value.get("data_requirements") not in (None, {})):
        raise F6FixtureRejected("strategy_scope_invalid")
    return value


def _fg1_arguments(index: int, prompt: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    run_id = _run_id(records) if index >= 1 else None
    if index == 0:
        return {"role_id": "quant_orchestrator", "idempotency_key": "f6-ci-fg1-agent-run"}
    if index == 1:
        return {"run_id": run_id, "action": "byq_research_task_create"}
    if index == 2:
        return {
            "owner_principal": _line(prompt, "owner_principal"),
            "title": _line(prompt, "task_title"),
            "objective": _line(prompt, "task_objective"),
            "trace_id": _line(prompt, "session_trace_id"),
            "idempotency_key": _line(prompt, "task_create_idempotency_key"),
        }
    if index == 3:
        task = _required_string(_result(records, "byq_research_task_create"), "task_id", TASK_PATTERN)
        return {"run_id": run_id, "action": "byq_research_task_create", "outcome": "success",
                "resource_type": "research_task", "resource_id": task}
    if index == 4:
        return {"run_id": run_id, "action": "byq_strategy_validate"}
    if index == 5:
        task = _required_string(_result(records, "byq_research_task_create"), "task_id", TASK_PATTERN)
        return {"task_id": task, "trace_id": _line(prompt, "session_trace_id"),
                "idempotency_key": _line(prompt, "strategy_validate_idempotency_key"),
                "agent_run_id": run_id, "strategy": _strategy(prompt)}
    if index == 6:
        draft = _required_string(_result(records, "byq_strategy_validate"), "artifact_id", ARTIFACT_PATTERN)
        return {"run_id": run_id, "action": "byq_strategy_validate", "outcome": "success",
                "resource_type": "strategy_draft", "resource_id": draft}
    if index == 7:
        return {"run_id": run_id, "action": "byq_strategy_version_create"}
    if index == 8:
        task = _required_string(_result(records, "byq_research_task_create"), "task_id", TASK_PATTERN)
        draft = _required_string(_result(records, "byq_strategy_validate"), "artifact_id", ARTIFACT_PATTERN)
        return {"task_id": task, "draft_artifact_id": draft, "trace_id": _line(prompt, "session_trace_id"),
                "idempotency_key": _line(prompt, "strategy_version_idempotency_key"),
                "agent_run_id": run_id}
    if index == 9:
        task = _required_string(_result(records, "byq_research_task_create"), "task_id", TASK_PATTERN)
        version = _required_string(_result(records, "byq_strategy_version_create"), "artifact_id", ARTIFACT_PATTERN)
        return {"run_id": run_id, "action": "byq_strategy_version_create", "outcome": "success",
                "resource_type": "strategy_version", "resource_id": version}
    raise F6FixtureRejected("fg1_sequence_exceeded")


def _fg2_scope(prompt: str) -> dict[str, Any]:
    fields = {
        "task_id": _line(prompt, "task_id"),
        "strategy_version_artifact_id": _line(prompt, "strategy_version_artifact_id"),
        "approval_artifact_id": _line(prompt, "approval_artifact_id"),
        "stock_pool_snapshot_id": _line(prompt, "stock_pool_snapshot_id"),
        "start_date": _line(prompt, "start_date"),
        "end_date": _line(prompt, "end_date"),
        "parameters": _json_line(prompt, "parameters"),
        "execution": _json_line(prompt, "execution"),
        "order_quantity": int(_line(prompt, "order_quantity")),
    }
    if (not TASK_PATTERN.fullmatch(fields["task_id"])
            or not ARTIFACT_PATTERN.fullmatch(fields["strategy_version_artifact_id"])
            or not ARTIFACT_PATTERN.fullmatch(fields["approval_artifact_id"])
            or not fields["stock_pool_snapshot_id"].startswith("stock_pool_snapshot_")
            or fields["start_date"] != "2026-03-12"
            or fields["end_date"] != "2026-03-30"
            or fields["order_quantity"] != 100):
        raise F6FixtureRejected("fg2_scope_invalid")
    return fields


def _fg2_arguments(index: int, prompt: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    run_id = _run_id(records) if index >= 1 else None
    if index == 0:
        return {"role_id": "quant_orchestrator", "idempotency_key": "f6-ci-fg2-agent-run"}
    if index == 1:
        return {"run_id": run_id, "action": "byq_backtest_task_create"}
    if index == 2:
        scope = _fg2_scope(prompt)
        return {
            **{key: value for key, value in scope.items() if key != "approval_artifact_id"},
            "idempotency_key": _line(prompt, "backtest_task_idempotency_key"),
        }
    if index == 3:
        task = _fg2_scope(prompt)["task_id"]
        result = _result(records, "byq_backtest_task_create")
        backtest_task = _required_string(result, "backtest_task_id", BACKTEST_TASK_PATTERN)
        return {"run_id": run_id, "action": "byq_backtest_task_create", "outcome": "success",
                "resource_type": "backtest_task", "resource_id": backtest_task}
    raise F6FixtureRejected("fg2_sequence_exceeded")


def _bg_arguments(index: int, scope: dict[str, str], records: list[dict[str, Any]]) -> dict[str, Any]:
    run_id = _run_id(records) if index >= 1 else None
    if index == 0:
        return {"role_id": "quant_orchestrator", "idempotency_key": "f6-ci-bg-agent-run"}
    if index == 1:
        return {"run_id": run_id, "action": "byq_research_get",
                "resource_type": "research_task", "resource_id": scope["task_id"]}
    if index == 2:
        return {"entity_type": "research_task", "entity_id": scope["task_id"]}
    if index == 3:
        return {"run_id": run_id, "action": "byq_research_get", "outcome": "success",
                "resource_type": "research_task", "resource_id": scope["task_id"]}
    if index == 4:
        return {"run_id": run_id, "action": "byq_backtest_task_get",
                "resource_type": "backtest_task", "resource_id": scope["backtest_task_id"]}
    if index == 5:
        return {"backtest_task_id": scope["backtest_task_id"]}
    if index == 6:
        return {"run_id": run_id, "action": "byq_backtest_task_get", "outcome": "success",
                "resource_type": "backtest_task", "resource_id": scope["backtest_task_id"]}
    raise F6FixtureRejected("background_sequence_exceeded")


def _verify_result(stage: str, index: int, records: list[dict[str, Any]], scope: dict[str, Any]) -> None:
    row = records[index]
    if row["name"] == "byq_agent_run_start":
        _run_id(records[:index + 1])
    elif row["name"] == "byq_agent_authorize":
        expected_actions = {
            "fg1": ("byq_research_task_create", "byq_strategy_validate", "byq_strategy_version_create"),
            "fg2": ("byq_backtest_task_create",),
            "background": ("byq_research_get", "byq_backtest_task_get"),
        }[stage]
        authorization_index = sum(item["name"] == "byq_agent_authorize" for item in records[:index])
        if authorization_index >= len(expected_actions):
            raise F6FixtureRejected("agent_authorization_sequence_invalid")
        _authorize(row, records[:index + 1], expected_actions[authorization_index])
    elif row["name"] == "byq_agent_audit":
        _verify_agent_audit_result(row, records[:index + 1])
    elif row["name"] == "byq_research_task_create":
        task = row["result"].get("task")
        if not isinstance(task, dict) or task.get("status") != "planned":
            raise F6FixtureRejected("research_task_create_result_invalid")
        task_id = _required_string(task, "task_id", TASK_PATTERN)
        if (task.get("conversation_id") != _line(scope["prompt"], "conversation_id")
                or task.get("trace_id") != _line(scope["prompt"], "session_trace_id")
                or task.get("owner_principal") != _line(scope["prompt"], "owner_principal")):
            raise F6FixtureRejected("research_task_lineage_invalid")
        scope["task_id"] = task_id
    elif row["name"] == "byq_strategy_validate":
        artifact = _field(row["result"], "artifact")
        if not isinstance(artifact, dict):
            raise F6FixtureRejected("strategy_draft_not_validated")
        draft = _required_string(artifact, "artifact_id", ARTIFACT_PATTERN)
        if (artifact.get("kind") != "strategy_draft" or artifact.get("status") != "validated"
                or artifact.get("task_id") != scope["task_id"]):
            raise F6FixtureRejected("strategy_draft_not_validated")
        scope["draft_artifact_id"] = draft
    elif row["name"] == "byq_strategy_version_create":
        artifact = _field(row["result"], "artifact")
        if not isinstance(artifact, dict):
            raise F6FixtureRejected("strategy_version_not_validated")
        version = _required_string(artifact, "artifact_id", ARTIFACT_PATTERN)
        lineage = artifact.get("lineage")
        if (artifact.get("kind") != "strategy_version" or artifact.get("status") != "validated"
                or artifact.get("task_id") != scope["task_id"]
                or not isinstance(lineage, list)
                or not any(isinstance(item, dict) and item.get("kind") == "artifact"
                           and item.get("id") == scope["draft_artifact_id"] for item in lineage)):
            raise F6FixtureRejected("strategy_version_not_validated")
        scope["strategy_version_artifact_id"] = version
    elif row["name"] == "byq_backtest_task_create":
        task = _required_string(row["result"], "backtest_task_id", BACKTEST_TASK_PATTERN)
        job = _required_string(row["result"], "signal_producer_job_id", SIGNAL_JOB_PATTERN)
        if task != "backtesttask_" + SIGNAL_JOB_PATTERN.fullmatch(job).group(1):
            raise F6FixtureRejected("signal_job_task_link_invalid")
        references = _field(row["result"], "references")
        if not isinstance(references, dict) or any(references.get(key) != expected for key, expected in (
            ("research_task_id", scope["task_id"]),
            ("strategy_version_artifact_id", scope["strategy_version_artifact_id"]),
            ("approval_artifact_id", scope["approval_artifact_id"]),
            ("stock_pool_snapshot_id", scope["stock_pool_snapshot_id"]),
            ("signal_producer_job_id", job),
        )):
            raise F6FixtureRejected("backtest_task_lineage_invalid")
        scope["backtest_task_id"], scope["signal_job_id"] = task, job
    elif row["name"] == "byq_research_get" and stage == "background":
        result_task = _field(row["result"], "task")
        if (not isinstance(result_task, dict)
                or _required_string(result_task, "task_id", TASK_PATTERN) != scope["task_id"]
                or result_task.get("status") not in {"planned", "running"}):
            raise F6FixtureRejected("background_research_read_out_of_scope")
    elif row["name"] == "byq_backtest_task_get" and stage == "background":
        result_task = _required_string(row["result"], "backtest_task_id", BACKTEST_TASK_PATTERN)
        if result_task != scope["backtest_task_id"]:
            raise F6FixtureRejected("background_backtest_read_out_of_scope")
        references = _field(row["result"], "references")
        if not isinstance(references, dict) or (
            references.get("research_task_id") != scope["task_id"]
            or references.get("signal_producer_job_id") != scope["signal_job_id"]
            or references.get("signal_snapshot_artifact_id") != scope["signal_snapshot_artifact_id"]
        ):
            raise F6FixtureRejected("background_ready_result_mismatch")


def _sequence_for(stage: str) -> tuple[str, ...]:
    return {"fg1": FG1_SEQUENCE, "fg2": FG2_SEQUENCE, "background": BG_SEQUENCE}[stage]


def _args_for(stage: str, index: int, prompt: str, records: list[dict[str, Any]],
              bg_scope: dict[str, str] | None) -> dict[str, Any]:
    if stage == "fg1":
        return _fg1_arguments(index, prompt, records)
    if stage == "fg2":
        return _fg2_arguments(index, prompt, records)
    if bg_scope is None:
        raise F6FixtureRejected("background_scope_missing")
    return _bg_arguments(index, bg_scope, records)


def _final_answer(stage: str, prompt: str, records: list[dict[str, Any]],
                  bg_scope: dict[str, str] | None) -> str:
    if stage == "fg1":
        task_id = _required_string(_result(records, "byq_research_task_create"), "task_id", TASK_PATTERN)
        draft = _field(_result(records, "byq_strategy_validate"), "artifact")
        version = _field(_result(records, "byq_strategy_version_create"), "artifact")
        if not isinstance(draft, dict) or not isinstance(version, dict):
            raise F6FixtureRejected("strategy_artifacts_missing")
        draft_id = _required_string(draft, "artifact_id", ARTIFACT_PATTERN)
        version_id = _required_string(version, "artifact_id", ARTIFACT_PATTERN)
        return (f"F6 foreground 1 saved ResearchTask {task_id}, StrategyDraft {draft_id}, and validated "
                f"StrategyVersion {version_id} in this conversation.")
    if stage == "fg2":
        created = _result(records, "byq_backtest_task_create")
        task_id = _required_string(created, "backtest_task_id", BACKTEST_TASK_PATTERN)
        job_id = _required_string(created, "signal_producer_job_id", SIGNAL_JOB_PATTERN)
        return f"F6 foreground 2 admitted BacktestTask {task_id} with SignalJob {job_id}; signal production is pending."
    if bg_scope is None:
        raise F6FixtureRejected("background_scope_missing")
    return (
        f"F6 read-only follow-up verified ResearchTask {bg_scope['task_id']} and "
        f"BacktestTask {bg_scope['backtest_task_id']} for SignalJob {bg_scope['signal_job_id']} "
        f"with validated signal Artifact {bg_scope['signal_snapshot_artifact_id']}. No domain writes were made."
    )


def next_action(body: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    messages = body.get("messages")
    stage, prompt, instruction_index = _selected_instruction(messages)
    if not isinstance(messages, list):
        raise F6FixtureRejected("provider_messages_invalid")
    bg_scope = _background_scope(prompt) if stage == "background" else None
    records = _mcp_records(messages, instruction_index)
    sequence = _sequence_for(stage)
    if len(records) > len(sequence):
        raise F6FixtureRejected("f6_tool_sequence_exceeded")
    if stage == "fg1":
        scope: dict[str, Any] = {"prompt": prompt}
    elif stage == "fg2":
        scope = _fg2_scope(prompt)
    else:
        scope = dict(bg_scope or {})
    for index, record in enumerate(records):
        if record["name"] != sequence[index]:
            raise F6FixtureRejected("unexpected_f6_tool_sequence")
        expected_args = _args_for(stage, index, prompt, records[:index], bg_scope)
        if record["arguments"] != expected_args:
            raise F6FixtureRejected("unexpected_f6_tool_arguments")
        _verify_result(stage, index, records, scope)
    if len(records) == len(sequence):
        _final_answer(stage, prompt, records, bg_scope)
        return None
    name = sequence[len(records)]
    arguments = _args_for(stage, len(records), prompt, records, bg_scope)
    available = body.get("tools")
    offered = {
        item.get("function", {}).get("name")
        for item in available if isinstance(item, dict) and isinstance(item.get("function"), dict)
    } if isinstance(available, list) else set()
    full_name = MCP_PREFIX + name
    if full_name not in offered:
        raise F6FixtureRejected("required_mcp_tool_not_offered")
    return full_name, arguments


def _sse_completion(body: dict[str, Any], action: tuple[str, dict[str, Any]] | None) -> bytes:
    completion_id = "chatcmpl-f6-" + hashlib.sha256(
        json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:24]
    created = int(time.time())
    if action is None:
        stage, prompt, instruction_index = _selected_instruction(body.get("messages"))
        messages = body.get("messages")
        if not isinstance(messages, list):
            raise F6FixtureRejected("provider_messages_invalid")
        bg_scope = _background_scope(prompt) if stage == "background" else None
        delta: dict[str, Any] = {"content": _final_answer(
            stage, prompt, _mcp_records(messages, instruction_index), bg_scope)}
        finish_reason = "stop"
    else:
        name, arguments = action
        call_id = "call_" + hashlib.sha256(
            (completion_id + name + json.dumps(arguments, sort_keys=True)).encode("utf-8")
        ).hexdigest()[:24]
        delta = {"tool_calls": [{"index": 0, "id": call_id, "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False, sort_keys=True)}}]}
        finish_reason = "tool_calls"
    chunks = [
        {"id": completion_id, "object": "chat.completion.chunk", "created": created,
         "model": "deepseek-v4-flash", "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
        {"id": completion_id, "object": "chat.completion.chunk", "created": created,
         "model": "deepseek-v4-flash", "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}]},
    ]
    # No provider usage is fabricated. ADR-0090 records actual usage as unknown
    # while the real RequestGateProxy still measures request attempts and inputs.
    return ("".join("data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n" for chunk in chunks)
            + "data: [DONE]\n\n").encode("utf-8")


def _install_f6_provider_routes(loopback_url: str) -> None:
    import app.runtime as runtime_module

    if re.fullmatch(r"http://127\.0\.0\.1:[0-9]{1,5}", loopback_url) is None:
        raise F6FixtureRejected("synthetic_provider_must_bind_loopback")

    proxy_type = runtime_module.RequestGateProxy
    original_init = proxy_type.__init__

    def init_with_local_upstream(self: Any, gate: object, upstream: str) -> None:
        original_init(self, gate, upstream)
        if upstream.rstrip("/") != "https://api.deepseek.com":
            raise F6FixtureRejected("continuation_proxy_official_upstream_required")
        # Preserve the actual RequestGateProxy, request gate, handler and journal;
        # only replace its official network destination with this test process.
        self._upstream = loopback_url.rstrip("/")
        self._server.upstream = self._upstream

    proxy_type.__init__ = init_with_local_upstream

    # Foreground roots do not own a RequestGateProxy. Route only their copied
    # child environment to the test Provider. Background roots retain the
    # Runtime Adapter's exact metering proxy URL, guard patch, and handler.
    adapter_type = runtime_module.RuntimeAdapter
    original_build = adapter_type._build_harness
    compatibility_sample = runtime_module.compatibility_for_release(
        os.environ.get("BYQ_DSH_COMPATIBILITY_RELEASE", "dsh-0.1.2rc1"))
    compatibility_type = type(compatibility_sample)
    original_compatibility_build = compatibility_type.build_harness
    route_context: ContextVar[tuple[str | None, bool] | None] = ContextVar(
        "f6_synthetic_provider_route", default=None)

    def build_under_selected_route(self: Any, *args: Any, **kwargs: Any) -> Any:
        selected = route_context.get()
        if selected is None:
            return original_compatibility_build(self, *args, **kwargs)
        continuation_proxy_url, continuation_enabled = selected
        environment = kwargs.get("environment")
        if not isinstance(environment, dict):
            raise F6FixtureRejected("runtime_child_environment_missing")
        max_tokens = kwargs.get("max_tokens")
        routed_environment = dict(environment)
        if continuation_proxy_url is None:
            if continuation_enabled or max_tokens is not None or "DEEPSEEK_BASE_URL" in environment:
                raise F6FixtureRejected("foreground_request_gate_state_invalid")
            routed_environment["DEEPSEEK_BASE_URL"] = loopback_url
        else:
            if (not continuation_enabled or max_tokens is None
                    or environment.get("DEEPSEEK_BASE_URL") != continuation_proxy_url
                    or continuation_proxy_url == loopback_url):
                raise F6FixtureRejected("background_request_gate_proxy_not_preserved")
        kwargs["environment"] = routed_environment
        return original_compatibility_build(self, *args, **kwargs)

    def build_f6_harness(self: Any, *args: Any, **kwargs: Any) -> Any:
        continuation_proxy_url = kwargs.get("continuation_proxy_url")
        continuation_budget = kwargs.get("continuation_budget")
        continuation_deadline = kwargs.get("continuation_deadline_epoch_ms")
        if continuation_proxy_url is None:
            if continuation_budget is not None or continuation_deadline is not None:
                raise F6FixtureRejected("foreground_request_gate_state_invalid")
        elif (continuation_budget is None or continuation_deadline is None
              or not isinstance(continuation_proxy_url, str)
              or re.fullmatch(r"http://127\.0\.0\.1:[0-9]{1,5}", continuation_proxy_url) is None
              or continuation_proxy_url == loopback_url):
            raise F6FixtureRejected("background_request_gate_proxy_not_preserved")
        token = route_context.set((continuation_proxy_url, continuation_budget is not None))
        try:
            return original_build(self, *args, **kwargs)
        finally:
            route_context.reset(token)

    compatibility_type.build_harness = build_under_selected_route
    adapter_type._build_harness = build_f6_harness


def main() -> None:
    validate_environment()

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *_: object) -> None:
            return

        def do_POST(self) -> None:
            try:
                length = int(self.headers.get("content-length", "0"))
                if length <= 0 or length > 2 * 1024 * 1024:
                    raise F6FixtureRejected("provider_request_size_invalid")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise F6FixtureRejected("provider_request_invalid")
                action = next_action(body)
                response = _sse_completion(body, action)
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.send_header("content-length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)
            except Exception as exc:
                # Never include prompts, cookies, credentials, MCP arguments or
                # raw responses in logs or the error body.
                print("f6 scripted provider rejected request: " + type(exc).__name__, flush=True)
                try:
                    self.send_error(400, "synthetic F6 contract rejected the request")
                except OSError:
                    pass

        def do_GET(self) -> None:
            self.send_error(405, "method not allowed")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    loopback_url = f"http://127.0.0.1:{server.server_port}"
    try:
        _install_f6_provider_routes(loopback_url)
        from app import main as runtime_main
        import uvicorn

        uvicorn.run(runtime_main.app, host="0.0.0.0", port=8400)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()
