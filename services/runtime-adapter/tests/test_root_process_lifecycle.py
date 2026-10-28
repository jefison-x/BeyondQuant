import hashlib
import json
import threading
from types import SimpleNamespace

import pytest

from packages.contracts.domain_call_admission import call_evidence_receipt, request_evidence
from app.compat.types import RuntimeObservation, RuntimeToolResult
from app.runtime import RuntimeAdapter, SessionConflict, SessionStatus
from .test_process_cleanup import adapter, FakeHarness, wait_for_status
from .runtime_test_support import NotificationDTO as Notification


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


def test_terminal_ack_during_release_cannot_reap_before_finalization(root_adapter):
    runtime = root_adapter
    runtime.create_session("release-race", "release-trace", "alice", "workspace_alice")
    root = runtime.submit_prompt("release-race", "first")
    FakeHarness.allow_run.set()
    wait_for_status(runtime, "release-race", SessionStatus.IDLE)
    record = runtime._get("release-race")
    # Exercise the state between release marking CLOSED and finalizing its
    # subscriber/process cleanup; an ACK must not reap in that interval.
    with record.lock:
        record.status = SessionStatus.CLOSED
    runtime.acknowledge_terminal("release-race", record.terminal_receipts[root])
    assert runtime._get("release-race") is record
    with record.lock:
        record.status = SessionStatus.IDLE
    runtime.release_session("release-race")
    assert record.release_finalized
    with pytest.raises(KeyError):
        runtime._get("release-race")


def test_root_mode_rejects_mismatched_profile(root_adapter, monkeypatch, tmp_path):
    path = tmp_path / "wrong-identity.json"
    path.write_text(json.dumps({"root_identity_contract": "byq-root-process.v1", "composition_hash": "sha256:" + "0" * 64}))
    monkeypatch.setenv("BYQ_DSH_COMPOSITION_IDENTITY", str(path))
    with pytest.raises(ValueError, match="independent verified"):
        RuntimeAdapter(root_adapter._compatibility)


