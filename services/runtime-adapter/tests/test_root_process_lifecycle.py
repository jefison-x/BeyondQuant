import hashlib
import json
import threading
from importlib.metadata import version
from types import SimpleNamespace

import pytest
from deepseek_harness import Notification

from app.runtime import RuntimeAdapter, SessionConflict, SessionStatus
from .test_process_cleanup import adapter, FakeHarness, wait_for_status


@pytest.fixture
def root_adapter(adapter, monkeypatch, tmp_path):
    composition = "X-BYQ-Root-Run-ID: !!js process.env.BYQ_ROOT_RUN_ID\n"
    profile = tmp_path / "root-profile.yml"
    profile.write_text(composition)
    identity = tmp_path / "root-identity.json"
    identity.write_text(json.dumps({"root_identity_contract": "byq-root-process.v1",
        "composition_hash": "sha256:" + hashlib.sha256(composition.encode()).hexdigest()}))
    monkeypatch.setenv("BYQ_DSH_PROCESS_OWNERSHIP", "root-turn")
    monkeypatch.setenv("BYQ_DSH_COMPOSITION", str(profile))
    monkeypatch.setenv("BYQ_DSH_COMPOSITION_IDENTITY", str(identity))
    runtime = RuntimeAdapter(adapter._compatibility)
    yield runtime
    runtime.close()


def test_three_roots_have_distinct_processes_with_stable_public_identity(root_adapter):
    runtime = root_adapter
    runtime.create_session("three-roots", "stable-trace", "alice", "workspace_alice")
    FakeHarness.allow_run.set()
    roots, generations, private_sessions = [], [], []
    for index in range(3):
        root = runtime.submit_prompt("three-roots", f"合成研究第{index}轮",
            conversation_context=[{"role": "user", "content": "沪深300近三年每周调仓"}])
        wait_for_status(runtime, "three-roots", SessionStatus.IDLE)
        record = runtime._get("three-roots")
        harness = FakeHarness.instances[index]
        assert harness.closed and harness.run_count == 1
        assert harness.config.env["BYQ_ROOT_RUN_ID"] == root
        assert "沪深300近三年每周调仓" in harness.last_content
        assert record.session_id == "three-roots" and record.trace_id == "stable-trace"
        roots.append(root)
        generations.append(record.runtime_generation)
        private_sessions.append(record.runtime_session_id)
        runtime.acknowledge_terminal("three-roots", record.terminal_receipts[root])
    assert len(set(roots)) == len(set(generations)) == len(set(private_sessions)) == 3
    assert runtime.readiness()["process_ownership"] == "one-per-root-turn"


def test_next_product_root_requires_fresh_context_and_exact_ack(root_adapter):
    runtime = root_adapter
    runtime.create_session("root-context", "root-trace", "alice", "workspace_alice")
    first = runtime.submit_prompt("root-context", "first", idempotency_key="original-root-key")
    FakeHarness.allow_run.set()
    wait_for_status(runtime, "root-context", SessionStatus.IDLE)
    with pytest.raises(SessionConflict, match="cleanup"):
        runtime.submit_prompt("root-context", "second", conversation_context=[])
    record = runtime._get("root-context")
    runtime.acknowledge_terminal("root-context", record.terminal_receipts[first])
    with pytest.raises(SessionConflict, match="fresh public"):
        runtime.submit_prompt("root-context", "second")
    assert runtime.submit_prompt("root-context", "first", idempotency_key="original-root-key") == first
    assert len(FakeHarness.instances) == 1
    runtime.submit_prompt("root-context", "second", conversation_context=[])
    wait_for_status(runtime, "root-context", SessionStatus.IDLE)
    assert len(FakeHarness.instances) == 2


def test_root_mode_rejects_mismatched_profile(root_adapter, monkeypatch, tmp_path):
    path = tmp_path / "wrong-identity.json"
    path.write_text(json.dumps({"root_identity_contract": "byq-root-process.v1", "composition_hash": "sha256:" + "0" * 64}))
    monkeypatch.setenv("BYQ_DSH_COMPOSITION_IDENTITY", str(path))
    with pytest.raises(ValueError, match="independent verified"):
        RuntimeAdapter(root_adapter._compatibility)


