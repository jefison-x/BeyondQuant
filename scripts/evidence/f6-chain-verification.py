#!/usr/bin/env python3
"""One-shot Product API driver for the current ADR-0090 F6 contract.

The model-facing Provider is scripted locally, while Agent sessions, BYQ MCP,
Product approvals, durable Jobs, the signal Worker and request settlement use
this isolated CI stack's normal wiring. No SQL fixture writes or retry/recovery
of uncertain mutations are performed here.
"""
from __future__ import annotations

import http.cookiejar
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.error
from pathlib import Path
from urllib.request import HTTPCookieProcessor, Request, build_opener


PROJECT_PATTERN = re.compile(r"byq-ci-stack-[A-Za-z0-9][A-Za-z0-9_-]{0,80}\Z")
TASK_PATTERN = re.compile(r"task_[0-9a-f]{32}\Z")
ARTIFACT_PATTERN = re.compile(r"artifact_[0-9a-f]{32}\Z")
SIGNAL_JOB_PATTERN = re.compile(r"signaljob_[0-9a-f]{32}\Z")
BACKTEST_TASK_PATTERN = re.compile(r"backtesttask_[0-9a-f]{32}\Z")
AGENT_RUN_PATTERN = re.compile(r"agent_run_[0-9a-f]{32}\Z")
AUDIT_PATTERN = re.compile(r"agent_audit_[0-9a-f]{32}\Z")
RUNTIME_ROOT_PATTERN = re.compile(r"[0-9a-f]{32}\Z")
RESERVATION_PATTERN = re.compile(r"continuation_[0-9a-f]{32}\Z")
SESSION_PATTERN = re.compile(r"byq-session-[0-9a-f]{32}\Z")
TRACE_PATTERN = re.compile(r"byq-trace-[0-9a-f]{32}\Z")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


class EvidenceError(RuntimeError):
    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


class HttpFailure(EvidenceError):
    def __init__(self, status: int) -> None:
        super().__init__("http_status_" + str(status))
        self.status = status


def require(condition: bool, category: str) -> None:
    if not condition:
        raise EvidenceError(category)


def identifier(value: object, pattern: re.Pattern[str], category: str) -> str:
    require(isinstance(value, str) and pattern.fullmatch(value) is not None, category)
    return str(value)


def _body_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(str(item.get("text", "")) for item in value if isinstance(item, dict))
    return ""


def _messages(body: object) -> list[dict[str, object]]:
    require(isinstance(body, dict) and isinstance(body.get("messages"), list), "agent_messages_invalid")
    return [item for item in body["messages"] if isinstance(item, dict)]


def _session_call(client, session_id: str) -> dict[str, object]:
    body = client("GET", f"/v1/agent/sessions/{session_id}", timeout=12)
    require(isinstance(body, dict) and body.get("conversation", {}).get("conversation_id") == session_id,
            "original_agent_session_identity_changed")
    return body


def _answer_after(body: dict[str, object], prompt: str) -> str | None:
    messages = _messages(body)
    matches = [index for index, item in enumerate(messages)
               if item.get("role") == "user" and _body_text(item.get("content")) == prompt]
    require(len(matches) <= 1, "agent_user_turn_duplicate")
    if not matches:
        return None
    following = messages[matches[0] + 1:]
    return "\n".join(_body_text(item.get("content")) for item in following
                     if item.get("role") == "assistant")


def _wait_answer(client, session_id: str, prompt: str, required: tuple[str, ...], *, timeout: int = 180) -> tuple[dict[str, object], str]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = _session_call(client, session_id)
        answer = _answer_after(body, prompt)
        if answer is not None and all(value in answer for value in required):
            return body, answer
        conversation = body.get("conversation")
        require(not isinstance(conversation, dict)
                or conversation.get("status") not in {"failed", "interrupted", "archived"},
                "original_agent_session_failed")
        time.sleep(1)
    raise EvidenceError("agent_answer_not_persisted_before_deadline")


def _post_once(client, label: str, path: str, payload: object, *, expected: int = 200,
               headers: dict[str, str] | None = None, timeout: int = 45) -> dict[str, object]:
    state["mutation_attempts"].append(label)
    try:
        result = client("POST", path, payload, expected=expected, headers=headers, timeout=timeout)
    except EvidenceError as error:
        if not isinstance(error, HttpFailure) or error.status >= 500:
            state["uncertain_actions"].append(label)
        raise
    if not isinstance(result, dict):
        state["uncertain_actions"].append(label)
        raise EvidenceError("mutation_response_invalid")
    return result


def _compose(*args: str, timeout: int = 45) -> str:
    try:
        result = subprocess.run(["docker", "compose", *args], check=True, capture_output=True,
                                text=True, timeout=timeout)
    except subprocess.CalledProcessError:
        raise EvidenceError("dedicated_compose_action_failed") from None
    except (OSError, subprocess.TimeoutExpired):
        raise EvidenceError("dedicated_compose_action_outcome_unknown") from None
    return result.stdout.strip()


def _compose_once(label: str, *args: str, timeout: int = 45) -> str:
    state["mutation_attempts"].append(label)
    try:
        return _compose(*args, timeout=timeout)
    except EvidenceError:
        state["uncertain_actions"].append(label)
        raise


def _write_evidence(*, suffix: str = "") -> str:
    destination = Path(evidence_path + suffix)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "f6-current-ci-evidence.v1",
        "phase": "closeout" if suffix else "primary",
        "status": state["status"],
        "scope": "keyless DSH-to-BYQ-MCP/domain/signal-Worker wiring; synthetic Provider; not model-quality evidence",
        "last_confirmed_stage": state["stage"],
        "failure_category": state.get("failure_category"),
        "mutation_attempts": list(state["mutation_attempts"]),
        "uncertain_actions": list(state["uncertain_actions"]),
        "identities": {key: value for key, value in state["identities"].items() if value is not None},
        "checks": state["checks"],
        "structured_agent_audits": state.get("audit_summaries", {}),
        "failure_observation": state.get("failure_observation"),
        "actual_usage_policy": "provider usage omitted by the synthetic Provider; actual model usage and provider attempts remain unknown; RequestGateProxy admission measurements are retained separately",
        "excluded_old_chain": ["ML training/prediction", "native backtest execution", "comparison report", "ResearchTask completion"],
    }
    encoded = (json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    digest = hashlib.sha256(encoded).hexdigest()
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)
    print(json.dumps({
        "stage": "f6_evidence_saved", "status": state["status"], "phase": payload["phase"],
        "sha256": digest, "failure_category": state.get("failure_category"),
        "identities": payload["identities"],
        "structured_agent_audits": payload["structured_agent_audits"],
    }, sort_keys=True), flush=True)
    if not suffix:
        state["primary_evidence_written"] = True
    return digest


