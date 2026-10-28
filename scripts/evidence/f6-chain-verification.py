#!/usr/bin/env python3
"""One-shot Product API driver for the current ADR-0111 F6 contract.

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
import runpy
import subprocess
import sys
import time
import threading
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
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
_continuation_contract_path = Path(__file__).resolve().parents[2] / "packages/contracts/continuation_request.py"
_continuation_contract = runpy.run_path(str(_continuation_contract_path))
_execution_profile_v2 = _continuation_contract["execution_profile_v2"]
_request_limits_v2 = _continuation_contract["request_limits_v2"]
_validate_request_usage_v2 = _continuation_contract["validate_request_usage_v2"]
_validate_reservation_v3 = _continuation_contract["validate_reservation_v3"]
del _continuation_contract
SESSION_IDENTITY_FAILURES = frozenset({
    "original_agent_session_identity_changed", "original_agent_session_trace_changed",
})
UNTRUSTED_IDENTITY_FAILURES = frozenset({
    *SESSION_IDENTITY_FAILURES,
    "reconciliation_task_identity_changed", "reconciliation_execution_options_identity_changed",
    "reconciliation_signal_job_identity_changed", "execution_options_identity_changed",
    "reconciliation_request_identity_changed",
    "structured_agent_audit_task_scope_invalid", "structured_agent_audit_runtime_session_invalid",
    "structured_agent_audit_envelope_invalid", "structured_agent_audit_event_invalid",
    "structured_agent_audit_scope_mismatch", "unexpected_structured_request_receipt",
    "structured_runtime_root_identity_invalid", "structured_runtime_root_scope_invalid",
    "structured_agent_run_identity_invalid", "structured_agent_audit_event_identity_invalid",
    "structured_agent_audit_actions_or_resources_invalid", "structured_settlement_root_link_invalid",
    "research_task_original_conversation_identity_invalid", "strategy_draft_product_lineage_invalid",
    "validated_strategy_version_product_lineage_invalid", "human_strategy_approval_lineage_invalid",
    "default_execution_options_not_unbounded", "background_execution_profile_binding_invalid",
    "background_execution_profile_limits_invalid", "background_execution_options_binding_changed",
    "foreground_structured_runtime_session_changed", "background_structured_runtime_session_changed",
    "original_session_answer_or_trace_changed_after_gateway_restart", "same_job_identity_changed",
    "signal_worker_job_identity_changed", "unexpected_active_job_in_dedicated_f6_owner_scope",
    "gateway_event_identity_changed",
    "validated_signal_artifact_identity_invalid", "validated_signal_artifact_content_lineage_invalid",
    "validated_signal_artifact_lineage_invalid",
    "background_runtime_root_identity_invalid", "background_reservation_identity_invalid",
    "background_settlement_digest_invalid", "background_ready_event_identity_invalid",
    "background_request_carrier_or_usage_invalid", "background_request_receipt_not_exactly_settled",
    "background_ready_event_does_not_match_delivered_signal_job",
    "background_root_correlation_ambiguous", "background_answer_correlation_ambiguous",
    "structured_ready_event_input_binding_invalid",
})


class EvidenceError(RuntimeError):
    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


class HttpFailure(EvidenceError):
    def __init__(self, status: int, public_reason: str | None = None) -> None:
        super().__init__("http_status_" + str(status))
        self.status = status
        self.public_reason = public_reason


def _product_session_public_error_reason(response: object) -> str:
    """Classify only exact public Gateway messages; never persist response text."""
    try:
        body = json.loads(response.read(2048))
    except Exception:
        # A failed read (including http.client.IncompleteRead) must not escape
        # the HTTPError path and drop the mutation's unknown-outcome marker.
        return "unclassified"
    detail = body.get("detail") if isinstance(body, dict) else None
    return {
        "Agent runtime authority is not ready": "runtime_authority_not_ready",
        "runtime adapter unavailable": "runtime_adapter_unavailable",
        "product model is unavailable": "product_model_unavailable",
        "runtime adapter rejected the request": "runtime_adapter_rejected",
    }.get(detail, "unclassified") if isinstance(detail, str) else "unclassified"


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


def _session_call(api_call, session_id: str, trace_id: str, *, timeout: float = 12) -> dict[str, object]:
    body = api_call("GET", f"/v1/agent/sessions/{session_id}", timeout=timeout)
    conversation = body.get("conversation") if isinstance(body, dict) else None
    require(isinstance(conversation, dict) and conversation.get("session_id") == session_id,
            "original_agent_session_identity_changed")
    require(conversation.get("trace_id") == trace_id,
            "original_agent_session_trace_changed")
    return body


def _answer_after(body: dict[str, object], prompt: str) -> str | None:
    messages = _messages(body)
    persisted_prompt = " ".join(prompt.split())
    matches = [index for index, item in enumerate(messages)
               if item.get("role") == "user"
               and " ".join(_body_text(item.get("content")).split()) == persisted_prompt]
    require(len(matches) <= 1, "agent_user_turn_duplicate")
    if not matches:
        return None
    following = messages[matches[0] + 1:]
    return "\n".join(_body_text(item.get("content")) for item in following
                     if item.get("role") == "assistant")


def _wait_answer(api_call, session_id: str, trace_id: str, prompt: str,
                 required: tuple[str, ...], *, timeout: int = 180) -> tuple[dict[str, object], str]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        body = _session_call(api_call, session_id, trace_id, timeout=min(12, remaining))
        answer = _answer_after(body, prompt)
        messages = _messages(body)
        conversation = body.get("conversation")
        status = conversation.get("status") if isinstance(conversation, dict) else None
        state["answer_wait_observation"] = {
            "foreground_step": ("fg1" if prompt.startswith("F6-CI:FG1\n") else
                                "fg2" if prompt.startswith("F6-CI:FG2\n") else "unknown"),
            "session_status": (status if status in {
                "active", "unknown", "interrupted", "archived", "failed",
            } else "other"),
            "session_message_count": len(messages),
            "prompt_matched": answer is not None,
            "assistant_answer_present": bool(answer),
            "required_answer_present": answer is not None and all(value in answer for value in required),
        }
        if answer is not None and all(value in answer for value in required):
            return body, answer
        require(not isinstance(conversation, dict)
                or conversation.get("status") not in {"failed", "interrupted", "archived"},
                "original_agent_session_failed")
        time.sleep(min(1, max(0, deadline - time.monotonic())))
    raise EvidenceError("agent_answer_not_persisted_before_deadline")


def _post_once(client, label: str, path: str, payload: object, *, expected: int = 200,
               headers: dict[str, str] | None = None, timeout: int = 45) -> dict[str, object]:
    state["mutation_attempts"].append(label)
    try:
        result = client("POST", path, payload, expected=expected, headers=headers, timeout=timeout)
    except EvidenceError as error:
        if label == "product_session_create" and isinstance(error, HttpFailure):
            state["product_session_public_error_reason"] = error.public_reason or "unclassified"
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


def _proxy_diagnostic(stage):
    try:
        diagnostic = Path(__file__).resolve().parents[1] / "ci" / "f6-proxy-diagnostics.py"
        response = subprocess.run([sys.executable, str(diagnostic), "--project", os.environ.get("COMPOSE_PROJECT_NAME", ""),
                                   "--stage", stage], capture_output=True, text=True, timeout=35)
        if response.returncode == 0 and len(response.stdout.encode()) <= 16384:
            print(response.stdout.strip(), flush=True)
        else:
            print("F6 proxy diagnostics: collector incomplete; proxy cause unknown", flush=True)
    except (OSError, subprocess.SubprocessError):
        print("F6 proxy diagnostics: collector incomplete; proxy cause unknown", flush=True)


def _compose_once(label: str, *args: str, timeout: int = 45) -> str:
    state["mutation_attempts"].append(label)
    try:
        return _compose(*args, timeout=timeout)
    except EvidenceError:
        state["uncertain_actions"].append(label)
        raise


def _fixture_workspace(prepared_id: str | None, product_slot_id: str | None,
                       create_user) -> str:
    """Use the release fixture's prepared user without another write."""
    if prepared_id is not None:
        workspace_id = identifier(prepared_id, re.compile(r"workspace_[0-9a-f]{32}\Z"),
                                  "test_user_workspace_invalid")
        require(workspace_id == product_slot_id, "test_user_product_slot_mismatch")
        return workspace_id
    fixture_result = create_user()
    require(isinstance(fixture_result, dict) and set(fixture_result) == {"owner", "workspace_id"}
            and fixture_result["owner"] == "f6-chain-user", "test_user_fixture_invalid")
    return identifier(fixture_result["workspace_id"],
                      re.compile(r"workspace_[0-9a-f]{32}\Z"),
                      "test_user_workspace_invalid")


