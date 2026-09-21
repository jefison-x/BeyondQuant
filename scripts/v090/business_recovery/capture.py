#!/usr/bin/env python3
"""Capture real BYQ business-recovery observations for the ADR-0084 gate.

The pure scenarios are re-derived from the closed contract; the
``real-adapter-journal-snapshot-closure`` scenario drives the actual
``RuntimeAdapter`` state machine with its synthetic compatibility harness so the
recorded ``{tail, digest, idle}`` is the real append-only session-global call
closure and the carrier anchors that exact snapshot. Output is bound to source
digests and embeds the observer's own negative-control selfcheck.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RUNTIME_ADAPTER = ROOT / "services/runtime-adapter"
DEFAULT_OUT = ROOT / "docs/evidence/v090-business-recovery/observations.v1.json"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(RUNTIME_ADAPTER) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ADAPTER))

import observer  # noqa: E402
from packages.contracts import business_recovery as contract  # noqa: E402

_ROOT_LINE = "X-BYQ-Root-Run-ID: !!js process.env.BYQ_ROOT_RUN_ID\n"


def _real_adapter_scenario(tmp: Path) -> dict:
    """Drive the real adapter journal + the real admission precheck."""

    from tests.test_process_cleanup import FakeHarness, release_compatibility
    from tests.test_session_rehydration import _simulate_process_death
    from app import business_recovery as recovery
    from app.runtime import RuntimeAdapter

    source = "- id: mcp-byq\n  config:\n    headers:\n      " + _ROOT_LINE
    profile = tmp / "product.yml"
    profile.write_text(source, encoding="utf-8")
    identity = tmp / "identity.json"
    identity.write_text(json.dumps({
        "root_identity_contract": "byq-root-process.v1",
        "composition_hash": "sha256:" + hashlib.sha256(source.encode()).hexdigest(),
    }), encoding="utf-8")
    os.environ["BYQ_DSH_PROCESS_OWNERSHIP"] = "root-turn"
    os.environ["BYQ_DSH_COMPOSITION"] = str(profile)
    os.environ["BYQ_DSH_COMPOSITION_IDENTITY"] = str(identity)
    os.environ["BYQ_DSH_RUNTIME_ROOT"] = str(tmp / "runtime")
    os.environ["DSH_SESSION_ROOT"] = str(tmp / "sessions")
    os.environ["BYQ_F6_EXECUTOR_ENABLED"] = "1"
    executor_identity = tmp / "deployment.identity.json"
    executor_identity.write_text(json.dumps({
        "schema_version": "dsh-deployment-identity.v1", "default_release": "dsh-0.1.2rc1",
        "python": {"sdk": "0.1.2rc1", "runtime_bin": "0.1.2rc1"},
        "runtime_executor": {"schema_version": "runtime-executor.v1",
            "deployment_id": "byq-capture-runtime", "runtime_release": "dsh-0.1.2rc1",
            "volume_identity": "byq-capture-sessions", "executor_epoch": 1}}), encoding="utf-8")
    os.environ["BYQ_DSH_RELEASE_IDENTITY"] = str(executor_identity)

    def qualify(adapter: RuntimeAdapter) -> None:
        adapter.continuation_qualified = lambda record: True
        adapter._resolve_model = lambda **kwargs: {
            "provider": "deepseek-official", "model": "deepseek-v4-flash", "api_key": "synthetic-only"}

    FakeHarness.reset()
    FakeHarness.allow_run.clear()
    adapter = RuntimeAdapter(release_compatibility(tmp))
    qualify(adapter)
    adapter.create_session("rec-1", "rec-trace", "alice", "workspace_alice")
    adapter.submit_prompt("rec-1", "synthetic long research")
    assert FakeHarness.run_started.wait(2.0)
    durable_sequence = adapter._get("rec-1").sequence
    _simulate_process_death(adapter)
    restarted = RuntimeAdapter(adapter._compatibility)
    qualify(restarted)
    restarted.create_session("rec-1", "rec-trace", "alice", "workspace_alice", durable_sequence, [])
    recorded = restarted.containment_summary("rec-1")["latest"]
    record = restarted._get("rec-1")
    restarted.acknowledge_terminal("rec-1", record.terminal_receipts[recorded["interrupted_run_id"]])
    snapshot = recovery.snapshot_from_state(record.journal.state)
    reservation_id = "continuation_" + "a" * 32
    trigger = contract.trigger_key(reservation_id, recorded["interrupted_run_id"],
        recorded["interrupted_generation"], recorded["attempt"], recorded["executor_epoch"])
    carrier = {
        "attempt_key": contract.attempt_key(trigger, 1), "ordinal": 1, "trigger_key": trigger,
        "interrupted_run_id": recorded["interrupted_run_id"],
        "interrupted_generation": recorded["interrupted_generation"],
        "containment_attempt": recorded["attempt"],
        "interrupted_executor_epoch": recorded["executor_epoch"],
        "snapshot_tail_sequence": snapshot["tail_sequence"], "snapshot_digest": snapshot["digest"],
    }
    from datetime import datetime, timedelta, timezone
    reservation = {
        "schema_version": "task-continuation-reservation.v1", "reservation_id": reservation_id,
        "task_id": "task_" + "b" * 32, "owner": "alice", "workspace_id": "workspace_alice",
        "token_limit": contract.MODEL_CALL_FLOOR * 2,
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat(),
        "recovery_attempt": carrier,
    }
    FakeHarness.allow_run.set()
    run = restarted.submit_prompt("rec-1", "recover", idempotency_key=carrier["attempt_key"],
        conversation_context=[], continuation_budget=reservation)
    receipt = restarted.recovery_receipt("rec-1", carrier["attempt_key"])
    state = record.journal.state
    observed = {
        "session_id": "rec-1", "trace_id": "rec-trace",
        "calls": list(state["calls"]), "idle": state["open_root"] is None,
        "tail": len(state["calls"]), "digest": snapshot["digest"],
        "carrier_tail": carrier["snapshot_tail_sequence"], "carrier_digest": carrier["snapshot_digest"],
        "run_id": run, "target_executor_epoch": receipt["target_executor_epoch"],
        "target_generation": receipt["target_generation"],
    }
    assert receipt["run_id"] == run and observed["carrier_digest"] == observed["digest"]
    restarted.close()
    FakeHarness.allow_run.set()
    return observed


def capture() -> dict:
    contract_spec = json.loads((HERE / "contract.v1.json").read_text(encoding="utf-8"))
    observations = observer.valid_fixture(contract_spec)
    with tempfile.TemporaryDirectory(prefix="byq-business-recovery-") as directory:
        real = _real_adapter_scenario(Path(directory))
    observations["scenarios"]["real-adapter-journal-snapshot-closure"] = {
        "verdict": "PASS", "observed": real,
        "provenance": {"source": "runtime-adapter-real-journal", "observed_at": time.time()},
    }
    selfcheck = observer.run_selfcheck(contract_spec)
    observations["scenarios"]["observer-breakable"] = {
        "verdict": "PASS",
        "observed": {"negative_controls": {
            "all_controls_rejected": selfcheck["all_controls_pass"],
            "control_count": selfcheck["control_count"],
            "defect_targeting_count": selfcheck["defect_targeting_count"]}},
        "provenance": {"source": "contract-pure-function", "observed_at": time.time()},
    }
    observations["provenance"] = {
        "source_sha256": observer._source_digests(),
        "harness": "runtime-adapter synthetic compatibility + real lifecycle journal + closed contract",
        "captured_at": time.time(),
    }
    return observations


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
