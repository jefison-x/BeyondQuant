"""Strict loopback Provider for the current keyless F6 wiring contract.

The fixture scripts two foreground Agent turns and one ADR-0090 read-only
follow-up. Every domain result comes from the real BYQ MCP/Backend path; unknown
calls, malformed results, or failed writes stop the fixture without replay.
No model/provider credential or raw prompt/result is written to logs.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
import threading
import time
from contextvars import ContextVar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


PROJECT_PATTERN = re.compile(r"byq-ci-stack-[A-Za-z0-9][A-Za-z0-9_-]{0,80}\Z")
TASK_PATTERN = re.compile(r"task_[0-9a-f]{32}\Z")
ARTIFACT_PATTERN = re.compile(r"artifact_[0-9a-f]{32}\Z")
SIGNAL_JOB_PATTERN = re.compile(r"signaljob_([0-9a-f]{32})\Z")
BACKTEST_TASK_PATTERN = re.compile(r"backtesttask_([0-9a-f]{32})\Z")
AGENT_RUN_PATTERN = re.compile(r"agent_run_[0-9a-f]{32}\Z")
AUDIT_PATTERN = re.compile(r"agent_audit_[0-9a-f]{32}\Z")
MCP_PREFIX = "mcp__byq__"
_REHYDRATION_OPEN = "[BYQ_CONVERSATION_REHYDRATION]"
_REHYDRATION_CLOSE = "[/BYQ_CONVERSATION_REHYDRATION]"
_CURRENT_USER_OPEN = "[CURRENT_USER_MESSAGE]"
_CURRENT_USER_CLOSE = "[/CURRENT_USER_MESSAGE]"
_REHYDRATION_SCHEMA_VERSION = "conversation-rehydration.v1"
_RUNTIME_SNAPSHOT_PREFIX = (
    "Current runtime context. This snapshot supersedes earlier runtime-context snapshots.\n\n"
)
_SKILL_CATALOG_HEADER = (
    "<system-reminder>\n"
    "A skill is a reusable set of task-specific instructions. The following skills are available in this session:\n\n"
    "<available_skills>\n"
)
_SKILL_CATALOG_FOOTER = (
    "\n</available_skills>\n\n"
    "If the user names a skill, or the task clearly matches a skill's description, call the `skill` tool with the exact skill name before taking task actions. Load all applicable skills, then follow their full instructions. This catalog contains summaries only; do not infer or follow a skill's instructions until it has been loaded.\n"
    "A user may also invoke a skill directly; its <skill_content> block then appears in this conversation. Follow it, and do not call the `skill` tool again for that skill.\n"
    "</system-reminder>"
)
_BACKGROUND_INSTRUCTION_PREFIX = "BYQ trusted read-only task-ready follow-up for exact task "
_BACKGROUND_INSTRUCTION_TEMPLATE = (
    _BACKGROUND_INSTRUCTION_PREFIX + "{task_id}. "
    'First call byq_agent_run_start with role_id "quant_orchestrator" and idempotency key "task-ready-run-{signal_job_id}" to bind this turn. '
    'Then follow the existing role contract: call byq_agent_authorize with action exactly "byq_research_get" before byq_research_get and with action exactly "byq_backtest_task_get" before byq_backtest_task_get, and byq_agent_audit with the same exact action and bounded outcome after each read. '
    "Use byq_research_get to read this exact ResearchTask and byq_backtest_task_get "
    "to read the exact BacktestTask linked to the completed ready signal below. "
    "Exact BacktestTask ID: {backtest_task_id}. "
    "Do not create or update domain objects, request approvals, execute jobs, browse the web, "
    "delegate, or access another task. Summarize only facts returned by these exact read tools. "
    "Ready signal: {ready_signal}"
)
DIAGNOSTIC_PATH = "/tmp/byq-f6-provider-diagnostics.jsonl"
DIAGNOSTIC_SCHEMA_VERSION = "byq.f6.synthetic-provider-diagnostic.v1"
DIAGNOSTIC_MAX_RECORDS = 256
DIAGNOSTIC_STAGES = frozenset({"fg1", "fg2", "background", "unknown"})
DIAGNOSTIC_OUTCOMES = frozenset({
    "response_written", "fixture_rejected", "request_rejected", "handler_error",
})
DIAGNOSTIC_RESPONSE_KINDS = frozenset({"tool_call", "completion", "none"})
_SKILL_CATALOG_EMPTY_UPDATE = (
    "<system-reminder>\n"
    "The available skill catalog changed. This complete catalog replaces every earlier available-skills list in this session:\n\n"
    "<available_skills>\n"
    "</available_skills>\n\n"
    "No skills are currently available through the `skill` tool. Do not use names from earlier skill catalogs.\n"
    "A user may still invoke a skill directly; its <skill_content> block then appears in this conversation. Follow it, and do not call the `skill` tool for it.\n"
    "</system-reminder>"
)


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


FIXTURE_REJECTION_CODES = frozenset({
    "agent_action_not_authorized",
    "agent_audit_result_missing",
    "agent_audit_result_scope_mismatch",
    "agent_authorization_sequence_invalid",
    "agent_run_not_active",
    "agent_run_not_registered",
    "background_backtest_read_out_of_scope",
    "background_ready_event_invalid",
    "background_ready_result_mismatch",
    "background_request_gate_proxy_not_preserved",
    "background_research_read_out_of_scope",
    "background_scope_invalid",
    "background_scope_missing",
    "background_sequence_exceeded",
    "backtest_task_lineage_invalid",
    "continuation_proxy_official_upstream_required",
    "f6_instruction_role_invalid",
    "f6_stage_instruction_ambiguous",
    "f6_tool_sequence_exceeded",
    "fg1_sequence_exceeded",
    "fg2_scope_invalid",
    "fg2_sequence_exceeded",
    "foreground_request_gate_state_invalid",
    "isolated_ci_project_required",
    "mcp_action_outcome_unconfirmed",
    "mcp_action_result_ambiguous",
    "mcp_identity_missing_or_invalid",
    "mcp_result_unrecognized",
    "mcp_tool_error",
    "non_mcp_tool_in_f6_turn",
    "provider_current_user_instruction_missing",
    "provider_current_user_message_missing",
    "provider_diagnostics_file_invalid",
    "provider_messages_invalid",
    "provider_request_invalid",
    "provider_request_size_invalid",
    "provider_supplemental_context_marker_rejected",
    "provider_tool_arguments_invalid",
    "provider_tool_history_invalid",
    "rehydrated_current_message_malformed",
    "required_mcp_tool_not_offered",
    "required_prompt_field_missing",
    "required_prompt_json_invalid",
    "research_task_create_result_invalid",
    "research_task_lineage_invalid",
    "runtime_child_environment_missing",
    "signal_job_task_link_invalid",
    "strategy_artifacts_missing",
    "strategy_draft_not_validated",
    "strategy_scope_invalid",
    "strategy_version_not_validated",
    "synthetic_provider_marker_required",
    "synthetic_provider_must_bind_loopback",
    "synthetic_runtime_flag_required",
    "unexpected_f6_tool_arguments",
    "unexpected_f6_tool_sequence",
    "unsupported_foreground_or_background_prompt",
})
DIAGNOSTIC_REJECTION_CODES = FIXTURE_REJECTION_CODES | {"unclassified_fixture_rejection"}


def _diagnostic_rejection_code(exc: F6FixtureRejected) -> str:
    category = exc.args[0] if len(exc.args) == 1 else None
    if type(category) is str and category in FIXTURE_REJECTION_CODES:
        return category
    return "unclassified_fixture_rejection"


class _ProviderDiagnostics:
    """Bounded private JSONL evidence for actual loopback Provider dispatches."""

    def __init__(self, descriptor: int) -> None:
        self._descriptor = descriptor
        self._lock = threading.Lock()
        self._dispatches_seen = 0
        self._rows_written = 0
        self._overflow_written = False

    @classmethod
    def create(cls, path: str = DIAGNOSTIC_PATH) -> "_ProviderDiagnostics":
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, 0o600)
        try:
            metadata = os.fstat(descriptor)
            if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
                    or stat.S_IMODE(metadata.st_mode) != 0o600):
                raise F6FixtureRejected("provider_diagnostics_file_invalid")
        except BaseException:
            os.close(descriptor)
            raise
        return cls(descriptor)

    @staticmethod
    def _write_line(descriptor: int, record: dict[str, Any]) -> None:
        payload = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])

    def record_dispatch(self, *, stage: str, outcome: str, response_kind: str,
                        rejection_code: str | None, tool_call_count: int) -> None:
        with self._lock:
            self._dispatches_seen = min(self._dispatches_seen + 1, DIAGNOSTIC_MAX_RECORDS)
            if self._rows_written < DIAGNOSTIC_MAX_RECORDS - 1:
                safe_stage = stage if stage in DIAGNOSTIC_STAGES else "unknown"
                safe_outcome = outcome if outcome in DIAGNOSTIC_OUTCOMES else "handler_error"
                safe_response_kind = (response_kind if response_kind in DIAGNOSTIC_RESPONSE_KINDS
                                      else "none")
                safe_code = (rejection_code if type(rejection_code) is str
                             and rejection_code in DIAGNOSTIC_REJECTION_CODES else None)
                count_is_bounded = type(tool_call_count) is int and 0 <= tool_call_count <= 256
                safe_tool_count = tool_call_count if count_is_bounded else 256
                self._write_line(self._descriptor, {
                    "schema_version": DIAGNOSTIC_SCHEMA_VERSION,
                    "record_type": "dispatch",
                    "sequence": self._dispatches_seen,
                    "stage": safe_stage,
                    "outcome": safe_outcome,
                    "response_kind": safe_response_kind,
                    "rejection_code": safe_code,
                    "tool_call_count": safe_tool_count,
                    "tool_call_count_capped": not count_is_bounded,
                })
                self._rows_written += 1
                return
            if not self._overflow_written:
                self._write_line(self._descriptor, {
                    "schema_version": DIAGNOSTIC_SCHEMA_VERSION,
                    "record_type": "overflow",
                    "dispatches_at_least": DIAGNOSTIC_MAX_RECORDS,
                    "first_omitted_dispatch": DIAGNOSTIC_MAX_RECORDS,
                })
                self._rows_written += 1
                self._overflow_written = True

    def close(self) -> None:
        os.close(self._descriptor)


def validate_environment(environment: dict[str, str] | None = None) -> str:
    env = os.environ if environment is None else environment
    project = env.get("COMPOSE_PROJECT_NAME", "")
    fixture_project = env.get("BYQ_F6_CI_PROJECT", "")
    if not PROJECT_PATTERN.fullmatch(project) or fixture_project != project:
        raise F6FixtureRejected("isolated_ci_project_required")
    if env.get("BYQ_F6_SYNTHETIC_RUNTIME") != "1":
        raise F6FixtureRejected("synthetic_runtime_flag_required")
    if env.get("OPENCODE_API_KEY") != "f6-synthetic-only":
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


def _has_rehydration_marker(text: str) -> bool:
    return any(marker in text for marker in (
        _REHYDRATION_OPEN, _REHYDRATION_CLOSE, _CURRENT_USER_OPEN, _CURRENT_USER_CLOSE,
        f"schema_version={_REHYDRATION_SCHEMA_VERSION}",
    ))


def _has_instruction_marker(text: str) -> bool:
    return any(marker in text for marker in (
        "F6-CI:FG1", "F6-CI:FG2", _BACKGROUND_INSTRUCTION_PREFIX,
    ))


def _is_skill_catalog(text: str) -> bool:
    # Native DSH may append this exact empty update after the current user
    # instruction. It is supplemental context, never a replacement prompt.
    if text == _SKILL_CATALOG_EMPTY_UPDATE:
        return True
    if (not text.startswith(_SKILL_CATALOG_HEADER) or not text.endswith(_SKILL_CATALOG_FOOTER)
            or text.count("<system-reminder>") != 1 or text.count("</system-reminder>") != 1
            or text.count("<available_skills>") != 1 or text.count("</available_skills>") != 1):
        return False
    entries_text = text[len(_SKILL_CATALOG_HEADER):-len(_SKILL_CATALOG_FOOTER)]
    if not entries_text or "\r" in entries_text:
        return False
    names: set[str] = set()
    for line in entries_text.split("\n"):
        match = re.fullmatch(r"- `([A-Za-z0-9][A-Za-z0-9_.:-]{0,100})`: ([^\r\n]+)", line)
        if match is None or match.group(1) in names:
            return False
        names.add(match.group(1))
    return bool(names)


def _is_supplemental_user_context(text: str) -> bool:
    runtime_candidate = text.startswith(_RUNTIME_SNAPSHOT_PREFIX)
    catalog_candidate = text.startswith("<system-reminder>")
    if not runtime_candidate and not catalog_candidate:
        return False
    if _has_instruction_marker(text) or _has_rehydration_marker(text):
        raise F6FixtureRejected("provider_supplemental_context_marker_rejected")
    if runtime_candidate:
        return bool(text[len(_RUNTIME_SNAPSHOT_PREFIX):].strip())
    return _is_skill_catalog(text)


def _extract_current_user_prompt(text: str) -> str | None:
    if not _has_rehydration_marker(text):
        return None
    if any(text.count(marker) != 1 for marker in (
        _REHYDRATION_OPEN, _REHYDRATION_CLOSE, _CURRENT_USER_OPEN, _CURRENT_USER_CLOSE,
    )):
        raise F6FixtureRejected("rehydrated_current_message_malformed")
    header = f"{_REHYDRATION_OPEN}\nschema_version={_REHYDRATION_SCHEMA_VERSION}\n"
    separator = f"\n{_REHYDRATION_CLOSE}\n{_CURRENT_USER_OPEN}\n"
    ending = f"\n{_CURRENT_USER_CLOSE}"
    if (not text.startswith(header) or text.count(separator) != 1
            or text.count(f"schema_version={_REHYDRATION_SCHEMA_VERSION}") != 1
            or not text.endswith(ending)):
        raise F6FixtureRejected("rehydrated_current_message_malformed")
    start = text.index(separator) + len(separator)
    end = len(text) - len(ending)
    if end < start:
        raise F6FixtureRejected("rehydrated_current_message_malformed")
    current = text[start:end]
    if not current.strip() or _has_rehydration_marker(current):
        raise F6FixtureRejected("rehydrated_current_message_malformed")
    return current


def _instruction_stages(text: str) -> list[str]:
    stages: list[str] = []
    stages.extend(["fg1"] * len(re.findall(r"(?m)^F6-CI:FG1[ \t]*\r?$", text)))
    stages.extend(["fg2"] * len(re.findall(r"(?m)^F6-CI:FG2[ \t]*\r?$", text)))
    stages.extend(["background"] * len(re.findall(
        rf"{re.escape(_BACKGROUND_INSTRUCTION_PREFIX)}task_[0-9a-f]{{32}}\.",
        text,
    )))
    return stages


def _selected_instruction(messages: object) -> tuple[str, str, int]:
    if not isinstance(messages, list):
        raise F6FixtureRejected("provider_messages_invalid")
    user_messages: list[tuple[int, str]] = []
    non_user_instruction_seen = False
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        text = _content_text(message.get("content"))
        if role != "user":
            if _has_instruction_marker(text) or _has_rehydration_marker(text):
                non_user_instruction_seen = True
            continue
        if _is_supplemental_user_context(text):
            continue
        user_messages.append((index, text))
    if not user_messages:
        if non_user_instruction_seen:
            raise F6FixtureRejected("f6_instruction_role_invalid")
        raise F6FixtureRejected("provider_current_user_message_missing")

    instruction_index, current_text = user_messages[-1]
    prompt = _extract_current_user_prompt(current_text)
    if prompt is None:
        prompt = current_text
    stages = _instruction_stages(prompt)
    if len(stages) != 1:
        if stages:
            raise F6FixtureRejected("f6_stage_instruction_ambiguous")
        if prompt != current_text or non_user_instruction_seen or any(
            _has_instruction_marker(text) or _has_rehydration_marker(text)
            for _index, text in user_messages[:-1]
        ):
            raise F6FixtureRejected("provider_current_user_instruction_missing")
        raise F6FixtureRejected("unsupported_foreground_or_background_prompt")
    return stages[0], prompt, instruction_index


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
    placeholders = {
        "{task_id}": ("task_id", r"task_[0-9a-f]{32}"),
        "{signal_job_id}": ("signal_job_id", r"signaljob_[0-9a-f]{32}"),
        "{backtest_task_id}": ("backtest_task_id", r"backtesttask_[0-9a-f]{32}"),
        "{ready_signal}": ("ready_signal", r"\{[^\r\n]+\}"),
    }
    seen: set[str] = set()
    pattern_parts: list[str] = []
    for piece in re.split(r"(\{task_id\}|\{signal_job_id\}|\{backtest_task_id\}|\{ready_signal\})",
                          _BACKGROUND_INSTRUCTION_TEMPLATE):
        entry = placeholders.get(piece)
        if entry is None:
            pattern_parts.append(re.escape(piece))
            continue
        name, inner = entry
        if name in seen:
            pattern_parts.append(f"(?P={name})")
        else:
            seen.add(name)
            pattern_parts.append(f"(?P<{name}>{inner})")
    match = re.fullmatch("".join(pattern_parts), prompt)
    if match is None:
        raise F6FixtureRejected("background_scope_missing")
    task_id = match.group("task_id")
    backtest_task_id = match.group("backtest_task_id")
    serialized_event = match.group("ready_signal")
    try:
        event = json.loads(serialized_event)
    except (ValueError, TypeError):
        raise F6FixtureRejected("background_ready_event_invalid") from None
    if (not isinstance(event, dict)
            or json.dumps(event, sort_keys=True, separators=(",", ":")) != serialized_event):
        raise F6FixtureRejected("background_ready_event_invalid")
    job_id = event.get("identity")
    job_match = SIGNAL_JOB_PATTERN.fullmatch(job_id) if isinstance(job_id, str) else None
    snapshot_id = event.get("result_artifact_id")
    derived = "backtesttask_" + job_match.group(1) if job_match else None
    if (not TASK_PATTERN.fullmatch(task_id)
            or not BACKTEST_TASK_PATTERN.fullmatch(backtest_task_id)
            or match.group("signal_job_id") != job_id
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
        return {"role_id": "quant_orchestrator", "idempotency_key": "task-ready-run-" + scope["signal_job_id"]}
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


def _route_foreground_composition_to_loopback(kwargs: dict, loopback_url: str) -> None:
    composition = kwargs.get("composition")
    session_root = kwargs.get("session_root")
    if not isinstance(composition, Path) or not composition.is_file() or session_root is None:
        return
    text = composition.read_text(encoding="utf-8")
    if "https://opencode.ai/zen/go/v1" not in text:
        return
    target = Path(session_root) / "synthetic-provider-composition.yml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text.replace("https://opencode.ai/zen/go/v1", loopback_url), encoding="utf-8")
    kwargs["composition"] = target


def _guard_pins_local_proxy(guard_b64: Any, proxy_url: str) -> bool:
    if not isinstance(guard_b64, str) or not guard_b64:
        return False
    try:
        overlay = json.loads(base64.b64decode(guard_b64))
    except Exception:
        return False
    if not isinstance(overlay, list):
        return False
    for entry in overlay:
        if (isinstance(entry, dict) and entry.get("id") == "llm-pi-ai"
                and isinstance(entry.get("config"), dict)):
            chat = entry["config"].get("providers", {}).get("opencode-go-chat")
            return isinstance(chat, dict) and chat.get("baseURL") == proxy_url
    return False


def _install_f6_provider_routes(loopback_url: str) -> None:
    import app.runtime as runtime_module

    if re.fullmatch(r"http://127\.0\.0\.1:[0-9]{1,5}", loopback_url) is None:
        raise F6FixtureRejected("synthetic_provider_must_bind_loopback")

    proxy_type = runtime_module.RequestGateProxy
    original_init = proxy_type.__init__

    def init_with_local_upstream(self: Any, gate: object, upstream: str) -> None:
        original_init(self, gate, upstream)
        if upstream.rstrip("/") not in {"https://api.deepseek.com", "https://opencode.ai/zen/go/v1"}:
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
            _route_foreground_composition_to_loopback(kwargs, loopback_url)
        else:
            # ADR-0105: the background OpenCode chat route's baseURL is pinned in
            # the runner-applied guard overlay, not in the child environment.
            if (not continuation_enabled or max_tokens is None
                    or not _guard_pins_local_proxy(kwargs.get("continuation_guard_b64"),
                                                   continuation_proxy_url)
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
    diagnostics = _ProviderDiagnostics.create()
    from tests.f6_runtime_diagnostics import RuntimeDiagnostics, install
    runtime_diagnostics = RuntimeDiagnostics()
    install(runtime_diagnostics)

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *_: object) -> None:
            return

        def do_POST(self) -> None:
            stage = "unknown"
            outcome = "request_rejected"
            response_kind = "none"
            rejection_code: str | None = None
            tool_call_count = 0
            try:
                length = int(self.headers.get("content-length", "0"))
                if length <= 0 or length > 2 * 1024 * 1024:
                    raise F6FixtureRejected("provider_request_size_invalid")
                try:
                    body = json.loads(self.rfile.read(length))
                except (TypeError, ValueError):
                    raise F6FixtureRejected("provider_request_invalid") from None
                if not isinstance(body, dict):
                    raise F6FixtureRejected("provider_request_invalid")
                stage, _, _ = _selected_instruction(body.get("messages"))
                action = next_action(body)
                tool_call_count = 1 if action is not None else 0
                response_kind = "tool_call" if action is not None else "completion"
                response = _sse_completion(body, action)
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.send_header("content-length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)
                outcome = "response_written"
            except F6FixtureRejected as exc:
                rejection_code = _diagnostic_rejection_code(exc)
                outcome = ("request_rejected" if rejection_code in {
                    "provider_request_invalid", "provider_request_size_invalid",
                } else "fixture_rejected")
                # Never include prompts, cookies, credentials, MCP arguments or
                # raw responses in logs or the error body.
                print("f6 scripted provider rejected request: " + rejection_code, flush=True)
                try:
                    self.send_error(400, "synthetic F6 contract rejected the request")
                except OSError:
                    pass
            except Exception as exc:
                outcome = "handler_error"
                # Never include prompts, cookies, credentials, MCP arguments or
                # raw responses in logs or the error body.
                print("f6 scripted provider rejected request: " + type(exc).__name__, flush=True)
                try:
                    self.send_error(400, "synthetic F6 contract rejected the request")
                except OSError:
                    pass
            finally:
                self.server.diagnostics.record_dispatch(
                    stage=stage, outcome=outcome, response_kind=response_kind,
                    rejection_code=rejection_code, tool_call_count=tool_call_count,
                )

        def do_GET(self) -> None:
            self.send_error(405, "method not allowed")

    server: ThreadingHTTPServer | None = None
    thread: threading.Thread | None = None
    try:
        server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
        server.diagnostics = diagnostics
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        loopback_url = f"http://127.0.0.1:{server.server_port}"
        _install_f6_provider_routes(loopback_url)
        from app import main as runtime_main
        import uvicorn

        uvicorn.run(runtime_main.app, host="0.0.0.0", port=8400)
    finally:
        if server is not None:
            if thread is not None:
                server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=2)
        runtime_diagnostics.close()
        diagnostics.close()


if __name__ == "__main__":
    main()