F6_OBSERVER_STAGES = frozenset({
    "preflight", "isolate_signal_worker", "prepare_only_test_user",
    "product_login_and_original_session", "foreground_1_task_and_strategy_version",
    "verify_exact_task_and_strategy_lineage", "human_strategy_approval_and_stock_pool",
    "default_execution_options_exact_conversation", "foreground_2_exact_backtest_task_and_signal_job",
    "durable_exact_job_admission_with_worker_stopped", "gateway_restart_and_original_logical_session_connect",
    "gateway_ready_original_session_before_connect", "gateway_original_event_connection_once",
    "gateway_same_original_session_after_connect", "start_exact_signal_worker_once",
    "wait_for_exact_completed_job_and_validated_signal_artifact", "background_one_exact_task_ready_read",
    "exact_execution_options_stop_and_get_confirmation", "passed",
})
F6_OBSERVER_ACTIONS = frozenset({
    "signal_worker_stop_before_job", "isolated_ci_user_fixture", "product_login",
    "product_session_create", "foreground_agent_turn_1", "product_strategy_approval",
    "product_stock_pool", "foreground_agent_turn_2",
    "gateway_restart", "signal_worker_start_after_durable_job",
    "signal_worker_stop_after_chain", "execution_options_disable",
})


def _closed_execution_observation() -> dict[str, object]:
    """Only bounded, known observer categories may enter the uploaded summary."""
    stage = state.get("stage")
    result: dict[str, object] = {
        "observer_stage": stage if type(stage) is str and stage in F6_OBSERVER_STAGES else "unknown",
    }
    for key in ("mutation_attempts", "uncertain_actions"):
        values = state.get(key)
        if type(values) is not list:
            result[key] = []
            result[key + "_values_unknown"] = True
            result[key + "_truncated"] = False
            continue
        result[key] = [item for item in values[:32]
                       if type(item) is str and item in F6_OBSERVER_ACTIONS]
        result[key + "_values_unknown"] = any(
            type(item) is not str or item not in F6_OBSERVER_ACTIONS for item in values[:32])
        result[key + "_truncated"] = len(values) > 32
    return result


def _wait_gateway_original_session(api_call, session_id: str, trace_id: str,
                                   prompt: str, answer: str, *, seconds: float = 35) -> None:
    """Wait by bounded reads before connecting the original public event stream."""
    deadline = time.monotonic() + min(35, max(0, seconds))
    reads = 0
    while time.monotonic() < deadline:
        try:
            reads += 1
            ready = api_call("GET", "/agent-readyz", timeout=_remaining_timeout(deadline, 5))
            require(isinstance(ready, dict) and ready.get("status") == "ready",
                    "gateway_agent_readiness_invalid")
            reads += 1
            view = _session_call(api_call, session_id, trace_id,
                                 timeout=_remaining_timeout(deadline, 5))
            require(view.get("conversation", {}).get("status") in {"active", "unknown"},
                    "original_agent_session_failed")
            require(_answer_after(view, prompt) == answer,
                    "original_session_answer_or_trace_changed_after_gateway_restart")
            require(time.monotonic() <= deadline, "gateway_readiness_deadline")
            state["checks"]["gateway_readiness"] = {
                "status": "agent_ready_and_original_durable_answer_observed",
                "reads": min(reads, 256), "reads_capped": reads > 256,
                "methods": ["GET"],
            }
            return
        except EvidenceError as error:
            if (error.category != "http_transport_or_read_outcome_unknown"
                    and not (isinstance(error, HttpFailure) and error.status in {502, 503, 504})):
                raise
        time.sleep(min(0.5, max(0, deadline - time.monotonic())))
    raise EvidenceError("gateway_readiness_deadline")


class GatewayEventConnection:
    """One bounded public connection to the existing logical session.

    Gateway may bind its transient delivery map through attach_live_only. This
    neither resumes a closed DSH process nor submits another model request.
    Keep this connection through evidence saving and failure reconciliation.
    """

    def __init__(self, opener, base_origin: str, session_id: str, trace_id: str):
        self.stop = threading.Event()
        self.failure = None
        self.deadline = time.monotonic() + 600
        self.session_id, self.trace_id = session_id, trace_id
        request = Request(base_origin + f"/v1/workflows/{session_id}/events",
                          headers={"Accept": "text/event-stream"}, method="GET")
        try:
            self.response = opener.open(request, timeout=30)
        except urllib.error.HTTPError as error:
            raise HttpFailure(int(error.code)) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise EvidenceError("gateway_event_connection_unconfirmed") from None
        if self.response.status != 200 or self.response.headers.get_content_type() != "text/event-stream":
            self.response.close()
            raise EvidenceError("gateway_event_connection_invalid")
        self.thread = threading.Thread(target=self._drain, name="f6-public-events", daemon=True)
        self.thread.start()

    def _drain(self):
        total = 0
        try:
            while not self.stop.is_set() and time.monotonic() < self.deadline:
                line = self.response.readline(65537)
                if self.stop.is_set():
                    return
                if not line:
                    raise EvidenceError("gateway_event_connection_closed")
                total += len(line)
                require(len(line) <= 65536 and total <= 16777216,
                        "gateway_event_observation_limit")
                if line.startswith(b"data:"):
                    try:
                        event = json.loads(line[5:].strip())
                    except (ValueError, TypeError):
                        raise EvidenceError("gateway_event_projection_invalid") from None
                    require(isinstance(event, dict) and event.get("session_id") == self.session_id
                            and event.get("trace_id") == self.trace_id,
                            "gateway_event_identity_changed")
            if not self.stop.is_set():
                raise EvidenceError("gateway_event_observation_deadline")
        except EvidenceError as error:
            self.failure = error.category
        except Exception:
            if not self.stop.is_set():
                self.failure = "gateway_event_read_unconfirmed"

    def assert_healthy(self):
        require(self.failure is None and self.thread.is_alive()
                and time.monotonic() < self.deadline,
                self.failure or "gateway_event_connection_not_live")

    def close(self):
        self.stop.set()
        self.response.close()
        self.thread.join(timeout=1)


def _assert_original_session_connected(view: object, session_id: str, trace_id: str,
                                       prompt: str, answer: str) -> None:
    require(isinstance(view, dict)
            and view.get("conversation", {}).get("session_id") == session_id
            and view.get("conversation", {}).get("trace_id") == trace_id
            and view.get("conversation", {}).get("status") == "active"
            and _answer_after(view, prompt) == answer,
            "original_session_answer_or_trace_changed_after_gateway_restart")


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
        "product_session_public_error_reason": state.get("product_session_public_error_reason"),
        "failure_reconciliation_mode": state.get("failure_reconciliation_mode"),
        "mutation_attempts": list(state["mutation_attempts"]),
        "uncertain_actions": list(state["uncertain_actions"]),
        "identities": {key: value for key, value in state["identities"].items() if value is not None},
        "checks": state["checks"],
        "structured_agent_audits": state.get("audit_summaries", {}),
        "answer_wait_observation": state.get("answer_wait_observation"),
        "background_wait_observation": state.get("background_wait_observation"),
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
        "project": project,
        "identities": payload["identities"],
        "structured_agent_audits": payload["structured_agent_audits"],
        "answer_wait_observation": payload["answer_wait_observation"],
        "background_wait_observation": payload["background_wait_observation"],
        "failure_reconciliation": _failure_observation_summary(state.get("failure_observation")),
        "execution_observation": _closed_execution_observation(),
    }, sort_keys=True), flush=True)
    if not suffix:
        state["primary_evidence_written"] = True
    return digest


