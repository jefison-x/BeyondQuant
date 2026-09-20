#!/usr/bin/env python3
"""Capture-layer negatives for the D15 runtime-continuity qualification.

Unlike the observer's synthetic JSON fixtures, these cases exercise the real
capture-layer helper functions (``derive_goal_receipt``, ``derive_replay_run``,
``derive_approval``, ``derive_trace_evidence``) with faulty inputs, then show:

* the PRE-FIX observation (what the old capture fabricated/masked) passes the
  reconstructed legacy algorithm, and
* the POST-FIX observation (what the fixed capture emits) fails the verdict.

Exits non-zero unless every post-fix case fails and every pre-fix case passes.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_modules():
    observer = _load("d15_obs_capture_neg", HERE / "observer.py")
    runner = _load("d15_rq_capture_neg", HERE / "run_qualification.py")
    contract = json.loads((HERE / "contract.v3.json").read_text(encoding="utf-8"))
    return observer, runner, contract


def _runtime_fixture(observer, contract) -> dict:
    fixture = observer.valid_fixture(contract)
    fixture["evidence_class"] = contract["required_evidence_class"]
    return fixture


def _scenario(observer, contract, mutate) -> dict:
    fixture = _runtime_fixture(observer, contract)
    mutate(fixture["scenarios"][0])
    return fixture


def _new_verdict(observer, contract, observations) -> dict:
    return observer.compute_verdict(contract, observations)


def _legacy_verdict(observer, contract, observations) -> dict:
    return observer.legacy_compute_verdict(contract, observations)


def build_cases(observer, runner, contract) -> list[dict]:
    cases: list[dict] = []

    def add(name: str, description: str, pre_fix, post_fix) -> None:
        cases.append({"case": name, "description": description,
                      "pre_fix": pre_fix, "post_fix": post_fix})

    # 1. Deleted durable journal receipt.
    receipt, error = runner.derive_goal_receipt({}, "message-x")
    assert receipt is None and error

    def pre_deleted(scenario):
        pass  # old capture fabricated the receipt from self.goal/artifacts -> unchanged fixture passes

    def post_deleted(scenario):
        scenario["after"]["goal"]["prompt_receipt"] = None
        scenario["after"]["capture_ok"] = False
        scenario["after"]["capture_errors"] = [error]
        scenario["after"]["result"].update({"status": "incomplete", "attributed_message_sequence": None})

    add("deleted-journal-receipt",
        "journal prompt receipt deleted; old capture fabricated one, fixed capture reports capture_ok=false",
        _scenario(observer, contract, pre_deleted), _scenario(observer, contract, post_deleted))

    # 2. Replay request error.
    replay_run, replay_error = runner.derive_replay_run({"_error": "adapter 500"})
    assert replay_run is None and replay_error

    def pre_replay(scenario):
        pass  # old capture fell back to the original run id and hardcoded count=1

    def post_replay(scenario):
        scenario["after"]["capture_ok"] = False
        scenario["after"]["capture_errors"] = [replay_error]
        scenario["after"]["action_receipts"][0]["receipt"] = {"state": "accepted", "run_id": None}
        scenario["after"]["action_receipts"][0]["replay"]["receipt"] = {"state": "accepted", "run_id": None}
        scenario["after"]["action_receipts"][0]["side_effect_count"] = 0
        scenario["after"]["action_receipts"][0]["replay"]["side_effect_count"] = 0

    add("replay-error",
        "prompt replay errored; old capture fell back to the original run id, fixed capture reports the error",
        _scenario(observer, contract, pre_replay), _scenario(observer, contract, post_replay))

    # 3. Approval expiry / bypass.
    expired_response = {"artifact": {"artifact_id": "artifact_" + "e" * 32,
                                     "content": {"decision": "expired", "reviewer_principal": "human-owner",
                                                 "execution_authorized": False}}}
    # A reject request that wrongly produced an approval is a deny-trial side effect.
    rejected_response = {"artifact": {"artifact_id": "artifact_" + "f" * 32,
                                      "content": {"decision": "approved", "reviewer_principal": "human-owner",
                                                  "execution_authorized": True}}}
    approval = runner.derive_approval(expired_response, rejected_response,
                                      {"artifact": {"artifact_id": "artifact_" + "a" * 32}}, None)
    assert approval["state"] == "expired" and approval["bypassed"] is True

    def pre_expiry(scenario):
        scenario["after"]["approval"].update({"state": "approved", "bypassed": False,
                                              "execution_authorized": True, "reuse_denied": True})
        scenario["after"]["approval"].pop("trials", None)

    def post_expiry(scenario):
        scenario["after"]["approval"].update(approval)
        scenario["after"]["capture_ok"] = False
        scenario["after"]["capture_errors"] = ["persisted approval state is 'expired', not approved"]

    add("approval-expiry-bypass",
        "persisted approval is expired and a deny trial created a side effect; old capture hardcoded approved",
        _scenario(observer, contract, pre_expiry), _scenario(observer, contract, post_expiry))

    # 4. Trace gap.
    gapped_events = [
        {"sequence": 1, "kind": "session.started", "payload": {"run_id": "1" * 32}},
        {"sequence": 3, "kind": "session.result", "payload": {"run_id": "1" * 32}},
    ]
    trace = runner.derive_trace_evidence(gapped_events, [{"role": "assistant", "workflow_sequence": 2}], "1" * 32)
    assert trace["trace_contiguous"] is False and trace["errors"]

    def pre_trace_gap(scenario):
        pass  # old capture used sequence > 0, so the gap looked contiguous

    def post_trace_gap(scenario):
        scenario["after"]["result"].update({"trace_contiguous": False, "status": "incomplete"})
        scenario["after"]["capture_ok"] = False
        scenario["after"]["capture_errors"] = list(trace["errors"])

    add("trace-gap",
        "persisted trace has a sequence gap; old capture only checked sequence > 0",
        _scenario(observer, contract, pre_trace_gap), _scenario(observer, contract, post_trace_gap))

    # 5. Only an old assistant result (target run did not complete).
    old_only_events = [
        {"sequence": 1, "kind": "session.started", "payload": {"run_id": "1" * 32}},
        {"sequence": 2, "kind": "session.result", "payload": {"run_id": "1" * 32}},
        {"sequence": 3, "kind": "session.started", "payload": {"run_id": "2" * 32}},
    ]
    trace_old = runner.derive_trace_evidence(
        old_only_events,
        [{"role": "assistant", "workflow_sequence": 2}],  # belongs to the old run, not the target
        "2" * 32)
    assert trace_old["completed"] is False and trace_old["errors"]

    def pre_old_assistant(scenario):
        pass  # old capture reported completed because any assistant existed

    def post_old_assistant(scenario):
        scenario["after"]["goal"]["prompt_receipt"]["root_run_id"] = "2" * 32
        scenario["after"]["result"].update({
            "run_id": "2" * 32, "target_run_id": "2" * 32,
            "status": "incomplete", "attributed_message_sequence": None,
            "terminal_kind": None, "trace_contiguous": False,
        })
        scenario["after"]["capture_ok"] = False
        scenario["after"]["capture_errors"] = list(trace_old["errors"])

    add("only-old-assistant-result",
        "target run never completed but a historical assistant exists; old capture reported completed",
        _scenario(observer, contract, pre_old_assistant), _scenario(observer, contract, post_old_assistant))

    return cases


def run() -> dict:
    observer, runner, contract = load_modules()
    baseline = _new_verdict(observer, contract, _runtime_fixture(observer, contract))
    cases = build_cases(observer, runner, contract)
    results = []
    for case in cases:
        legacy = _legacy_verdict(observer, contract, case["pre_fix"])
        fixed = _new_verdict(observer, contract, case["post_fix"])
        results.append({
            "case": case["case"],
            "description": case["description"],
            "pre_fix_legacy_all_pass": legacy["all_pass"],
            "pre_fix_legacy_exit_code": legacy["exit_code"],
            "post_fix_all_pass": fixed["all_pass"],
            "post_fix_exit_code": fixed["exit_code"],
            "post_fix_first_failure": (fixed["failures"] + fixed["coverage_failures"])[0]
            if (fixed["failures"] or fixed["coverage_failures"]) else None,
            "passes": legacy["all_pass"] is True and fixed["all_pass"] is False,
        })
    all_pass = baseline["all_pass"] and all(item["passes"] for item in results)
    return {
        "schema_version": "byq-d15-runtime-capture-negatives.v3",
        "baseline_all_pass": baseline["all_pass"],
        "case_count": len(results),
        "all_cases_pass": all(item["passes"] for item in results),
        "all_pass": all_pass,
        "cases": results,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    result = run()
    payload = json.dumps(result, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0 if result["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