def test_fake_legacy_callback_evidence_is_private_and_exactly_root_scoped(root_adapter, monkeypatch):
    runtime = root_adapter
    # This exercises RuntimeAdapter's legacy callback/evidence contract with
    # the local structural test double. It does not qualify a DSH SDK carrier.
    assert runtime._compatibility.family == "test-runtime-observation.v1"
    assert runtime._root_scoped and not runtime._acp
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
    second_arguments = {**arguments, "idempotency_key": "private-key-2"}
    second_notice = Notification(method="session.event", payload={"sessionId": record.runtime_session_id,
        "event": {"type": "tool/call", "seq": 2, "data": {"callId": "synthetic-call-2", "name": "mcp__byq__byq_strategy_validate",
            "arguments": json.dumps(second_arguments)}}})
    runtime._on_notification(record, second_notice, source_run=run,
                             source_runtime_session_id=record.runtime_session_id)
    assert len(record.domain_call_evidence) == 2
    evidence = record.domain_call_evidence[0]
    second_evidence = record.domain_call_evidence[1]
    assert evidence["root_run_id"] == root
    assert evidence["generation"] == record.runtime_generation
    public = json.dumps([record.history, runtime.describe_session(record)])
    for private in ("private-synthetic-source", "private-key", evidence["request_sha256"], evidence["input_sha256"]):
        assert private not in public
    runtime.cancel_session(context["session_id"], "hard")
    runtime._on_notification(record, notice, source_run=run, source_runtime_session_id=record.runtime_session_id)
    runtime.release_session(context["session_id"])
    count = len(FakeHarness.instances)
    assert runtime._get(context["session_id"]) is record  # Unacknowledged terminal/private evidence pins it.
    page = runtime.domain_call_evidence(context)
    assert page == {"schema_version": "domain-call-page.v1", "events": record.domain_call_evidence,
                    "more": False, "idle": True}
    assert runtime.domain_call_evidence(context, 1)["events"] == [second_evidence]
    assert record.domain_call_drained_sequence == 0
    for field in ("owner", "workspace_id", "trace_id"):
        with pytest.raises(ValueError):
            runtime.domain_call_evidence({**context, field: "foreign"})
    receipt = record.terminal_receipts[root]
    runtime.acknowledge_terminal(context["session_id"], receipt)
    assert runtime._get(context["session_id"]) is record  # Terminal ACK cannot replace Backend call receipts.

    from fastapi.testclient import TestClient
    from app import main
    monkeypatch.setattr(main, "adapter", runtime)
    client = TestClient(main.app)
    ack_path = f"/internal/runtime/sessions/{context['session_id']}/domain-call-receipt"
    row_receipt = call_evidence_receipt(evidence)
    wrong_receipt = {**row_receipt, "event_sha256": ("0" if row_receipt["event_sha256"][0] != "0" else "1")
                     + row_receipt["event_sha256"][1:]}
    payload = {"trace_id": context["trace_id"], "owner": context["owner"],
               "workspace_id": context["workspace_id"], "receipt": wrong_receipt}
    assert client.post(ack_path, json=payload).status_code == 409
    assert record.domain_call_drained_sequence == 0
    assert runtime._get(context["session_id"]) is record
    assert client.post(ack_path, json={**payload, "receipt": row_receipt, "extra": True}).status_code == 422
    accepted = client.post(ack_path, json={**payload, "receipt": row_receipt})
    assert accepted.status_code == 200
    assert accepted.json() == {"receipt": row_receipt}
    assert record.domain_call_drained_sequence == 1
    assert record.domain_call_sequence == 2
    # A later unacknowledged call keeps the released session available.
    assert runtime._get(context["session_id"]) is record
    assert runtime.acknowledge_domain_call_evidence(context, row_receipt) == {"receipt": row_receipt}
    second_receipt = call_evidence_receipt(second_evidence)
    second_payload = {**payload, "receipt": second_receipt}
    second_accepted = client.post(ack_path, json=second_payload)
    assert second_accepted.status_code == 200
    assert second_accepted.json() == {"receipt": second_receipt}
    assert record.domain_call_drained_sequence == record.domain_call_sequence == 2
    with pytest.raises(KeyError):
        runtime._get(context["session_id"])
    # Same-boot retries remain exact and idempotent after in-memory reaping.
    assert client.post(ack_path, json=second_payload).json() == {"receipt": second_receipt}
    assert runtime.acknowledge_domain_call_evidence(context, row_receipt) == {"receipt": row_receipt}
    assert client.post(ack_path, json={**payload, "receipt": wrong_receipt}).status_code == 409
    with pytest.raises(SessionConflict, match="context mismatch"):
        runtime.acknowledge_domain_call_evidence({**context, "trace_id": "foreign-trace"}, second_receipt)
    with pytest.raises(SessionConflict, match="not owned by this Adapter boot"):
        runtime.acknowledge_domain_call_evidence(context, {**second_receipt, "sequence": 3})
    assert len(FakeHarness.instances) == count


def test_unproven_call_stops_only_its_owned_root(root_adapter, monkeypatch):
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
    notice = RuntimeObservation(kind="tool.call", session_id=alice.runtime_session_id,
        root_session=True, runtime_activity=True, event_sequence=1, call_id="missing-reference",
        tool_name="mcp__byq__byq_strategy_validate",
        domain_arguments={"task_id": "unproven", "strategy": {}})
    runtime._on_notification(alice, notice, source_run=old_run, source_runtime_session_id=alice.runtime_session_id)
    wait_for_status(runtime, "alice", SessionStatus.FAILED)
    assert bob.active_run is bob_run and bob.status == SessionStatus.RUNNING
    assert not FakeHarness.instances[1].closed
    assert alice.domain_call_evidence == []  # Missing references never create fabricated evidence.
    gates[bob.harness].set()
    wait_for_status(runtime, "bob", SessionStatus.IDLE)
    assert not any(event["payload"].get("code") == "domain-call-reference-unproven" for event in bob.history)