def _background_wait_observation(session_view: dict, root_id: str | None, *,
                                 bg_user_count: int, answer_present: bool,
                                 answer_ready: bool) -> dict[str, object]:
    """Closed diagnostic projection; no answer text or receipt is a PASS proof."""
    def category(value, allowed):
        return value if type(value) is str and value in allowed else "invalid_or_unknown"

    def count(value, maximum):
        return value if type(value) is int and 0 <= value <= maximum else "invalid_or_unknown"

    return {
        "qualification": "diagnostic_only_not_a_pass",
        "session_status": category(session_view.get("conversation", {}).get("status"),
            {"active", "failed", "interrupted", "archived"}),
        "message_count": count(len(_messages(session_view)), 10000),
        "background_user_count": count(bg_user_count, 1),
        "assistant_answer_present": answer_present is True,
        "exact_answer_ready": answer_ready is True,
        "runtime_root_sha256": (hashlib.sha256(root_id.encode()).hexdigest()
            if isinstance(root_id, str) and RUNTIME_ROOT_PATTERN.fullmatch(root_id) else None),
        "settlement_status": "not_read_in_public_session",
    }


def _background_answer_for_root(session_view: dict[str, object], runtime_root_id: str) -> str | None:
    """Correlate durable Product output with one normalized root, never a fake user."""
    require(isinstance(runtime_root_id, str) and RUNTIME_ROOT_PATTERN.fullmatch(runtime_root_id) is not None,
            "background_runtime_root_identity_invalid")
    conversation = session_view.get("conversation")
    require(isinstance(conversation, dict), "background_conversation_missing")
    events = session_view.get("events")
    require(isinstance(events, list), "background_root_events_missing")
    owned = [event for event in events if isinstance(event, dict)
             and event.get("source") == "runtime-adapter"
             and event.get("session_id") == conversation.get("session_id")
             and event.get("trace_id") == conversation.get("trace_id")
             and type(event.get("sequence")) is int]
    starts = [event for event in owned if event.get("kind") == "session.started"
              and isinstance(event.get("payload"), dict)
              and event["payload"].get("run_id") == runtime_root_id]
    terminals = [event for event in owned if event.get("kind") in {
        "session.result", "session.failed", "session.cancelled", "session.result.discarded"}
        and isinstance(event.get("payload"), dict)
        and event["payload"].get("run_id") == runtime_root_id]
    require(len(starts) <= 1 and len(terminals) <= 1, "background_root_correlation_ambiguous")
    if not starts or not terminals:
        return None
    start, terminal = starts[0], terminals[0]
    require(terminal.get("kind") == "session.result", "background_agent_root_not_completed")
    require(start["sequence"] < terminal["sequence"] and not any(
        event.get("kind") == "session.started"
        and start["sequence"] < event["sequence"] < terminal["sequence"] for event in owned),
        "background_root_correlation_ambiguous")
    # Gateway intentionally omits an output event from this GET once its exact
    # workflow_sequence is persisted. Product assistant rows are the durable
    # answer projection; the closed Backend root/audit is checked separately.
    answers = [message for message in _messages(session_view)
               if message.get("role") == "assistant"
               and type(message.get("workflow_sequence")) is int
               and start["sequence"] < message["workflow_sequence"] < terminal["sequence"]
               and isinstance(message.get("content"), str) and message["content"].strip()]
    require(len(answers) <= 16 and len({item["workflow_sequence"] for item in answers}) == len(answers),
            "background_answer_correlation_ambiguous")
    return "\n".join(item["content"].strip() for item in sorted(
        answers, key=lambda item: item["workflow_sequence"])) if answers else None


def _assert_background_ready_signal(receipt: dict[str, object], signal_job_id: str,
                                    artifact_id: str) -> None:
    carrier = _validate_reservation_v3(receipt.get("reservation"))
    digest = carrier["idempotency_key"].removeprefix("task-ready-event:")
    require(receipt.get("signal_job_id") == carrier["signal_job_id"] == signal_job_id
            and carrier["result_artifact_id"] == artifact_id
            and receipt.get("reservation_id") == "continuation_" + digest[:32]
            and receipt.get("event_key") == carrier["event_key"] == "ready-v1:" + digest,
            "background_ready_event_does_not_match_delivered_signal_job")


