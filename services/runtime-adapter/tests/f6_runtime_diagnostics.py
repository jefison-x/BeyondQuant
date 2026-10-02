"""Closed test-only terminal diagnostics for the keyless F6 fixture.

Observes the existing RuntimeAdapter/SDK; creates no session, prompt or receipt.
"""
from contextvars import ContextVar
import hashlib
import json
import os
import re
import stat
import threading

PATH = "/tmp/byq-f6-runtime-diagnostics.jsonl"
SCHEMA = "byq.f6.synthetic-runtime-diagnostic.v1"
MAX_ROWS = 8
ENUMS = {
    "native_finish": {"completed", "cancelled", "max_tokens", "failed", "exception", "not_returned", "unknown"},
    "runtime_status": {"ready", "running", "idle", "failed", "interrupted", "closed", "unknown"},
    "terminal_kind": {"session.result", "session.failed", "session.cancelled", "session.result.discarded", "none", "unknown"},
    "terminal_code": {"model-run-failed", "runtime-run-timeout", "runtime-no-progress-timeout", "runtime-subagent-timeout", "domain-correction-stopped", "domain-call-reference-unproven", "domain-call-retention-bound", "none", "unknown"},
    "receipt_cache_status": {"not_cached", "settled", "accepted", "outcome_unknown", "unknown"},
    "terminal_exception_kind": {"JsonRpcError", "TransportError", "ProtocolError", "RuntimeError", "ValueError", "OSError", "TimeoutError", "KeyError", "TypeError", "none", "unknown"},
    "request_outcome": {"completed", "needs_attention", "unknown"},
    "guard_blocked": {"BYQ_CONTINUATION_TOOL_UNQUALIFIED", "BYQ_CONTINUATION_TOOL_LIMIT", "BYQ_CONTINUATION_TOOL_STORAGE_FAILED", "BYQ_CONTINUATION_CANCELLED", "BYQ_CONTINUATION_DEADLINE_EXCEEDED", "none", "unknown"},
    "gate_reason": {"within_request_budget", "deadline_exceeded", "provider_outcome_unknown", "provider_redirect_blocked", "output_tokens_exceeded", "concurrency_limit", "provider_call_limit", "attempt_limit", "input_bytes_limit", "total_input_bytes_limit", "output_tokens_limit", "total_output_tokens_limit", "tool_payload_limit", "total_tool_payload_limit", "model_route_unqualified", "budget_invalid", "cancelled", "none", "unknown"},
    "usage_completeness": {"known", "partial", "unknown"},
}
BOOLS = {"active_run", "process_closed", "process_closing", "proxy_closed", "guard_observed", "usage_observed"}
COUNTS = {"provider_attempts": 16, "tool_calls": 16, "limit_violation_count": 32}
HASHES = {"session_sha256", "reservation_sha256", "root_sha256"}


def _enum(field, value):
    return value if type(value) is str and value in ENUMS[field] else "unknown"


def _hash(value, pattern):
    return hashlib.sha256(value.encode()).hexdigest() if type(value) is str and re.fullmatch(pattern, value) else None


