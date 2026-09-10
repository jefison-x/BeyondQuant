from __future__ import annotations

import threading
import json
import hashlib
import time
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace

import pytest
from deepseek_harness import Notification

import app.runtime as runtime_module
from app.identifiers import MAX_IDENTIFIER_LENGTH
from app.runtime import ModelCredentialUnavailable, RuntimeAdapter, SessionConflict, SessionStatus


class FakeHarness:
    instances: list["FakeHarness"] = []
    run_started = threading.Event()
    allow_run = threading.Event()
    finish_reason = "completed"

    def __init__(self, config: object) -> None:
        self.config = config
        self.started = False
        self.closed = False
        self.run_count = 0
        self.session_id = ""
        self.last_content = ""
        self.__class__.instances.append(self)

    @classmethod
    def reset(cls) -> None:
        cls.instances.clear()
        cls.run_started.clear()
        cls.allow_run.clear()
        cls.finish_reason = "completed"

    def start(self) -> None:
        self.started = True

    def start_session(self, session_id: str) -> "FakeHarness":
        self.session_id = session_id
        return self

    def run(self, content: str, *, on_notification: object) -> SimpleNamespace:
        self.run_count += 1
        self.last_content = content
        self.__class__.run_started.set()
        self.__class__.allow_run.wait(timeout=2.0)
        return SimpleNamespace(finish_reason=self.__class__.finish_reason)

    def close(self) -> None:
        self.closed = True
        self.__class__.allow_run.set()


@pytest.mark.parametrize("operation", ["create", "resume"])
def test_release_rejects_inflight_process_initialization(adapter, monkeypatch, operation):
    entered, proceed = threading.Event(), threading.Event()
    errors = []
    if operation == "resume":
        adapter.create_session("starting-race", "race-trace")
        adapter._get("starting-race").status = SessionStatus.FAILED
    original = FakeHarness.start

    def blocked_start(harness):
        entered.set()
        assert proceed.wait(3)
        original(harness)

    def initialize():
        try:
            if operation == "create":
                adapter.create_session("starting-race", "race-trace")
            else:
                adapter.resume_session("starting-race")
        except BaseException as exc:
            errors.append(exc)

    monkeypatch.setattr(FakeHarness, "start", blocked_start)
    worker = threading.Thread(target=initialize)
    worker.start()
    try:
        assert entered.wait(2)
        with pytest.raises(SessionConflict):
            adapter.release_session("starting-race")
        proceed.set()
        worker.join(3)
        assert not worker.is_alive()
        assert not errors
        assert adapter._get("starting-race").status == SessionStatus.READY
    finally:
        proceed.set()
        worker.join(3)
        adapter.close()
        for harness in FakeHarness.instances:
            harness.close()


@pytest.mark.parametrize("operation", ["create", "resume"])
def test_shutdown_cannot_publish_a_late_initialized_process(adapter, monkeypatch, operation):
    entered, proceed = threading.Event(), threading.Event()
    errors = []
    if operation == "resume":
        adapter.create_session("shutdown-race", "race-trace")
        adapter._get("shutdown-race").status = SessionStatus.FAILED
    original = FakeHarness.start

    def blocked_start(harness):
        entered.set()
        assert proceed.wait(3)
        original(harness)

    def initialize():
        try:
            if operation == "create":
                adapter.create_session("shutdown-race", "race-trace")
            else:
                adapter.resume_session("shutdown-race")
        except BaseException as exc:
            errors.append(exc)

    monkeypatch.setattr(FakeHarness, "start", blocked_start)
    worker = threading.Thread(target=initialize)
    worker.start()
    try:
        assert entered.wait(2)
        record = adapter._get("shutdown-race")
        adapter.close()
        proceed.set()
        worker.join(3)
        assert not worker.is_alive()
        assert record.status == SessionStatus.CLOSED
        assert all(harness.closed for harness in FakeHarness.instances)
        assert errors and isinstance(errors[0], SessionConflict)
    finally:
        proceed.set()
        worker.join(3)
        adapter.close()
        for harness in FakeHarness.instances:
            harness.close()


@pytest.mark.parametrize("stage", ["build", "start"])
def test_failed_resume_initialization_does_not_leave_starting(adapter, monkeypatch, stage):
    adapter.create_session("failed-init", "failed-init-trace")
    record = adapter._get("failed-init")
    record.status = SessionStatus.FAILED

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic initialize failure")

    if stage == "build":
        monkeypatch.setattr(adapter, "_build_harness", fail)
    else:
        monkeypatch.setattr(FakeHarness, "start", fail)
    try:
        with pytest.raises(RuntimeError, match="synthetic initialize"):
            adapter.resume_session("failed-init")
        assert record.status == SessionStatus.FAILED
        assert all(harness.closed for harness in FakeHarness.instances)
        adapter.release_session("failed-init")
    finally:
        adapter.close()


def release_compatibility(tmp_path: Path) -> object:
    from app.compat.dsh_012 import Dsh012Compatibility

    executable = tmp_path / "candidate-dsh"
    executable.write_text("candidate", encoding="utf-8")
    composition = tmp_path / "composition.yml"
    composition.write_text("candidate", encoding="utf-8")
    return Dsh012Compatibility(
        harness_factory=FakeHarness,
        runtime_path_factory=lambda: executable,
    )