def _validate_settlement_identity(candidate: object, options_view: dict) -> dict[str, object]:
    require(isinstance(candidate, dict), "background_request_identity_missing")
    require(candidate.get("status") == "settled"
            and type(candidate.get("dispatch_attempts")) is int and candidate.get("dispatch_attempts") == 1,
            "background_request_receipt_not_exactly_settled")
    try:
        carrier = _validate_reservation_v3(candidate.get("reservation"))
        usage = _validate_request_usage_v2(candidate.get("request_usage"))
    except ValueError:
        raise EvidenceError("background_request_carrier_or_usage_invalid") from None
    require(carrier["execution_profile"] == _execution_profile_v2(
                options_view["options"], revision=options_view["revision"])
            and carrier["request_limits"] == _request_limits_v2(options_view["options"])
            and carrier["conversation_id"] == options_view["conversation_id"]
            and carrier["owner_principal"] == options_view["owner_principal"]
            and carrier["workspace_id"] == options_view["workspace_id"]
            and carrier["task_id"] == state["identities"].get("task_id"),
            "background_execution_options_binding_changed")
    runtime_root_id = candidate.get("run_id")
    require(isinstance(runtime_root_id, str)
            and RUNTIME_ROOT_PATTERN.fullmatch(runtime_root_id) is not None,
            "background_runtime_root_identity_invalid")
    require(isinstance(candidate.get("reservation_id"), str)
            and RESERVATION_PATTERN.fullmatch(candidate["reservation_id"]) is not None,
            "background_reservation_identity_invalid")
    require(usage["execution_profile"] == carrier["execution_profile"]
            and usage["request_limits"] == carrier["request_limits"],
            "background_request_usage_profile_invalid")
    require(isinstance(candidate.get("settlement_sha256"), str)
            and SHA256_PATTERN.fullmatch(candidate["settlement_sha256"]) is not None,
            "background_settlement_digest_invalid")
    digest = carrier["idempotency_key"].removeprefix("task-ready-event:")
    require(candidate.get("reservation_id") == "continuation_" + digest[:32]
            and candidate.get("event_key") == carrier["event_key"] == "ready-v1:" + digest,
            "background_ready_event_identity_invalid")
    runtime_receipt = {"reservation_id": candidate["reservation_id"],
                       "idempotency_key": carrier["idempotency_key"],
                       "status": "settled", "run_id": runtime_root_id,
                       "outcome": candidate.get("outcome"), "request_usage": usage}
    require(hashlib.sha256(json.dumps(runtime_receipt, sort_keys=True,
            separators=(",", ":")).encode()).hexdigest() == candidate["settlement_sha256"],
            "background_settlement_digest_invalid")
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
    require(isinstance(root, dict), "structured_runtime_root_terminal_not_confirmed")
    require(root.get("root_run_id") == runtime_root_id,
            "structured_runtime_root_identity_invalid")
    require(root.get("owner_principal") == "f6-chain-user"
            and root.get("workspace_id") == task.get("workspace_id")
            and root.get("session_id") == runtime_session_id
            and root.get("trace_id") == trace_id,
            "structured_runtime_root_scope_invalid")
    require(root.get("status") == "completed" and root.get("authority_status") == "closed"
            and type(root.get("terminal_sequence")) is int and root["terminal_sequence"] > 0
            and isinstance(root.get("terminal_event_sha256"), str)
            and SHA256_PATTERN.fullmatch(root["terminal_event_sha256"]) is not None,
            "structured_runtime_root_terminal_not_confirmed")
    require(isinstance(run, dict), "structured_agent_run_terminal_not_confirmed")
    require(isinstance(run.get("run_id"), str)
            and AGENT_RUN_PATTERN.fullmatch(run["run_id"]) is not None
            and run.get("root_run_id") == runtime_root_id
            and run.get("owner_principal") == "f6-chain-user"
            and run.get("actor_principal") == "byq-product-agent-" + runtime_session_id
            and run.get("role_id") == "quant_orchestrator"
            and run.get("session_id") == runtime_session_id and run.get("trace_id") == trace_id,
            "structured_agent_run_identity_invalid")
    require(run.get("status") == "completed" and run.get("authority_status") == "closed",
            "structured_agent_run_terminal_not_confirmed")
    require(isinstance(events, list) and len(events) <= 32,
            "structured_agent_audit_events_invalid")
    actual_events: list[tuple[str, str, str | None, str | None]] = []
    seen_audit_ids: set[str] = set()
    for event in events:
        require(isinstance(event, dict) and isinstance(event.get("audit_id"), str)
                and AUDIT_PATTERN.fullmatch(event["audit_id"]) is not None
                and event["audit_id"] not in seen_audit_ids
                and isinstance(event.get("action"), str)
                and isinstance(event.get("outcome"), str)
                and (event.get("resource_type") is None or isinstance(event.get("resource_type"), str))
                and (event.get("resource_id") is None or isinstance(event.get("resource_id"), str)),
                "structured_agent_audit_event_invalid")
        seen_audit_ids.add(event["audit_id"])
        require(event.get("run_id") == run["run_id"] and event.get("owner_principal") == "f6-chain-user"
                and event.get("actor_principal") == run["actor_principal"],
                "structured_agent_audit_event_identity_invalid")
        actual_events.append((event["action"], event.get("outcome"),
                              event.get("resource_type"), event.get("resource_id")))

    if stage == "fg1":
        callbacks = [event for event in events
                     if event["action"] == "local_strategy_validation_callback_exit"]
        require(document.get("fg1_callback_exit_verified") is True and len(callbacks) == 1,
                "structured_agent_audit_actions_or_resources_invalid")
        callback = callbacks[0]
        claim_id = callback.get("resource_id")
        require(isinstance(claim_id, str) and re.fullmatch(r"[0-9a-f]{32}", claim_id)
                and callback.get("outcome") == "callback_exited"
                and callback.get("resource_type") == "domain_call_claim"
                and callback.get("audit_id") == "agent_audit_" + hashlib.sha256(
                    b"byq-local-strategy-validation-callback-exit.v1\0" + claim_id.encode("ascii")
                ).hexdigest()[:32], "structured_agent_audit_actions_or_resources_invalid")
        expected_events = [*expected_events, (
            "local_strategy_validation_callback_exit", "callback_exited", "domain_call_claim", claim_id)]

    expected_active_binding = ("runtime_turn_binding", "active", "runtime_turn", runtime_root_id)
    expected_completed_binding = ("runtime_turn_binding", "completed", "runtime_turn", runtime_root_id)
    binding_events = [event for event in actual_events if event[0] == "runtime_turn_binding"]
    active_bindings = [event for event in binding_events if event[1] == "active"]
    completed_bindings = [event for event in binding_events if event[1] == "completed"]
    invalid_bindings = [event for event in binding_events
                        if event not in {expected_active_binding, expected_completed_binding}]
    domain_events = [event for event in actual_events if event[0] != "runtime_turn_binding"]

    def multiset_delta(observed: list[tuple[str, str, str | None, str | None]],
                       expected: list[tuple[str, str, str | None, str | None]]) -> tuple[list, list]:
        remaining = list(expected)
        extras = []
        for item in observed:
            try:
                remaining.remove(item)
            except ValueError:
                extras.append(item)
        return remaining, extras

    missing_domain_events, extra_domain_events = multiset_delta(domain_events, expected_events)
    known_events = {expected_active_binding, expected_completed_binding, *expected_events}

    def event_projection(items: list[tuple[str, str, str | None, str | None]]) -> list[dict[str, object]]:
        projected = []
        for item in items:
            if item in known_events:
                action, outcome, resource_type, resource_id = item
                projected.append({"action": action, "outcome": outcome,
                                  "resource_type": resource_type, "resource_id": resource_id})
                continue
            fields = {}
            for name, value in zip(("action", "outcome", "resource_type", "resource_id"), item):
                if value is None:
                    encoded = b"null"
                    fields[name] = {"type": "null", "length": 0,
                                    "sha256": hashlib.sha256(encoded).hexdigest()}
                else:
                    encoded = value.encode("utf-8")
                    fields[name] = {"type": "string", "length": len(value),
                                    "sha256": hashlib.sha256(encoded).hexdigest()}
            projected.append(fields)
        return projected

    observation = {
        "qualification": "diagnostic_only_not_a_pass",
        "stage": stage,
        "authority": {
            "runtime_root_id": root["root_run_id"], "agent_run_id": run["run_id"],
            "owner_principal": task["owner_principal"], "workspace_id": task["workspace_id"],
            "session_id": runtime_session_id, "trace_id": trace_id,
            "root_status": root["status"], "root_authority_status": root["authority_status"],
            "terminal_sequence": root["terminal_sequence"],
            "terminal_event_sha256": root["terminal_event_sha256"],
            "agent_run_status": run["status"],
            "agent_run_authority_status": run["authority_status"],
        },
        "event_count": len(actual_events),
        "events": event_projection(actual_events),
        "binding_events": {
            "active_count": len(active_bindings),
            "completed_count": len(completed_bindings),
            "invalid": event_projection(invalid_bindings),
        },
        "domain_event_multiset": {
            "status": "pending",
            "missing": event_projection(missing_domain_events),
            "extra": event_projection(extra_domain_events),
        },
        "settlement_check": "pending",
    }
    # Persist only the bounded, identity-scoped projection before event and
    # settlement assertions. It intentionally cannot qualify a run as PASS.
    state["checks"]["structured_audit_observed_" + stage] = observation

    bindings_valid = (len(active_bindings) == 1 and len(completed_bindings) <= 1
                      and not invalid_bindings)
    if not bindings_valid:
        observation["domain_event_multiset"]["status"] = "not_checked_binding_invalid"
        raise EvidenceError("structured_agent_audit_actions_or_resources_invalid")
    if missing_domain_events or extra_domain_events:
        observation["domain_event_multiset"]["status"] = (
            "incomplete" if missing_domain_events and not extra_domain_events else "invalid")
        if missing_domain_events and not extra_domain_events:
            raise EvidenceError("structured_agent_audit_events_incomplete")
        raise EvidenceError("structured_agent_audit_actions_or_resources_invalid")
    observation["domain_event_multiset"]["status"] = "exact"
    observed_settlement = document.get("settlement")
    if stage != "background":
        require(observed_settlement is None, "unexpected_structured_request_receipt")
    else:
        require(isinstance(observed_settlement, dict), "structured_settlement_not_confirmed")
        if settlement is not None:
            require(observed_settlement == settlement, "structured_settlement_root_link_invalid")
        require(observed_settlement.get("run_id") == runtime_root_id
                and observed_settlement.get("outcome") == "completed",
                "structured_settlement_root_link_invalid")
        _validate_settlement_identity(observed_settlement, state["execution_options_before"])
        _assert_background_ready_signal(observed_settlement,
            state["identities"]["signal_job_id"], state["identities"]["signal_snapshot_artifact_id"])
        state["_settlement_receipt"] = observed_settlement
    observation["settlement_check"] = "validated"
    return {
        "stage": stage, "runtime_root_id": runtime_root_id, "agent_run_id": run["run_id"],
        "owner_principal": "f6-chain-user", "workspace_id": task["workspace_id"],
        "session_id": runtime_session_id, "trace_id": trace_id,
        "terminal": "completed/closed", "audit_events": event_projection(actual_events),
        "settlement_status": observed_settlement.get("status") if isinstance(observed_settlement, dict) else None,
        "active_binding_count": len(active_bindings),
        "completed_binding_count": len(completed_bindings),
    }


