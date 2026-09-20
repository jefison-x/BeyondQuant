#!/usr/bin/env python3
"""Fail-able observer/verdict for the D15 runtime-continuity qualification.

The observer is intentionally strict and independent of the harness that
produces observations. It reads a contract (single source of truth for required
scenarios, invariant vocabulary and fail-closed conditions) plus an observations
artifact, and either exits non-zero on any violation or emits a PASS verdict.

It never inspects implementation internals and never treats missing evidence as
a pass. ``--selfcheck`` mutates a known-good fixture in every fail-closed way
and asserts each mutation is rejected, proving the verdict can actually fail.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_CONTRACT = HERE / "contract.v1.json"


class Failure(Exception):
    """Raised only for an unreadable contract/observations artifact."""


def _load(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise Failure(f"missing artifact: {path}") from exc
    except json.JSONDecodeError as exc:
        raise Failure(f"malformed artifact: {path}: {exc}") from exc


def _is_nonempty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _require(mapping: object, key: str, ctx: str, failures: list[str]) -> object:
    if not isinstance(mapping, dict) or key not in mapping:
        failures.append(f"{ctx}: missing required field '{key}'")
        return None
    return mapping[key]


def _require_before_after(block: object, fields: list[str], ctx: str, failures: list[str]) -> dict:
    if not isinstance(block, dict):
        failures.append(f"{ctx}: not an object")
        return {}
    for field in fields:
        if field not in block:
            failures.append(f"{ctx}: missing '{field}'")
    return block


def _check_action_receipts(receipts: object, fields: list[str], ctx: str, failures: list[str]) -> bool:
    if not isinstance(receipts, list) or not receipts:
        failures.append(f"{ctx}: action_receipts must be a non-empty list")
        return False
    seen: dict[str, str] = {}
    ok = True
    for index, receipt in enumerate(receipts):
        item_ctx = f"{ctx}.action_receipts[{index}]"
        if not isinstance(receipt, dict):
            failures.append(f"{item_ctx}: not an object")
            ok = False
            continue
        for field in fields:
            if field not in receipt:
                failures.append(f"{item_ctx}: missing '{field}'")
                ok = False
        key = receipt.get("idempotency_key")
        if not _is_nonempty_str(key):
            failures.append(f"{item_ctx}: empty idempotency_key")
            ok = False
        if receipt.get("side_effect_count") != 1:
            failures.append(
                f"{item_ctx}: duplicate side effect (side_effect_count={receipt.get('side_effect_count')!r})")
            ok = False
        prior = seen.get(str(key))
        if prior is not None and prior != receipt.get("receipt"):
            failures.append(f"{item_ctx}: replay receipt changed for idempotency key {key!r}")
            ok = False
        if _is_nonempty_str(key):
            seen[str(key)] = str(receipt.get("receipt"))
        replay = receipt.get("replay")
        if not isinstance(replay, dict) or replay.get("receipt") != receipt.get("receipt") \
                or replay.get("side_effect_count") != 1:
            failures.append(f"{item_ctx}: replay did not deduplicate the side effect")
            ok = False
    return ok


def _check_approval(approval: object, states: list[str], ctx: str, failures: list[str]) -> bool:
    if not isinstance(approval, dict):
        failures.append(f"{ctx}: approval must be an object")
        return False
    ok = True
    approval_id = approval.get("approval_id")
    if not _is_nonempty_str(approval_id):
        failures.append(f"{ctx}.approval: missing approval_id")
        ok = False
    if approval.get("state") not in states:
        failures.append(f"{ctx}.approval: invalid state {approval.get('state')!r}")
        ok = False
    if approval.get("bypassed") is not False:
        failures.append(f"{ctx}.approval: approval was bypassed")
        ok = False
    decided_by = approval.get("decided_by")
    initiator = approval.get("initiator")
    if _is_nonempty_str(decided_by) and _is_nonempty_str(initiator) and decided_by == initiator:
        failures.append(f"{ctx}.approval: initiator self-approved")
        ok = False
    if "reuse_denied" in approval and approval.get("reuse_denied") is not True:
        failures.append(f"{ctx}.approval: recorded approval reuse was not denied")
        ok = False
    return ok


def _check_scenario(
    scenario: dict, contract: dict, failures: list[str],
) -> dict:
    scenario_id = scenario.get("id")
    ctx = f"scenario[{scenario_id}]"
    result = scenario.get("result")
    vocabulary = contract["results_vocabulary"]
    if result not in vocabulary:
        failures.append(f"{ctx}: invalid result {result!r}")
    checks = {
        "identity_stable": False,
        "original_goal_retained": False,
        "no_duplicate_side_effect": False,
        "approval_not_bypassed": False,
        "result_traceable": False,
        "before_after_captured": False,
        "continuity_truthful": False,
        "sequence_contiguous": False,
    }

    if result in {"NOT_RUN", "BLOCKED"}:
        if contract.get("not_run_requires_reason") and not _is_nonempty_str(scenario.get("not_run_reason")):
            failures.append(f"{ctx}: {result} without a reason")
        return {"id": scenario_id, "result": result, "invariants": checks}

    if result != "PASS":
        failures.append(f"{ctx}: result {result!r} is not PASS")
        return {"id": scenario_id, "result": result, "invariants": checks}

    if scenario.get("fault_applied") is not True:
        failures.append(f"{ctx}: fault_applied is not true (scenario was not actually exercised)")

    before = _require_before_after(
        scenario.get("before"), contract["required_before_after_fields"],
        f"{ctx}.before", failures)
    after = _require_before_after(
        scenario.get("after"), contract["required_before_after_fields"],
        f"{ctx}.after", failures)

    # identity_stable
    if _is_nonempty_str(before.get("session_id")) and before.get("session_id") == after.get("session_id") \
            and before.get("trace_id") == after.get("trace_id"):
        checks["identity_stable"] = True
    else:
        failures.append(f"{ctx}: durable session/trace identity changed across the fault")

    # original_goal_retained
    before_goal = before.get("goal") if isinstance(before.get("goal"), dict) else {}
    after_goal = after.get("goal") if isinstance(after.get("goal"), dict) else {}
    for goal_ctx, goal in ((f"{ctx}.before.goal", before_goal), (f"{ctx}.after.goal", after_goal)):
        for field in contract["goal_fields"]:
            if field not in goal:
                failures.append(f"{goal_ctx}: missing '{field}'")
    if _is_nonempty_str(before_goal.get("content_sha256")) \
            and before_goal.get("content_sha256") == after_goal.get("content_sha256") \
            and after_goal.get("prompt_receipt") == before_goal.get("prompt_receipt") \
            and after_goal.get("prompt_receipt") is not None:
        checks["original_goal_retained"] = True
    else:
        failures.append(f"{ctx}: original goal drifted or prompt receipt was not retained")

    # no_duplicate_side_effect
    checks["no_duplicate_side_effect"] = _check_action_receipts(
        after.get("action_receipts"), contract["action_receipt_fields"],
        f"{ctx}.after", failures)

    # approval_not_bypassed
    checks["approval_not_bypassed"] = _check_approval(
        after.get("approval"), contract["approval_states"], f"{ctx}.after", failures)

    # result_traceable
    after_result = after.get("result") if isinstance(after.get("result"), dict) else {}
    for field in contract["result_fields"]:
        if field not in after_result:
            failures.append(f"{ctx}.after.result: missing '{field}'")
    if _is_nonempty_str(after_result.get("run_id")) and _is_nonempty_str(after_result.get("status")) \
            and after_result.get("trace_contiguous") is True:
        checks["result_traceable"] = True
    else:
        failures.append(f"{ctx}: result was not durably traceable")

    # before_after_captured (all fields + pid/generation/epoch present)
    if all(field in before and field in after for field in contract["required_before_after_fields"]):
        checks["before_after_captured"] = True
    else:
        failures.append(f"{ctx}: before/after capture incomplete")

    # continuity_truthful
    allowed = set(scenario.get("allowed_continuity", contract["continuity_vocabulary"]))
    forbidden = set(scenario.get("forbidden_continuity", []))
    continuity = after.get("continuity")
    if continuity not in contract["continuity_vocabulary"]:
        failures.append(f"{ctx}: invalid continuity {continuity!r}")
    elif continuity in forbidden:
        failures.append(f"{ctx}: fabricated continuity {continuity!r} after a fault")
    elif continuity not in allowed:
        failures.append(f"{ctx}: continuity {continuity!r} not in allowed set {sorted(allowed)}")
    else:
        checks["continuity_truthful"] = True

    # sequence_contiguous
    before_sequence = (before.get("result") or {}).get("sequence") if isinstance(before.get("result"), dict) else None
    after_sequence = after_result.get("sequence")
    if isinstance(before_sequence, int) and isinstance(after_sequence, int) \
            and after_sequence >= before_sequence and after_result.get("trace_contiguous") is True:
        checks["sequence_contiguous"] = True
    else:
        failures.append(f"{ctx}: result sequence regressed or is not contiguous")

    return {"id": scenario_id, "result": result, "continuity": continuity, "invariants": checks}


def compute_verdict(contract: dict, observations: dict) -> dict:
    failures: list[str] = []
    candidate = contract["candidate"]

    if not isinstance(observations, dict):
        raise Failure("observations must be an object")

    observed_candidate = observations.get("candidate")
    if not isinstance(observed_candidate, dict) or observed_candidate.get("release") != candidate["release"]:
        failures.append(
            f"candidate mismatch: expected {candidate['release']!r}, got {observed_candidate!r}")

    llm = observations.get("llm")
    if not isinstance(llm, dict) or llm.get("class") != contract["llm_evidence_class"] \
            or llm.get("real_llm_quality") is not False:
        failures.append("LLM evidence class must be explicitly keyless/scripted with real_llm_quality=false")

    scenarios_value = observations.get("scenarios")
    if not isinstance(scenarios_value, list):
        failures.append("scenarios must be a list")
        scenarios_value = []

    required = {item["id"]: item for item in contract["required_scenarios"]}
    observed_ids = [item.get("id") if isinstance(item, dict) else None for item in scenarios_value]
    if len(observed_ids) != len(set(map(str, observed_ids))):
        failures.append("duplicate scenario id in observations")

    if contract.get("closed_scenario_set"):
        for scenario_id in observed_ids:
            if scenario_id not in required:
                failures.append(f"unknown scenario id {scenario_id!r} (closed set)")

    scenario_results = []
    for item in scenarios_value:
        if not isinstance(item, dict):
            failures.append("scenario entry is not an object")
            continue
        scenario_id = item.get("id")
        spec = required.get(scenario_id)
        merged = dict(item)
        if spec is not None:
            merged.setdefault("allowed_continuity", spec["allowed_continuity"])
            merged.setdefault("forbidden_continuity", spec["forbidden_continuity"])
        scenario_results.append(_check_scenario(merged, contract, failures))

    seen_ids = set(observed_ids)
    for scenario_id in required:
        if scenario_id not in seen_ids:
            failures.append(f"missing required scenario {scenario_id!r}")

    pass_scenarios = [row for row in scenario_results if row["result"] == "PASS"]
    uncovered = [row["id"] for row in scenario_results if row["result"] in {"NOT_RUN", "BLOCKED"}]
    failed = [row["id"] for row in scenario_results if row["result"] == "FAIL"]

    all_pass = not failures and not failed
    return {
        "schema_version": "byq-d15-runtime-verdict.v1",
        "all_pass": all_pass,
        "exit_code": 0 if all_pass else 1,
        "candidate": candidate,
        "llm_evidence_class": contract["llm_evidence_class"],
        "required_scenario_count": len(required),
        "pass_scenarios": [row["id"] for row in pass_scenarios],
        "failed_scenarios": failed,
        "uncovered_scenarios": uncovered,
        "scenarios": scenario_results,
        "failures": failures,
        "invariant_coverage": {
            invariant: all(row["invariants"][invariant] for row in pass_scenarios)
            for invariant in contract["invariants"]
        } if pass_scenarios else {invariant: False for invariant in contract["invariants"]},
    }


# --------------------------------------------------------------------------
# Negative controls: a known-good fixture plus every fail-closed mutation.
# --------------------------------------------------------------------------

def _valid_scenario(scenario_id: str, continuity: str, *, pid: int, generation: str,
                    epoch: int, sequence: int, approval_state: str = "pending") -> dict:
    def side(state: dict) -> dict:
        return state

    base = {
        "session_id": "byq-session-d15-runtime-0001",
        "trace_id": "byq-trace-d15-runtime-0001",
        "adapter_pid": pid,
        "adapter_generation": generation,
        "executor_epoch": epoch,
        "continuity": continuity,
        "goal": {
            "content_sha256": "a" * 64,
            "prompt_receipt": {"schema_version": "prompt-receipt.v1", "state": "accepted",
                               "run_id": "run-0001"},
        },
        "approval": {
            "approval_id": "agent_approval_" + "b" * 32,
            "state": approval_state,
            "bypassed": False,
            "decided_by": "human-owner",
            "initiator": "byq-product-agent-byq-session-d15-runtime-0001",
        },
        "action_receipts": [{
            "tool": "byq_agent_approval_request",
            "idempotency_key": "d15-runtime-idem-0001",
            "receipt": {"state": "accepted", "approval_id": "agent_approval_" + "b" * 32},
            "side_effect_count": 1,
            "replay": {
                "receipt": {"state": "accepted", "approval_id": "agent_approval_" + "b" * 32},
                "side_effect_count": 1,
            },
        }],
        "result": {
            "run_id": "run-0001",
            "status": "completed",
            "sequence": sequence,
            "trace_contiguous": True,
        },
    }
    return {
        "id": scenario_id,
        "result": "PASS",
        "fault_applied": True,
        "before": copy.deepcopy(base),
        "after": side(copy.deepcopy(base)),
        "evidence": [f"docs/evidence/d15/d15-runtime/{scenario_id}.v1.json"],
    }


def valid_fixture(contract: dict) -> dict:
    scenarios = []
    for index, spec in enumerate(contract["required_scenarios"]):
        continuity = spec["allowed_continuity"][0]
        scenarios.append(_valid_scenario(
            spec["id"], continuity, pid=2000 + index, generation=f"generation-fixture-{index}",
            epoch=1, sequence=10 + index,
            approval_state="pending" if index != 3 else "approved"))
    return {
        "schema_version": "byq-d15-runtime-observations.v1",
        "candidate": dict(contract["candidate"]),
        "llm": {"class": contract["llm_evidence_class"], "real_llm_quality": False,
                "note": "negative-control fixture"},
        "scenarios": scenarios,
    }


def _mutations(fixture: dict) -> list[tuple[str, dict]]:
    mutations: list[tuple[str, dict]] = []

    def add(name: str, mutate) -> None:
        value = copy.deepcopy(fixture)
        mutate(value)
        mutations.append((name, value))

    add("missing-required-scenario", lambda v: v["scenarios"].pop(0))
    add("duplicate-scenario-id", lambda v: v["scenarios"].append(copy.deepcopy(v["scenarios"][0])))
    add("unknown-scenario-id", lambda v: v["scenarios"][0].update({"id": "invented-scenario"}))
    add("missing-evidence-field", lambda v: v["scenarios"][0]["after"].pop("goal"))
    add("original-goal-drift", lambda v: v["scenarios"][0]["after"]["goal"].update(
        {"content_sha256": "c" * 64}))
    add("duplicate-side-effect", lambda v: v["scenarios"][0]["after"]["action_receipts"][0].update(
        {"side_effect_count": 2}))
    add("replay-did-not-deduplicate", lambda v: v["scenarios"][0]["after"]["action_receipts"][0][
        "replay"].update({"side_effect_count": 2}))
    add("changed-replay-receipt", lambda v: v["scenarios"][0]["after"]["action_receipts"][0][
        "replay"].update({"receipt": {"state": "accepted", "approval_id": "other"}}))
    add("approval-bypassed", lambda v: v["scenarios"][0]["after"]["approval"].update({"bypassed": True}))
    add("expired-approval-reuse", lambda v: v["scenarios"][0]["after"]["approval"].update(
        {"state": "expired", "reuse_denied": False}))
    add("initiator-self-approval", lambda v: v["scenarios"][0]["after"]["approval"].update(
        {"decided_by": v["scenarios"][0]["after"]["approval"]["initiator"]}))
    add("fabricated-fresh-continuity", lambda v: v["scenarios"][0]["after"].update(
        {"continuity": "fresh"}))
    add("sequence-regression", lambda v: v["scenarios"][0]["after"]["result"].update(
        {"sequence": v["scenarios"][0]["before"]["result"]["sequence"] - 1}))
    add("non-contiguous-trace", lambda v: v["scenarios"][0]["after"]["result"].update(
        {"trace_contiguous": False}))
    add("not-run-without-reason", lambda v: v["scenarios"][0].update(
        {"result": "NOT_RUN", "fault_applied": False}))
    add("candidate-mismatch", lambda v: v.update({"candidate": {"release": "dsh-0.1.2rc1"}}))
    add("llm-claims-real-quality", lambda v: v["llm"].update(
        {"class": "real-llm", "real_llm_quality": True}))
    add("fault-not-applied", lambda v: v["scenarios"][0].update({"fault_applied": False}))
    return mutations


def run_selfcheck(contract: dict) -> dict:
    fixture = valid_fixture(contract)
    baseline = compute_verdict(contract, fixture)
    controls = []
    for name, mutated in _mutations(fixture):
        verdict = compute_verdict(contract, mutated)
        controls.append({
            "control": name,
            "pre_fix_would_pass": True,
            "observed_all_pass": verdict["all_pass"],
            "observed_exit_code": verdict["exit_code"],
            "first_failure": verdict["failures"][0] if verdict["failures"] else None,
            "passes": verdict["all_pass"] is False,
        })
    all_controls_pass = all(item["passes"] for item in controls)
    result = {
        "schema_version": "byq-d15-runtime-negative-controls.v1",
        "baseline_all_pass": baseline["all_pass"],
        "baseline_exit_code": baseline["exit_code"],
        "control_count": len(controls),
        "all_controls_pass": all_controls_pass,
        "controls": controls,
    }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--observations", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--selfcheck", action="store_true",
                        help="run negative controls over a known-good fixture and fail if any does not fail")
    args = parser.parse_args(argv)

    try:
        contract = _load(args.contract)
    except Failure as exc:
        print(json.dumps({"all_pass": False, "error": str(exc)}, indent=2))
        return 2

    if args.selfcheck:
        result = run_selfcheck(contract)
        payload = json.dumps(result, indent=2, sort_keys=True)
        if args.out:
            args.out.write_text(payload + "\n", encoding="utf-8")
        print(payload)
        return 0 if result["all_controls_pass"] and result["baseline_all_pass"] else 1

    if args.observations is None:
        parser.error("--observations is required unless --selfcheck is used")
    try:
        observations = _load(args.observations)
    except Failure as exc:
        print(json.dumps({"all_pass": False, "error": str(exc)}, indent=2))
        return 2

    verdict = compute_verdict(contract, observations)
    payload = json.dumps(verdict, indent=2, sort_keys=True)
    if args.out:
        args.out.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return verdict["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