def terminal_projection(adapter, record, run_id, native_finish, *, phase="background_terminal"):
    """Hash exact local identities; copy only closed state categories."""
    from app.continuation_budget import read_request_guard
    reservation = record.continuation_budget
    if not isinstance(reservation, dict) or record.budget_run_id != run_id:
        return None
    root_hash = _hash(run_id, r"[0-9a-f]{32}")
    session_hash = _hash(record.session_id, r"byq-session-[0-9a-f]{32}")
    reservation_hash = _hash(reservation.get("reservation_id"), r"continuation_[0-9a-f]{32}")
    if None in (root_hash, session_hash, reservation_hash):
        return None
    receipt = record.budget_receipts.get(reservation["reservation_id"], {})
    terminal = next((event for event in reversed(record.history)
        if event.get("kind") in ENUMS["terminal_kind"]
        and isinstance(event.get("payload"), dict)
        and event["payload"].get("run_id") == run_id), {})
    payload = terminal.get("payload", {})
    # Usage/elapsed here is a diagnostic sample, not a new durable settlement.
    guard, usage, gate_rows = {}, {}, []
    try:
        guard = read_request_guard(record.budget_journal, reservation, terminal=True)
    except (OSError, ValueError, TypeError, KeyError):
        pass
    gate = record.continuation_request_gate
    if gate is not None:
        gate_rows = gate.receipts()
        try:
            usage = gate.request_usage(tool_calls=guard["tool_calls"])
        except (OSError, ValueError, TypeError, KeyError):
            pass
    admission = usage.get("admission_usage", {})
    actual = usage.get("actual_usage", {})
    violations = usage.get("limit_violations")
    blocked = next((row for row in reversed(gate_rows)
        if row.get("phase") == "rejected" or row.get("forwarded") is False), None)
    reason = blocked.get("reason") if blocked is not None else (
        gate_rows[-1].get("reason") if gate_rows else "none")
    row = {
        "schema_version": SCHEMA, "record_type": phase,
        "session_sha256": session_hash, "reservation_sha256": reservation_hash, "root_sha256": root_hash,
        "native_finish": _enum("native_finish", native_finish),
        "runtime_status": _enum("runtime_status", record.status),
        "terminal_kind": _enum("terminal_kind", terminal.get("kind", "none")),
        "terminal_code": _enum("terminal_code", payload.get("code", "none")),
        "receipt_cache_status": _enum("receipt_cache_status", receipt.get("status") if receipt else "not_cached"),
        "terminal_exception_kind": _enum("terminal_exception_kind", payload.get("error", "none")),
        "request_outcome": _enum("request_outcome", receipt.get("outcome")),
        "guard_blocked": _enum("guard_blocked", guard.get("blocked_reason") or ("none" if guard else "unknown")),
        "gate_reason": _enum("gate_reason", reason),
        "usage_completeness": _enum("usage_completeness", actual.get("completeness")),
        "active_run": record.active_run is not None,
        "process_closed": record.process_closed is True,
        "process_closing": record.process_closing is True,
        "proxy_closed": record.continuation_proxy_closed is True,
        "guard_observed": bool(guard), "usage_observed": bool(usage),
        "provider_attempts": admission.get("provider_attempts"),
        "tool_calls": guard.get("tool_calls"),
        "limit_violation_count": len(violations) if isinstance(violations, list) else None,
    }
    for field, maximum in COUNTS.items():
        value = row[field]
        if type(value) is not int or not 0 <= value <= maximum:
            row[field] = "unknown"
    return row


class RuntimeDiagnostics:
    def __init__(self, path=PATH):
        self.fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        metadata = os.fstat(self.fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or stat.S_IMODE(metadata.st_mode) != 0o600:
            os.close(self.fd)
            raise ValueError("unqualified runtime diagnostic file")
        self.lock, self.count = threading.Lock(), 0

    def record(self, row):
        with self.lock:
            if self.count >= MAX_ROWS:
                return
            encoded = (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode()
            if len(encoded) > 4096:
                return
            offset = 0
            while offset < len(encoded):
                written = os.write(self.fd, encoded[offset:])
                if written <= 0:
                    raise OSError("runtime diagnostics incomplete")
                offset += written
            os.fsync(self.fd)
            self.count += 1

    def close(self):
        os.close(self.fd)


def install(diagnostics):
    """Test-only wrapper; original SDK call, Runtime result and errors are retained."""
    from app import runtime as runtime_module
    adapter_type = runtime_module.RuntimeAdapter
    compatibility_type = type(runtime_module.compatibility_for_release(
        os.environ.get("BYQ_DSH_COMPATIBILITY_RELEASE", "dsh-0.1.2rc1")))
    original_run = adapter_type._run_prompt
    original_sdk_run = compatibility_type.run_prepared_prompt
    observation = ContextVar("f6_runtime_terminal", default=None)

    def observe(state, phase):
        try:
            with state["record"].lock:
                row = terminal_projection(state["adapter"], state["record"], state["run_id"],
                    state["finish"], phase=phase)
            if row is not None:
                diagnostics.record(row)
        except Exception:
            print("F6 runtime terminal diagnostic unavailable", flush=True)

    def sdk_run(prepared, content, callback):
        state = observation.get()
        try:
            result = original_sdk_run(prepared, content, callback)
        except BaseException:
            if state is not None:
                state["finish"] = "exception"
                observe(state, "native_finished")
            raise
        if state is not None:
            state["finish"] = _enum("native_finish", result)
            observe(state, "native_finished")
        return result

    def run(self, record, active_run, *args, **kwargs):
        state = {"finish": "not_returned", "adapter": self, "record": record, "run_id": active_run.run_id}
        token = observation.set(state)
        observe(state, "background_started")
        try:
            return original_run(self, record, active_run, *args, **kwargs)
        finally:
            try:
                observe(state, "background_terminal")
            finally:
                observation.reset(token)

    compatibility_type.run_prepared_prompt = staticmethod(sdk_run)
    adapter_type._run_prompt = run