def _assert_validated_signal_artifact(artifact: object, *, artifact_id: str, task_id: str,
                                      owner_principal: str, workspace_id: str,
                                      strategy_version_artifact_id: str,
                                      stock_pool_snapshot_id: str, signal_job_id: str) -> dict[str, object]:
    require(isinstance(artifact, dict) and artifact.get("artifact_id") == artifact_id
            and artifact.get("owner_principal") == owner_principal
            and artifact.get("workspace_id") == workspace_id
            and artifact.get("task_id") == task_id,
            "validated_signal_artifact_identity_invalid")
    require(artifact.get("kind") == "signal_snapshot" and artifact.get("status") == "validated",
            "validated_signal_artifact_state_invalid")
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
    if stage == "background":
        payload["signal_job_id"] = state["identities"]["signal_job_id"]
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
            stderr = result.stderr.strip() if isinstance(result.stderr, str) else ""
            known_audit_failures = {
                "exact F6 Product conversation scope changed": "structured_agent_audit_task_scope_invalid",
                "F6 Runtime root exists outside the exact owner/session/workspace/trace scope":
                    "structured_runtime_root_scope_invalid",
                "F6 Runtime root identity is ambiguous": "structured_runtime_root_identity_invalid",
                "F6 Runtime root identity changed during read": "structured_runtime_root_identity_invalid",
                "F6 AgentRun terminal or owner context is invalid": "structured_agent_run_identity_invalid",
                "F6 Runtime root has no exact completed terminal proof":
                    "structured_runtime_root_terminal_not_confirmed",
                "F6 Runtime root does not identify one AgentRun": "structured_agent_run_terminal_not_confirmed",
                "exact F6 task/conversation scope not found": "structured_agent_audit_task_not_visible",
                "exact F6 settled request receipt is ambiguous": "structured_settlement_root_link_invalid",
                "F6 settlement is not bound to the exact Runtime root": "structured_settlement_root_link_invalid",
                "F6 AgentRun audit event count exceeds the exact bounded contract":
                    "structured_agent_audit_actions_or_resources_invalid",
            }
            if stderr in known_audit_failures:
                raise EvidenceError(known_audit_failures[stderr])
            raise EvidenceError("structured_agent_audit_read_failed")
        try:
            document = json.loads(result.stdout)
        except (ValueError, TypeError):
            raise EvidenceError("structured_agent_audit_response_invalid") from None
        if (isinstance(document, dict)
                and document.get("schema_version") == "f6-agent-audit-readiness.v1"):
            if document.get("stage") != stage:
                raise EvidenceError("structured_agent_audit_scope_mismatch")
            if document.get("status") == "not_ready":
                category = document.get("category")
                if category in {"runtime_root_not_visible", "runtime_root_active", "settlement_not_visible"}:
                    observations["last_not_ready_category"] = category
                    time.sleep(min(1, max(0, deadline - time.monotonic())))
                    continue
                if category == "scope_mismatch":
                    raise EvidenceError("structured_agent_audit_scope_mismatch")
                raise EvidenceError("structured_agent_audit_readiness_unknown")
        summary = _assert_structured_agent_audit(
            document, stage=stage, task_id=task_id, conversation_id=conversation_id,
            trace_id=trace_id, runtime_root_id=runtime_root_id,
            expected_events=expected_events, settlement=settlement)
        observations["status"] = "terminal_proof_observed"
        return summary
    raise EvidenceError("structured_agent_audit_terminal_proof_deadline")


def _remaining_timeout(deadline: float, maximum: float) -> float:
    remaining = deadline - time.monotonic()
    require(remaining > 0, "reconciliation_deadline_exhausted")
    return min(maximum, remaining)


def _failure_observation_summary(observation: object) -> dict[str, object] | None:
    if not isinstance(observation, dict):
        return None
    return {key: observation.get(key) for key in (
        "classification", "reconcile_mode", "stop_category", "session_reads", "task_reads",
        "permission_reads", "job_reads", "session_status", "session_messages_observed",
        "answer_wait_observation", "side_effects_resolved",
        "resource_cleanup_is_terminal_proof",
    )}


def _is_untrusted_identity(category: object) -> bool:
    return isinstance(category, str) and category in UNTRUSTED_IDENTITY_FAILURES


def _failure_readonly_window(api_call, *, seconds: int) -> None:
    """Reconcile only by bounded reads; never turn missing proof into health."""
    identities = state.get("identities", {})
    task_id = identities.get("task_id")
    conversation_id = identities.get("conversation_id")
    trace_id = identities.get("trace_id")
    mode = _failure_reconciliation_mode()
    state["failure_reconciliation_mode"] = mode
    observations: dict[str, object] = {
        "classification": "unknown_unresolved_side_effects",
        "reconcile_mode": mode,
        "session_reads": 0, "task_reads": 0, "permission_reads": 0, "job_reads": 0,
        "session_status": None, "session_messages_observed": None,
        "request_state": None, "signal_job_status": None, "task_state_valid": False,
        "known_runtime_root_ids": {
            key: identities.get(key) for key in (
                "foreground_1_runtime_root_id", "foreground_2_runtime_root_id",
                "background_runtime_root_id") if identities.get(key) is not None
        },
        "side_effects_resolved": False,
        "resource_cleanup_is_terminal_proof": False,
    }
    wait_observation = state.get("answer_wait_observation")
    if isinstance(wait_observation, dict):
        observations["answer_wait_observation"] = {
            key: wait_observation.get(key) for key in (
                "foreground_step", "session_status", "session_message_count", "prompt_matched",
                "assistant_answer_present", "required_answer_present",
            )
        }
    if mode == "untrusted_identity":
        observations.update(classification="untrusted_identity", stop_category=state.get("failure_category"))
        state["failure_observation"] = observations
        return
    if (not isinstance(conversation_id, str) or not isinstance(trace_id, str)
            or re.fullmatch(r"conversation_[0-9a-f]{32}", conversation_id) is None
            or TRACE_PATTERN.fullmatch(trace_id) is None):
        observations["classification"] = "unknown_scope_incomplete"
        state["failure_observation"] = observations
        return

    deadline = time.monotonic() + max(0, min(seconds, 20))
    while time.monotonic() < deadline:
        # A previous read may be stale. Every closure decision uses one exact pass.
        observations["request_state"] = None
        observations["signal_job_status"] = None
        session_ok = False
        task_ok = not isinstance(task_id, str)
        options_ok = state.get("execution_options_before") is None
        job_ok = not isinstance(identities.get("signal_job_id"), str)
        try:
            session_view = _session_call(
                api_call, conversation_id, trace_id,
                timeout=_remaining_timeout(deadline, 12))
            observations["session_reads"] = int(observations["session_reads"]) + 1
            conversation = session_view.get("conversation")
            observations["session_status"] = conversation.get("status")
            messages = _messages(session_view)
            observations["session_messages_observed"] = len(messages)
            session_ok = True
        except EvidenceError as error:
            observations["session_read_category"] = error.category
            if _is_untrusted_identity(error.category):
                observations.update(classification="untrusted_identity", stop_category=error.category)
                break
            if error.category == "reconciliation_deadline_exhausted":
                break

        if isinstance(task_id, str):
            try:
                task = api_call("GET", f"/api/product/research/tasks/{task_id}",
                                timeout=_remaining_timeout(deadline, 15))
                observations["task_reads"] = int(observations["task_reads"]) + 1
                require(isinstance(task, dict) and task.get("task_id") == task_id
                        and task.get("owner_principal") == "f6-chain-user"
                        and task.get("conversation_id") == conversation_id
                        and task.get("trace_id") == trace_id
                        and (not isinstance(identities.get("workspace_id"), str)
                             or task.get("workspace_id") == identities.get("workspace_id")),
                        "reconciliation_task_identity_changed")
                observations["task_status"] = task.get("status")
                observations["task_state_valid"] = task.get("status") in {"planned", "running"}
                task_ok = True
            except EvidenceError as error:
                observations["task_read_category"] = error.category
                if _is_untrusted_identity(error.category):
                    observations.update(classification="untrusted_identity", stop_category=error.category)
                    break
                if error.category == "reconciliation_deadline_exhausted":
                    break

            if task_ok:
                try:
                    options_view = _permission_view(
                        api_call, conversation_id, timeout=_remaining_timeout(deadline, 15))
                    observations["permission_reads"] = int(observations["permission_reads"]) + 1
                    before = state.get("execution_options_before")
                    if isinstance(before, dict):
                        unchanged = (options_view.get("revision") == before.get("revision")
                                     and options_view.get("options") == before.get("options"))
                        disabled = (state.get("options_disable_attempted") is True
                                    and options_view.get("revision") == before.get("revision", -1) + 1
                                    and options_view.get("options") == {
                                        **before["options"], "auto_continue": False})
                        require(unchanged or disabled, "reconciliation_execution_options_identity_changed")
                        options_ok = disabled or not state.get("options_disable_attempted")
                    observations["execution_options_revision"] = options_view["revision"]
                    observations["auto_continue"] = options_view["options"].get("auto_continue")
                except EvidenceError as error:
                    observations["permission_read_category"] = error.category
                    if _is_untrusted_identity(error.category):
                        observations.update(classification="untrusted_identity", stop_category=error.category)
                        break
                    if error.category == "reconciliation_deadline_exhausted":
                        break

        signal_job_id = identities.get("signal_job_id")
        if task_ok and isinstance(signal_job_id, str):
            try:
                job_view = api_call("GET", f"/api/product/signal-producer/jobs/{signal_job_id}",
                                    timeout=_remaining_timeout(deadline, 15))
                observations["job_reads"] = int(observations["job_reads"]) + 1
                job = job_view.get("job") if isinstance(job_view, dict) else None
                require(isinstance(job, dict) and job.get("job_id") == signal_job_id
                        and job.get("task_id") == task_id
                        and job.get("owner_principal") == "f6-chain-user"
                        and job.get("strategy_version_artifact_id") == identities.get("strategy_version_artifact_id")
                        and job.get("stock_pool_snapshot_id") == identities.get("stock_pool_snapshot_id"),
                        "reconciliation_signal_job_identity_changed")
                observations["signal_job_status"] = job.get("status")
                expected_artifact_id = identities.get("signal_snapshot_artifact_id")
                job_ok = (job.get("status") in {"completed", "failed", "cancelled"}
                          and (job.get("status") != "completed"
                               or (isinstance(expected_artifact_id, str)
                                   and job.get("result_artifact_id") == expected_artifact_id)))
            except EvidenceError as error:
                observations["job_read_category"] = error.category
                if _is_untrusted_identity(error.category):
                    observations.update(classification="untrusted_identity", stop_category=error.category)
                    break
                if error.category == "reconciliation_deadline_exhausted":
                    break

        receipt = state.get("_settlement_receipt")
        request_ok = (isinstance(receipt, dict)
                      and receipt.get("reservation_id") == identities.get("background_reservation_id")
                      and receipt.get("event_key") == identities.get("background_event_key")
                      and receipt.get("run_id") == identities.get("background_runtime_root_id")
                      and receipt.get("status") == "settled"
                      and receipt.get("dispatch_attempts") == 1
                      and _audit_closes_root("background", receipt.get("run_id")))

        roots_closed = True
        for stage, key in (
            ("fg1", "foreground_1_runtime_root_id"),
            ("fg2", "foreground_2_runtime_root_id"),
            ("background", "background_runtime_root_id"),
        ):
            root_id = identities.get(key)
            if isinstance(root_id, str) and not _audit_closes_root(stage, root_id):
                roots_closed = False
        turn_attempts = state.get("mutation_attempts", [])
        if (("foreground_agent_turn_1" in turn_attempts and not isinstance(identities.get("foreground_1_runtime_root_id"), str))
                or ("foreground_agent_turn_2" in turn_attempts and not isinstance(identities.get("foreground_2_runtime_root_id"), str))):
            roots_closed = False

        if (mode == "bounded_readonly" and session_ok and task_ok
                and observations.get("task_state_valid", task_id is None) and options_ok
                and request_ok and job_ok and roots_closed):
            observations.update(classification="healthy_observer_confirmed", side_effects_resolved=True)
            break
        if time.monotonic() + 2 >= deadline:
            break
        time.sleep(min(2, max(0, deadline - time.monotonic())))

    if observations.get("classification") != "untrusted_identity":
        observations["classification"] = (
            "healthy_observer_confirmed" if observations.get("side_effects_resolved")
            else "bounded_reconcile_incomplete_unknown"
        )
    # A bounded resource stop or the enclosing ephemeral CI cleanup never
    # upgrades an unknown turn/job/request into terminal proof.
    observations["resource_cleanup_is_terminal_proof"] = False
    state["failure_observation"] = observations