def test_domain_observation_is_durable_private_and_exactly_root_scoped(root_adapter):
    if version("deepseek-harness-sdk") != "0.1.2rc1":
        pytest.skip("domain observations are qualified on the pinned 0.1.2 carrier")
    runtime = root_adapter
    context = {"session_id": "private-calls", "trace_id": "private-trace", "owner": "alice", "workspace_id": "workspace_alice"}
    runtime.create_session(context["session_id"], context["trace_id"], context["owner"], context["workspace_id"])
    root = runtime.submit_prompt(context["session_id"], "synthetic private call")
    assert FakeHarness.run_started.wait(1)
    record = runtime._get(context["session_id"])
    run = record.active_run
    arguments = {"task_id": "private-task", "agent_run_id": "private-agent", "idempotency_key": "private-key",
                 "strategy": {"script": "private-synthetic-source"}}
    notice = Notification(method="session.event", payload={"sessionId": record.runtime_session_id,
        "event": {"type": "tool/call", "seq": 1, "data": {"callId": "synthetic-call", "name": "mcp__byq__byq_strategy_validate",
            "arguments": json.dumps(arguments)}}})
    for _ in range(2):
        runtime._on_notification(record, notice, source_run=run, source_runtime_session_id=record.runtime_session_id)
    page = runtime.domain_call_evidence(context)
    assert len(page["events"]) == 1
    evidence = page["events"][0]
    assert evidence["root_run_id"] == root
    assert evidence["generation"] == record.runtime_generation
    assert runtime.domain_call_evidence(context, 1)["events"] == []
    for field in ("owner", "workspace_id", "trace_id"):
        with pytest.raises(ValueError):
            runtime.domain_call_evidence({**context, field: "foreign"})
    public = json.dumps([record.history, runtime.describe_session(record)])
    for private in ("private-synthetic-source", "private-key", evidence["request_sha256"], evidence["input_sha256"]):
        assert private not in public
    assert "private-synthetic-source" not in record.journal.path.read_text()
    runtime.cancel_session(context["session_id"], "hard")
    runtime._on_notification(record, notice, source_run=run, source_runtime_session_id=record.runtime_session_id)
    assert runtime.domain_call_evidence(context) == {**page, "idle": True}
    runtime.release_session(context["session_id"])
    count = len(FakeHarness.instances)
    assert runtime.domain_call_evidence(context) == {**page, "idle": True}
    assert len(FakeHarness.instances) == count


def test_unproven_call_stops_only_its_owned_root(root_adapter, monkeypatch):
    if version("deepseek-harness-sdk") != "0.1.2rc1":
        pytest.skip("closed admission stop qualified on 0.1.2 only")
    runtime = root_adapter
    # Each process needs its own completion signal: the ordinary single-session
    # fixture's class-wide Event makes closing Alice also finish Bob spuriously.
    gates = {}

    def run(harness, content, *, on_notification):
        harness.run_count += 1
        assert gates[harness].wait(3)
        return SimpleNamespace(finish_reason="completed")

    def close(harness):
        harness.closed = True
        gates[harness].set()

    monkeypatch.setattr(FakeHarness, "run", run)
    monkeypatch.setattr(FakeHarness, "close", close)
    for owner in ("alice", "bob"):
        runtime.create_session(owner, "trace-" + owner, owner, "workspace_" + owner)
        gates[runtime._get(owner).harness] = threading.Event()
        runtime.submit_prompt(owner, "synthetic separate owner")
    alice, bob = runtime._get("alice"), runtime._get("bob")
    old_run, bob_run = alice.active_run, bob.active_run
    notice = Notification(method="session.event", payload={"sessionId": alice.runtime_session_id,
        "event": {"type": "tool/call", "seq": 1, "data": {"callId": "missing-reference", "name": "mcp__byq__byq_strategy_validate",
            "arguments": json.dumps({"task_id": "unproven", "strategy": {}})}}})
    runtime._on_notification(alice, notice, source_run=old_run, source_runtime_session_id=alice.runtime_session_id)
    wait_for_status(runtime, "alice", SessionStatus.FAILED)
    assert bob.active_run is bob_run and bob.status == SessionStatus.RUNNING
    assert not FakeHarness.instances[1].closed
    assert alice.journal.state["calls"] == []  # Missing references never create fabricated evidence.
    gates[bob.harness].set()
    wait_for_status(runtime, "bob", SessionStatus.IDLE)
    assert not any(event["payload"].get("code") == "domain-call-reference-unproven" for event in bob.history)


@pytest.mark.parametrize("change", [
    {"stop": False}, {"reason": "arbitrary"}, {"schema_version": "unknown"}, {"request_sha256": "private"},
])
def test_stop_marker_is_closed_and_not_a_generic_error_instruction(change):
    marker = {"schema_version": "domain-call-admission.v1", "state": "blocked",
              "reason": "correction_budget_exhausted", "stop": True}
    assert not RuntimeAdapter._domain_stop_result({"service": "beyondquant-mcp", "status": "error",
        "backend": {"admission": {**marker, **change}}})