@pytest.mark.parametrize("acp_callback", [False, True], ids=["legacy-session-cursor", "acp-no-second-cursor"])
def test_session_evidence_sequence_1025_on_next_root(root_adapter, acp_callback):
    runtime = root_adapter
    session_id = "session-evidence-1025-" + str(acp_callback)
    runtime.create_session(session_id, "evidence-trace", "alice", "workspace_alice")

    FakeHarness.allow_run.clear()
    FakeHarness.run_started.clear()
    first_root = runtime.submit_prompt(session_id, "close first synthetic root")
    assert FakeHarness.run_started.wait(1)
    record = runtime._get(session_id)
    first_run = record.active_run
    assert first_run is not None and first_run.run_id == first_root
    first_generation = record.runtime_generation
    history = []
    # These are contract-valid in-memory retained rows, not model calls or
    # claims that a Backend Job was created. Keep one task/action/input hash
    # and vary only the replay identity and event receipt fields.
    for sequence in range(1, 1025):
        arguments = {
            "task_id": "retained-history-task",
            "agent_run_id": "retained-history-agent",
            "idempotency_key": f"retained-history-{sequence}",
            "strategy": {"code": "VALID_SYNTHETIC_HISTORY"},
        }
        evidence = {
            "schema_version": "domain-call-observed.v1",
            "sequence": sequence,
            "root_run_id": first_root,
            "generation": first_generation,
            "call_id": f"retained-history-call-{sequence}",
            **request_evidence("byq_strategy_validate", arguments, trace_id=record.trace_id),
        }
        receipt = call_evidence_receipt(evidence)
        assert receipt["sequence"] == sequence and receipt["root_run_id"] == first_root
        if history:
            assert evidence["input_sha256"] == history[0]["input_sha256"]
        history.append(evidence)
    record.domain_call_evidence.extend(history)
    record.domain_call_sequence = record.domain_call_drained_sequence = 1024
    first_run.domain_calls.update(event["call_id"] for event in history)
    assert len(record.domain_call_evidence) == len(first_run.domain_calls) == 1024

    FakeHarness.allow_run.set()
    wait_for_status(runtime, session_id, SessionStatus.IDLE)
    record = runtime._get(session_id)
    assert record.domain_call_sequence == record.domain_call_drained_sequence == 1024
    runtime.acknowledge_terminal(session_id, record.terminal_receipts[first_root])

    FakeHarness.allow_run.clear()
    FakeHarness.run_started.clear()
    next_root = runtime.submit_prompt(session_id, "start next synthetic root", conversation_context=[])
    assert next_root != first_root
    assert FakeHarness.run_started.wait(1)
    record = runtime._get(session_id)
    run = record.active_run
    assert run is not None and run.run_id == next_root
    # The first root's 1024 already-drained rows remain session-wide; do not
    # manufacture a second Adapter cursor or mutate the retained prefix.
    assert len(record.domain_call_evidence) == 1024
    assert record.domain_call_sequence == record.domain_call_drained_sequence == 1024
    arguments = {"task_id": "private-task", "agent_run_id": "private-agent",
        "idempotency_key": "sequence-1025", "strategy": {"code": "VALID_SYNTHETIC"}}
    notice = RuntimeObservation(kind="tool.call", session_id=record.runtime_session_id,
        root_session=True, runtime_activity=True, event_sequence=1, call_id="sequence-1025-call",
        tool_name="mcp__byq__byq_strategy_validate", domain_arguments=arguments)

    # This callback-only switch exercises the existing ACP branch that leaves
    # evidence sequence ownership to Backend. FakeCompatibility is not ACP
    # process or profile qualification; its retained history prefix remains
    # internally consistent while the callback creates no Adapter cursor row.
    previous_acp_mode = runtime._acp
    try:
        runtime._acp = acp_callback
        runtime._on_notification(record, notice, source_run=run,
            source_runtime_session_id=record.runtime_session_id)
    finally:
        runtime._acp = previous_acp_mode
    evidence_context = {"session_id": record.session_id, "trace_id": record.trace_id,
        "owner": record.owner_principal, "workspace_id": record.workspace_id}
    if acp_callback:
        assert record.domain_call_sequence == 1024
        assert record.domain_call_drained_sequence == 1024
        assert len(record.domain_call_evidence) == 1024
        assert run.domain_stop_code is None and "sequence-1025-call" in run.domain_calls
    else:
        assert record.domain_call_sequence == 1025
        assert record.domain_call_drained_sequence == 1024
        assert record.domain_call_evidence[-1]["sequence"] == 1025
        assert record.domain_call_evidence[-1]["root_run_id"] == next_root
        assert run.domain_stop_code is None and "sequence-1025-call" in run.domain_calls
    FakeHarness.allow_run.set()
    wait_for_status(runtime, session_id, SessionStatus.IDLE)
    if not acp_callback:
        assert record.domain_call_sequence == 1025 and record.domain_call_drained_sequence == 1024
        page = runtime.domain_call_evidence(evidence_context, after_sequence=1024)
        assert page == {"schema_version": "domain-call-page.v1",
            "events": [record.domain_call_evidence[-1]], "more": False, "idle": True}
        row_receipt = call_evidence_receipt(page["events"][0])
        assert runtime.acknowledge_domain_call_evidence(evidence_context, row_receipt) == {"receipt": row_receipt}
        assert record.domain_call_drained_sequence == record.domain_call_sequence == 1025
    runtime.acknowledge_terminal(session_id, record.terminal_receipts[next_root])
    runtime.release_session(session_id)
    final_sequence = 1024 if acp_callback else 1025
    assert runtime.domain_call_evidence(evidence_context, after_sequence=final_sequence) == {
        "schema_version": "domain-call-page.v1", "events": [], "more": False, "idle": True,
    }