def _permission_view(api_call, conversation_id: str, *, timeout: float = 15) -> dict[str, object]:
    view = api_call("GET", f"/api/product/agent/conversations/{conversation_id}/execution-options", timeout=timeout)
    require(isinstance(view, dict) and view.get("schema_version") == "agent-execution-options.v1"
            and view.get("conversation_id") == conversation_id
            and view.get("owner_principal") == "f6-chain-user"
            and view.get("workspace_id") == state["identities"].get("workspace_id")
            and type(view.get("revision")) is int and view["revision"] >= 0
            and isinstance(view.get("options"), dict),
            "execution_options_identity_changed")
    return view


def _assert_task_ready_read_profile(carrier: object, options_view: dict) -> dict[str, object]:
    require(isinstance(carrier, dict), "background_execution_profile_invalid")
    require(carrier.get("execution_profile") == _execution_profile_v2(
                options_view["options"], revision=options_view["revision"]),
            "background_execution_profile_binding_invalid")
    limits = _request_limits_v2(options_view["options"])
    require(carrier.get("request_limits") == limits,
            "background_execution_profile_limits_invalid")
    try:
        _validate_reservation_v3(carrier)
    except ValueError:
        raise EvidenceError("background_execution_profile_binding_invalid") from None
    return limits


def _audit_closes_root(stage: str, root_id: object) -> bool:
    summary = state.get("audit_summaries", {}).get(stage)
    return (isinstance(root_id, str) and isinstance(summary, dict)
            and summary.get("runtime_root_id") == root_id
            and summary.get("terminal") == "completed/closed")


def _failure_reconciliation_mode() -> str:
    if _is_untrusted_identity(state.get("failure_category")):
        return "untrusted_identity"
    if state.get("uncertain_actions"):
        return "unknown_mutation_unresolved"
    identities = state.get("identities", {})
    attempts = state.get("mutation_attempts", [])
    for stage, action, key in (
        ("fg1", "foreground_agent_turn_1", "foreground_1_runtime_root_id"),
        ("fg2", "foreground_agent_turn_2", "foreground_2_runtime_root_id"),
    ):
        if action in attempts:
            root_id = identities.get(key)
            if not _audit_closes_root(stage, root_id):
                return "accepted_root_terminal_unobserved"
    return "bounded_readonly"


def _stop_owned_signal_worker(compose_once, *, attempted: bool, project: str) -> None:
    if not attempted:
        return
    require(PROJECT_PATTERN.fullmatch(project) is not None
            and os.environ.get("COMPOSE_PROJECT_NAME") == project,
            "signal_worker_cleanup_project_mismatch")
    require(state.get("worker_cleanup_attempted") is not True,
            "signal_worker_cleanup_duplicate_attempt")
    state["worker_cleanup_attempted"] = True
    try:
        compose_once("signal_worker_stop_after_chain", "stop", "signal-worker")
    except EvidenceError as error:
        state["checks"]["worker_final_cleanup"] = {
            "status": error.category, "project": project, "service": "signal-worker",
            "worker_start_attempted": True,
            "purpose": "ci_resource_cleanup_only", "terminal_proof": False,
        }
        if "signal_worker_stop_after_chain" not in state["uncertain_actions"]:
            state["uncertain_actions"].append("signal_worker_stop_after_chain")
        state["failure_reconciliation_mode"] = "unknown_mutation_unresolved"
        observation = state.get("failure_observation")
        if isinstance(observation, dict) and observation.get("classification") == "healthy_observer_confirmed":
            observation.update(classification="bounded_reconcile_incomplete_unknown",
                               side_effects_resolved=False,
                               stop_category="signal_worker_cleanup_outcome_unknown")
        raise
    state["checks"]["worker_final_cleanup"] = {
        "status": "dedicated_signal_worker_stopped", "project": project,
        "service": "signal-worker", "worker_start_attempted": True,
        "purpose": "ci_resource_cleanup_only",
        "terminal_proof": False,
    }