def _validate_settlement_identity(candidate: object, grant_version: int) -> dict[str, object]:
    require(isinstance(candidate, dict), "background_request_identity_missing")
    require(candidate.get("status") == "settled"
            and candidate.get("dispatch_attempts") == 1
            and candidate.get("grant_version") == grant_version,
            "background_request_receipt_not_exactly_settled")
    runtime_root_id = candidate.get("run_id")
    require(isinstance(runtime_root_id, str)
            and RUNTIME_ROOT_PATTERN.fullmatch(runtime_root_id) is not None,
            "background_runtime_root_identity_invalid")
    require(isinstance(candidate.get("reservation_id"), str)
            and RESERVATION_PATTERN.fullmatch(candidate["reservation_id"]) is not None,
            "background_reservation_identity_invalid")
    require(isinstance(candidate.get("settlement_sha256"), str)
            and SHA256_PATTERN.fullmatch(candidate["settlement_sha256"]) is not None,
            "background_settlement_digest_invalid")
    require(candidate.get("event_key") is not None
            and isinstance(candidate.get("event_key"), str)
            and re.fullmatch(r"ready-v1:[0-9a-f]{64}", candidate["event_key"]) is not None
            and candidate.get("grant_version") == grant_version,
            "background_ready_event_identity_invalid")
    return candidate


def _assert_structured_agent_audit(document: object, *, stage: str, task_id: str,
                                   conversation_id: str, trace_id: str, runtime_root_id: str,
                                   expected_events: list[tuple[str, str, str | None, str | None]],
                                   settlement: dict[str, object] | None = None) -> dict[str, object]:
    require(isinstance(document, dict) and document.get("schema_version") == "f6-agent-run-audit.v1"
            and document.get("stage") == stage, "structured_agent_audit_envelope_invalid")
    task = document.get("task")
    root = document.get("runtime_root")
    run = document.get("agent_run")
    events = document.get("events")
    require(isinstance(task, dict) and task.get("task_id") == task_id
            and task.get("owner_principal") == "f6-chain-user"
            and task.get("conversation_id") == conversation_id
            and task.get("trace_id") == trace_id
            and isinstance(task.get("workspace_id"), str)
            and task["workspace_id"].startswith("workspace_"),
            "structured_agent_audit_task_scope_invalid")
    runtime_session_id = document.get("runtime_session_id")
    require(isinstance(runtime_session_id, str)
            and SESSION_PATTERN.fullmatch(runtime_session_id) is not None,
            "structured_agent_audit_runtime_session_invalid")
    require(isinstance(root, dict) and root.get("root_run_id") == runtime_root_id
            and root.get("owner_principal") == "f6-chain-user"
            and root.get("workspace_id") == task.get("workspace_id")
            and root.get("session_id") == runtime_session_id
            and root.get("trace_id") == trace_id
            and root.get("status") == "completed" and root.get("authority_status") == "closed"
            and type(root.get("terminal_sequence")) is int and root["terminal_sequence"] > 0
            and isinstance(root.get("terminal_event_sha256"), str)
            and SHA256_PATTERN.fullmatch(root["terminal_event_sha256"]) is not None,
            "structured_runtime_root_terminal_invalid")
    require(isinstance(run, dict) and isinstance(run.get("run_id"), str)
            and AGENT_RUN_PATTERN.fullmatch(run["run_id"]) is not None
            and run.get("root_run_id") == runtime_root_id
            and run.get("owner_principal") == "f6-chain-user"
            and run.get("actor_principal") == "byq-product-agent-" + runtime_session_id
            and run.get("role_id") == "quant_orchestrator"
            and run.get("session_id") == runtime_session_id and run.get("trace_id") == trace_id
            and run.get("status") == "completed" and run.get("authority_status") == "closed",
            "structured_agent_run_terminal_or_lineage_invalid")
    require(isinstance(events, list), "structured_agent_audit_events_invalid")
    actual_events: list[tuple[str, str, str | None, str | None]] = []
    for event in events:
        require(isinstance(event, dict) and isinstance(event.get("audit_id"), str)
                and AUDIT_PATTERN.fullmatch(event["audit_id"]) is not None
                and isinstance(event.get("action"), str), "structured_agent_audit_event_invalid")
        require(event.get("run_id") == run["run_id"] and event.get("owner_principal") == "f6-chain-user"
                and event.get("actor_principal") == run["actor_principal"],
                "structured_agent_audit_event_identity_invalid")
        actual_events.append((event["action"], event.get("outcome"),
                              event.get("resource_type"), event.get("resource_id")))
    expected = [
        ("runtime_turn_binding", "active", "runtime_turn", runtime_root_id),
        *expected_events,
        ("runtime_turn_binding", "completed", "runtime_turn", runtime_root_id),
    ]
    require(sorted(actual_events, key=str) == sorted(expected, key=str),
            "structured_agent_audit_actions_or_resources_invalid")
    observed_settlement = document.get("settlement")
    if settlement is None:
        require(observed_settlement is None, "unexpected_structured_request_receipt")
    else:
        require(isinstance(observed_settlement, dict)
                and observed_settlement.get("reservation_id") == settlement.get("reservation_id")
                and observed_settlement.get("run_id") == runtime_root_id
                and observed_settlement.get("grant_version") == settlement.get("grant_version") == 1
                and observed_settlement.get("status") == "settled"
                and observed_settlement.get("outcome") == "completed"
                and observed_settlement.get("dispatch_attempts") == 1
                and observed_settlement.get("event_key") == settlement.get("event_key")
                and observed_settlement.get("settlement_sha256") == settlement.get("settlement_sha256"),
                "structured_settlement_root_link_invalid")
    return {
        "stage": stage, "runtime_root_id": runtime_root_id, "agent_run_id": run["run_id"],
        "owner_principal": "f6-chain-user", "workspace_id": task["workspace_id"],
        "session_id": runtime_session_id, "trace_id": trace_id,
        "terminal": "completed/closed", "audit_events": [
            {"action": action, "outcome": outcome, "resource_type": resource_type,
             "resource_id": resource_id}
            for action, outcome, resource_type, resource_id in actual_events
        ],
        "settlement_status": observed_settlement.get("status") if isinstance(observed_settlement, dict) else None,
    }


def _assert_validated_signal_artifact(artifact: object, *, artifact_id: str, task_id: str,
                                      owner_principal: str, workspace_id: str,
                                      strategy_version_artifact_id: str,
                                      stock_pool_snapshot_id: str, signal_job_id: str) -> dict[str, object]:
    require(isinstance(artifact, dict) and artifact.get("artifact_id") == artifact_id
            and artifact.get("owner_principal") == owner_principal
            and artifact.get("workspace_id") == workspace_id
            and artifact.get("task_id") == task_id
            and artifact.get("kind") == "signal_snapshot" and artifact.get("status") == "validated",
            "validated_signal_artifact_scope_or_status_invalid")
    content = artifact.get("content")
    strategy = content.get("strategy") if isinstance(content, dict) else None
    universe = content.get("universe") if isinstance(content, dict) else None
    require(isinstance(content, dict) and content.get("schema_version") == "signal-snapshot-v2"
            and isinstance(strategy, dict)
            and strategy.get("strategy_version_artifact_id") == strategy_version_artifact_id
            and isinstance(universe, dict)
            and universe.get("version_id") == stock_pool_snapshot_id,
            "validated_signal_artifact_content_lineage_invalid")
    expected_lineage = [
        {"kind": "research_task", "id": task_id},
        {"kind": "artifact", "id": strategy_version_artifact_id},
        {"kind": "stock_pool_snapshot", "id": stock_pool_snapshot_id},
        {"kind": "signal_producer_job", "id": signal_job_id},
    ]
    require(artifact.get("lineage") == expected_lineage,
            "validated_signal_artifact_lineage_invalid")
    return artifact