@pytest.fixture
def adapter(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> RuntimeAdapter:
    FakeHarness.reset()
    monkeypatch.delenv("BYQ_CREDENTIAL_RESOLVER_TOKEN", raising=False)
    monkeypatch.setenv("BYQ_DSH_RUNTIME_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("BYQ_DSH_COMPOSITION", str(tmp_path / "composition.yml"))
    monkeypatch.setenv("DSH_SESSION_ROOT", str(tmp_path / "sessions"))
    monkeypatch.setenv("BYQ_DSH_RUN_TIMEOUT_SECONDS", "3600")
    monkeypatch.setenv("BYQ_DSH_SUBAGENT_TIMEOUT_SECONDS", "3600")
    monkeypatch.setenv("BYQ_DSH_NO_PROGRESS_TIMEOUT_SECONDS", "3600")
    return RuntimeAdapter(release_compatibility(tmp_path))


def wait_for_status(adapter: RuntimeAdapter, session_id: str, status: str) -> None:
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        record = adapter._get(session_id)
        if adapter.describe_session(record)["status"] == status:
            return
        time.sleep(0.01)
    raise AssertionError(f"session did not reach {status}")


@pytest.mark.parametrize("finish_reason", ["max-tokens", "aborted", "future-unknown"])
def test_incomplete_model_finish_is_never_a_success_result(adapter: RuntimeAdapter, finish_reason: str) -> None:
    FakeHarness.finish_reason = finish_reason
    try:
        adapter.create_session("incomplete", "incomplete-trace")
        receipt = adapter.submit_prompt("incomplete", "synthetic incomplete outcome")
        FakeHarness.allow_run.set()
        deadline = time.monotonic() + 2.0
        record = adapter._get("incomplete")
        while record.active_run is not None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert record.status == SessionStatus.FAILED
        terminal = [item for item in record.history if item["kind"] in {"session.result", "session.failed"}]
        assert len(terminal) == 1
        assert terminal[0]["kind"] == "session.failed"
        assert terminal[0]["payload"]["run_id"] == receipt
    finally:
        adapter.close()


@pytest.mark.parametrize("fresh", [[], [{"role": "user", "content": "沪深300近三年周调仓"}]])
def test_prompt_can_atomically_replace_prepared_public_context(adapter, fresh):
    try:
        adapter.create_session("fresh-context", "fresh-trace",
                               conversation_context=[{"role": "user", "content": "旧研究对象"}])
        root = adapter.submit_prompt("fresh-context", "继续研究", idempotency_key="fresh-prompt-key",
                                    conversation_context=fresh)
        assert FakeHarness.run_started.wait(1)
        content = FakeHarness.instances[0].last_content
        assert "旧研究对象" not in content
        assert ("沪深300近三年周调仓" in content) == bool(fresh)
        # A retry must preserve the original root without consuming another
        # projection or executing again, even if a caller supplies bad context.
        assert adapter.submit_prompt("fresh-context", "继续研究", idempotency_key="fresh-prompt-key",
                                     conversation_context={"invalid": True}) == root
        assert FakeHarness.instances[0].run_count == 1
    finally:
        adapter.close()


def test_prompt_rejects_invalid_context_before_claiming_root(adapter):
    try:
        adapter.create_session("invalid-context", "invalid-trace")
        with pytest.raises(ValueError):
            adapter.submit_prompt("invalid-context", "继续", idempotency_key="invalid-context-key",
                                  conversation_context=[{"role": "system", "content": "not public"}])
        record = adapter._get("invalid-context")
        assert record.status == SessionStatus.READY
        assert record.active_run is None
        assert not record.prompt_idempotency
        assert FakeHarness.instances[0].run_count == 0
    finally:
        adapter.close()


def test_registration_observation_uses_captured_turn_without_exposing_arguments(adapter: RuntimeAdapter):
    if version("deepseek-harness-sdk") != "0.1.2rc1":
        pytest.skip("requires qualified 0.1.2 notification carrier")
    from packages.contracts.agent_run_lifecycle import registration_fingerprint

    try:
        adapter.create_session("binding", "binding-trace", "alice", "workspace_alice")
        root_id = adapter.submit_prompt("binding", "synthetic registration")
        record = adapter._get("binding")
        run = record.active_run
        notice = Notification(method="session.event", payload={"sessionId": record.runtime_session_id,
            "event": {"type": "tool/call", "seq": 1, "data": {
                "callId": "register", "name": "mcp__byq__byq_agent_run_start",
                "arguments": json.dumps({"idempotency_key": "private-registration-key", "role_id": "quant_orchestrator"}),
            }}})
        for _ in range(2):
            adapter._on_notification(record, notice, source_run=run, source_runtime_session_id=record.runtime_session_id)
        bindings = [item for item in record.history if item["kind"] == "agent.run.registration"]
        assert len(bindings) == 1
        assert bindings[0]["payload"] == {
            "schema_version": "agent-run-registration-observed.v1", "run_id": root_id,
            "registration_fingerprint": registration_fingerprint(
                "alice", "workspace_alice", "byq-product-agent-binding", "binding-trace", "binding",
                FakeHarness.instances[0].config.env["BYQ_DSH_RUN_ID"], "private-registration-key"),
        }
        serialized = json.dumps(record.history)
        assert "private-registration-key" not in serialized
        assert record.runtime_generation not in serialized
        adapter.cancel_session("binding", "hard")
        adapter._on_notification(record, notice, source_run=run, source_runtime_session_id=record.runtime_session_id)
        assert len([item for item in record.history if item["kind"] == "agent.run.registration"]) == 1
    finally:
        adapter.close()


def test_product_process_cannot_start_next_turn_until_exact_terminal_ack(adapter):
    from packages.contracts.agent_run_lifecycle import lifecycle_receipt, project_lifecycle_event
    try:
        adapter.create_session("ack-barrier", "ack-trace", "alice", "workspace_alice")
        first = adapter.submit_prompt("ack-barrier", "first", idempotency_key="original-prompt")
        FakeHarness.allow_run.set()
        wait_for_status(adapter, "ack-barrier", SessionStatus.IDLE)
        record = adapter._get("ack-barrier")
        terminal = next(item for item in record.history if item["kind"] == "session.result")
        receipt = lifecycle_receipt(project_lifecycle_event(terminal, "ack-barrier", "ack-trace"))
        with pytest.raises(SessionConflict, match="cleanup"):
            adapter.submit_prompt("ack-barrier", "second")
        assert adapter.submit_prompt("ack-barrier", "first", idempotency_key="original-prompt") == first
        assert FakeHarness.instances[0].run_count == 1
        for invalid in ({**receipt, "event_sha256": "0" * 64}, {**receipt, "sequence": receipt["sequence"] + 1},
                        {**receipt, "root_run_id": "f" * 32}, {**receipt, "extra": True},
                        {**receipt, "sequence": float(receipt["sequence"])}):
            with pytest.raises(SessionConflict):
                adapter.acknowledge_terminal("ack-barrier", invalid)
        assert adapter.acknowledge_terminal("ack-barrier", receipt) == {"receipt": receipt}
        assert adapter.acknowledge_terminal("ack-barrier", receipt) == {"receipt": receipt}
        second = adapter.submit_prompt("ack-barrier", "second")
        assert second != first
        wait_for_status(adapter, "ack-barrier", SessionStatus.IDLE)
        adapter.acknowledge_terminal("ack-barrier", receipt)
        with pytest.raises(SessionConflict, match="cleanup"):
            adapter.submit_prompt("ack-barrier", "third")
    finally:
        adapter.close()


@pytest.mark.parametrize("ack_while_released", [False, True])
def test_terminal_ack_barrier_survives_session_release_and_recreation(adapter, ack_while_released):
    try:
        adapter.create_session("durable-ack", "durable-trace", "alice", "workspace_alice")
        root = adapter.submit_prompt("durable-ack", "synthetic first")
        FakeHarness.allow_run.set()
        wait_for_status(adapter, "durable-ack", SessionStatus.IDLE)
        receipt = adapter._get("durable-ack").terminal_receipts[root]
        adapter.release_session("durable-ack")
        if ack_while_released:
            count = len(FakeHarness.instances)
            assert adapter.acknowledge_terminal("durable-ack", receipt) == {"receipt": receipt}
            assert len(FakeHarness.instances) == count  # evidence only, no process
        adapter.create_session("durable-ack", "durable-trace", "alice", "workspace_alice")
        if not ack_while_released:
            with pytest.raises(SessionConflict, match="cleanup"):
                adapter.submit_prompt("durable-ack", "synthetic second")
            adapter.acknowledge_terminal("durable-ack", receipt)
        assert root not in adapter._get("durable-ack").pending_terminal_receipts
        assert adapter.submit_prompt("durable-ack", "synthetic second") != root
    finally:
        adapter.close()


def test_terminal_ack_write_failure_does_not_release_admission(adapter, monkeypatch):
    try:
        adapter.create_session("ack-disk-failure", "ack-disk-trace", "alice", "workspace_alice")
        root = adapter.submit_prompt("ack-disk-failure", "synthetic first")
        FakeHarness.allow_run.set()
        wait_for_status(adapter, "ack-disk-failure", SessionStatus.IDLE)
        record = adapter._get("ack-disk-failure")
        save = record.journal._save

        def fail(state):
            raise OSError("synthetic unavailable storage")

        monkeypatch.setattr(record.journal, "_save", fail)
        with pytest.raises(OSError):
            adapter.acknowledge_terminal("ack-disk-failure", record.terminal_receipts[root])
        assert root in record.pending_terminal_receipts
        assert record.journal.state["terminal_acks"] == {}
        with pytest.raises(SessionConflict, match="cleanup"):
            adapter.submit_prompt("ack-disk-failure", "synthetic second")
        monkeypatch.setattr(record.journal, "_save", save)
    finally:
        adapter.close()


def test_new_process_generation_preserves_old_ack_barrier(adapter):
    try:
        adapter.create_session("new-generation", "generation-trace", "alice", "workspace_alice")
        adapter.submit_prompt("new-generation", "first")
        assert FakeHarness.run_started.wait(1)
        record = adapter._get("new-generation")
        previous = record.runtime_generation
        adapter.cancel_session("new-generation", "hard")
        assert record.pending_terminal_receipts
        adapter.resume_session("new-generation")
        assert record.runtime_generation != previous
        assert record.pending_terminal_receipts
        with pytest.raises(SessionConflict, match="cleanup"):
            adapter.submit_prompt("new-generation", "new generation")
        receipt = next(iter(record.terminal_receipts.values()))
        adapter.acknowledge_terminal("new-generation", receipt)
        adapter.submit_prompt("new-generation", "new generation")
    finally:
        adapter.close()


@pytest.mark.parametrize("cleanup", ["cancel", "watchdog"])
def test_resume_waits_for_old_process_cleanup(adapter, monkeypatch, cleanup):
    entered, release = threading.Event(), threading.Event()
    original_close = FakeHarness.close
    errors = []

    def slow_close(harness):
        entered.set()
        assert release.wait(2)
        original_close(harness)

    def terminate():
        try:
            if cleanup == "cancel":
                adapter.cancel_session("closing-root", "hard")
            else:
                record = adapter._get("closing-root")
                run = record.active_run
                adapter._enforce_run_guards(record, run, now=run.started_at + 7200)
        except BaseException as error:
            errors.append(error)

    thread = None
    try:
        adapter.create_session("closing-root", "closing-trace")
        adapter.submit_prompt("closing-root", "synthetic request")
        assert FakeHarness.run_started.wait(1)
        monkeypatch.setattr(FakeHarness, "close", slow_close)
        thread = threading.Thread(target=terminate)
        thread.start()
        assert entered.wait(1)
        with pytest.raises(SessionConflict, match="cleanup"):
            adapter.resume_session("closing-root")
        assert len(FakeHarness.instances) == 1
        release.set()
        thread.join(2)
        assert not thread.is_alive()
        assert not errors
        adapter.resume_session("closing-root")
        assert FakeHarness.instances[0].closed
        assert not FakeHarness.instances[1].closed
    finally:
        release.set()
        if thread:
            thread.join(2)
        adapter.close()


def test_delayed_prompt_worker_cannot_execute_on_resumed_process(adapter, monkeypatch):
    workers = []

    class DeferredThread:
        def __init__(self, *, target, args, name, daemon):
            if name.startswith("byq-dsh-session-"):
                workers.append((target, args))

        def start(self):
            pass

    monkeypatch.setattr(runtime_module.threading, "Thread", DeferredThread)
    try:
        adapter.create_session("delayed-worker", "delayed-trace")
        adapter.submit_prompt("delayed-worker", "old synthetic request")
        old_harness = FakeHarness.instances[0]
        adapter.cancel_session("delayed-worker", "hard")
        adapter.resume_session("delayed-worker")
        new_harness = FakeHarness.instances[1]
        target, args = workers[0]
        target(*args)
        assert old_harness.run_count == 0
        assert new_harness.run_count == 0
        assert adapter._get("delayed-worker").status == SessionStatus.READY
    finally:
        adapter.close()


def test_terminal_receipt_http_is_closed_and_exact_session_scoped(adapter, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    monkeypatch.setattr(main, "adapter", adapter)
    client = TestClient(main.app)
    try:
        adapter.create_session("receipt-http", "receipt-trace", "alice", "workspace_alice")
        adapter.create_session("other-http", "other-trace", "bob", "workspace_bob")
        adapter.submit_prompt("receipt-http", "first")
        FakeHarness.allow_run.set()
        wait_for_status(adapter, "receipt-http", SessionStatus.IDLE)
        receipt = next(iter(adapter._get("receipt-http").terminal_receipts.values()))
        path = "/internal/runtime/sessions/receipt-http/terminal-receipt"
        assert client.post(path, json={"receipt": receipt, "bypass": True}).status_code == 422
        assert client.post(path, json={"receipt": {}}).status_code == 409
        assert client.post("/internal/runtime/sessions/other-http/terminal-receipt",
                           json={"receipt": receipt}).status_code == 409
        assert client.post("/internal/runtime/sessions/missing/terminal-receipt",
                           json={"receipt": receipt}).status_code == 404
        assert client.post(path, json={"receipt": receipt}).json() == {"receipt": receipt}
    finally:
        adapter.close()


def test_recovery_and_durable_prompt_lookup_never_construct_or_run_a_harness(adapter):
    from app.lifecycle_journal import LifecycleJournal
    from app.contracts import make_workflow_trace_event
    ctx = {"session_id": "orphan", "trace_id": "orphan-trace", "owner": "alice", "workspace_id": "workspace_alice"}
    journal = LifecycleJournal.claim(adapter._session_root / "byq-lifecycle-evidence", ctx, create=True)
    content = "synthetic private prompt not stored"
    root = "a" * 32
    journal.observe(make_workflow_trace_event(session_id="orphan", trace_id="orphan-trace", sequence=4,
        kind="session.started", source="runtime-adapter", payload={"run_id": root}),
        generation="old-generation", prompt=("original-prompt", hashlib.sha256(content.encode()).hexdigest()))
    assert adapter.recover_evidence(ctx)["state"] == "owned"
    journal.close()
    recovered = adapter.recover_evidence(ctx)
    assert [e["kind"] for e in recovered["events"]] == ["session.started", "session.closed"]
    assert adapter.recover_evidence(ctx, after_sequence=5)["events"] == []
    assert adapter.reconcile_prompt("orphan", "original-prompt", hashlib.sha256(content.encode()).hexdigest())["run_id"] == root
    assert FakeHarness.instances == []
    assert content not in journal.path.read_text()
    with pytest.raises(ValueError):
        adapter.recover_evidence({**ctx, "owner": "bob"})
    try:
        adapter.create_session("orphan", "orphan-trace", "alice", "workspace_alice")
        assert adapter.submit_prompt("orphan", content, idempotency_key="original-prompt") == root
        assert FakeHarness.instances[0].run_count == 0
        assert adapter._get("orphan").sequence > 5
    finally:
        adapter.close()


def test_failed_journal_write_prevents_model_start_and_shutdown_still_closes_process(adapter, monkeypatch):
    adapter.create_session("disk-failure", "disk-trace", "alice", "workspace_alice")
    record = adapter._get("disk-failure")
    def fail(*args, **kwargs):
        raise OSError("synthetic evidence storage failure")
    monkeypatch.setattr(record.journal, "_save", fail)
    with pytest.raises(OSError):
        adapter.submit_prompt("disk-failure", "must not execute", idempotency_key="disk-failure-key")
    assert FakeHarness.instances[0].run_count == 0
    with pytest.raises(OSError):
        adapter.close()
    assert FakeHarness.instances[0].closed
    assert record.journal.lock is None


def test_default_whole_run_ceiling_allows_bounded_complex_research(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BYQ_DSH_RUN_TIMEOUT_SECONDS", raising=False)

    assert RuntimeAdapter().readiness()["run_guards"]["run_timeout_seconds"] == 900.0


def test_lifecycle_has_single_active_prompt_and_duplicate_create_is_explicit(adapter: RuntimeAdapter) -> None:
    created = adapter.create_session("s-1", "t-1")
    assert created["status"] == SessionStatus.READY
    assert FakeHarness.instances[0].started is True

    first_run = adapter.submit_prompt("s-1", "first")
    assert first_run
    assert FakeHarness.run_started.wait(timeout=1.0)
    with pytest.raises(SessionConflict):
        adapter.submit_prompt("s-1", "concurrent")
    with pytest.raises(SessionConflict):
        adapter.create_session("s-1", "t-duplicate")

    FakeHarness.allow_run.set()
    wait_for_status(adapter, "s-1", SessionStatus.IDLE)
    released = adapter.release_session("s-1")
    assert released["status"] == SessionStatus.CLOSED
    assert FakeHarness.instances[0].closed is True

    recreated = adapter.create_session("s-1", "t-2")
    assert recreated["status"] == SessionStatus.READY
    adapter.release_session("s-1")


def test_prompt_idempotency_returns_the_original_run_without_reexecution(adapter: RuntimeAdapter) -> None:
    adapter.create_session("s-idempotent", "t-idempotent")
    first_run = adapter.submit_prompt(
        "s-idempotent", "continue approval", idempotency_key="approval-continuation-1",
    )
    assert FakeHarness.run_started.wait(timeout=1.0)
    assert adapter.submit_prompt(
        "s-idempotent", "continue approval", idempotency_key="approval-continuation-1",
    ) == first_run
    digest = hashlib.sha256(b"continue approval").hexdigest()
    receipt = adapter.reconcile_prompt("s-idempotent", "approval-continuation-1", digest)
    assert receipt == {"schema_version": "prompt-receipt.v1", "state": "accepted", "run_id": first_run}
    assert "continue approval" not in str(receipt)
    assert adapter.reconcile_prompt("s-idempotent", "missing-key", digest)["state"] == "outcome_unknown"
    with pytest.raises(SessionConflict):
        adapter.reconcile_prompt("s-idempotent", "approval-continuation-1", "0" * 64)
    with pytest.raises(SessionConflict, match="reused"):
        adapter.submit_prompt(
            "s-idempotent", "different continuation", idempotency_key="approval-continuation-1",
        )

    FakeHarness.allow_run.set()
    wait_for_status(adapter, "s-idempotent", SessionStatus.IDLE)
    assert adapter.submit_prompt(
        "s-idempotent", "continue approval", idempotency_key="approval-continuation-1",
    ) == first_run
    adapter.release_session("s-idempotent")
    adapter.create_session("s-idempotent", "t-recreated")
    assert adapter.reconcile_prompt("s-idempotent", "approval-continuation-1", digest)["state"] == "outcome_unknown"
    adapter.release_session("s-idempotent")


def test_hard_cancel_closes_runtime_and_rejects_later_prompt(adapter: RuntimeAdapter) -> None:
    adapter.create_session("s-1", "t-1")
    adapter.submit_prompt("s-1", "running")
    assert FakeHarness.run_started.wait(timeout=1.0)

    cancelled = adapter.cancel_session("s-1", "hard")
    assert cancelled["status"] == SessionStatus.INTERRUPTED
    assert cancelled["active_prompt"] is False
    assert FakeHarness.instances[0].closed is True
    with pytest.raises(SessionConflict):
        adapter.submit_prompt("s-1", "must-not-run")

    released = adapter.release_session("s-1")
    assert released["status"] == SessionStatus.CLOSED


@pytest.mark.parametrize("outcome", ["completed", "error", "hard_cancel", "soft_cancel", "timeout", "shutdown"])
def test_terminal_events_identify_the_exact_submitted_root_run(adapter: RuntimeAdapter, outcome: str) -> None:
    adapter.create_session("s-terminal", "t-terminal")
    run_id = adapter.submit_prompt("s-terminal", "synthetic lifecycle")
    assert FakeHarness.run_started.wait(timeout=1.0)
    record = adapter._get("s-terminal")
    try:
        if outcome in {"completed", "error"}:
            FakeHarness.finish_reason = outcome
            FakeHarness.allow_run.set()
            wait_for_status(adapter, "s-terminal", SessionStatus.IDLE if outcome == "completed" else SessionStatus.FAILED)
        elif outcome in {"hard_cancel", "soft_cancel"}:
            adapter.cancel_session("s-terminal", "hard" if outcome == "hard_cancel" else "soft")
            if outcome == "soft_cancel":
                FakeHarness.allow_run.set()
                wait_for_status(adapter, "s-terminal", SessionStatus.IDLE)
                discarded = [event for event in record.history if event["kind"] == "session.result.discarded"]
                assert discarded[0]["payload"]["run_id"] == run_id
        elif outcome == "timeout":
            run = record.active_run
            assert run is not None
            assert adapter._enforce_run_guards(record, run, now=run.started_at + 3601)
        else:
            adapter.close()
        terminals = [event for event in record.history if event["kind"] in
                     {"session.result", "session.failed", "session.cancelled", "session.closed"}]
        assert len(terminals) == 1
        assert terminals[0]["payload"].get("run_id") == run_id
        started = next(event for event in record.history if event["kind"] == "session.started")
        assert started["payload"]["run_id"] == run_id
        assert run_id != record.session_id
    finally:
        adapter.close()


def test_two_turns_in_one_process_keep_distinct_terminal_identities(adapter: RuntimeAdapter) -> None:
    adapter.create_session("s-two-turns", "t-two-turns")
    FakeHarness.allow_run.set()
    try:
        first = adapter.submit_prompt("s-two-turns", "first synthetic question")
        wait_for_status(adapter, "s-two-turns", SessionStatus.IDLE)
        second = adapter.submit_prompt("s-two-turns", "second synthetic question")
        wait_for_status(adapter, "s-two-turns", SessionStatus.IDLE)
        assert first != second
        results = [event["payload"]["run_id"] for event in adapter._get("s-two-turns").history
                   if event["kind"] == "session.result"]
        assert results == [first, second]
        assert len(FakeHarness.instances) == 1
    finally:
        adapter.close()


def test_no_progress_watchdog_fails_and_closes_only_the_stuck_runtime(adapter: RuntimeAdapter) -> None:
    adapter.create_session("s-stuck", "t-stuck")
    adapter.submit_prompt("s-stuck", "running")
    assert FakeHarness.run_started.wait(timeout=1.0)
    record = adapter._get("s-stuck")
    run = record.active_run
    assert run is not None

    run.last_runtime_activity_at = 10.0
    assert adapter._enforce_run_guards(record, run, now=3611.0) is True

    wait_for_status(adapter, "s-stuck", SessionStatus.FAILED)
    assert FakeHarness.instances[0].closed is True
    assert record.active_run is None
    assert record.history[-1]["kind"] == "session.failed"
    assert record.history[-1]["payload"] == {
        "code": "runtime-no-progress-timeout",
        "retryable": True,
        "run_id": run.run_id,
    }
    history_length = len(record.history)
    adapter._on_notification(record, Notification(
        method="session.status",
        payload={"sessionId": record.runtime_session_id, "status": "idle"},
    ))
    assert len(record.history) == history_length


def test_answer_text_chunks_refresh_liveness_without_crossing_public_boundary(
    adapter: RuntimeAdapter, monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter.create_session("s-answer-stream", "t-answer-stream")
    adapter.submit_prompt("s-answer-stream", "running")
    assert FakeHarness.run_started.wait(timeout=1.0)
    record = adapter._get("s-answer-stream")
    run = record.active_run
    assert run is not None
    run.last_runtime_activity_at = 10.0
    history_length = len(record.history)
    monkeypatch.setattr(runtime_module.time, "monotonic", lambda: 42.0)

    adapter._on_notification(record, Notification(
        method="session.event",
        payload={
            "sessionId": record.runtime_session_id,
            "event": {"type": "assistant/chunk", "data": {
                "turn": 1, "step": 5,
                "chunk": {"type": "text-delta", "index": 1, "text": "结论"},
            }},
        },
    ))

    assert run.last_runtime_activity_at == 42.0
    assert len(record.history) == history_length
    adapter.cancel_session("s-answer-stream", "hard")


def test_reasoning_chunks_refresh_internal_liveness_without_crossing_public_boundary(
    adapter: RuntimeAdapter, monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter.create_session("s-reasoning-stream", "t-reasoning-stream")
    adapter.submit_prompt("s-reasoning-stream", "running")
    assert FakeHarness.run_started.wait(timeout=1.0)
    record = adapter._get("s-reasoning-stream")
    run = record.active_run
    assert run is not None
    run.last_runtime_activity_at = 10.0
    history_length = len(record.history)
    monkeypatch.setattr(runtime_module.time, "monotonic", lambda: 42.0)

    adapter._on_notification(record, Notification(
        method="session.event",
        payload={
            "sessionId": record.runtime_session_id,
            "event": {"type": "assistant/chunk", "data": {
                "turn": 1, "step": 5,
                "chunk": {"type": "reasoning-delta", "index": 0, "text": "private"},
            }},
        },
    ))

    assert run.last_runtime_activity_at == 42.0
    assert len(record.history) == history_length
    assert "private" not in str(record.history)
    adapter.cancel_session("s-reasoning-stream", "hard")


def test_late_notification_from_previous_run_cannot_extend_next_run(
    adapter: RuntimeAdapter,
) -> None:
    adapter.create_session("s-late", "t-late")
    adapter.submit_prompt("s-late", "first")
    assert FakeHarness.run_started.wait(timeout=1.0)
    record = adapter._get("s-late")
    first_run = record.active_run
    assert first_run is not None

    FakeHarness.allow_run.set()
    wait_for_status(adapter, "s-late", SessionStatus.IDLE)
    FakeHarness.run_started.clear()
    FakeHarness.allow_run.clear()
    adapter.submit_prompt("s-late", "second")
    assert FakeHarness.run_started.wait(timeout=1.0)
    second_run = record.active_run
    assert second_run is not None
    second_run.last_runtime_activity_at = 10.0
    history_length = len(record.history)

    adapter._on_notification(
        record,
        Notification(
            method="session.event",
            payload={
                "sessionId": record.runtime_session_id,
                "event": {"type": "assistant/chunk", "data": {
                    "chunk": {"type": "reasoning-delta", "text": "late-private"},
                }},
            },
        ),
        source_run=first_run,
        source_runtime_session_id=record.runtime_session_id,
    )

    assert second_run.last_runtime_activity_at == 10.0
    assert len(record.history) == history_length
    adapter.cancel_session("s-late", "hard")


@pytest.mark.parametrize("event_type", ["step/start", "step/end"])
def test_step_boundaries_refresh_internal_liveness_without_public_projection(
    adapter: RuntimeAdapter,
    monkeypatch: pytest.MonkeyPatch,
    event_type: str,
) -> None:
    adapter.create_session("s-step", "t-step")
    adapter.submit_prompt("s-step", "running")
    assert FakeHarness.run_started.wait(timeout=1.0)
    record = adapter._get("s-step")
    run = record.active_run
    assert run is not None
    run.last_runtime_activity_at = 10.0
    history_length = len(record.history)
    monkeypatch.setattr(runtime_module.time, "monotonic", lambda: 42.0)

    adapter._on_notification(record, Notification(
        method="session.event",
        payload={
            "sessionId": record.runtime_session_id,
            "event": {"type": event_type, "data": {"turn": 1, "step": 2}},
        },
    ))

    assert run.last_runtime_activity_at == 42.0
    assert len(record.history) == history_length
    adapter.cancel_session("s-step", "hard")


def test_unassociated_descendant_cannot_refresh_owned_run(
    adapter: RuntimeAdapter, monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter.create_session("s-child-live", "t-child-live")
    adapter.submit_prompt("s-child-live", "running")
    assert FakeHarness.run_started.wait(timeout=1.0)
    record = adapter._get("s-child-live")
    run = record.active_run
    assert run is not None
    run.last_runtime_activity_at = 10.0
    history_length = len(record.history)
    monkeypatch.setattr(runtime_module.time, "monotonic", lambda: 42.0)

    adapter._on_notification(record, Notification(
        method="session.event",
        payload={
            "sessionId": "private-descendant-session",
            "event": {"type": "assistant/chunk", "data": {
                "turn": 1, "step": 1,
                "chunk": {"type": "reasoning-delta", "index": 0, "text": "child-private"},
            }},
        },
    ))

    assert run.last_runtime_activity_at == 10.0
    assert len(record.history) == history_length
    assert "private-descendant-session" not in str(record.history)
    assert "child-private" not in str(record.history)
    adapter.cancel_session("s-child-live", "hard")


def test_unknown_or_malformed_events_do_not_refresh_runtime_liveness(
    adapter: RuntimeAdapter, monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter.create_session("s-invalid-live", "t-invalid-live")
    adapter.submit_prompt("s-invalid-live", "running")
    assert FakeHarness.run_started.wait(timeout=1.0)
    record = adapter._get("s-invalid-live")
    run = record.active_run
    assert run is not None
    run.last_runtime_activity_at = 10.0
    monkeypatch.setattr(runtime_module.time, "monotonic", lambda: 42.0)

    for raw_event in (
        {"type": "heartbeat", "data": {}},
        {"type": "assistant/chunk", "data": {
            "chunk": {"type": "reasoning-delta", "text": ""},
        }},
        {"type": "tool/call", "data": {"callId": "", "name": ""}},
    ):
        adapter._on_notification(record, Notification(
            method="session.event",
            payload={"sessionId": record.runtime_session_id, "event": raw_event},
        ))

    assert run.last_runtime_activity_at == 10.0
    adapter.cancel_session("s-invalid-live", "hard")


def test_subagent_wall_clock_timeout_wins_even_when_public_progress_continues(
    adapter: RuntimeAdapter,
) -> None:
    adapter.create_session("s-child", "t-child")
    adapter.submit_prompt("s-child", "running")
    assert FakeHarness.run_started.wait(timeout=1.0)
    record = adapter._get("s-child")
    run = record.active_run
    assert run is not None
    run.last_runtime_activity_at = 3600.0
    run.active_subagent_calls["delegate-call"] = 10.0

    assert adapter._enforce_run_guards(record, run, now=3611.0) is True

    wait_for_status(adapter, "s-child", SessionStatus.FAILED)
    assert record.history[-1]["payload"] == {
        "code": "runtime-subagent-timeout",
        "retryable": True,
        "run_id": run.run_id,
    }


def test_active_subagent_uses_its_dedicated_timeout_before_no_activity_guard(
    adapter: RuntimeAdapter,
) -> None:
    adapter.create_session("s-child-deadline", "t-child-deadline")
    adapter.submit_prompt("s-child-deadline", "running")
    assert FakeHarness.run_started.wait(timeout=1.0)
    record = adapter._get("s-child-deadline")
    run = record.active_run
    assert run is not None
    adapter._run_timeout_seconds = 300.0
    adapter._subagent_timeout_seconds = 180.0
    adapter._no_progress_timeout_seconds = 120.0
    run.started_at = 0.0
    run.last_runtime_activity_at = 10.0
    run.active_subagent_calls["delegate-call"] = 50.0

    assert adapter._enforce_run_guards(record, run, now=171.0) is False
    assert record.status == SessionStatus.RUNNING
    assert adapter._enforce_run_guards(record, run, now=231.0) is True

    wait_for_status(adapter, "s-child-deadline", SessionStatus.FAILED)
    assert record.history[-1]["payload"] == {
        "code": "runtime-subagent-timeout",
        "retryable": True,
        "run_id": run.run_id,
    }


def test_wait_notices_are_bounded_do_not_renew_and_stop_with_run(adapter: RuntimeAdapter) -> None:
    adapter.create_session("s-wait", "t-wait")
    adapter.submit_prompt("s-wait", "running")
    assert FakeHarness.run_started.wait(timeout=1.0)
    record = adapter._get("s-wait")
    run = record.active_run
    run.started_at = 0
    run.last_runtime_activity_at = 10
    adapter._emit_wait_notice(record, run, now=59)
    assert not any(e["kind"] == "session.waiting" for e in record.history)
    adapter._emit_wait_notice(record, run, now=60)
    adapter._emit_wait_notice(record, run, now=61)
    notices = [e for e in record.history if e["kind"] == "session.waiting"]
    assert len(notices) == 1
    assert notices[0]["payload"] == {"run_id": run.run_id, "elapsed_seconds": 60, "last_activity_seconds": 50}
    assert run.last_runtime_activity_at == 10
    adapter.cancel_session("s-wait", "hard")
    adapter._emit_wait_notice(record, run, now=120)
    assert len([e for e in record.history if e["kind"] == "session.waiting"]) == 1


def test_total_run_wall_clock_is_a_final_ceiling(adapter: RuntimeAdapter) -> None:
    adapter.create_session("s-run-limit", "t-run-limit")
    adapter.submit_prompt("s-run-limit", "running")
    assert FakeHarness.run_started.wait(timeout=1.0)
    record = adapter._get("s-run-limit")
    run = record.active_run
    assert run is not None
    run.started_at = 10.0
    run.last_runtime_activity_at = 3_610.0
    run.active_subagent_calls["delegate-call"] = 3_610.0

    assert adapter._enforce_run_guards(record, run, now=3_611.0) is True

    wait_for_status(adapter, "s-run-limit", SessionStatus.FAILED)
    assert record.history[-1]["payload"] == {
        "code": "runtime-run-timeout",
        "retryable": True,
        "run_id": run.run_id,
    }


def test_delegate_notifications_track_subagent_lifetime_without_exposing_raw_names(
    adapter: RuntimeAdapter, monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter.create_session("s-child-events", "t-child-events")
    adapter.submit_prompt("s-child-events", "running")
    assert FakeHarness.run_started.wait(timeout=1.0)
    record = adapter._get("s-child-events")
    run = record.active_run
    assert run is not None
    run.last_runtime_activity_at = 10.0
    monkeypatch.setattr(runtime_module.time, "monotonic", lambda: 42.0)

    adapter._on_notification(record, Notification(
        method="session.event",
        payload={
            "sessionId": record.runtime_session_id,
            "event": {"type": "tool/call", "data": {
                "callId": "delegate-1", "name": "byq_delegate_backtest_analysis",
            }},
        },
    ))
    assert set(run.active_subagent_calls) == {"delegate-1"}
    assert run.active_subagent_calls["delegate-1"] == 42.0
    assert run.last_runtime_activity_at == 42.0

    monkeypatch.setattr(runtime_module.time, "monotonic", lambda: 43.0)
    adapter._on_notification(record, Notification(
        method="session.event",
        payload={
            "sessionId": record.runtime_session_id,
            "event": {"type": "tool/result", "data": {"message": {"content": [{
                "type": "tool-result", "toolCallId": "delegate-1", "content": [],
            }]}}},
        },
    ))
    assert run.active_subagent_calls == {}
    assert run.last_runtime_activity_at == 43.0
    assert "byq_delegate_backtest_analysis" not in str(record.history)
    adapter.cancel_session("s-child-events", "hard")


def test_session_creation_can_continue_a_durable_trace_sequence(adapter: RuntimeAdapter) -> None:
    created = adapter.create_session("s-sequence", "t-sequence", initial_sequence=41)

    record = adapter._get("s-sequence")
    assert created["status"] == SessionStatus.READY
    assert record.history[0]["sequence"] == 42
    assert record.sequence == 42
    assert record.runtime_session_id.startswith("resume-")
    adapter.release_session("s-sequence")


def test_recreated_runtime_uses_private_generation_and_bounded_public_context(
    adapter: RuntimeAdapter,
) -> None:
    FakeHarness.allow_run.set()
    adapter.create_session(
        "s-durable",
        "t-durable",
        initial_sequence=9,
        conversation_context=[
            {"role": "user", "content": "第一轮问题"},
            {"role": "assistant", "content": "第一轮回答"},
        ],
    )

    record = adapter._get("s-durable")
    assert record.runtime_session_id.startswith("resume-")
    assert record.runtime_session_id != record.session_id
    adapter.submit_prompt("s-durable", "第二轮追问")
    wait_for_status(adapter, "s-durable", SessionStatus.IDLE)

    harness = FakeHarness.instances[0]
    assert harness.session_id == record.runtime_session_id
    assert '"role":"user","content":"第一轮问题"' in harness.last_content
    assert '"role":"assistant","content":"第一轮回答"' in harness.last_content
    assert "[CURRENT_USER_MESSAGE]\n第二轮追问" in harness.last_content
    assert record.pending_conversation_context == []
    adapter.release_session("s-durable")


def test_recovery_reaches_fresh_runtime_once(adapter: RuntimeAdapter) -> None:
    FakeHarness.allow_run.set()
    subject = "沪深300近三年周频双均线，凯利仓位"
    recovery = {
        "schema_version": "conversation-recovery.v2", "session_id": "s-recovery",
        "trace_id": "t-recovery", "status": "resolved",
        "unanswered_turn": {"message_id": "m-original", "content": subject},
        "failure": {"sequence": 9, "run_id": "run-original", "code": "runtime-subagent-timeout"},
    }
    adapter.create_session("s-recovery", "t-recovery", initial_sequence=9, conversation_recovery=recovery)
    adapter.submit_prompt("s-recovery", subject)
    wait_for_status(adapter, "s-recovery", SessionStatus.IDLE)
    assert FakeHarness.instances[0].last_content.count(subject) == 1
    assert "runtime-subagent-timeout" in FakeHarness.instances[0].last_content
    assert adapter._get("s-recovery").pending_conversation_recovery is None
    adapter.release_session("s-recovery")


def test_ambiguous_recovery_does_not_start_run(adapter: RuntimeAdapter) -> None:
    recovery = {
        "schema_version": "conversation-recovery.v2", "session_id": "s-ambiguous",
        "trace_id": "t-ambiguous", "status": "needs_confirmation", "unanswered_turn": None,
        "failure": {"sequence": 9, "run_id": None, "code": "unknown"},
    }
    adapter.create_session("s-ambiguous", "t-ambiguous", initial_sequence=9, conversation_recovery=recovery)
    with pytest.raises(ValueError, match="请明确"):
        adapter.submit_prompt("s-ambiguous", "继续")
    assert FakeHarness.instances[0].run_count == 0
    assert adapter._get("s-ambiguous").pending_conversation_recovery == recovery
    adapter.release_session("s-ambiguous")


def test_conversation_context_rejects_private_or_unbounded_shapes(adapter: RuntimeAdapter) -> None:
    with pytest.raises(ValueError, match="field set"):
        adapter.create_session(
            "s-private", "t-private", initial_sequence=1,
            conversation_context=[{"role": "user", "content": "问题", "raw_dsh": "no"}],
        )
    with pytest.raises(ValueError, match="character limit"):
        adapter.create_session(
            "s-large", "t-large", initial_sequence=1,
            conversation_context=[{"role": "assistant", "content": "x" * 6_001}],
        )


def test_resume_is_idempotent_after_runtime_recreation(adapter: RuntimeAdapter) -> None:
    adapter.create_session("s-ready", "t-ready", initial_sequence=7)

    resumed = adapter.resume_session("s-ready")

    assert resumed["status"] == SessionStatus.READY
    assert resumed["resumed_from_run_id"] is None
    assert len(FakeHarness.instances) == 1
    adapter.release_session("s-ready")


def test_hard_cancel_resume_uses_a_new_owned_runtime(adapter: RuntimeAdapter) -> None:
    adapter.create_session("s-1", "t-1")
    adapter.submit_prompt("s-1", "running")
    assert FakeHarness.run_started.wait(timeout=1.0)

    adapter.cancel_session("s-1", "hard")
    resumed = adapter.resume_session("s-1")

    assert resumed["status"] == SessionStatus.READY
    assert resumed["resumed_from_run_id"]
    assert len(FakeHarness.instances) == 2
    assert FakeHarness.instances[0].closed is True
    record = adapter._get("s-1")
    assert record.runtime_session_id != "s-1"
    old_generation = FakeHarness.instances[0].config.env["BYQ_DSH_RUN_ID"]
    new_generation = FakeHarness.instances[1].config.env["BYQ_DSH_RUN_ID"]
    assert old_generation != new_generation
    assert new_generation != record.runtime_session_id
    adapter.release_session("s-1")


def test_resume_private_id_remains_valid_for_maximum_public_id(adapter: RuntimeAdapter) -> None:
    public_session_id = "s" * MAX_IDENTIFIER_LENGTH
    adapter.create_session(public_session_id, "t-1")
    adapter.submit_prompt(public_session_id, "running")
    assert FakeHarness.run_started.wait(timeout=1.0)

    adapter.cancel_session(public_session_id, "hard")
    resumed = adapter.resume_session(public_session_id)

    record = adapter._get(public_session_id)
    assert resumed["status"] == SessionStatus.READY
    assert len(record.runtime_session_id) <= MAX_IDENTIFIER_LENGTH
    assert record.runtime_session_id != public_session_id
    adapter.release_session(public_session_id)


def test_error_finish_reason_is_failed_and_can_resume_with_fresh_runtime(adapter: RuntimeAdapter) -> None:
    FakeHarness.finish_reason = "error"
    FakeHarness.allow_run.set()
    adapter.create_session("s-1", "t-1")
    run_id = adapter.submit_prompt("s-1", "fails")
    wait_for_status(adapter, "s-1", SessionStatus.FAILED)

    record = adapter._get("s-1")
    assert record.history[-1]["kind"] == "session.failed"
    assert record.history[-1]["payload"] == {
        "code": "model-run-failed",
        "retryable": True,
        "run_id": run_id,
    }
    assert "error" not in str(record.history[-1]["payload"]).lower()

    previous_runtime_session_id = record.runtime_session_id
    resumed = adapter.resume_session("s-1")
    assert resumed["status"] == SessionStatus.READY
    assert record.runtime_session_id != previous_runtime_session_id
    assert FakeHarness.instances[0].closed is True
    adapter.release_session("s-1")


def test_product_turn_requires_a_model_credential_without_exposing_it(adapter: RuntimeAdapter) -> None:
    adapter.create_session("s-1", "t-1")
    with pytest.raises(ModelCredentialUnavailable):
        adapter.submit_prompt("s-1", "product turn", require_model_key=True)
    assert "DEEPSEEK_API_KEY" not in str(adapter.readiness())
    assert "DEEPSEEK_API_KEY" not in str(adapter.describe_session(adapter._get("s-1")))
    adapter.release_session("s-1")


def test_existing_prompt_receipt_precedes_missing_credential_rejection(adapter: RuntimeAdapter):
    adapter.create_session("s-1", "t-1")
    record = adapter._get("s-1")
    record.prompt_idempotency["message_original"] = ("synthetic original", "original-run")
    assert adapter.submit_prompt("s-1", "synthetic original", require_model_key=True,
                                 idempotency_key="message_original") == "original-run"
    with pytest.raises(SessionConflict):
        adapter.submit_prompt("s-1", "different content", require_model_key=True,
                              idempotency_key="message_original")
    adapter.release_session("s-1")


def test_operations_snapshot_normalizes_and_deduplicates_dsh_usage(adapter: RuntimeAdapter) -> None:
    adapter.create_session("s-1", "t-1")
    record = adapter._get("s-1")
    notification = Notification(
        method="session.event",
        payload={
            "sessionId": "s-1",
            "event": {
                "type": "assistant/message",
                "data": {
                    "message": {"id": "message-usage-1", "content": []},
                    "usage": {
                        "inputTokens": 100,
                        "outputTokens": 20,
                        "cacheReadTokens": 30,
                        "cacheWriteTokens": 5,
                        "reasoningTokens": 10,
                    },
                    "private": {"apiKey": "must-not-escape"},
                },
            },
        },
    )
    adapter._on_notification(record, notification)
    adapter._on_notification(record, notification)

    snapshot = adapter.operations_snapshot()
    assert snapshot["usage"] == {
        "input_tokens": 100,
        "output_tokens": 20,
        "cache_read_tokens": 30,
        "cache_write_tokens": 5,
        "reasoning_tokens": 10,
        "model_calls": 1,
        "total_tokens": 155,
        "scope": "adapter_process_lifetime",
        "source": "normalized_dsh_token_usage",
    }
    assert snapshot["raw_dsh_events"] is False
    assert "must-not-escape" not in str(snapshot)
    adapter.release_session("s-1")


def test_invalid_usage_is_dropped_atomically(adapter: RuntimeAdapter) -> None:
    adapter.create_session("s-1", "t-1")
    record = adapter._get("s-1")
    adapter._on_notification(record, Notification(
        method="session.event",
        payload={
            "sessionId": "s-1",
            "event": {
                "type": "assistant/message",
                "data": {
                    "message": {"id": "message-usage-invalid", "content": []},
                    "usage": {"inputTokens": -1, "outputTokens": 2},
                },
            },
        },
    ))
    assert adapter.operations_snapshot()["usage"]["model_calls"] == 0
    adapter.release_session("s-1")


def test_configured_model_credential_is_scoped_to_the_owned_sdk_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    FakeHarness.reset()
    monkeypatch.setenv("BYQ_DSH_RUNTIME_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("BYQ_DSH_COMPOSITION", str(tmp_path / "composition.yml"))
    monkeypatch.setenv("DSH_SESSION_ROOT", str(tmp_path / "sessions"))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-provider-secret")

    adapter = RuntimeAdapter(release_compatibility(tmp_path))
    adapter.create_session("s-1", "t-1")
    sdk_environment = FakeHarness.instances[0].config.env
    assert sdk_environment["DEEPSEEK_API_KEY"] == "test-provider-secret"
    assert "test-provider-secret" not in str(adapter.readiness())
    assert "test-provider-secret" not in str(adapter.describe_session(adapter._get("s-1")))
    adapter.release_session("s-1")


def test_personal_model_binding_is_resolved_directly_without_public_exposure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    FakeHarness.reset()
    monkeypatch.setenv("BYQ_DSH_RUNTIME_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("BYQ_DSH_COMPOSITION", str(tmp_path / "composition.yml"))
    monkeypatch.setenv("DSH_SESSION_ROOT", str(tmp_path / "sessions"))
    monkeypatch.setenv("BYQ_BACKEND_URL", "http://backend.test")
    monkeypatch.setenv("BYQ_CREDENTIAL_RESOLVER_TOKEN", "resolver-test-only")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "system-fallback-must-not-win")
    captured: dict[str, object] = {}

    class Response:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "resolution": {
                    "source": "user_binding",
                    "provider": "deepseek-official",
                    "model": "deepseek-reasoner",
                    "api_key": "personal-provider-secret",
                }
            }

    def post(url: str, **kwargs: object) -> Response:
        captured["url"] = url
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr(runtime_module.httpx, "post", post)
    adapter = RuntimeAdapter(release_compatibility(tmp_path))
    adapter.create_session("s-1", "t-1", "alice")

    assert captured["url"] == "http://backend.test/internal/credentials/model-resolution"
    assert captured["headers"] == {"x-byq-credential-resolver-token": "resolver-test-only"}
    assert captured["json"]["owner_principal"] == "alice"
    config = FakeHarness.instances[0].config
    assert config.provider == "deepseek-official"
    assert config.model == "deepseek-reasoner"
    assert config.env["DEEPSEEK_API_KEY"] == "personal-provider-secret"
    assert "personal-provider-secret" not in str(adapter.readiness())
    assert "personal-provider-secret" not in str(adapter.describe_session(adapter._get("s-1")))
    adapter.release_session("s-1")


@pytest.mark.parametrize("provider", [
    "opencode-go-responses",
    "opencode-go-chat",
    "opencode-go-messages",
    "opencode-zen-responses",
    "opencode-zen-chat",
    "opencode-zen-messages",
])
def test_opencode_personal_key_is_scoped_to_each_reviewed_runtime_route(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    provider: str,
) -> None:
    FakeHarness.reset()
    monkeypatch.setenv("BYQ_DSH_RUNTIME_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("BYQ_DSH_COMPOSITION", str(tmp_path / "composition.yml"))
    monkeypatch.setenv("DSH_SESSION_ROOT", str(tmp_path / "sessions"))
    adapter = RuntimeAdapter(release_compatibility(tmp_path))
    harness = adapter._build_harness(
        "s-1",
        tmp_path / "sessions" / "s-1",
        trace_id="t-1",
        owner_principal="alice",
        workspace_id="workspace_alice",
        runtime_generation="generation-provider-test",
        model_resolution={
            "provider": provider,
            "model": "catalog-model",
            "api_key": "opencode-personal-secret",
        },
    )

    assert harness.config.provider == provider
    assert harness.config.env["OPENCODE_API_KEY"] == "opencode-personal-secret"
    routing_id = harness.config.env["BYQ_PROVIDER_SESSION_ID"]
    assert len(routing_id) == 36
    assert "alice" not in routing_id and "s-1" not in routing_id
    for session, generation, same in (("s-1", "generation-next-root", True), ("s-2", "generation-other", False)):
        other = adapter._build_harness(session, tmp_path / "sessions" / session,
            trace_id="t-other", owner_principal="alice", workspace_id="workspace_alice",
            runtime_generation=generation,
            model_resolution={"provider": provider, "model": "catalog-model", "api_key": "synthetic"})
        assert (other.config.env["BYQ_PROVIDER_SESSION_ID"] == routing_id) is same
    assert "DEEPSEEK_API_KEY" not in harness.config.env
    assert "opencode-personal-secret" not in str(adapter.readiness())


def test_unreviewed_runtime_provider_cannot_receive_a_personal_key(
    adapter: RuntimeAdapter,
    tmp_path: Path,
) -> None:
    with pytest.raises(ModelCredentialUnavailable, match="provider is unavailable"):
        adapter._build_harness(
            "s-1",
            tmp_path / "sessions" / "s-1",
            trace_id="t-1",
            owner_principal="alice",
            workspace_id="workspace_alice",
            runtime_generation="generation-provider-test",
            model_resolution={
                "provider": "browser-controlled-provider",
                "model": "arbitrary-model",
                "api_key": "must-not-enter-child-env",
            },
        )


def test_broken_personal_resolution_never_falls_back_to_system_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    FakeHarness.reset()
    monkeypatch.setenv("BYQ_DSH_RUNTIME_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("BYQ_DSH_COMPOSITION", str(tmp_path / "composition.yml"))
    monkeypatch.setenv("DSH_SESSION_ROOT", str(tmp_path / "sessions"))
    monkeypatch.setenv("BYQ_CREDENTIAL_RESOLVER_TOKEN", "resolver-test-only")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "system-fallback-must-not-win")

    class Response:
        status_code = 409

        def raise_for_status(self) -> None:
            raise runtime_module.httpx.HTTPStatusError(
                "conflict",
                request=runtime_module.httpx.Request("POST", "http://backend"),
                response=runtime_module.httpx.Response(409),
            )

    monkeypatch.setattr(runtime_module.httpx, "post", lambda *args, **kwargs: Response())
    adapter = RuntimeAdapter(release_compatibility(tmp_path))
    with pytest.raises(ModelCredentialUnavailable):
        adapter.create_session("s-1", "t-1", "alice")
    assert FakeHarness.instances == []


def test_product_context_is_scoped_to_the_owned_sdk_environment(adapter: RuntimeAdapter) -> None:
    adapter.create_session("s-1", "t-1", "alice", "workspace_alice")
    sdk_environment = FakeHarness.instances[0].config.env
    assert sdk_environment["BYQ_WORKSPACE_ID"] == "workspace_alice"
    assert sdk_environment["BYQ_OWNER_PRINCIPAL"] == "alice"
    assert sdk_environment["BYQ_ACTOR_PRINCIPAL"] == "byq-product-agent-s-1"
    assert sdk_environment["BYQ_TRACE_ID"] == "t-1"
    assert sdk_environment["BYQ_SESSION_ID"] == "s-1"
    assert sdk_environment["BYQ_DSH_RUN_ID"].startswith("generation-")
    assert sdk_environment["BYQ_DSH_RUN_ID"] not in str(adapter.describe_session(adapter._get("s-1")))
    adapter.release_session("s-1")


def test_soft_cancel_is_scoped_to_current_run_and_returns_to_idle(adapter: RuntimeAdapter) -> None:
    adapter.create_session("s-1", "t-1")
    adapter.submit_prompt("s-1", "first")
    assert FakeHarness.run_started.wait(timeout=1.0)
    assert adapter.cancel_session("s-1", "soft")["status"] == SessionStatus.CANCELLING
    with pytest.raises(SessionConflict):
        adapter.submit_prompt("s-1", "while-cancelling")

    FakeHarness.allow_run.set()
    wait_for_status(adapter, "s-1", SessionStatus.IDLE)
    FakeHarness.run_started.clear()
    FakeHarness.allow_run.clear()
    second_run = adapter.submit_prompt("s-1", "second")
    assert second_run
    assert FakeHarness.run_started.wait(timeout=1.0)
    assert FakeHarness.instances[0].run_count == 2
    FakeHarness.allow_run.set()
    wait_for_status(adapter, "s-1", SessionStatus.IDLE)
    adapter.release_session("s-1")


@pytest.mark.parametrize(
    "value",
    ["../escape", "/absolute", "", "a" * (MAX_IDENTIFIER_LENGTH + 1), "has space", "ümlaut"],
)
def test_session_and_trace_identifiers_are_controlled(adapter: RuntimeAdapter, value: str) -> None:
    with pytest.raises(ValueError):
        adapter.create_session(value, "trace-ok")
    with pytest.raises(ValueError):
        adapter.create_session("session-ok", value)


def test_workflow_trace_sequence_and_publish_order_are_atomic(adapter: RuntimeAdapter) -> None:
    adapter.create_session("s-1", "t-1")
    record = adapter._get("s-1")
    subscriber = adapter.subscribe("s-1")
    assert record.sequence == 1

    barrier = threading.Barrier(33)

    def emit(index: int) -> None:
        barrier.wait()
        if index % 2:
            adapter._on_notification(
                record,
                Notification(
                    method="session.status",
                    payload={"sessionId": "s-1", "status": "idle"},
                ),
            )
        else:
            adapter._emit(record, "session.result", "runtime-adapter", {"index": index})

    workers = [threading.Thread(target=emit, args=(index,)) for index in range(32)]
    for worker in workers:
        worker.start()
    barrier.wait()
    for worker in workers:
        worker.join(timeout=1.0)

    events = [subscriber.get(timeout=1.0) for _ in workers]
    sequences = [event["sequence"] for event in events]
    assert sequences == list(range(2, 34))
    assert len(set(sequences)) == len(sequences)
    adapter.release_session("s-1")