def _revoke_exact_grant(api_call) -> None:
    """Close future automatic events with one exact CAS, preserving the settled event."""
    conversation_id = state["identities"].get("conversation_id")
    before = state.get("execution_options_before")
    if not isinstance(conversation_id, str) or not isinstance(before, dict):
        return
    try:
        view = _permission_view(api_call, conversation_id)
    except EvidenceError:
        state["checks"]["execution_options_stop"] = "could_not_read_exact_options_state"
        return
    if (view.get("revision") != before.get("revision") or view.get("options") != before.get("options")):
        state["checks"]["execution_options_stop"] = "options_changed_no_mutation"
        return
    expected_options = {**view["options"], "auto_continue": False}
    state["options_disable_attempted"] = True
    state["mutation_attempts"].append("execution_options_disable")
    try:
        updated = api_call("PUT", f"/api/product/agent/conversations/{conversation_id}/execution-options",
            {"schema_version": "agent-execution-options.v1", "expected_revision": view["revision"],
             "options": expected_options}, expected=200, timeout=20)
        require(isinstance(updated, dict) and updated.get("revision") == view["revision"] + 1
                and updated.get("options") == expected_options,
                "exact_execution_options_update_not_confirmed")
    except EvidenceError as error:
        state["checks"]["execution_options_put_category"] = error.category
        if "execution_options_disable" not in state["uncertain_actions"]:
            state["uncertain_actions"].append("execution_options_disable")
    try:
        after = _permission_view(api_call, conversation_id)
        require(after.get("revision") == view["revision"] + 1
                and after.get("options") == expected_options,
                "exact_execution_options_get_not_confirmed")
        state["checks"]["execution_options_stop"] = "one_exact_cas_and_get_confirmed"
        state["uncertain_actions"] = [action for action in state["uncertain_actions"]
                                       if action != "execution_options_disable"]
    except EvidenceError as error:
        state["checks"]["execution_options_stop"] = error.category


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
        reason = (_product_session_public_error_reason(error)
                  if method == "POST" and path == "/v1/agent/sessions" else None)
        raise HttpFailure(int(error.code), reason) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise EvidenceError("http_transport_or_read_outcome_unknown") from None
    try:
        return json.loads(body)
    except (ValueError, TypeError):
        raise EvidenceError("http_json_response_invalid") from None


state: dict[str, object] = {
    "status": "failed", "stage": "preflight", "failure_category": None,
    "identities": {key: None for key in (
        "conversation_id", "runtime_session_id", "trace_id", "workspace_id",
        "foreground_1_runtime_root_id", "foreground_1_agent_run_id",
        "foreground_2_runtime_root_id", "foreground_2_agent_run_id",
        "background_runtime_root_id", "background_agent_run_id", "background_reservation_id",
        "background_event_key",
        "task_id", "strategy_draft_artifact_id",
        "strategy_version_artifact_id", "approval_artifact_id", "stock_pool_snapshot_id",
        "backtest_task_id", "signal_job_id", "signal_snapshot_artifact_id")},
    "checks": {}, "audit_summaries": {}, "mutation_attempts": [], "uncertain_actions": [],
    "execution_options_before": None, "options_disable_attempted": False,
    "worker_cleanup_attempted": False,
    "primary_evidence_written": False, "failure_observation": None,
    "product_session_public_error_reason": None,
}
worker_start_attempted = False
worker_stopped_at_start = False
gateway_events = None