def _read_structured_agent_audit(stage: str, *, task_id: str, conversation_id: str, trace_id: str,
                                 runtime_root_id: str, expected_events: list[tuple[str, str, str | None, str | None]],
                                 backtest_task_id: str | None = None,
                                 draft_artifact_id: str | None = None,
                                 strategy_version_artifact_id: str | None = None,
                                 settlement: dict[str, object] | None = None,
                                 timeout: int = 45) -> dict[str, object]:
    payload: dict[str, object] = {
        "action": "audit", "stage": stage, "owner": "f6-chain-user",
        "conversation_id": conversation_id, "trace_id": trace_id,
        "task_id": task_id, "runtime_root_id": runtime_root_id,
    }
    if backtest_task_id is not None:
        payload["backtest_task_id"] = backtest_task_id
    if draft_artifact_id is not None:
        payload["strategy_draft_artifact_id"] = draft_artifact_id
    if strategy_version_artifact_id is not None:
        payload["strategy_version_artifact_id"] = strategy_version_artifact_id
    if settlement is not None:
        payload["reservation_id"] = settlement["reservation_id"]
        payload["settlement_sha256"] = settlement["settlement_sha256"]
    project = os.environ.get("COMPOSE_PROJECT_NAME", "")
    require(PROJECT_PATTERN.fullmatch(project) is not None, "isolated_ci_project_required")
    deadline = time.monotonic() + timeout
    observations: dict[str, object] = {"attempts": 0, "last_not_ready_category": None}
    state["checks"]["structured_audit_wait_" + stage] = observations
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            result = subprocess.run([
                "docker", "compose", "exec", "-T", "-e", "BYQ_F6_FIXTURE=1",
                "-e", "COMPOSE_PROJECT_NAME=" + project, "-e", "BYQ_F6_CI_PROJECT=" + project,
                "backend", "python", "/tmp/f6-chain-fixture.py", "audit",
            ], input=json.dumps(payload, separators=(",", ":")), text=True,
               capture_output=True, check=False, timeout=min(15, remaining))
        except (OSError, subprocess.TimeoutExpired):
            raise EvidenceError("structured_agent_audit_read_outcome_unknown") from None
        observations["attempts"] = int(observations["attempts"]) + 1
        if result.returncode != 0:
            raise EvidenceError("structured_agent_audit_read_failed")
        try:
            document = json.loads(result.stdout)
        except (ValueError, TypeError):
            raise EvidenceError("structured_agent_audit_response_invalid") from None
        if (isinstance(document, dict) and document.get("schema_version") == "f6-agent-audit-readiness.v1"
                and document.get("stage") == stage and document.get("status") == "not_ready"
                and document.get("category") in {"runtime_root_not_visible", "runtime_root_active"}):
            observations["last_not_ready_category"] = document["category"]
            time.sleep(min(1, max(0, deadline - time.monotonic())))
            continue
        summary = _assert_structured_agent_audit(
            document, stage=stage, task_id=task_id, conversation_id=conversation_id,
            trace_id=trace_id, runtime_root_id=runtime_root_id,
            expected_events=expected_events, settlement=settlement)
        observations["status"] = "terminal_proof_observed"
        return summary
    raise EvidenceError("structured_agent_audit_terminal_proof_deadline")


def _failure_readonly_window(client, *, seconds: int) -> None:
    """Preserve one bounded GET-only reconciliation window after first evidence."""
    deadline = time.monotonic() + seconds
    observations: dict[str, object] = {"session_reads": 0, "permission_reads": 0,
                                      "request_status": None, "answer_persisted": False}
    task_id = state["identities"].get("task_id")
    conversation_id = state["identities"].get("conversation_id")
    if not isinstance(conversation_id, str):
        state["failure_observation"] = observations
        return
    while time.monotonic() < deadline:
        try:
            session_view = _session_call(client, conversation_id)
            observations["session_reads"] = int(observations["session_reads"]) + 1
            if isinstance(task_id, str):
                messages = _messages(session_view)
                bg_indices = [index for index, item in enumerate(messages)
                              if item.get("role") == "user"
                              and "BYQ trusted read-only task-ready follow-up for exact task " + task_id
                                  in _body_text(item.get("content"))]
                if bg_indices:
                    answer = "\n".join(_body_text(item.get("content")) for item in messages[bg_indices[0] + 1:]
                                        if item.get("role") == "assistant")
                    exact_ids = [state["identities"].get(key) for key in (
                        "task_id", "backtest_task_id", "signal_job_id", "signal_snapshot_artifact_id")]
                    observations["answer_persisted"] = (
                        all(isinstance(value, str) and value in answer for value in exact_ids)
                        and "No domain writes were made." in answer)
        except EvidenceError as error:
            observations["session_read_category"] = error.category
        if isinstance(task_id, str):
            try:
                view = _permission_view(client, task_id)
                observations["permission_reads"] = int(observations["permission_reads"]) + 1
                request_state = view.get("request_state")
                identity = request_state.get("request_identity") if isinstance(request_state, dict) else None
                if isinstance(identity, dict):
                    observations["request_status"] = identity.get("status")
                    observations["runtime_root_id"] = identity.get("run_id")
                    observations["dispatch_attempts"] = identity.get("dispatch_attempts")
            except EvidenceError as error:
                observations["permission_read_category"] = error.category
        if observations.get("answer_persisted") and observations.get("request_status") == "settled":
            break
        if seconds <= 4 or time.monotonic() + 2 >= deadline:
            break
        time.sleep(2)
    state["failure_observation"] = observations


def _permission_view(client, task_id: str) -> dict[str, object]:
    view = client("GET", f"/api/product/research/tasks/{task_id}/continuation-permission", timeout=15)
    require(isinstance(view, dict) and view.get("task_id") == task_id,
            "continuation_permission_identity_changed")
    return view


