"""Zero-model terminal provider-settlement guard for ``_run_prompt`` and the
F6 execution receipt.

The request-scoped provider gate admits every model request that reaches the
per-root proxy, including a delegated background child whose provider call may
still be in flight when the root's SDK turn returns. Closing the proxy only
seals the gate; it does not join the handler thread. These deterministic tests
drive the real ``RuntimeAdapter._run_prompt`` terminal decision with a real
``ResearchRequestGate``, a real on-disk journal and a faithful close double (or
a real ``RequestGateProxy``). No provider, DSH process, database or paid call is
used.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from app.research_request_gate import (
    KNOWN_BLOCKED,
    SETTLED_OK,
    UNKNOWN_OR_UNPAIRED,
    RequestGateBlocked,
    RequestGateProxy,
    ResearchRequestGate,
)
from app.runtime import RuntimeAdapter, SessionStatus
from packages.contracts.product_turn_request import product_turn_limits, product_turn_profile

_USAGE_BODY = b'{"choices":[{"index":0,"message":{"role":"assistant","content":"ok"}}],' \
              b'"usage":{"prompt_tokens":3,"completion_tokens":2}}'
_NO_USAGE_BODY = b'{"choices":[{"index":0,"message":{"role":"assistant","content":"ok"}}]}'


def _provider_body() -> bytes:
    return json.dumps({
        "model": "deepseek-v4.1-flash", "max_tokens": 8,
        "messages": [{"role": "user", "content": "synthetic settlement"}],
    }, separators=(",", ":")).encode()


def _usage_body(*, output_tokens: int) -> bytes:
    return json.dumps({
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": output_tokens},
    }, separators=(",", ":")).encode()


def _gate(journal: Path) -> ResearchRequestGate:
    return ResearchRequestGate(
        product_turn_limits(), execution_profile=product_turn_profile(),
        request_id="product-turn-settlement-test", journal=journal)


def _journal(tmp_path: Path) -> Path:
    return tmp_path / "product-turn-provider-request.jsonl"


def _release_compatibility(tmp_path: Path):
    from .test_process_cleanup import release_compatibility

    return release_compatibility(tmp_path)


@pytest.fixture
def adapter(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> RuntimeAdapter:
    from .test_process_cleanup import FakeHarness

    FakeHarness.reset()
    monkeypatch.delenv("BYQ_CREDENTIAL_RESOLVER_TOKEN", raising=False)
    monkeypatch.setenv("BYQ_DSH_PROCESS_OWNERSHIP", "session")
    monkeypatch.setenv("BYQ_DSH_RUNTIME_ROOT", str(tmp_path / "runtime"))
    composition = tmp_path / "composition.yml"
    composition.write_text("[]\n", encoding="utf-8")
    monkeypatch.setenv("BYQ_DSH_COMPOSITION", str(composition))
    monkeypatch.setenv("DSH_SESSION_ROOT", str(tmp_path / "sessions"))
    monkeypatch.setenv("BYQ_DSH_RUN_TIMEOUT_SECONDS", "3600")
    monkeypatch.setenv("BYQ_DSH_SUBAGENT_TIMEOUT_SECONDS", "3600")
    monkeypatch.setenv("BYQ_DSH_NO_PROGRESS_TIMEOUT_SECONDS", "3600")
    return RuntimeAdapter(_release_compatibility(tmp_path))


def _wait_for_active_run(adapter: RuntimeAdapter, session_id: str, timeout: float = 2.0) -> None:
    record = adapter._get(session_id)
    with record.lock:
        run = record.active_run
        if run is None:
            assert any(event["kind"] in {"session.result", "session.failed"}
                       for event in record.history), "prompt has no terminal event"
            return
    assert run.watchdog_stop.wait(timeout), "prompt worker did not finish"
    # The worker signals watchdog_stop before it records its terminal event,
    # while holding record.lock. Reacquiring that lock waits for the complete
    # terminal transition and prevents observing its intermediate active_run=None.
    with record.lock:
        assert record.active_run is None, "prompt worker signalled before terminal cleanup"
        assert any(event["kind"] in {"session.result", "session.failed"}
                   and event["payload"].get("run_id") == run.run_id
                   for event in record.history), "prompt worker did not emit a terminal event"


class _CloseDouble:
    """Faithful thin proxy close: seals the gate exactly like ``proxy.close``.

    ``fail`` makes the close raise after sealing so the runtime's
    ``continuation_proxy_closed`` uncertainty is exercised in isolation.
    ``seal=False`` leaves the gate unsealed while still reporting a closed
    proxy, reproducing an unproven admission seal.
    """

    def __init__(self, gate: ResearchRequestGate, *, fail: bool = False, seal: bool = True) -> None:
        self._gate = gate
        self._fail = fail
        self._seal = seal

    def close(self) -> None:
        if self._seal:
            self._gate.release_waiters()
        if self._fail:
            raise OSError("synthetic continuation proxy close failure")


def _drive(adapter: RuntimeAdapter, session_id: str, prepare):
    """Run one real prompt, injecting the gate and its proxy close before return.

    ``prepare`` receives the gate and returns the object assigned as
    ``continuation_request_proxy`` (a close double or a real proxy).
    """

    from .test_process_cleanup import FakeHarness

    adapter.create_session(session_id, f"trace-{session_id}")
    root = adapter.submit_prompt(session_id, "synthetic settlement")
    assert FakeHarness.run_started.wait(timeout=1.0)
    record = adapter._get(session_id)
    gate = _gate(Path(adapter._session_root) / f"{session_id}-provider.jsonl")
    proxy = prepare(gate)
    record.current_generation.continuation_request_gate = gate
    record.current_generation.continuation_request_proxy = proxy
    FakeHarness.allow_run.set()
    _wait_for_active_run(adapter, session_id)
    return record, gate, proxy, root


def _terminal_kinds(record: object) -> list[str]:
    return [event["kind"] for event in record.history
            if event["kind"] in {"session.result", "session.failed"}]


def _read_journal(journal: Path) -> list[dict]:
    if not journal.is_file():
        return []
    return [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines() if line.strip()]


# --------------------------------------------------------------------------- #
# Gate classification (atomic, one lock)
# --------------------------------------------------------------------------- #

def test_gate_unsealed_scope_is_unknown_or_unpaired(tmp_path: Path) -> None:
    gate = _gate(_journal(tmp_path))
    assert gate.settlement_state() == UNKNOWN_OR_UNPAIRED


def test_gate_sealed_empty_scope_is_settled_ok(tmp_path: Path) -> None:
    gate = _gate(_journal(tmp_path))
    gate.release_waiters()
    assert gate.settlement_state() == SETTLED_OK


def test_gate_settled_pair_requires_matching_jsonl_rows(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    gate = _gate(journal)
    receipt = gate.before_request(_provider_body())
    gate.complete(receipt, status=200, body=_USAGE_BODY)
    gate.release_waiters()
    rows = _read_journal(journal)
    admitted = sorted((r["call"], r["attempt"]) for r in rows if r["phase"] == "admitted")
    completed = sorted((r["call"], r["attempt"]) for r in rows if r["phase"] == "completed")
    assert admitted == completed and len(admitted) == 1
    assert gate.settlement_state() == SETTLED_OK


def test_gate_missing_provider_billing_usage_is_settled_ok(tmp_path: Path) -> None:
    gate = _gate(_journal(tmp_path))
    receipt = gate.before_request(_provider_body())
    assert gate.complete(receipt, status=200, body=_NO_USAGE_BODY)["forward"] is True
    gate.release_waiters()
    assert gate.settlement_state() == SETTLED_OK


def test_gate_admitted_without_completion_is_unknown_or_unpaired(tmp_path: Path) -> None:
    gate = _gate(_journal(tmp_path))
    gate.before_request(_provider_body())
    gate.release_waiters()
    assert gate.settlement_state() == UNKNOWN_OR_UNPAIRED


def test_gate_waiting_request_is_unknown_or_unpaired(tmp_path: Path) -> None:
    gate = _gate(_journal(tmp_path))
    with gate._cond:
        gate._waiting = 1
    gate.release_waiters()
    assert gate.settlement_state() == UNKNOWN_OR_UNPAIRED


def test_gate_duplicate_or_substituted_completion_is_unknown_or_unpaired(tmp_path: Path) -> None:
    # Duplicate completion with a matching total count must not be masked.
    gate = _gate(_journal(tmp_path))
    receipt = gate.before_request(_provider_body())
    gate.complete(receipt, status=200, body=_USAGE_BODY)
    gate.release_waiters()
    assert gate.settlement_state() == SETTLED_OK
    with gate._lock:
        gate._receipts.append({**gate._receipts[-1]})
    assert gate.settlement_state() == UNKNOWN_OR_UNPAIRED

    # A completion carrying a different (call, attempt) key is unpaired.
    gate2 = _gate(_journal(tmp_path))
    receipt2 = gate2.before_request(_provider_body())
    gate2.complete(receipt2, status=200, body=_USAGE_BODY)
    gate2.release_waiters()
    with gate2._lock:
        gate2._receipts[-1]["call"] = receipt2["call"] + 1
    assert gate2.settlement_state() == UNKNOWN_OR_UNPAIRED


@pytest.mark.parametrize(
    ("phase", "field", "value"),
    [
        ("admitted", "request_id", "different-scope"),
        ("completed", "request_id", "different-scope"),
        ("admitted", "call", True),
        ("admitted", "attempt", 0),
        ("completed", "attempt", True),
        ("completed", "phase", "unexpected"),
        ("completed", "forwarded", 1),
        ("completed", "forwarded", None),
    ],
)
def test_gate_malformed_phase_key_or_forwarded_receipt_is_unknown(
    tmp_path: Path, phase: str, field: str, value: object,
) -> None:
    gate = _gate(_journal(tmp_path))
    receipt = gate.before_request(_provider_body())
    gate.complete(receipt, status=200, body=_USAGE_BODY)
    gate.release_waiters()
    with gate._lock:
        row = next(item for item in gate._receipts if item["phase"] == phase)
        row[field] = value
    assert gate.settlement_state() == UNKNOWN_OR_UNPAIRED


def test_gate_missing_forwarded_receipt_is_unknown_but_literal_false_is_known_blocked(
    tmp_path: Path,
) -> None:
    gate = _gate(_journal(tmp_path))
    receipt = gate.before_request(_provider_body())
    gate.complete(receipt, status=200, body=_USAGE_BODY)
    gate.release_waiters()
    with gate._lock:
        completed = next(row for row in gate._receipts if row["phase"] == "completed")
        completed.pop("forwarded")
    assert gate.settlement_state() == UNKNOWN_OR_UNPAIRED

    gate2 = _gate(tmp_path / "false-forwarded.jsonl")
    receipt2 = gate2.before_request(_provider_body())
    gate2.complete(receipt2, status=200, body=_USAGE_BODY)
    gate2.release_waiters()
    with gate2._lock:
        completed2 = next(row for row in gate2._receipts if row["phase"] == "completed")
        completed2["forwarded"] = False
    assert gate2.settlement_state() == KNOWN_BLOCKED


def test_gate_missing_both_receipts_or_mismatched_actual_counters_is_unknown(
    tmp_path: Path,
) -> None:
    gate = _gate(_journal(tmp_path))
    receipt = gate.before_request(_provider_body())
    gate.complete(receipt, status=200, body=_USAGE_BODY)
    gate.release_waiters()
    with gate._lock:
        gate._receipts.clear()
    assert gate.settlement_state() == UNKNOWN_OR_UNPAIRED

    gate2 = _gate(tmp_path / "counter-mismatch.jsonl")
    receipt2 = gate2.before_request(_provider_body())
    gate2.complete(receipt2, status=200, body=_USAGE_BODY)
    gate2.release_waiters()
    with gate2._lock:
        gate2._attempts = 2
    assert gate2.settlement_state() == UNKNOWN_OR_UNPAIRED

    with gate2._lock:
        gate2._provider_calls = True
    assert gate2.settlement_state() == UNKNOWN_OR_UNPAIRED


def test_gate_matching_receipts_with_substituted_call_attempt_is_unknown(tmp_path: Path) -> None:
    gate = _gate(_journal(tmp_path))
    receipt = gate.before_request(_provider_body())
    gate.complete(receipt, status=200, body=_USAGE_BODY)
    gate.release_waiters()
    with gate._lock:
        for row in gate._receipts:
            if row["phase"] in {"admitted", "completed"}:
                row["call"] = 99
                row["attempt"] = 99
    assert gate.settlement_state() == UNKNOWN_OR_UNPAIRED


def test_gate_settlement_state_is_atomic_over_late_nonforwarded_completion(tmp_path: Path) -> None:
    """A late known non-forwarded completion must be caught by ONE snapshot.

    The split checks used to read ``has_blocked_request`` earlier and the
    outstanding/admitted predicate later; a receipt arriving between the two
    escaped. The atomic classifier must observe it in the same lock.
    """

    gate = _gate(_journal(tmp_path))
    receipt = gate.before_request(_provider_body())
    # The earlier split check reads no block while the request is in flight.
    assert gate.has_blocked_request() is False
    # A late known non-forwarded completion arrives before the snapshot.
    gate.complete(receipt, status=200, body=_usage_body(output_tokens=9))  # > declared 8
    gate.release_waiters()
    # A later split check would now see the non-forwarded row; the ONE atomic
    # snapshot must observe it without a window between separate checks.
    assert gate.has_blocked_request() is True
    assert gate.settlement_state() == KNOWN_BLOCKED


def test_gate_known_nonforwarded_completion_is_known_blocked(tmp_path: Path) -> None:
    gate = _gate(_journal(tmp_path))
    receipt = gate.before_request(_provider_body())
    gate.complete(receipt, status=200, body=_usage_body(output_tokens=9))
    gate.release_waiters()
    assert gate.settlement_state() == KNOWN_BLOCKED


def test_gate_rejected_request_is_known_blocked(tmp_path: Path) -> None:
    gate = _gate(_journal(tmp_path))
    big = json.dumps({"model": "deepseek-v4.1-flash", "max_tokens": 8,
                      "messages": [{"role": "user", "content": "x" * 262145}]}).encode()
    with pytest.raises(RequestGateBlocked):
        gate.before_request(big)
    gate.release_waiters()
    assert gate.settlement_state() == KNOWN_BLOCKED


def test_gate_provider_outcome_unknown_is_unknown_or_unpaired(tmp_path: Path) -> None:
    gate = _gate(_journal(tmp_path))
    receipt = gate.before_request(_provider_body())
    gate.complete(receipt, status=0, body=b"", outcome_unknown=True)
    gate.release_waiters()
    assert gate.settlement_state() == UNKNOWN_OR_UNPAIRED


def test_gate_predispatch_journal_failure_is_known_blocked(tmp_path: Path) -> None:
    gate = _gate(_journal(tmp_path))

    def fail_write(_receipt):
        raise RequestGateBlocked("storage_failed")

    gate._write_journal = fail_write
    with pytest.raises(RequestGateBlocked, match="storage_failed"):
        gate.before_request(_provider_body())
    gate.release_waiters()
    assert gate._provider_calls == 0
    assert gate.settlement_state() == KNOWN_BLOCKED


def test_gate_postdispatch_journal_failure_is_unknown_or_unpaired(tmp_path: Path) -> None:
    gate = _gate(_journal(tmp_path))
    real = gate._write_journal
    calls = {"n": 0}

    def flaky(receipt):
        calls["n"] += 1
        if calls["n"] >= 2:  # admitted write ok; completion write fails
            raise RequestGateBlocked("storage_failed")
        return real(receipt)

    gate._write_journal = flaky
    receipt = gate.before_request(_provider_body())
    with pytest.raises(RequestGateBlocked, match="storage_failed"):
        gate.complete(receipt, status=200, body=_USAGE_BODY)
    gate.release_waiters()
    assert gate.settlement_state() == UNKNOWN_OR_UNPAIRED


# --------------------------------------------------------------------------- #
# Runtime terminal decision
# --------------------------------------------------------------------------- #

def test_inflight_admitted_request_fails_root_closed(adapter: RuntimeAdapter) -> None:
    """A provider request in flight when the SDK returns must fail the root."""

    def prepare(gate: ResearchRequestGate):
        assert gate.before_request(_provider_body())["admitted"] is True
        return _CloseDouble(gate)

    record, gate, _proxy, _root = _drive(adapter, "inflight", prepare)
    assert gate.settlement_state() == UNKNOWN_OR_UNPAIRED
    assert record.status == SessionStatus.FAILED
    assert _terminal_kinds(record) == ["session.failed"]


def test_late_completion_cannot_flip_failed_to_success(adapter: RuntimeAdapter) -> None:
    box: dict = {}

    def prepare(gate: ResearchRequestGate):
        box["receipt"] = gate.before_request(_provider_body())
        return _CloseDouble(gate)

    record, gate, _proxy, _root = _drive(adapter, "late-flip", prepare)
    assert record.status == SessionStatus.FAILED
    gate.complete(box["receipt"], status=200, body=_USAGE_BODY)
    assert gate.settlement_state() == SETTLED_OK
    assert record.status == SessionStatus.FAILED
    assert _terminal_kinds(record) == ["session.failed"]


def test_unsealed_close_reports_failure_not_success(adapter: RuntimeAdapter) -> None:
    def prepare(gate: ResearchRequestGate):
        receipt = gate.before_request(_provider_body())
        gate.complete(receipt, status=200, body=_USAGE_BODY)
        return _CloseDouble(gate, seal=False)  # proxy reports closed, seal unproven

    record, gate, _proxy, _root = _drive(adapter, "unsealed", prepare)
    assert gate.settlement_state() == UNKNOWN_OR_UNPAIRED
    assert record.status == SessionStatus.FAILED
    assert _terminal_kinds(record) == ["session.failed"]


def test_proxy_close_failure_reports_failure_not_success(adapter: RuntimeAdapter) -> None:
    def prepare(gate: ResearchRequestGate):
        receipt = gate.before_request(_provider_body())
        gate.complete(receipt, status=200, body=_USAGE_BODY)
        return _CloseDouble(gate, fail=True)  # seals, then the close itself fails

    record, gate, _proxy, _root = _drive(adapter, "close-fail", prepare)
    assert gate.settlement_state() == SETTLED_OK
    assert record.current_generation.continuation_proxy_closed is False
    assert record.status == SessionStatus.FAILED
    assert _terminal_kinds(record) == ["session.failed"]


def test_all_known_settled_request_succeeds(adapter: RuntimeAdapter) -> None:
    def prepare(gate: ResearchRequestGate):
        receipt = gate.before_request(_provider_body())
        gate.complete(receipt, status=200, body=_USAGE_BODY)
        return _CloseDouble(gate)

    record, gate, _proxy, _root = _drive(adapter, "settled", prepare)
    assert gate.settlement_state() == SETTLED_OK
    assert record.status == SessionStatus.IDLE
    assert _terminal_kinds(record) == ["session.result"]


def test_settled_http200_without_billing_usage_succeeds(adapter: RuntimeAdapter) -> None:
    def prepare(gate: ResearchRequestGate):
        receipt = gate.before_request(_provider_body())
        assert gate.complete(receipt, status=200, body=_NO_USAGE_BODY)["forward"] is True
        return _CloseDouble(gate)

    record, gate, _proxy, _root = _drive(adapter, "missing-usage", prepare)
    assert gate.settlement_state() == SETTLED_OK
    assert record.status == SessionStatus.IDLE
    assert _terminal_kinds(record) == ["session.result"]


def test_unknown_provider_outcome_fails_root_closed(adapter: RuntimeAdapter) -> None:
    def prepare(gate: ResearchRequestGate):
        receipt = gate.before_request(_provider_body())
        gate.complete(receipt, status=0, body=b"", outcome_unknown=True)
        return _CloseDouble(gate)

    record, gate, _proxy, _root = _drive(adapter, "unknown-provider", prepare)
    assert gate.settlement_state() == UNKNOWN_OR_UNPAIRED
    assert record.status == SessionStatus.FAILED
    assert _terminal_kinds(record) == ["session.failed"]


def test_known_nonforwarded_completion_fails_root_closed(adapter: RuntimeAdapter) -> None:
    """A completed but non-forwarded response (output cap) is not success."""

    def prepare(gate: ResearchRequestGate):
        receipt = gate.before_request(_provider_body())
        gate.complete(receipt, status=200, body=_usage_body(output_tokens=9))
        return _CloseDouble(gate)

    record, gate, _proxy, _root = _drive(adapter, "nonforwarded", prepare)
    assert gate.settlement_state() == KNOWN_BLOCKED
    assert record.status == SessionStatus.FAILED
    assert _terminal_kinds(record) == ["session.failed"]


def test_late_known_nonforwarded_completion_after_f6_budget_check_fails_root_closed(
    adapter: RuntimeAdapter, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The fresh terminal snapshot catches a receipt after the earlier F6 check."""

    from app import runtime as runtime_module
    from app.research_request_gate import build_continuation_request_gate
    from packages.contracts.continuation_request import profile_binding, request_limits
    from .test_process_cleanup import FakeHarness

    adapter.create_session("late-nonforwarded", "trace-late-nonforwarded")
    root = adapter.submit_prompt("late-nonforwarded", "synthetic settlement")
    assert FakeHarness.run_started.wait(timeout=1.0)
    record = adapter._get("late-nonforwarded")
    gate = build_continuation_request_gate(
        request_id="continuation-late-nonforwarded",
        execution_profile=profile_binding(), limits=request_limits(),
        journal=tmp_path / "late-nonforwarded-provider.jsonl")
    receipt = gate.before_request(_provider_body())
    record.current_generation.continuation_request_gate = gate
    record.current_generation.continuation_request_proxy = _CloseDouble(gate)
    record.continuation_budget = {"reservation_id": gate.request_id}
    record.budget_journal = tmp_path / "synthetic-tool-guard.jsonl"
    record.budget_run_id = root

    budget_check_done = threading.Event()
    allow_terminal_snapshot = threading.Event()
    old_has_blocked_request = gate.has_blocked_request
    observed_old_check: list[bool] = []

    def hold_after_old_budget_check():
        blocked = old_has_blocked_request()
        observed_old_check.append(blocked)
        budget_check_done.set()
        assert allow_terminal_snapshot.wait(4), "terminal snapshot barrier was not released"
        return blocked

    gate.has_blocked_request = hold_after_old_budget_check
    monkeypatch.setattr(runtime_module, "read_request_guard", lambda *_args, **_kwargs: {
        "tool_calls": 0, "blocked_reason": None,
    })
    monkeypatch.setattr(runtime_module, "exceeded_request_limits", lambda _usage: [])

    try:
        FakeHarness.allow_run.set()
        assert budget_check_done.wait(3), "runtime did not reach the earlier F6 budget check"
        assert observed_old_check == [False]
        completion = gate.complete(
            receipt, status=200, body=_usage_body(output_tokens=9))
        assert completion["forward"] is False
        assert completion["reason"] == "output_tokens_exceeded"
        allow_terminal_snapshot.set()
        _wait_for_active_run(adapter, "late-nonforwarded")
        assert gate.settlement_state() == KNOWN_BLOCKED
        assert record.status == SessionStatus.FAILED
        assert record.current_generation.state == "failed"
        assert _terminal_kinds(record) == ["session.failed"]
        assert record.history[-1]["payload"]["run_id"] == root
        assert _read_journal(gate._journal)[-1]["forwarded"] is False
    finally:
        allow_terminal_snapshot.set()
        FakeHarness.allow_run.set()
        _wait_for_active_run(adapter, "late-nonforwarded")