try:
    state["stage"] = "isolate_signal_worker"
    _compose_once("signal_worker_stop_before_job", "stop", "signal-worker")
    worker_stopped_at_start = True

    state["stage"] = "prepare_only_test_user"

    def create_test_user():
        state["mutation_attempts"].append("isolated_ci_user_fixture")
        try:
            completed = subprocess.run(
                ["docker", "compose", "exec", "-T", "-e", "BYQ_F6_FIXTURE=1",
                 "-e", "COMPOSE_PROJECT_NAME=" + project, "-e", "BYQ_F6_CI_PROJECT=" + project, "backend",
                 "python", "/tmp/f6-chain-fixture.py", "user"],
                input="", text=True, capture_output=True, check=True, timeout=30)
            return json.loads(completed.stdout)
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError, TypeError):
            state["uncertain_actions"].append("isolated_ci_user_fixture")
            raise EvidenceError("isolated_ci_user_fixture_outcome_unknown") from None

    fixture_workspace_id = _fixture_workspace(
        os.environ.get("BYQ_F6_PREPARED_WORKSPACE_ID"),
        os.environ.get("BYQ_ACP_PRODUCT_WORKSPACE_ID"), create_test_user)
    state["identities"]["workspace_id"] = fixture_workspace_id

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
    fg1_body, fg1_answer = _wait_answer(call, session_id, trace_id, fg1,
                                        ("ResearchTask ", "StrategyVersion "))
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
            and task.get("workspace_id") == fixture_workspace_id,
            "research_task_original_conversation_identity_invalid")
    require(task.get("status") in {"planned", "running"}, "research_task_status_invalid")
    state["identities"]["workspace_id"] = task["workspace_id"]
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

    state["stage"] = "default_execution_options_exact_conversation"
    options_before = _permission_view(call, session_id)
    require(options_before["revision"] == 0
            and options_before["options"].get("auto_continue") is True
            and set(options_before["options"]) == {
                "auto_continue", "max_provider_calls", "max_provider_attempts", "max_tool_calls",
                "max_concurrent_provider_calls", "max_input_bytes_per_call", "max_input_bytes_total",
                "max_output_tokens_per_call", "max_output_tokens_total",
                "max_tool_payload_bytes_per_call", "max_tool_payload_bytes_total",
                "max_continuations", "max_runtime_seconds", "max_no_progress_seconds",
                "max_child_runtime_seconds", "max_child_no_progress_seconds"}
            and all(value is None for key, value in options_before["options"].items()
                    if key != "auto_continue"), "default_execution_options_not_unbounded")
    state["execution_options_before"] = options_before
    state["checks"]["execution_options"] = "default_auto_continue_true_all_optional_limits_null"

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
    _, fg2_answer = _wait_answer(call, session_id, trace_id, fg2,
                                 ("BacktestTask ", "SignalJob "))
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

    state["stage"] = "gateway_restart_and_original_logical_session_connect"
    _proxy_diagnostic("before_restart")
    _compose_once("gateway_restart", "restart", "gateway")
    binding = _compose("port", "gateway", "8100", timeout=15)
    require(re.fullmatch(r"127\.0\.0\.1:[0-9]{1,5}", binding) is not None,
            "restarted_gateway_not_loopback_bound")
    origin = "http://" + binding
    state["stage"] = "gateway_ready_original_session_before_connect"
    _wait_gateway_original_session(call, session_id, trace_id, fg2, fg2_answer)
    state["stage"] = "gateway_original_event_connection_once"
    gateway_events = GatewayEventConnection(client, origin, session_id, trace_id)
    state["stage"] = "gateway_same_original_session_after_connect"
    session_after_restart = _session_call(call, session_id, trace_id)
    _assert_original_session_connected(session_after_restart, session_id, trace_id, fg2, fg2_answer)
    gateway_events.assert_healthy()
    same_job = call("GET", f"/api/product/signal-producer/jobs/{signal_job_id}")
    same_job_row = same_job.get("job") if isinstance(same_job, dict) else None
    require(isinstance(same_job_row, dict) and same_job_row.get("job_id") == signal_job_id
            and same_job_row.get("task_id") == task_id
            and same_job_row.get("owner_principal") == "f6-chain-user"
            and same_job_row.get("strategy_version_artifact_id") == version_id
            and same_job_row.get("stock_pool_snapshot_id") == snapshot_id,
            "same_job_identity_changed")
    require(same_job_row.get("status") == "waiting_for_data", "same_job_status_changed")
    state["checks"]["gateway_restart"] = "original_logical_session_public_events_same_durable_job_no_turn_replay"
    _proxy_diagnostic("after_restart")

    state["stage"] = "start_exact_signal_worker_once"
    active_jobs_view = call("GET", "/api/product/signal-producer/jobs?limit=100&offset=0")
    existing_rows = active_jobs_view.get("jobs") if isinstance(active_jobs_view, dict) else None
    require(isinstance(existing_rows, list), "signal_job_list_invalid")
    f6_jobs = [row for row in existing_rows if isinstance(row, dict)
               and row.get("owner_principal") == "f6-chain-user"
               and row.get("status") in {"waiting_for_data", "queued", "running"}]
    require(len(f6_jobs) == 1 and f6_jobs[0].get("job_id") == signal_job_id,
            "unexpected_active_job_in_dedicated_f6_owner_scope")
    gateway_events.assert_healthy()
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
        gateway_events.assert_healthy()
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
    assistant_answer = None
    background_root = None
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        gateway_events.assert_healthy()
        session_view = _session_call(call, session_id, trace_id,
            timeout=_remaining_timeout(deadline, 12))
        messages = _messages(session_view)
        events = session_view.get("events")
        require(isinstance(events, list), "background_root_events_missing")
        roots = {event["payload"]["run_id"] for event in events if isinstance(event, dict)
            and event.get("source") == "runtime-adapter" and event.get("kind") == "session.started"
            and event.get("session_id") == session_id
            and event.get("trace_id") == trace_id and isinstance(event.get("payload"), dict)
            and isinstance(event["payload"].get("run_id"), str)
            and event["payload"]["run_id"] not in {
                state["identities"]["foreground_1_runtime_root_id"],
                state["identities"]["foreground_2_runtime_root_id"]}}
        require(len(roots) <= 1, "background_root_correlation_ambiguous")
        background_root = next(iter(roots), None)
        assistant_answer = (_background_answer_for_root(session_view, background_root)
                            if background_root is not None else None)
        answer_ready = (isinstance(assistant_answer, str)
                        and all(value in assistant_answer for value in (
                            task_id, backtest_task_id, signal_job_id,
                            state["identities"]["signal_snapshot_artifact_id"],
                        ))
                        and "No domain writes were made." in assistant_answer)
        observed = _background_wait_observation(session_view, background_root,
            bg_user_count=sum(item.get("role") == "user" and
                "BYQ trusted read-only task-ready follow-up for exact task " + task_id
                in _body_text(item.get("content")) for item in messages),
            answer_present=bool(assistant_answer), answer_ready=answer_ready)
        previous = state.get("background_wait_observation") or {}
        state["background_wait_observation"] = {
            "poll_count": min(int(previous.get("poll_count", 0)) + 1, 10000),
            "last_poll": observed,
        }
        if answer_ready and time.monotonic() <= deadline:
            break
        if isinstance(session_view.get("conversation"), dict):
            require(session_view["conversation"].get("status") not in {"failed", "interrupted", "archived"},
                    "background_agent_session_failed")
        time.sleep(min(2, max(0, deadline - time.monotonic())))
    require(isinstance(background_root, str) and RUNTIME_ROOT_PATTERN.fullmatch(background_root),
            "single_background_root_not_observed")
    require(isinstance(assistant_answer, str)
            and all(value in assistant_answer for value in (task_id, backtest_task_id, signal_job_id,
                                                             state["identities"]["signal_snapshot_artifact_id"]))
            and "No domain writes were made." in assistant_answer,
            "background_answer_not_persisted_for_exact_ready_evidence")

    background_audit = _read_structured_agent_audit(
        "background", task_id=task_id, conversation_id=session_id, trace_id=trace_id,
        runtime_root_id=background_root, backtest_task_id=backtest_task_id,
        expected_events=[
            ("byq_research_get", "authorized", "research_task", task_id),
            ("byq_research_get", "success", "research_task", task_id),
            ("byq_backtest_task_get", "authorized", "backtest_task", backtest_task_id),
            ("byq_backtest_task_get", "success", "backtest_task", backtest_task_id),
        ])
    request_settlement = state.get("_settlement_receipt")
    require(isinstance(request_settlement, dict), "single_background_request_not_durably_settled")
    limits = _assert_task_ready_read_profile(request_settlement["reservation"], options_before)
    usage = _validate_request_usage_v2(request_settlement["request_usage"])
    require(usage.get("schema_version") == "continuation-request-usage.v2"
            and usage.get("execution_profile") == request_settlement["reservation"]["execution_profile"]
            and usage.get("request_limits") == limits
            and usage.get("limit_violations") == [], "settled_request_usage_profile_invalid")
    admission = usage.get("admission_usage")
    actual = usage.get("actual_usage")
    require(isinstance(admission, dict) and isinstance(actual, dict)
            and admission.get("provider_calls") == admission.get("provider_attempts")
            and admission.get("provider_attempts") is not None
            and admission["provider_attempts"] >= 1
            and admission.get("tool_calls") == 7
            and admission.get("max_concurrent") is not None
            and admission["max_concurrent"] >= 1,
            "request_gate_admission_measurements_invalid")
    require(actual == {
        "input_tokens": None, "cache_read_tokens": None, "output_tokens": None,
        "provider_attempts": None, "usage_source": "unknown", "completeness": "unknown",
    }, "synthetic_provider_usage_was_not_preserved_as_unknown")
    event_key = request_settlement.get("event_key")
    require(isinstance(event_key, str)
            and re.fullmatch(r"ready-v1:[0-9a-f]{64}", event_key) is not None,
            "request_ready_event_identity_invalid")
    state["identities"]["background_reservation_id"] = request_settlement["reservation_id"]
    state["identities"]["background_event_key"] = event_key
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
        "request_state": "one_exact_job_reservation_one_dispatch_exact_ready_event",
        "request_gate": "measured_admission_and_unknown_actual_model_usage_without_default_limits",
        "background_domain_scope": "only_byq_research_get_exact_task_and_byq_backtest_task_get_exact_task",
        "background_ready_event": "exact_signal_job_and_validated_artifact_hash_bound_to_v3_settlement",
        "task_completion": "not_required_and_not_fabricated",
    })

    state["stage"] = "exact_execution_options_stop_and_get_confirmation"
    _revoke_exact_grant(call)
    require(state["checks"].get("execution_options_stop") == "one_exact_cas_and_get_confirmed",
            "exact_execution_options_stop_not_confirmed")

    gateway_events.assert_healthy()
    state["stage"] = "passed"
    state["status"] = "passed"
    print(json.dumps({"stage": "f6_read_only_settlement_passed",
                      "task_id": task_id, "backtest_task_id": backtest_task_id,
                      "signal_job_id": signal_job_id,
                      "signal_snapshot_artifact_id": state["identities"]["signal_snapshot_artifact_id"]}), flush=True)
    _write_evidence()
except EvidenceError as error:
    state["failure_category"] = error.category
    state["failure_reconciliation_mode"] = _failure_reconciliation_mode()
    try:
        _write_evidence()
    except (FileExistsError, OSError):
        print(json.dumps({"stage": "first_failure_evidence_write_failed", "status": "failed",
                          "failure_category": error.category}), flush=True)
    try:
        uncertain_foreground = any(item.startswith("foreground_agent_turn")
                                   for item in state["uncertain_actions"])
        _failure_readonly_window(call, seconds=20 if "background" in str(state["stage"])
                                 or uncertain_foreground else 4)
    except EvidenceError as observation_error:
        state["failure_observation"] = {"category": observation_error.category}
except Exception as error:  # evidence stores only exception class, never message or payload
    state["failure_category"] = type(error).__name__
    state["failure_reconciliation_mode"] = _failure_reconciliation_mode()
    try:
        _write_evidence()
    except (FileExistsError, OSError):
        print(json.dumps({"stage": "first_failure_evidence_write_failed", "status": "failed",
                          "failure_category": state["failure_category"]}), flush=True)
    try:
        _failure_readonly_window(call, seconds=20 if "background" in str(state["stage"]) else 4)
    except EvidenceError as observation_error:
        state["failure_observation"] = {"category": observation_error.category}
finally:
    try:
        try:
            _stop_owned_signal_worker(_compose_once, attempted=worker_start_attempted, project=project)
        except EvidenceError as error:
            if state["status"] == "passed":
                state["status"] = "failed"
                state["failure_category"] = "worker_cleanup_failed"
        if not state["options_disable_attempted"]:
            _revoke_exact_grant(call)
            if state["status"] == "passed" and state["checks"].get("execution_options_stop") != "one_exact_cas_and_get_confirmed":
                state["status"] = "failed"
                state["failure_category"] = "exact_execution_options_stop_not_proven"
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
    finally:
        if gateway_events is not None:
            gateway_events.close()

if state["status"] != "passed":
    raise SystemExit("F6 current read-only settlement failed: " + str(state.get("failure_category") or "unknown"))
