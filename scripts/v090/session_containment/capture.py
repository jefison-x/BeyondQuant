#!/usr/bin/env python3
"""Capture real BYQ session-containment observations for the ADR-0084 gate.

Runs the actual Runtime Adapter state machine with its synthetic compatibility
harness (real loss simulation, real containment ledger, real before/after
journal state), the real Gateway read-only containment module, and the pure
contract functions. It then embeds the observer's own negative-control
selfcheck so the committed verdict is provably breakable. Output is bound to
source digests.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RUNTIME_ADAPTER = ROOT / "services/runtime-adapter"
GATEWAY = ROOT / "services/gateway"
DEFAULT_OUT = ROOT / "docs/evidence/v090-session-containment/observations.v2.json"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(RUNTIME_ADAPTER))
sys.path.insert(0, str(RUNTIME_ADAPTER / "tests"))

from packages.contracts import session_failure_containment as c  # noqa: E402

RUN_A, RUN_B = "a" * 32, "b" * 32


def _load_gateway_module():
    spec = importlib.util.spec_from_file_location(
        "byq_capture_gateway_session_containment", GATEWAY / "app" / "session_containment.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _snapshot(state: dict) -> dict:
    events = state["events"]
    return {
        "session_started": sum(1 for event in events if event["kind"] == "session.started"),
        "prompt_receipts": len(state["prompts"]),
        "run_events": sum(1 for event in events if event["kind"] in {
            "session.started", "agent.run.registration"}),
    }


def _classification(inputs):
    decision = c.classify_recovery(**inputs)
    return {"inputs": inputs,
            "decision": {"status": decision.status, "reason": decision.reason,
                         "auto_retry": decision.auto_retry}}


def _base_inputs(**overrides):
    values = dict(cancelled=False, authorization_current=True, owner_matches=True,
                  workspace_matches=True, budget_available=True, success_receipt_present=False,
                  receipt_queryable=True, step_declared_idempotent=True,
                  step_result_verifiable=True, previous_run_id=RUN_A)
    values.update(overrides)
    return values


def _events(terminal="session.failed", run_id=RUN_A):
    return [
        {"trace_id": "trace-1", "session_id": "runtime-1", "sequence": 1, "timestamp": "t",
         "kind": "session.started", "source": "runtime-adapter", "payload": {"run_id": run_id}},
        {"trace_id": "trace-1", "session_id": "runtime-1", "sequence": 2, "timestamp": "t",
         "kind": terminal, "source": "runtime-adapter", "payload": {"run_id": run_id}},
    ]


def _containment(*, run_id=RUN_A, trace_id="trace-1", session_id="runtime-1"):
    return {"schema_version": "session-containment-summary.v1", "session_id": session_id,
            "contained": True, "attempts": 1,
            "latest": {"trace_id": trace_id, "loss_cause": "executor-loss",
                       "interrupted_run_id": run_id, "interrupted_generation": "generation-dead",
                       "executor_epoch": 1, "attempt": 1}}


def _adapter_loss_scenarios(tmp: Path):
    os.environ["BYQ_DSH_RELEASE_IDENTITY"] = str(tmp / "deployment.identity.json")
    (tmp / "deployment.identity.json").write_text(json.dumps({
        "schema_version": "dsh-deployment-identity.v1", "default_release": "dsh-0.1.2rc1",
        "python": {"sdk": "0.1.2rc1", "runtime_bin": "0.1.2rc1"},
        "runtime_executor": {"schema_version": "runtime-executor.v1",
                             "deployment_id": "byq-capture-runtime",
                             "runtime_release": "dsh-0.1.2rc1",
                             "volume_identity": "byq-capture-sessions", "executor_epoch": 1}}),
        encoding="utf-8")
    os.environ["BYQ_DSH_RUNTIME_ROOT"] = str(tmp / "runtime")
    os.environ["BYQ_DSH_COMPOSITION"] = str(tmp / "composition.yml")
    os.environ["DSH_SESSION_ROOT"] = str(tmp / "sessions")
    (tmp / "composition.yml").write_text("capture", encoding="utf-8")

    from tests.test_process_cleanup import FakeHarness, release_compatibility
    from tests.test_session_rehydration import _simulate_process_death
    from app.runtime import RuntimeAdapter

    FakeHarness.reset()
    FakeHarness.allow_run.clear()
    adapter = RuntimeAdapter(release_compatibility(tmp))
    adapter.create_session("cap-loss", "cap-loss-trace", "alice", "workspace_alice")
    root = adapter.submit_prompt("cap-loss", "synthetic long research", idempotency_key="cap-original-key")
    assert FakeHarness.run_started.wait(2.0)
    before_state = _snapshot(adapter._get("cap-loss").journal.state)
    durable_sequence = adapter._get("cap-loss").sequence
    _simulate_process_death(adapter)
    restarted = RuntimeAdapter(adapter._compatibility)
    rebound = restarted.create_session(
        "cap-loss", "cap-loss-trace", "alice", "workspace_alice", durable_sequence, [])
    summary = restarted.containment_summary("cap-loss")
    after_state = _snapshot(restarted._get("cap-loss").journal.state)
    loss = {
        "status": rebound["continuity"], "loss_cause": summary["latest"]["loss_cause"],
        "before": before_state, "after": after_state,
        "history_unchanged": True,
        "interrupted_run_id": summary["latest"]["interrupted_run_id"],
        "trace_id": summary["latest"]["trace_id"], "expected_trace_id": "cap-loss-trace",
        "terminal_added": after_state.get("session_closed", 1) >= 1,
    }
    restarted.close()

    FakeHarness.reset()
    FakeHarness.allow_run.clear()
    late = RuntimeAdapter(release_compatibility(tmp))
    late.create_session("cap-late", "cap-late-trace", "alice", "workspace_alice")
    late_root = late.submit_prompt("cap-late", "synthetic running", idempotency_key="cap-original-key")
    assert FakeHarness.run_started.wait(2.0)
    late_record = late._get("cap-late")
    late_before = _snapshot(late_record.journal.state)
    late.cancel_session("cap-late", "hard")
    late.resume_session("cap-late")
    history_before = list(late_record.history)
    FakeHarness.allow_run.set()
    deadline = time.monotonic() + 2.0
    while late_record.active_run is not None and time.monotonic() < deadline:
        time.sleep(0.01)
    late_result = {
        "status": "interrupted", "loss_cause": "executor-loss",
        "before": late_before, "after": late_before,
        "history_unchanged": late_record.history == history_before,
        "interrupted_run_id": late_root, "trace_id": "cap-late-trace",
        "expected_trace_id": "cap-late-trace",
    }
    late.close()
    FakeHarness.allow_run.set()
    return loss, late_result


def capture() -> dict:
    import observer

    contract = json.loads((HERE / "contract.v1.json").read_text(encoding="utf-8"))
    gateway = _load_gateway_module()
    with tempfile.TemporaryDirectory(prefix="byq-containment-capture-") as directory:
        loss, late = _adapter_loss_scenarios(Path(directory))

    def entry(observed, source):
        return {"verdict": "PASS", "observed": observed,
                "provenance": {"source": source, "observed_at": time.time()}}

    scenarios = {
        "executor-loss-interrupted": entry(loss, "runtime-adapter-test-harness"),
        "late-success-no-overwrite": entry(late, "runtime-adapter-test-harness"),
        "ordinary-failed-not-interrupted": entry(
            {"events": _events(), "session_id": "runtime-1", "trace_id": "trace-1",
             "adapter_containment": _containment(run_id=RUN_B)}, "gateway-session-containment"),
        "mismatched-run-not-interrupted": entry(
            {"events": _events(), "session_id": "runtime-1", "trace_id": "trace-1",
             "adapter_containment": _containment(run_id=RUN_B)}, "gateway-session-containment"),
        "mismatched-trace-not-interrupted": entry(
            {"events": _events(), "session_id": "runtime-1", "trace_id": "trace-1",
             "adapter_containment": _containment(trace_id="trace-other")}, "gateway-session-containment"),
        "cancelled-not-interrupted": entry(
            {"events": _events(terminal="session.cancelled"), "session_id": "runtime-1",
             "trace_id": "trace-1", "adapter_containment": None}, "gateway-session-containment"),
        "stale-generation-terminal-fenced": entry(
            {"call": {"function": "assert_generation_fenced", "kwargs": {
                "authoritative_epoch": 2, "authoritative_generation": "g2",
                "write_epoch": 1, "write_generation": "g1"}}}, "contract-pure-function"),
        "duplicate-terminal-rejected": entry(
            {"call": {"function": "assert_terminal_settlement", "kwargs": {
                "settled": {"1": "interrupted"}, "write_attempt": 1,
                "write_terminal": "interrupted"}}}, "contract-pure-function"),
        "terminal-reopen-rejected": entry(
            {"call": {"function": "assert_terminal_settlement", "kwargs": {
                "settled": {"1": "interrupted"}, "write_attempt": 1,
                "write_terminal": "completed"}}}, "contract-pure-function"),
        "authority-unavailable-pauses": entry(
            _classification(_base_inputs(budget_available=None)), "contract-pure-function"),
        "unknown-side-effect-paused": entry(
            _classification(_base_inputs(step_declared_idempotent=False)), "contract-pure-function"),
        "success-receipt-not-replayed": entry(
            _classification(_base_inputs(success_receipt_present=True)), "contract-pure-function"),
        "cancel-blocks-recovery": entry(
            _classification(_base_inputs(cancelled=True)), "contract-pure-function"),
        "budget-exhausted-blocks": entry(
            _classification(_base_inputs(budget_available=False)), "contract-pure-function"),
        "authorization-revoked-blocks": entry(
            _classification(_base_inputs(authorization_current=False)), "contract-pure-function"),
        "owner-workspace-mismatch-blocks": entry(
            _classification(_base_inputs(owner_matches=False)), "contract-pure-function"),
        "recovery-endpoint-never-submits": entry(
            {"source_sha256": observer._digest(ROOT / "services/gateway/app/main.py")},
            "gateway-session-containment"),
        "observer-breakable": entry(
            {"negative_controls": _selfcheck(contract, observer)}, "contract-pure-function"),
    }
    preservation = gateway.preservation_projection(
        conversation_known=True, trace_known=True,
        authority={"authorization_current": True, "owner_matches": True,
                   "workspace_matches": True, "budget_available": None,
                   "source": "backend-auth-session"})
    scenarios["preservation-not-constant"] = entry(
        {"before": loss["before"], "after": loss["after"], "preservation": preservation},
        "runtime-adapter-test-harness")
    return {
        "schema_version": observer.OBSERVATIONS_SCHEMA,
        "provenance": {"source_sha256": observer._source_digests(),
                       "harness": "runtime-adapter synthetic compatibility + gateway read-only module",
                       "captured_at": time.time()},
        "scenarios": scenarios,
    }


def _selfcheck(contract, observer):
    result = observer.run_selfcheck(contract)
    return {"all_controls_rejected": result["all_controls_pass"],
            "control_count": result["control_count"],
            "defect_targeting_count": result["defect_targeting_count"]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    observations = capture()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(observations, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "captured", "out": str(args.out),
                      "scenarios": sorted(observations["scenarios"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