@pytest.mark.parametrize("acp_callback", [False, True], ids=["legacy-cursor", "acp-backend-cursor"])
def test_per_root_domain_call_1025th_call_is_not_rejected_by_retention_count(
    root_adapter, acp_callback, monkeypatch,
):
    runtime = root_adapter
    session_id = "per-root-domain-call-count-" + str(acp_callback)
    runtime.create_session(session_id, "per-root-domain-call-limit-trace", "alice", "workspace_alice")
    FakeHarness.allow_run.clear()
    FakeHarness.run_started.clear()
    root = runtime.submit_prompt(session_id, "exercise per-root call count boundary")
    assert FakeHarness.run_started.wait(1)
    record = runtime._get(session_id)
    run = record.active_run
    assert run is not None and run.run_id == root

    history = []
    for sequence in range(1, 1025):
        arguments = {"task_id": "retained-history-task", "agent_run_id": "retained-history-agent",
            "idempotency_key": f"retained-history-{sequence}",
            "strategy": {"code": "VALID_SYNTHETIC_HISTORY"}}
        event = {"schema_version": "domain-call-observed.v1", "sequence": sequence,
            "root_run_id": root, "generation": record.runtime_generation,
            "call_id": f"retained-call-{sequence}",
            **request_evidence("byq_strategy_validate", arguments, trace_id=record.trace_id)}
        history.append(event)
    record.domain_call_evidence.extend(history)
    record.domain_call_sequence = record.domain_call_drained_sequence = 1024
    run.domain_calls.update(event["call_id"] for event in history)
    assert len(run.domain_calls) == len(record.domain_call_evidence) == 1024

    arguments = {"task_id": "private-task", "agent_run_id": "private-agent",
        "idempotency_key": "beyond-per-root-count", "strategy": {"code": "VALID_SYNTHETIC"}}
    notice = RuntimeObservation(kind="tool.call", session_id=record.runtime_session_id,
        root_session=True, runtime_activity=True, event_sequence=1, call_id="new-call",
        tool_name="mcp__byq__byq_strategy_validate", domain_arguments=arguments)

    # This toggles only the local notification branch for a synthetic callback;
    # it is not a claim of ACP process/profile qualification.
    previous_acp_mode = runtime._acp
    try:
        runtime._acp = acp_callback
        runtime._on_notification(record, notice, source_run=run,
            source_runtime_session_id=record.runtime_session_id)
        assert run.domain_stop_code is None and not run.domain_stop_dispatched
        assert len(run.domain_calls) == 1025 and "new-call" in run.domain_calls
        if acp_callback:
            assert record.domain_call_sequence == record.domain_call_drained_sequence == 1024
            assert len(record.domain_call_evidence) == 1024
        else:
            assert record.domain_call_sequence == 1025
            assert record.domain_call_drained_sequence == 1024
            assert len(record.domain_call_evidence) == 1025

        # Replayed notification sequence is ignored and cannot append another cursor row.
        runtime._on_notification(record, notice, source_run=run,
            source_runtime_session_id=record.runtime_session_id)
        assert run.domain_stop_code is None and len(run.domain_calls) == 1025
        assert record.domain_call_sequence == (1024 if acp_callback else 1025)
        assert len(record.domain_call_evidence) == (1024 if acp_callback else 1025)

        blocked_result = {"service": "beyondquant-mcp", "status": "error",
            "backend": {"admission": {"schema_version": "domain-call-admission.v1",
                "state": "unknown", "stop": True}}}
        unrelated_result = RuntimeObservation(kind="tool.result", session_id=record.runtime_session_id,
            root_session=True, runtime_activity=True, event_sequence=2,
            call_id="unrelated-call", tool_failed=True, tool_result=blocked_result,
            completed_call_ids=("unrelated-call",),
            tool_results=(RuntimeToolResult("unrelated-call", True, blocked_result),))
        guard_dispatches = []
        guard_dispatched = threading.Event()

        def record_guard_dispatch(actual_record, actual_run, *, now):
            if threading.current_thread().name == "byq-domain-stop":
                guard_dispatches.append((actual_record, actual_run, now))
                guard_dispatched.set()

        # Observe dispatch from this callback unit only. FakeHarness finalization
        # verifies the existing stop code; this is not process-cleanup qualification.
        monkeypatch.setattr(runtime, "_enforce_run_guards", record_guard_dispatch)
        runtime._on_notification(record, unrelated_result, source_run=run,
            source_runtime_session_id=record.runtime_session_id)
        assert run.domain_stop_code is None and not run.domain_stop_dispatched
        assert guard_dispatches == []

        linked_result = RuntimeObservation(kind="tool.result", session_id=record.runtime_session_id,
            root_session=True, runtime_activity=True, event_sequence=3,
            call_id="new-call", tool_failed=True, tool_result=blocked_result,
            completed_call_ids=("new-call",),
            tool_results=(RuntimeToolResult("new-call", True, blocked_result),))
        runtime._on_notification(record, linked_result, source_run=run,
            source_runtime_session_id=record.runtime_session_id)
        assert run.domain_stop_code == "domain-correction-stopped"
        assert run.domain_stop_dispatched
        assert guard_dispatched.wait(1)
        assert len(guard_dispatches) == 1 and guard_dispatches[0][:2] == (record, run)
    finally:
        runtime._acp = previous_acp_mode
        FakeHarness.allow_run.set()

    wait_for_status(runtime, session_id, SessionStatus.FAILED)
    assert any(event["kind"] == "session.failed"
        and event["payload"].get("code") == "domain-correction-stopped"
        for event in record.history)
    if not acp_callback:
        evidence_context = {"session_id": record.session_id, "trace_id": record.trace_id,
            "owner": record.owner_principal, "workspace_id": record.workspace_id}
        page = runtime.domain_call_evidence(evidence_context, after_sequence=1024)
        assert [event["call_id"] for event in page["events"]] == ["new-call"]
        runtime.acknowledge_domain_call_evidence(evidence_context, call_evidence_receipt(page["events"][0]))
        assert record.domain_call_drained_sequence == record.domain_call_sequence == 1025
    runtime.acknowledge_terminal(session_id, record.terminal_receipts[root])