def _revoke_exact_grant(client) -> None:
    task_id = state["identities"].get("task_id")
    version_id = state["identities"].get("strategy_version_artifact_id")
    if not isinstance(task_id, str) or not isinstance(version_id, str):
        return
    try:
        view = _permission_view(client, task_id)
    except EvidenceError:
        state["checks"]["revoke"] = "could_not_read_exact_permission_state"
        return
    permission = view.get("permission")
    if not isinstance(permission, dict):
        state["checks"]["revoke"] = "no_permission_to_revoke"
        return
    if (permission.get("confirmation_id") != state.get("grant_idempotency_key")
            or permission.get("confirmed_artifact_ids") != [version_id]
            or permission.get("grant_version") != 1):
        state["checks"]["revoke"] = "permission_identity_mismatch_no_mutation"
        return
    if permission.get("revoked_at") is not None:
        state["checks"]["revoke"] = "already_revoked"
        return
    before = view.get("request_state")
    state["revoke_attempted"] = True
    try:
        revoked = _post_once(client, "continuation_permission_revoke",
            f"/api/product/research/tasks/{task_id}/continuation-permission/revoke",
            {"grant_version": 1}, headers={"x-byq-continuation-confirmation": "v1"}, timeout=20)
        permission_after_post = revoked.get("permission")
        require(isinstance(permission_after_post, dict)
                and permission_after_post.get("grant_version") == 1
                and permission_after_post.get("revoked_at") is not None,
                "exact_permission_revoke_not_confirmed")
    except EvidenceError as error:
        state["checks"]["revoke_post_category"] = error.category
        if "continuation_permission_revoke" not in state["uncertain_actions"]:
            state["uncertain_actions"].append("continuation_permission_revoke")
    try:
        after = _permission_view(client, task_id)
        current = after.get("permission")
        require(isinstance(current, dict) and current.get("grant_version") == 1
                and current.get("revoked_at") is not None,
                "exact_permission_revoke_get_not_confirmed")
        require(after.get("request_state") == before,
                "request_state_changed_after_exact_revoke")
        state["checks"]["revoke"] = "one_exact_post_and_get_confirmed_no_second_request"
    except EvidenceError as error:
        state["checks"]["revoke"] = error.category


project = os.environ.get("COMPOSE_PROJECT_NAME", "")
require(PROJECT_PATTERN.fullmatch(project) is not None, "isolated_ci_project_required")
evidence_path = os.environ.get("BYQ_F6_EVIDENCE_PATH", f"/tmp/byq-f6-chain-{os.getpid()}.json")
origin = os.environ.get("BYQ_GOLDEN_ORIGIN", "").rstrip("/")
require(re.fullmatch(r"http://127\.0\.0\.1:[0-9]{1,5}", origin) is not None,
        "isolated_loopback_gateway_required")
client = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))


def call(method: str, path: str, payload: object = None, *, expected: int = 200,
         headers: dict[str, str] | None = None, timeout: int = 45) -> object:
    request = Request(origin + path,
        data=json.dumps(payload, separators=(",", ":")).encode() if payload is not None else None,
        headers={"content-type": "application/json", **(headers or {})}, method=method)
    try:
        with client.open(request, timeout=timeout) as response:
            if response.status != expected:
                raise HttpFailure(response.status)
            body = response.read()
    except urllib.error.HTTPError as error:
        raise HttpFailure(int(error.code)) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise EvidenceError("http_transport_or_read_outcome_unknown") from None
    try:
        return json.loads(body)
    except (ValueError, TypeError):
        raise EvidenceError("http_json_response_invalid") from None


state: dict[str, object] = {
    "status": "failed", "stage": "preflight", "failure_category": None,
    "identities": {key: None for key in (
        "conversation_id", "runtime_session_id", "trace_id",
        "foreground_1_runtime_root_id", "foreground_1_agent_run_id",
        "foreground_2_runtime_root_id", "foreground_2_agent_run_id",
        "background_runtime_root_id", "background_agent_run_id", "background_reservation_id",
        "background_event_key",
        "task_id", "strategy_draft_artifact_id",
        "strategy_version_artifact_id", "approval_artifact_id", "stock_pool_snapshot_id",
        "backtest_task_id", "signal_job_id", "signal_snapshot_artifact_id", "grant_version")},
    "checks": {}, "audit_summaries": {}, "mutation_attempts": [], "uncertain_actions": [],
    "grant_idempotency_key": None, "revoke_attempted": False,
    "primary_evidence_written": False, "failure_observation": None,
}
worker_start_attempted = False
worker_stopped_at_start = False