def test_serialized_completed_requests_succeed(adapter: RuntimeAdapter) -> None:
    def prepare(gate: ResearchRequestGate):
        for _ in range(2):
            receipt = gate.before_request(_provider_body())
            gate.complete(receipt, status=200, body=_USAGE_BODY)
        return _CloseDouble(gate)

    record, gate, _proxy, _root = _drive(adapter, "serialized", prepare)
    assert len([row for row in gate.receipts() if row["phase"] == "admitted"]) == 2
    assert gate.settlement_state() == SETTLED_OK
    assert record.status == SessionStatus.IDLE
    assert _terminal_kinds(record) == ["session.result"]


# --------------------------------------------------------------------------- #
# Real proxy: close returns while the HTTP handler completion is deferred
# --------------------------------------------------------------------------- #

def _responding_upstream(body: bytes = _USAGE_BODY):
    entered = threading.Event()
    finished = threading.Event()

    class Provider(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_POST(self):  # noqa: N802
            try:
                self.rfile.read(int(self.headers.get("content-length", "0")))
                entered.set()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except OSError:
                pass
            finally:
                finished.set()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    return server, server_thread, entered, finished


def test_real_proxy_close_with_deferred_handler_never_reports_success(
    adapter: RuntimeAdapter, tmp_path: Path,
) -> None:
    from .test_process_cleanup import FakeHarness

    server, server_thread, provider_entered, provider_finished = _responding_upstream()
    completion_entered = threading.Event()
    release_completion = threading.Event()
    completion_finished = threading.Event()
    record = None
    gate = None
    proxy = None
    client_thread = None
    root = None
    try:
        adapter.create_session("real-proxy", "trace-real-proxy")
        root = adapter.submit_prompt("real-proxy", "synthetic settlement")
        assert FakeHarness.run_started.wait(timeout=1.0)
        record = adapter._get("real-proxy")
        gate = _gate(tmp_path / "real-proxy-provider.jsonl")
        real_complete = gate.complete

        def defer_completion(receipt, **kwargs):
            # The provider response has already been fully read. This barrier is
            # outside the gate lock, so proxy.close() can return while the durable
            # completed receipt and inflight decrement are still pending.
            completion_entered.set()
            try:
                assert release_completion.wait(4), "completion barrier was not released"
                return real_complete(receipt, **kwargs)
            finally:
                completion_finished.set()

        gate.complete = defer_completion
        proxy = RequestGateProxy(gate, "https://opencode.ai/zen/go/v1")
        proxy._server.upstream = f"http://127.0.0.1:{server.server_port}"
        proxy.__enter__()
        record.current_generation.continuation_request_gate = gate
        record.current_generation.continuation_request_proxy = proxy

        def call():
            try:
                httpx.post(proxy.base_url + "/chat/completions",
                           content=_provider_body(), timeout=10)
            except httpx.HTTPError:
                pass

        client_thread = threading.Thread(target=call, daemon=True)
        client_thread.start()
        assert provider_entered.wait(3)
        assert completion_entered.wait(3)
        assert provider_finished.wait(3)
        assert [row["phase"] for row in _read_journal(gate._journal)] == ["admitted"]
        with gate._lock:
            assert gate._inflight == 1
        FakeHarness.allow_run.set()
        _wait_for_active_run(adapter, "real-proxy")
        # The real proxy close in _run_prompt returned while its HTTP handler
        # was paused immediately before gate.complete().
        assert record.current_generation.continuation_proxy_closed is True
        assert gate.settlement_state() == UNKNOWN_OR_UNPAIRED
        assert [row["phase"] for row in _read_journal(gate._journal)] == ["admitted"]
        with gate._lock:
            assert gate._inflight == 1
        assert record.status == SessionStatus.FAILED
        assert record.current_generation.state == "failed"
        assert _terminal_kinds(record) == ["session.failed"]
        assert record.history[-1]["payload"]["run_id"] == root

        release_completion.set()
        assert completion_finished.wait(3)
        client_thread.join(timeout=3)
        assert not client_thread.is_alive()
        rows = _read_journal(gate._journal)
        assert [row["phase"] for row in rows] == ["admitted", "completed"]
        assert rows[-1]["forwarded"] is True
        assert gate.settlement_state() == SETTLED_OK
        assert record.status == SessionStatus.FAILED
        assert _terminal_kinds(record) == ["session.failed"]
    finally:
        FakeHarness.allow_run.set()
        release_completion.set()
        if proxy is not None:
            proxy.close()
        server.shutdown()
        server.server_close()
        if record is not None:
            with record.lock:
                has_run_or_terminal = (record.active_run is not None or any(
                    event["kind"] in {"session.result", "session.failed"}
                    for event in record.history))
            if has_run_or_terminal:
                _wait_for_active_run(adapter, "real-proxy")
        if client_thread is not None:
            client_thread.join(timeout=3)
        server_thread.join(timeout=3)
        for handler in list(getattr(server, "_threads", ())):
            handler.join(timeout=3)
        if client_thread is not None:
            assert not client_thread.is_alive()
        assert not server_thread.is_alive()
        if provider_entered.is_set():
            assert provider_finished.is_set()
        if completion_entered.is_set():
            assert completion_finished.is_set()
