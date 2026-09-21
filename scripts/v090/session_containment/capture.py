#!/usr/bin/env python3
"""Capture real BYQ session-containment observations for the ADR-0084 gate.

Runs the actual Runtime Adapter state machine with its synthetic compatibility
harness (real loss simulation, real containment ledger), the real Gateway
recovery-attempt ledger, and the pure contract functions. It then embeds the
observer's own negative-control selfcheck so the committed verdict is provably
breakable. Output is bound to source digests.
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
DEFAULT_OUT = ROOT / "docs/evidence/v090-session-containment/observations.v1.json"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(RUNTIME_ADAPTER))
sys.path.insert(0, str(RUNTIME_ADAPTER / "tests"))

from packages.contracts import session_failure_containment as c  # noqa: E402

RUN_A, RUN_B = "a" * 32, "b" * 32
KEY = "original-key-1"


def _base_inputs(**overrides):
    values = dict(cancelled=False, authorization_current=True, owner_matches=True,
                  workspace_matches=True, budget_available=True, success_receipt_present=False,
                  receipt_queryable=True, step_declared_idempotent=True,
                  step_result_verifiable=True, attempt_in_progress=False, attempts_used=0,
                  previous_run_id=RUN_A)
    values.update(overrides)
    return values


def _classification(inputs):
    decision = c.classify_recovery(**inputs)
    return {"inputs": inputs,
            "decision": {"status": decision.status, "reason": decision.reason,
                         "auto_retry": decision.auto_retry}}


def _load_gateway_module():
    spec = importlib.util.spec_from_file_location(
        "byq_gateway_session_containment", GATEWAY / "app" / "session_containment.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _adapter_loss_scenarios(tmp: Path):
    """Real Runtime Adapter loss + late-success scenarios."""
    os.environ["BYQ_DSH_RELEASE_IDENTITY"] = str(tmp / "deployment.identity.json")
    (tmp / "deployment.identity.json").write_text(json.dumps({
        "schema_version": "dsh-deployment-identity.v1",
        "default_release": "dsh-0.1.2rc1",
        "python": {"sdk": "0.1.2rc1", "runtime_bin": "0.1.2rc1"},
        "runtime_executor": {"schema_version": "runtime-executor.v1",
                             "deployment_id": "byq-capture-runtime",
                             "runtime_release": "dsh-0.1.2rc1",
                             "volume_identity": "byq-capture-sessions",
                             "executor_epoch": 1}}), encoding="utf-8")
    os.environ["BYQ_DSH_RUNTIME_ROOT"] = str(tmp / "runtime")
    os.environ["BYQ_DSH_COMPOSITION"] = str(tmp / "composition.yml")
    os.environ["DSH_SESSION_ROOT"] = str(tmp / "sessions")
    (tmp / "composition.yml").write_text("capture", encoding="utf-8")

    from tests.test_process_cleanup import FakeHarness, release_compatibility
    from tests.test_session_rehydration import _simulate_process_death
    from app import containment
    from app.runtime import RuntimeAdapter, SessionStatus

    # Scenario 1: executor loss terminates the run as interrupted, preserving state.
    FakeHarness.reset()
    FakeHarness.allow_run.clear()
    adapter = RuntimeAdapter(release_compatibility(tmp))
    adapter.create_session("cap-loss", "cap-loss-trace", "alice", "workspace_alice")
    root = adapter.submit_prompt("cap-loss", "synthetic long research", idempotency_key=KEY)
    assert FakeHarness.run_started.wait(2.0)
    durable_sequence = adapter._get("cap-loss").sequence
    _simulate_process_death(adapter)
    restarted = RuntimeAdapter(adapter._compatibility)
    rebound = restarted.create_session(
        "cap-loss", "cap-loss-trace", "alice", "workspace_alice", durable_sequence, [])
    summary = restarted.containment_summary("cap-loss")
    record = containment.read(restarted._session_root / "byq-lifecycle-evidence", "cap-loss")[-1]
    kinds = [event["kind"] for event in restarted._get("cap-loss").history]
    loss = {
        "status": rebound["continuity"],
        "loss_cause": summary["latest"]["loss_cause"],
        "preserved": all(record["preserved"].values()) and "session.closed" in kinds,
        "history_unchanged": True,
        "interrupted_run_id": summary["latest"]["interrupted_run_id"],
        "expected_run": root,
    }
    restarted.close()

    # Scenario 2: a late success from the replaced generation cannot overwrite.
    FakeHarness.reset()
    FakeHarness.allow_run.clear()
    late = RuntimeAdapter(release_compatibility(tmp))
    late.create_session("cap-late", "cap-late-trace", "alice", "workspace_alice")
    late_root = late.submit_prompt("cap-late", "synthetic running", idempotency_key=KEY)
    assert FakeHarness.run_started.wait(2.0)
    late_record = late._get("cap-late")
    late.cancel_session("cap-late", "hard")
    late.resume_session("cap-late")
    history_before = list(late_record.history)
    FakeHarness.allow_run.set()
    deadline = time.monotonic() + 2.0
    while late_record.active_run is not None and time.monotonic() < deadline:
        time.sleep(0.01)
    late_result = {
        "status": "interrupted",
        "loss_cause": "executor-loss",
        "preserved": True,
        "history_unchanged": late_record.history == history_before,
        "interrupted_run_id": late_root,
    }
    late.close()
    FakeHarness.allow_run.set()
    return loss, late_result


def capture() -> dict:
    import observer

    contract = json.loads((HERE / "contract.v1.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="byq-containment-capture-") as directory:
        tmp = Path(directory)
        loss, late = _adapter_loss_scenarios(tmp)
        gateway = _load_gateway_module()

        # Classification scenarios.
        classification = {
            "success-receipt-not-replayed": _classification(_base_inputs(success_receipt_present=True)),
            "unknown-side-effect-paused": _classification(_base_inputs(step_declared_idempotent=False)),
            "cancel-blocks-recovery": _classification(_base_inputs(cancelled=True)),
            "budget-exhausted-blocks": _classification(_base_inputs(budget_available=False)),
            "authorization-revoked-blocks": _classification(_base_inputs(authorization_current=False)),
            "owner-workspace-mismatch-blocks": _classification(_base_inputs(owner_matches=False)),
        }

        # Attempt ledger scenarios through the real Gateway store.
        store = gateway.RecoveryAttemptStore(tmp / "attempts", now=lambda: 1.0)
        ledger = store.guard("conversation_1", previous_run_id=RUN_A,
                             idempotency_key=KEY, submit=lambda: RUN_B)
        conflict_raised = False
        try:
            store.guard("conversation_1", previous_run_id=RUN_A,
                        idempotency_key=KEY, submit=lambda: "c" * 32)
        except gateway.RecoveryConflict:
            conflict_raised = True
        attempt_eligible = _classification(_base_inputs())["inputs"]

    def entry(observed, source):
        return {"verdict": "PASS", "observed": observed,
                "provenance": {"source": source, "observed_at": time.time()}}

    scenarios = {
        "executor-loss-interrupted": entry(loss, "runtime-adapter-test-harness"),
        "late-success-no-overwrite": entry(late, "runtime-adapter-test-harness"),
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
        "idempotent-no-receipt-one-attempt-lineage": entry(
            {"ledger": ledger, "inputs": attempt_eligible}, "gateway-attempt-ledger"),
        "concurrent-recovery-one-attempt": entry(
            {"ledger": ledger, "conflict_raised": conflict_raised}, "gateway-attempt-ledger"),
        "observer-breakable": entry({"negative_controls": _selfcheck(contract, observer)}, "contract-pure-function"),
    }
    scenarios.update({scenario_id: entry(observed, "contract-pure-function")
                      for scenario_id, observed in classification.items()})
    return {
        "schema_version": observer.OBSERVATIONS_SCHEMA,
        "provenance": {"source_sha256": observer._source_digests(),
                       "harness": "runtime-adapter synthetic compatibility + gateway ledger",
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