try:
    state["stage"] = "isolate_signal_worker"
    _compose_once("signal_worker_stop_before_job", "stop", "signal-worker")
    worker_stopped_at_start = True

    state["stage"] = "prepare_only_test_user"
    state["mutation_attempts"].append("isolated_ci_user_fixture")
    try:
        completed = subprocess.run(
            ["docker", "compose", "exec", "-T", "-e", "BYQ_F6_FIXTURE=1",
             "-e", "COMPOSE_PROJECT_NAME=" + project, "-e", "BYQ_F6_CI_PROJECT=" + project, "backend",
             "python", "/tmp/f6-chain-fixture.py", "user"],
            input="", text=True, capture_output=True, check=True, timeout=30)
        fixture_result = json.loads(completed.stdout)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError, TypeError):
        state["uncertain_actions"].append("isolated_ci_user_fixture")
        raise EvidenceError("isolated_ci_user_fixture_outcome_unknown") from None
    require(fixture_result == {"owner": "f6-chain-user"}, "test_user_fixture_invalid")

    state["stage"] = "product_login_and_original_session"
    _post_once(call, "product_login", "/api/product/auth/login",
               {"username": "f6-chain-user", "password": "test-password-123"})
    session = _post_once(call, "product_session_create", "/v1/agent/sessions", {}, expected=201)
    require(isinstance(session, dict), "agent_session_create_invalid")
    session_id = identifier(session.get("session_id"), re.compile(r"conversation_[0-9a-f]{32}\Z"),
                             "agent_session_id_invalid")
    trace_id = session.get("trace_id")
    require(isinstance(trace_id, str) and bool(trace_id), "agent_session_trace_missing")
    state["identities"].update(conversation_id=session_id, trace_id=trace_id)

    title = "F6 current task-ready read qualification"
    objective = "Create one strategy version and one approved signal-production task in this conversation; the later background request may only read this exact task and its exact completed signal artifact."
    strategy = {
        "strategy_id": "F6SyntheticSignal", "name": "F6 synthetic signal fixture",
        "category": "momentum", "description": "Fixed keyless CI signal producer input",
        "parameters": {}, "parameter_schema": {}, "source_type": "python_script",
        "script": "class CustomStrategy:\n    def generate_signals(self, data, parameters=None):\n        return {}",
    "data_requirements": {},
    }
    fg1 = "\n".join((
        "F6-CI:FG1",
        "Use only BeyondQuant MCP. In this original Product conversation, create exactly one new ResearchTask, then validate the supplied strategy draft and create its validated StrategyVersion. Return the exact Task, Draft Artifact and StrategyVersion Artifact IDs. Do not approve the strategy, create or run any Job, create a report, or complete the Task.",
        f"owner_principal=f6-chain-user", f"conversation_id={session_id}", f"session_trace_id={trace_id}",
        f"task_title={title}", f"task_objective={objective}",
        "task_create_idempotency_key=f6-ci-task-" + project,
        "strategy_validate_idempotency_key=f6-ci-draft-" + project,
        "strategy_version_idempotency_key=f6-ci-version-" + project,
        "strategy_json=" + json.dumps(strategy, sort_keys=True, separators=(",", ":")),
    ))
    state["stage"] = "foreground_1_task_and_strategy_version"
    state["mutation_attempts"].append("foreground_agent_turn_1")
    try:
        accepted = call("POST", f"/v1/agent/sessions/{session_id}/turns", {"content": fg1},
                        expected=202, timeout=20)
        require(isinstance(accepted, dict) and accepted.get("accepted") is True
                and accepted.get("session_id") == session_id, "foreground_1_not_accepted")
        state["identities"]["foreground_1_runtime_root_id"] = identifier(
            accepted.get("run_id"), RUNTIME_ROOT_PATTERN, "foreground_1_runtime_root_missing")
    except EvidenceError as error:
        state["uncertain_actions"].append("foreground_agent_turn_1")
        state["checks"]["foreground_1_post_category"] = error.category
    fg1_body, fg1_answer = _wait_answer(call, session_id, fg1, ("ResearchTask ", "StrategyVersion "))
    task_match = re.search(r"ResearchTask (task_[0-9a-f]{32})", fg1_answer)
    draft_match = re.search(r"StrategyDraft (artifact_[0-9a-f]{32})", fg1_answer)
    version_match = re.search(r"StrategyVersion (artifact_[0-9a-f]{32})", fg1_answer)
    task_id = identifier(task_match.group(1) if task_match else None, TASK_PATTERN, "foreground_1_task_id_missing")
    draft_id = identifier(draft_match.group(1) if draft_match else None, ARTIFACT_PATTERN, "foreground_1_draft_id_missing")
    version_id = identifier(version_match.group(1) if version_match else None, ARTIFACT_PATTERN, "foreground_1_version_id_missing")
    state["identities"].update(task_id=task_id, strategy_draft_artifact_id=draft_id,
                                strategy_version_artifact_id=version_id)

    state["stage"] = "verify_exact_task_and_strategy_lineage"
    task = call("GET", f"/api/product/research/tasks/{task_id}")
    require(isinstance(task, dict) and task.get("task_id") == task_id
            and task.get("owner_principal") == "f6-chain-user"
            and task.get("conversation_id") == session_id and task.get("trace_id") == trace_id
            and task.get("status") in {"planned", "running"},
            "research_task_original_conversation_lineage_invalid")
    artifacts_response = call("GET", "/api/product/research/artifacts")
    artifacts = artifacts_response.get("artifacts") if isinstance(artifacts_response, dict) else None
    require(isinstance(artifacts, list), "product_artifact_list_invalid")
    by_id = {item.get("artifact_id"): item for item in artifacts if isinstance(item, dict)}
    draft = by_id.get(draft_id)
    version = by_id.get(version_id)
    require(isinstance(draft, dict) and draft.get("task_id") == task_id
            and draft.get("kind") == "strategy_draft" and draft.get("status") == "validated",
            "strategy_draft_product_lineage_invalid")
    lineage = version.get("lineage") if isinstance(version, dict) else None
    require(isinstance(version, dict) and version.get("task_id") == task_id
            and version.get("kind") == "strategy_version" and version.get("status") == "validated"
            and isinstance(lineage, list)
            and any(isinstance(item, dict) and item.get("kind") == "artifact" and item.get("id") == draft_id
                    for item in lineage),
            "validated_strategy_version_product_lineage_invalid")
    state["checks"]["task_strategy_lineage"] = "exact_conversation_task_validated_version_and_draft"
    fg1_audit = _read_structured_agent_audit(
        "fg1", task_id=task_id, conversation_id=session_id, trace_id=trace_id,
        runtime_root_id=state["identities"]["foreground_1_runtime_root_id"],
        draft_artifact_id=draft_id, strategy_version_artifact_id=version_id,
        expected_events=[
            ("byq_research_task_create", "authorized", None, None),
            ("byq_research_task_create", "success", "research_task", task_id),
            ("byq_strategy_validate", "authorized", None, None),
            ("byq_strategy_validate", "success", "strategy_draft", draft_id),
            ("byq_strategy_version_create", "authorized", None, None),
            ("byq_strategy_version_create", "success", "strategy_version", version_id),
        ])
    state["audit_summaries"]["fg1"] = fg1_audit
    state["identities"]["foreground_1_agent_run_id"] = fg1_audit["agent_run_id"]
    state["identities"]["runtime_session_id"] = fg1_audit["session_id"]
    state["checks"]["foreground_1_structured_audit"] = "exact_terminal_run_owner_workspace_session_trace_and_resources"

    state["stage"] = "human_strategy_approval_and_stock_pool"
    approval = _post_once(call, "product_strategy_approval", "/api/product/strategies/approvals", {
        "task_id": task_id, "strategy_version_artifact_id": version_id, "decision": "approved",
        "trace_id": trace_id, "idempotency_key": "f6-ci-approval-" + project,
    }, expected=201)
    approval_artifact = approval.get("artifact")
    approval_id = identifier(approval_artifact.get("artifact_id") if isinstance(approval_artifact, dict) else None,
                             ARTIFACT_PATTERN, "human_strategy_approval_artifact_missing")
    require(isinstance(approval_artifact, dict) and approval_artifact.get("task_id") == task_id
            and approval_artifact.get("kind") == "strategy_approval"
            and approval_artifact.get("status") == "validated"
            and approval_artifact.get("content", {}).get("strategy_version_artifact_id") == version_id
            and approval_artifact.get("content", {}).get("execution_authorized") is True,
            "human_strategy_approval_lineage_invalid")
    state["identities"]["approval_artifact_id"] = approval_id

    pool_result = _post_once(call, "product_stock_pool", "/api/product/paper/pools", {
        "name": "F6 current CI signal pool", "pool_type": "custom",
        "description": "Exact current-head F6 synthetic integration scope",
        "symbols": ["000001.SZ", "600000.SH"], "idempotency_key": "f6-ci-pool-" + project,
    }, expected=201)
    pool = pool_result.get("pool")
    snapshot = pool.get("snapshot") if isinstance(pool, dict) else None
    snapshot_id = identifier(snapshot.get("snapshot_id") if isinstance(snapshot, dict) else None,
                             re.compile(r"stock_pool_snapshot_[0-9a-f]{64}\Z"), "stock_pool_snapshot_missing")
    require(isinstance(pool, dict) and pool.get("status") == "active"
            and isinstance(snapshot, dict) and snapshot.get("member_count") == 2,
            "product_stock_pool_snapshot_invalid")
    state["identities"]["stock_pool_snapshot_id"] = snapshot_id

    state["stage"] = "human_product_api_v2_single_request_grant"
    grant_key = "f6-ci-read-grant-" + project
    state["grant_idempotency_key"] = grant_key
    grant_payload = {
        "idempotency_key": grant_key, "execution_profile_id": "task-ready-read.v1",
        "confirmed_artifact_ids": [version_id], "max_turns": 1,
        "valid_seconds": 900, "turn_timeout_seconds": 900,
    }
    try:
        grant = _post_once(call, "continuation_permission_grant",
            f"/api/product/research/tasks/{task_id}/continuation-permission", grant_payload,
            expected=201, headers={"x-byq-continuation-confirmation": "v1"}, timeout=30)
    except EvidenceError as error:
        state["checks"]["grant_post_category"] = error.category
        # A GET may reconcile the exact original grant; a second grant POST is never sent.
        grant = _permission_view(call, task_id)
        current_permission = grant.get("permission")
        require(isinstance(current_permission, dict)
                and current_permission.get("confirmation_id") == grant_key
                and current_permission.get("confirmed_artifact_ids") == [version_id],
                "single_request_grant_outcome_unknown")
    permission = grant.get("permission")
    require(grant.get("schema_version") == "task-continuation-permission.v2"
            and isinstance(permission, dict)
            and permission.get("confirmation_id") == grant_key
            and permission.get("confirmed_artifact_ids") == [version_id]
            and permission.get("max_turns") == 1
            and permission.get("execution_profile") == {
                "profile_id": "task-ready-read.v1", "profile_version": 1,
                "profile_sha256": permission.get("execution_profile", {}).get("profile_sha256")},
            "single_request_grant_contract_invalid")
    limits = permission.get("request_limits")
    require(isinstance(limits, dict) and limits.get("max_provider_calls") == 16
            and limits.get("max_tool_calls") == 16 and "token_limit" not in permission,
            "single_request_profile_limits_invalid")
    grant_version = permission.get("grant_version")
    require(grant_version == 1, "exact_grant_version_invalid")
    state["identities"]["grant_version"] = grant_version

    fg2 = "\n".join((
        "F6-CI:FG2",
        "Use only BeyondQuant MCP. Create exactly one approved BacktestTask for the exact ResearchTask, approved StrategyVersion and stock-pool snapshot below. This Agent turn must submit the BacktestTask and its durable SignalJob only. Do not execute a native backtest, create or train/predict ML, create comparisons/reports, use the Product API, or transition/complete the ResearchTask. Return the exact BacktestTask and SignalJob IDs.",
        f"task_id={task_id}", f"strategy_version_artifact_id={version_id}",
        f"approval_artifact_id={approval_id}", f"stock_pool_snapshot_id={snapshot_id}",
        "start_date=2026-03-12", "end_date=2026-03-30", "parameters={}",
        "execution={\"initial_capital\":100000,\"commission_rate\":0.0003,\"stamp_tax_rate\":0.001,\"slippage_rate\":0,\"lot_size\":100,\"max_positions\":10,\"a_share_rules\":true,\"max_runtime_seconds\":10,\"max_attempts\":2}",
        "order_quantity=100", "backtest_task_idempotency_key=f6-ci-backtest-task-" + project,
    ))
    state["stage"] = "foreground_2_exact_backtest_task_and_signal_job"
    state["mutation_attempts"].append("foreground_agent_turn_2")
    try:
        accepted = call("POST", f"/v1/agent/sessions/{session_id}/turns", {"content": fg2},
                        expected=202, timeout=20)
        require(isinstance(accepted, dict) and accepted.get("accepted") is True
                and accepted.get("session_id") == session_id, "foreground_2_not_accepted")
        state["identities"]["foreground_2_runtime_root_id"] = identifier(
            accepted.get("run_id"), RUNTIME_ROOT_PATTERN, "foreground_2_runtime_root_missing")
    except EvidenceError as error:
        state["uncertain_actions"].append("foreground_agent_turn_2")
        state["checks"]["foreground_2_post_category"] = error.category
    _, fg2_answer = _wait_answer(call, session_id, fg2, ("BacktestTask ", "SignalJob "))
    bt_match = re.search(r"BacktestTask (backtesttask_[0-9a-f]{32})", fg2_answer)
    job_match = re.search(r"SignalJob (signaljob_[0-9a-f]{32})", fg2_answer)
    backtest_task_id = identifier(bt_match.group(1) if bt_match else None, BACKTEST_TASK_PATTERN,
                                  "foreground_2_backtest_task_id_missing")
    signal_job_id = identifier(job_match.group(1) if job_match else None, SIGNAL_JOB_PATTERN,
                               "foreground_2_signal_job_id_missing")
    require(backtest_task_id == "backtesttask_" + signal_job_id.removeprefix("signaljob_"),
            "derived_backtest_task_identity_invalid")
    state["identities"].update(backtest_task_id=backtest_task_id, signal_job_id=signal_job_id)

    state["stage"] = "durable_exact_job_admission_with_worker_stopped"
    job_view = call("GET", f"/api/product/signal-producer/jobs/{signal_job_id}")
    job = job_view.get("job") if isinstance(job_view, dict) else None
    require(isinstance(job, dict) and job.get("job_id") == signal_job_id
            and job.get("task_id") == task_id and job.get("owner_principal") == "f6-chain-user"
            and job.get("strategy_version_artifact_id") == version_id
            and job.get("stock_pool_snapshot_id") == snapshot_id
            and job.get("status") == "waiting_for_data"
            and job.get("result_artifact_id") is None,
            "same_signal_job_not_durably_admitted_before_worker")
    state["checks"]["worker"] = "stopped_before_exact_waiting_for_data_job_admission"
    fg2_audit = _read_structured_agent_audit(
        "fg2", task_id=task_id, conversation_id=session_id, trace_id=trace_id,
        runtime_root_id=state["identities"]["foreground_2_runtime_root_id"],
        backtest_task_id=backtest_task_id,
        expected_events=[
            ("byq_backtest_task_create", "authorized", None, None),
            ("byq_backtest_task_create", "success", "backtest_task", backtest_task_id),
        ])
    state["audit_summaries"]["fg2"] = fg2_audit
    state["identities"]["foreground_2_agent_run_id"] = fg2_audit["agent_run_id"]
    require(fg2_audit["session_id"] == state["identities"]["runtime_session_id"],
            "foreground_structured_runtime_session_changed")
    state["checks"]["foreground_2_structured_audit"] = "exact_terminal_run_owner_workspace_session_trace_and_resources"

    state["stage"] = "gateway_restart_and_same_live_session_reattach"
    _compose_once("gateway_restart", "restart", "gateway")
    binding = _compose("port", "gateway", "8100", timeout=15)
    require(re.fullmatch(r"127\.0\.0\.1:[0-9]{1,5}", binding) is not None,
            "restarted_gateway_not_loopback_bound")
    origin = "http://" + binding
    reattached = _post_once(call, "gateway_session_resume", f"/v1/agent/sessions/{session_id}/resume",
                            {}, timeout=35)
    require(isinstance(reattached, dict) and reattached.get("continuity") == "reattached",
            "original_live_session_not_reattached")
    session_after_restart = _session_call(call, session_id)
    require(session_after_restart.get("conversation", {}).get("trace_id") == trace_id
            and _answer_after(session_after_restart, fg2) == fg2_answer,
            "original_session_answer_or_trace_changed_after_gateway_restart")
    same_job = call("GET", f"/api/product/signal-producer/jobs/{signal_job_id}")
    same_job_row = same_job.get("job") if isinstance(same_job, dict) else None
    require(isinstance(same_job_row, dict) and same_job_row.get("job_id") == signal_job_id
            and same_job_row.get("task_id") == task_id and same_job_row.get("status") == "waiting_for_data",
            "same_job_not_read_after_gateway_restart")
    state["checks"]["gateway_restart"] = "live_reattach_same_session_and_same_durable_job_no_turn_replay"

    state["stage"] = "start_exact_signal_worker_once"
    active_jobs_view = call("GET", "/api/product/signal-producer/jobs?limit=100&offset=0")
    existing_rows = active_jobs_view.get("jobs") if isinstance(active_jobs_view, dict) else None
    require(isinstance(existing_rows, list), "signal_job_list_invalid")
    f6_jobs = [row for row in existing_rows if isinstance(row, dict)
               and row.get("owner_principal") == "f6-chain-user"
               and row.get("status") in {"waiting_for_data", "queued", "running"}]
    require(len(f6_jobs) == 1 and f6_jobs[0].get("job_id") == signal_job_id,
            "unexpected_active_job_in_dedicated_f6_owner_scope")
    worker_start_attempted = True
    _compose_once("signal_worker_start_after_durable_job", "up", "-d", "--no-deps", "--no-build",
                  "signal-worker")
    state["checks"]["worker"] = "started_once_after_exact_durable_job_admission"

    state["stage"] = "wait_for_exact_completed_job_and_validated_signal_artifact"
    deadline = time.monotonic() + 240
    job = None
    artifact = None
    last_status = None
    while time.monotonic() < deadline:
        job_view = call("GET", f"/api/product/signal-producer/jobs/{signal_job_id}", timeout=15)
        job = job_view.get("job") if isinstance(job_view, dict) else None
        require(isinstance(job, dict) and job.get("job_id") == signal_job_id
                and job.get("task_id") == task_id and job.get("owner_principal") == "f6-chain-user"
                and job.get("strategy_version_artifact_id") == version_id
                and job.get("stock_pool_snapshot_id") == snapshot_id,
                "signal_worker_job_identity_changed")
        status = job.get("status")
        if status != last_status:
            print(json.dumps({"stage": "signal_job", "status": status}), flush=True)
            last_status = status
        if status in {"failed", "cancelled"}:
            raise EvidenceError("exact_signal_job_" + str(status))
        if status == "completed":
            artifact_id = identifier(job.get("result_artifact_id"), ARTIFACT_PATTERN,
                                     "completed_signal_job_artifact_missing")
            artifact = call("GET", f"/api/product/research/artifacts/{artifact_id}")
            task_workspace_id = task.get("workspace_id") if isinstance(task, dict) else None
            require(isinstance(task_workspace_id, str) and task_workspace_id.startswith("workspace_"),
                    "research_task_workspace_missing_for_signal_artifact")
            artifact = _assert_validated_signal_artifact(
                artifact, artifact_id=artifact_id, task_id=task_id, owner_principal="f6-chain-user",
                workspace_id=task_workspace_id, strategy_version_artifact_id=version_id,
                stock_pool_snapshot_id=snapshot_id, signal_job_id=signal_job_id)
            state["identities"]["signal_snapshot_artifact_id"] = artifact_id
            break
        require(status in {"waiting_for_data", "queued", "running"}, "exact_signal_job_status_invalid")
        time.sleep(2)
    require(isinstance(job, dict) and job.get("status") == "completed" and isinstance(artifact, dict),
            "exact_signal_job_or_artifact_deadline")

    state["stage"] = "background_one_exact_task_ready_read"
    request_settlement = None
    assistant_answer = None
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        # Both readiness facts must be observed in the same bounded polling
        # pass. A settlement from an earlier pass is not enough to close it.
        request_settlement = None
        session_view = _session_call(call, session_id)
        messages = _messages(session_view)
        bg_users = [index for index, item in enumerate(messages)
                    if item.get("role") == "user"
                    and "BYQ trusted read-only task-ready follow-up for exact task " + task_id
                       in _body_text(item.get("content"))]
        require(len(bg_users) <= 1, "background_user_turn_duplicated")
        ready_event_key = None
        if bg_users:
            user_text = _body_text(messages[bg_users[0]].get("content"))
            ready_events = re.findall(r"Ready signal: (\{[^\n]+\})", user_text)
            require(len(ready_events) == 1, "background_ready_signal_missing_or_ambiguous")
            try:
                ready_event = json.loads(ready_events[0])
            except (ValueError, TypeError):
                raise EvidenceError("background_ready_signal_invalid") from None
            require(isinstance(ready_event, dict)
                    and ready_event.get("kind") == "signal_producer_jobs"
                    and ready_event.get("data_ready") is True
                    and ready_event.get("identity") == signal_job_id
                    and ready_event.get("status") == "completed"
                    and ready_event.get("result_artifact_id") == state["identities"]["signal_snapshot_artifact_id"],
                    "background_ready_signal_not_exact_job_and_artifact")
            ready_event_key = "ready-v1:" + hashlib.sha256(
                json.dumps(ready_event, sort_keys=True).encode("utf-8")).hexdigest()
            assistant_answer = "\n".join(_body_text(item.get("content")) for item in messages[bg_users[0] + 1:]
                                          if item.get("role") == "assistant")
        view = _permission_view(call, task_id)
        require(view.get("schema_version") == "task-continuation-permission.v2"
                and view.get("permission", {}).get("grant_version") == grant_version,
                "background_grant_identity_changed")
        request_state = view.get("request_state")
        require(isinstance(request_state, dict), "background_request_state_missing")
        if (request_state.get("requests_reserved") == 1
                and request_state.get("requests_remaining") == 0
                and request_state.get("unconfirmed_requests") == 0):
            candidate = request_state.get("request_identity")
            if (ready_event_key is not None and isinstance(candidate, dict)
                    and candidate.get("status") == "settled"
                    and candidate.get("dispatch_attempts") == 1
                    and candidate.get("grant_version") == grant_version):
                require(candidate.get("event_key") == ready_event_key,
                        "settlement_ready_event_does_not_match_delivered_signal_job")
                request_settlement = _validate_settlement_identity(candidate, grant_version)
        answer_ready = (isinstance(assistant_answer, str)
                        and all(value in assistant_answer for value in (
                            task_id, backtest_task_id, signal_job_id,
                            state["identities"]["signal_snapshot_artifact_id"],
                        ))
                        and "No domain writes were made." in assistant_answer)
        if request_settlement is not None and answer_ready:
            break
        if bg_users and isinstance(session_view.get("conversation"), dict):
            require(session_view["conversation"].get("status") not in {"failed", "interrupted", "archived"},
                    "background_agent_session_failed")
        time.sleep(2)
    require(isinstance(request_settlement, dict)
            and request_settlement.get("status") == "settled"
            and request_settlement.get("dispatch_attempts") == 1
            and request_settlement.get("grant_version") == grant_version
            and isinstance(request_settlement.get("run_id"), str)
            and RUNTIME_ROOT_PATTERN.fullmatch(request_settlement["run_id"]) is not None
            and request_settlement.get("outcome") == "completed"
            and isinstance(request_settlement.get("settlement_sha256"), str)
            and SHA256_PATTERN.fullmatch(request_settlement["settlement_sha256"]) is not None,
            "single_background_request_not_durably_settled")
    require(isinstance(assistant_answer, str)
            and all(value in assistant_answer for value in (task_id, backtest_task_id, signal_job_id,
                                                             state["identities"]["signal_snapshot_artifact_id"]))
            and "No domain writes were made." in assistant_answer,
            "background_answer_not_persisted_for_exact_ready_evidence")

    permission_state = _permission_view(call, task_id)
    usage = permission_state.get("request_state", {}).get("request_usage")
    require(isinstance(usage, dict) and usage.get("schema_version") == "continuation-request-usage.v1"
            and usage.get("execution_profile") == permission.get("execution_profile")
            and usage.get("request_limits") == limits
            and usage.get("limit_violations") == [],
            "settled_request_usage_profile_invalid")
    admission = usage.get("admission_usage")
    actual = usage.get("actual_usage")
    require(isinstance(admission, dict) and isinstance(actual, dict)
            and admission.get("provider_calls") == admission.get("provider_attempts")
            and 1 <= admission.get("provider_attempts", 0) <= limits["max_attempts"]
            and admission.get("tool_calls") == 7
            and admission.get("max_concurrent") == 1
            and admission.get("input_bytes", 0) <= limits["max_total_input_bytes"]
            and admission.get("declared_output_tokens", 0) <= limits["max_total_output_tokens"]
            and admission.get("tool_payload_bytes", 0) <= limits["max_total_tool_payload_bytes"],
            "request_gate_admission_measurements_invalid")
    require(actual == {
        "input_tokens": "unknown", "cache_read_tokens": "unknown", "output_tokens": "unknown",
        "provider_attempts": "unknown", "usage_source": "unknown", "completeness": "unknown",
    }, "synthetic_provider_usage_was_not_preserved_as_unknown")
    event_key = request_settlement.get("event_key")
    require(isinstance(event_key, str)
            and re.fullmatch(r"ready-v1:[0-9a-f]{64}", event_key) is not None,
            "request_ready_event_identity_invalid")
    state["identities"]["background_reservation_id"] = request_settlement["reservation_id"]
    state["identities"]["background_event_key"] = event_key
    background_audit = _read_structured_agent_audit(
        "background", task_id=task_id, conversation_id=session_id, trace_id=trace_id,
        runtime_root_id=request_settlement["run_id"], backtest_task_id=backtest_task_id,
        settlement=request_settlement,
        expected_events=[
            ("byq_research_get", "authorized", "research_task", task_id),
            ("byq_research_get", "success", "research_task", task_id),
            ("byq_backtest_task_get", "authorized", "backtest_task", backtest_task_id),
            ("byq_backtest_task_get", "success", "backtest_task", backtest_task_id),
        ])
    state["audit_summaries"]["background"] = background_audit
    state["identities"]["background_runtime_root_id"] = request_settlement["run_id"]
    state["identities"]["background_agent_run_id"] = background_audit["agent_run_id"]
    require(background_audit["session_id"] == state["identities"]["runtime_session_id"],
            "background_structured_runtime_session_changed")
    task_after = call("GET", f"/api/product/research/tasks/{task_id}")
    require(isinstance(task_after, dict) and task_after.get("task_id") == task_id
            and task_after.get("conversation_id") == session_id
            and task_after.get("trace_id") == trace_id and task_after.get("status") != "completed",
            "background_turn_falsely_completed_research_task")
    state["checks"].update({
        "background_answer_and_settlement": "both_persisted_for_same_task_and_request",
        "background_structured_audit": "settlement_runtime_root_bound_to_exact_terminal_owner_run_and_two_read_actions",
        "request_state": "one_reservation_one_dispatch_exact_ready_event_no_second_request",
        "request_gate": "measured_admission_limits_and_unknown_actual_model_usage",
        "background_domain_scope": "only_byq_research_get_exact_task_and_byq_backtest_task_get_exact_task",
        "background_ready_event": "exact_signal_job_and_validated_artifact_hash_bound_to_grant_and_settlement",
        "task_completion": "not_required_and_not_fabricated",
    })

    state["stage"] = "exact_grant_revoke_and_get_confirmation"
    _revoke_exact_grant(call)
    require(state["checks"].get("revoke") == "one_exact_post_and_get_confirmed_no_second_request",
            "exact_grant_revoke_get_or_no_second_request_failed")

    state["stage"] = "passed"
    state["status"] = "passed"
    print(json.dumps({"stage": "f6_read_only_settlement_passed",
                      "task_id": task_id, "backtest_task_id": backtest_task_id,
                      "signal_job_id": signal_job_id,
                      "signal_snapshot_artifact_id": state["identities"]["signal_snapshot_artifact_id"]}), flush=True)