@pytest.mark.parametrize("change", [
    {"stop": False}, {"reason": "arbitrary"}, {"schema_version": "unknown"}, {"request_sha256": "private"},
])
def test_stop_marker_is_closed_and_not_a_generic_error_instruction(change):
    marker = {"schema_version": "domain-call-admission.v1", "state": "blocked",
              "reason": "correction_budget_exhausted", "stop": True}
    assert not RuntimeAdapter._domain_stop_result({"service": "beyondquant-mcp", "status": "error",
        "backend": {"admission": {**marker, **change}}})


def test_completed_root_live_attach_is_logical_and_does_not_resume_closed_process(root_adapter):
    runtime = root_adapter
    runtime.create_session("logical-reconnect", "logical-trace", "alice", "workspace_alice")
    FakeHarness.allow_run.set()
    first = runtime.submit_prompt("logical-reconnect", "first", conversation_context=[])
    wait_for_status(runtime, "logical-reconnect", SessionStatus.IDLE)
    record = runtime._get("logical-reconnect")
    assert record.process_closed and record.current_generation.state == "completed"
    first_harness = record.harness
    with pytest.raises(SessionConflict, match="cannot be resumed"):
        runtime.resume_session("logical-reconnect")
    attached = runtime.attach_live_session("logical-reconnect", "logical-trace", "alice", "workspace_alice")
    assert attached["status"] == "idle" and attached["session_id"] == "logical-reconnect"
    assert record.harness is first_harness and len(FakeHarness.instances) == 1
    assert first_harness.closed and first_harness.run_count == 1
    with pytest.raises(SessionConflict, match="identity"):
        runtime.attach_live_session("logical-reconnect", "logical-trace", "bob", "workspace_alice")
    runtime.acknowledge_terminal("logical-reconnect", record.terminal_receipts[first])
    second = runtime.submit_prompt("logical-reconnect", "next authorized turn", conversation_context=[])
    wait_for_status(runtime, "logical-reconnect", SessionStatus.IDLE)
    assert second != first and len(FakeHarness.instances) == 2
    assert runtime._get("logical-reconnect").session_id == "logical-reconnect"