except EvidenceError as error:
    state["failure_category"] = error.category
    try:
        _write_evidence()
    except (FileExistsError, OSError):
        print(json.dumps({"stage": "first_failure_evidence_write_failed", "status": "failed",
                          "failure_category": error.category}), flush=True)
    try:
        uncertain_foreground = any(item.startswith("foreground_agent_turn")
                                   for item in state["uncertain_actions"])
        _failure_readonly_window(client, seconds=20 if "background" in str(state["stage"])
                                 or uncertain_foreground else 4)
    except EvidenceError as observation_error:
        state["failure_observation"] = {"category": observation_error.category}
except Exception as error:  # evidence stores only exception class, never message or payload
    state["failure_category"] = type(error).__name__
    try:
        _write_evidence()
    except (FileExistsError, OSError):
        print(json.dumps({"stage": "first_failure_evidence_write_failed", "status": "failed",
                          "failure_category": state["failure_category"]}), flush=True)
    try:
        _failure_readonly_window(client, seconds=20 if "background" in str(state["stage"]) else 4)
    except EvidenceError as observation_error:
        state["failure_observation"] = {"category": observation_error.category}
finally:
    if worker_start_attempted:
        try:
            _compose_once("signal_worker_stop_after_chain", "stop", "signal-worker")
            state["checks"]["worker_final_cleanup"] = "dedicated_signal_worker_stopped"
        except EvidenceError as error:
            state["checks"]["worker_final_cleanup"] = error.category
            if state["status"] == "passed":
                state["status"] = "failed"
                state["failure_category"] = "worker_cleanup_failed"
    if not state["revoke_attempted"]:
        _revoke_exact_grant(call)
        if state["status"] == "passed" and state["checks"].get("revoke") != "one_exact_post_and_get_confirmed_no_second_request":
            # A successful run must use the single explicit revoke path above.
            state["status"] = "failed"
            state["failure_category"] = "exact_permission_revoke_not_proven"
    try:
        _write_evidence(suffix=".closeout.json" if state.get("primary_evidence_written") else "")
    except FileExistsError:
        print(json.dumps({"stage": "evidence_path_collision", "status": state["status"]}), flush=True)
        if state["status"] == "passed":
            raise
    except OSError:
        print(json.dumps({"stage": "evidence_write_failed", "status": state["status"]}), flush=True)
        if state["status"] == "passed":
            raise

if state["status"] != "passed":
    raise SystemExit("F6 current read-only settlement failed: " + str(state.get("failure_category") or "unknown"))
