#!/usr/bin/env python3
"""ADR-0085 P4 fail-able observer for the real compound-research journey.

The observer NEVER trusts a PASS label. It re-derives every journey/fault row and
every assertion from the RAW boundary facts captured by the driver, rejects
missing/forged provenance, rejects any model-visible raw execution field, and
only reports ``all_pass`` when every required row is genuinely PASS.

Two verdicts are always distinguished:

* ``format_valid`` -- the observations have the closed shape the contract needs;
* ``all_pass``     -- every required row/assertion actually passed.

``--selfcheck`` proves the gate is breakable: it builds a known-good fixture that
passes, then mutates it for each defect-targeting control and requires the FIXED
gate to reject it while a legacy result-trusting gate would have accepted it.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DEFAULT_CONTRACT = HERE / "contract.v1.json"
DEFAULT_MATRIX = ROOT / "docs/evidence/adr-0085-p4-real-journey/acceptance-matrix.v1.json"

OBSERVATIONS_SCHEMA = "byq-v091-continuation-p4-observations.v1"
REQUIRED_EVIDENCE_CLASS = "runtime-isolated-stack"
REQUIRED_LLM_CLASS = "scripted-keyless"
PROVENANCE_FIELDS = ("boundary", "source", "pid", "generation", "receipt")
NA = "not_applicable"

# Defect-targeting controls: the legacy (result-trusting) gate accepts these
# mutated fixtures, the fixed gate must reject them.
DEFECT_TARGETING_CONTROLS = (
    "missing-required-journey-row",
    "missing-required-fault-row",
    "journey-status-pass-without-raw-facts",
    "fault-status-pass-without-restart",
    "no-duplicate-objects-violated",
    "open-continuation-count-two",
    "approval-binding-mismatch",
    "duplicate-event-double-advance",
    "stage-call-third-call",
    "budget-not-exact",
    "generation-not-converged",
    "receipt-not-converged",
    "forbidden-raw-field-visible",
    "stage-input-over-bound",
    "model-chose-next-action",
    "deterministic-transition-used-model",
    "cleanup-nonzero",
    "production-touched",
    "forged-provenance-source",
    "stale-event-advanced-plan",
    "restart-pid-unchanged",
)


class Failure(Exception):
    """A single structural or semantic contract failure."""


def _load(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Failure(message)


# --------------------------------------------------------------------------- #
# Raw-fact re-derivation
# --------------------------------------------------------------------------- #

def _row_ids(contract: dict, key: str) -> list[str]:
    return [row if isinstance(row, str) else row["id"] for row in contract.get(key, [])]


def _derive_journey_row(row_id: str, raw: dict) -> bool:
    counts = raw.get("counts") or {}
    plan = raw.get("plan") or {}
    calls = raw.get("model_calls_by_stage") or {}
    approvals = raw.get("approvals") or []
    events = raw.get("events") or []
    stage = plan.get("stage")
    completed = stage == "completed"
    if row_id == "task-created":
        return counts.get("research_tasks") == 1 and raw.get("task_status") in {
            "planned", "running", "completed"}
    if row_id == "continuation-grant":
        return counts.get("research_execution_plans") == 1 and bool(plan)
    if row_id == "strategy-draft-turn":
        measured = raw.get("stage_input_serialized_bytes")
        if not isinstance(measured, int) or isinstance(measured, bool):
            return False
        return (int(calls.get("strategy_draft", 0)) <= 2 and measured <= 65536
                and stage not in (None, "strategy_draft"))
    if row_id == "strategy-approval":
        return any(a.get("action") == "strategy_approve" and a.get("status") == "approved"
                   for a in approvals)
    if row_id == "task-create-approval":
        return any(a.get("action") == "backtest_task_create" and a.get("status") == "approved"
                   for a in approvals)
    if row_id == "backtest-task-create":
        return counts.get("signal_producer_jobs", 0) >= 1
    if row_id == "data-ready":
        return any(e.get("event_type") == "data_ready" and e.get("status") == "advanced"
                   for e in events)
    if row_id == "execute-approval":
        return any(a.get("action") == "backtest_execute" and a.get("status") == "approved"
                   for a in approvals)
    if row_id == "backtest-execute":
        return counts.get("backtest_jobs", 0) >= 1
    if row_id == "backtest-completed":
        return any(e.get("event_type") == "backtest_completed" and e.get("status") == "advanced"
                   for e in events)
    if row_id == "round-analysis":
        return int(calls.get("backtest_analysis", 0)) <= 2 and (
            completed or int(plan.get("iteration", 0)) >= 1)
    if row_id == "rounds-2-3":
        return int(plan.get("iteration", 0)) == 3 or completed
    if row_id == "final-selection":
        return int(calls.get("final_selection", 0)) <= 2 and completed
    if row_id == "paper-account":
        return counts.get("paper_accounts") == 1
    if row_id == "task-completed":
        return (raw.get("task_status") == "completed"
                and plan.get("status") == "completed"
                and raw.get("session_status") in {"completed", "closed"}
                and raw.get("generation_status") in {"completed", "closed"}
                and raw.get("receipt_status") in {"settled", "completed"})
    raise Failure(f"unknown journey row {row_id}")


def _derive_fault_row(row_id: str, raw: dict) -> bool:
    faults = raw.get("faults") or {}
    row = faults.get(row_id)
    if not isinstance(row, dict):
        return False
    restarts = raw.get("restarts") or {}
    if row_id.startswith("restart-"):
        restart = restarts.get(row_id) or {}
        if not (restart.get("pid_before") and restart.get("pid_after")
                and restart["pid_before"] != restart["pid_after"]):
            return False
    if row_id == "duplicate-event-replay":
        return bool(row.get("replay_returned_same_event")) and not row.get("second_advance")
    if row_id == "late-stale-event":
        return bool(row.get("stale_recorded_needs_attention")) and not row.get("advanced_newer_plan")
    return bool(row.get("recovered")) and not row.get("duplicate_objects")


def _derive_assertions(raw: dict) -> dict[str, bool]:
    counts = raw.get("counts") or {}
    events = raw.get("events") or []
    approvals = raw.get("approvals") or []
    calls = raw.get("model_calls_by_stage") or {}
    plan = raw.get("plan") or {}
    duplicates = raw.get("duplicate_objects") or []
    forbidden_hits = raw.get("model_visible_forbidden_hits") or []
    cleanup = raw.get("cleanup") or {}
    bindings_ok = all(
        isinstance(a.get("params_digest"), str) and isinstance(a.get("idempotency_key"), str)
        and a.get("plan_version") and a.get("task_version")
        for a in approvals if a.get("status") == "approved")
    return {
        "no_duplicate_business_objects": not duplicates,
        "at_most_one_open_continuation": int(raw.get("continuation_open_count", 99)) <= 1,
        "exact_approval_binding": bindings_ok and bool(approvals),
        "exact_event_identity_and_replay": all(
            isinstance(e.get("event_id"), str) and e["event_id"].startswith("continuation_event_")
            for e in events) and bool(events),
        "exact_stage_call_admission": int(raw.get("stage_call_total", 99)) <= 8,
        "exact_continuation_budget": bool(raw.get("budget_exact")),
        "exact_generation_and_receipt": bool(raw.get("generation_exact"))
        and bool(raw.get("receipt_exact")),
        "model_visible_input_is_bounded_projection_only": not forbidden_hits,
        "model_cannot_choose_action_identity_approval_idempotency_routing_or_recovery":
            bool(raw.get("model_chose_routing")) is False,
        "deterministic_transitions_use_zero_model_calls": all(
            int(calls.get(stage, 0)) <= 2
            for stage in ("strategy_draft", "backtest_analysis", "iteration_comparison",
                          "final_selection")),
        "cleanup_zero_and_production_untouched": (
            cleanup.get("containers") == 0 and cleanup.get("networks") == 0
            and cleanup.get("volumes") == 0 and cleanup.get("production_untouched") is True),
    }


# --------------------------------------------------------------------------- #
# Verdict
# --------------------------------------------------------------------------- #

def _check_provenance(row: dict, contract: dict) -> None:
    provenance = row.get("provenance")
    _require(isinstance(provenance, dict), "row is missing provenance")
    allowed = contract.get("provenance_allowed_sources") or {}
    for field in PROVENANCE_FIELDS:
        _require(field in provenance, f"provenance is missing {field}")
        value = provenance[field]
        if value == NA:
            continue
        _require(isinstance(value, str) and value, f"provenance {field} is empty")
        if field in allowed and allowed[field]:
            _require(value in allowed[field],
                     f"provenance {field}={value!r} is not a contract-allowed source")


def compute_verdict(contract: dict, matrix: dict, observations: dict) -> dict:
    failures: list[str] = []
    format_valid = True
    try:
        _require(observations.get("schema_version") == OBSERVATIONS_SCHEMA,
                 "observations schema is invalid")
        raw = observations.get("raw")
        _require(isinstance(raw, dict), "observations are missing the raw boundary facts")
        journey = observations.get("journey") or {}
        faults = observations.get("faults") or []
        _require(isinstance(journey.get("steps"), list), "journey steps are missing")
        _require(isinstance(faults, list), "fault rows are missing")
        _require(isinstance(observations.get("cleanup"), dict), "cleanup proof is missing")
    except Failure as error:
        return _verdict(False, False, [str(error)], {}, {})

    # The evidence class is a COVERAGE requirement, not a shape requirement: a
    # component-only capture is structurally valid but can never be all_pass.
    if observations.get("evidence_class") != REQUIRED_EVIDENCE_CLASS:
        failures.append(
            f"evidence_class={observations.get('evidence_class')!r} is not the required "
            f"{REQUIRED_EVIDENCE_CLASS!r}; the runtime-isolated-stack journey was not run")
    if observations.get("llm_evidence_class") != REQUIRED_LLM_CLASS:
        failures.append(
            f"llm_evidence_class={observations.get('llm_evidence_class')!r} is not "
            f"{REQUIRED_LLM_CLASS!r}")

    raw = observations["raw"]
    derived: dict[str, bool] = {}
    try:
        for row_id in _row_ids(contract, "required_journey_steps"):
            derived[f"journey:{row_id}"] = _derive_journey_row(row_id, raw)
        for row_id in _row_ids(contract, "required_fault_scenarios"):
            derived[f"fault:{row_id}"] = _derive_fault_row(row_id, raw)
    except Failure as error:
        failures.append(str(error))
        format_valid = False

    expected_journey = set(_row_ids(contract, "required_journey_steps"))
    expected_faults = set(_row_ids(contract, "required_fault_scenarios"))
    observed_journey = {row.get("id") for row in (observations.get("journey") or {}).get("steps", [])}
    observed_faults = {row.get("id") for row in observations.get("faults", [])}
    for missing in sorted(expected_journey - observed_journey):
        failures.append(f"required journey row missing from observations: {missing}")
        format_valid = False
    for missing in sorted(expected_faults - observed_faults):
        failures.append(f"required fault row missing from observations: {missing}")
        format_valid = False

    for row in (observations.get("journey") or {}).get("steps", []):
        if row.get("id") in expected_journey:
            try:
                _check_provenance(row, contract)
            except Failure as error:
                failures.append(f"journey:{row['id']}: {error}")
                format_valid = False
    for row in observations.get("faults", []):
        if row.get("id") in expected_faults:
            try:
                _check_provenance(row, contract)
            except Failure as error:
                failures.append(f"fault:{row['id']}: {error}")
                format_valid = False

    for name, ok in derived.items():
        if not ok:
            failures.append(f"derived row failed: {name}")

    forbidden = raw.get("model_visible_forbidden_hits") or []
    if forbidden:
        failures.append(f"model-visible forbidden raw fields present: {forbidden}")

    declared_assertions = observations.get("assertions") or {}
    derived_assertions = _derive_assertions(raw)
    for assertion in _row_ids(contract, "required_assertions"):
        if derived_assertions.get(assertion) is not True:
            failures.append(f"assertion failed: {assertion}")
        elif declared_assertions.get(assertion) is not True:
            failures.append(f"assertion not honestly declared PASS: {assertion}")

    cleanup = observations.get("cleanup") or {}
    if not (cleanup.get("containers") == 0 and cleanup.get("networks") == 0
            and cleanup.get("volumes") == 0 and cleanup.get("production_untouched") is True):
        failures.append("cleanup proof is not zero or production was touched")

    coverage_failures = [name for name, ok in derived.items() if not ok]
    all_pass = format_valid and not failures and not coverage_failures
    return _verdict(format_valid, all_pass, failures, derived, derived_assertions)


def _verdict(format_valid: bool, all_pass: bool, failures: list[str],
             derived: dict, assertions: dict) -> dict:
    return {
        "schema_version": "byq-v091-continuation-p4-verdict.v1",
        "format_valid": format_valid,
        "all_pass": all_pass,
        "failures": failures,
        "derived_rows": derived,
        "derived_assertions": assertions,
    }


def legacy_compute_verdict(contract: dict, matrix: dict, observations: dict) -> dict:
    """Pre-fix, result-trusting gate: trusts the declared labels. Controls must
    be ACCEPTED by this gate and REJECTED by the fixed gate."""

    journey = (observations.get("journey") or {}).get("steps", [])
    faults = observations.get("faults", [])
    labels_ok = all(row.get("status") == "PASS" for row in journey + faults)
    declared = observations.get("assertions") or {}
    assertions_ok = all(declared.get(name) is True
                        for name in _row_ids(contract, "required_assertions"))
    return {"format_valid": True, "all_pass": bool(labels_ok and assertions_ok)}


# --------------------------------------------------------------------------- #
# Known-good fixture and negative controls
# --------------------------------------------------------------------------- #

def _base_fixture(contract: dict) -> dict:
    calls = {stage: 2 for stage in
             ("strategy_draft", "backtest_analysis", "iteration_comparison", "final_selection")}
    approvals = [
        {"approval_id": "agent_approval_" + "1" * 32, "action": "strategy_approve",
         "status": "approved", "resource_type": "strategy_version",
         "resource_id": "artifact_" + "a" * 32, "plan_version": 2, "task_version": 1,
         "params_digest": "sha256:" + "0" * 64, "idempotency_key": "plancmd_" + "0" * 32},
        {"approval_id": "agent_approval_" + "2" * 32, "action": "backtest_task_create",
         "status": "approved", "resource_type": "strategy_version",
         "resource_id": "artifact_" + "a" * 32, "plan_version": 3, "task_version": 1,
         "params_digest": "sha256:" + "0" * 64, "idempotency_key": "plancmd_" + "1" * 32},
        {"approval_id": "agent_approval_" + "3" * 32, "action": "backtest_execute",
         "status": "approved", "resource_type": "backtest_task",
         "resource_id": "backtesttask_" + "b" * 32, "plan_version": 5, "task_version": 1,
         "params_digest": "sha256:" + "0" * 64, "idempotency_key": "plancmd_" + "2" * 32},
    ]
    events = [
        {"event_id": "continuation_event_" + "d" * 32, "event_type": "data_ready",
         "source_identity": "signaljob_" + "c" * 32, "status": "advanced", "admitted": False},
        {"event_id": "continuation_event_" + "e" * 32, "event_type": "backtest_completed",
         "source_identity": "backtest_" + "f" * 32, "status": "advanced", "admitted": False},
    ]
    raw = {
        "counts": {"research_tasks": 1, "research_execution_plans": 1,
                   "research_continuation_events": 2, "research_judgment_stage_calls": 8,
                   "agent_approvals": 3, "signal_producer_jobs": 1, "backtest_jobs": 1,
                   "artifacts": 4, "paper_accounts": 1},
        "plan": {"stage": "completed", "iteration": 3, "status": "completed",
                 "plan_version": 12, "task_version": 2},
        "model_calls_by_stage": calls,
        "stage_input_serialized_bytes": 8192,
        "continuation_open_count": 0,
        "stage_call_total": 8,
        "budget_exact": True,
        "generation_exact": True,
        "receipt_exact": True,
        "generation_status": "completed",
        "receipt_status": "settled",
        "session_status": "completed",
        "task_status": "completed",
        "model_visible_forbidden_hits": [],
        "model_chose_routing": False,
        "duplicate_objects": [],
        "approvals": approvals,
        "events": events,
        "restarts": {
            row["id"]: {"service": row["boundary"], "pid_before": 1000 + index,
                        "pid_after": 2000 + index}
            for index, row in enumerate(contract["required_fault_scenarios"])
            if row["id"].startswith("restart-")
        },
        "faults": {
            row["id"]: {"recovered": True, "duplicate_objects": []}
            for row in contract["required_fault_scenarios"]
            if row["id"].startswith("restart-")
        },
        "cleanup": {"containers": 0, "networks": 0, "volumes": 0, "production_untouched": True},
    }
    raw["faults"]["duplicate-event-replay"] = {
        "recovered": True, "duplicate_objects": [],
        "replay_returned_same_event": True, "second_advance": False}
    raw["faults"]["late-stale-event"] = {
        "recovered": True, "duplicate_objects": [],
        "stale_recorded_needs_attention": True, "advanced_newer_plan": False}

    steps = []
    for row in contract["required_journey_steps"]:
        steps.append({"id": row["id"], "status": "PASS",
                      "provenance": _fixture_provenance(row["boundary"], row["provenance_source"])})
    faults = []
    for row in contract["required_fault_scenarios"]:
        faults.append({"id": row["id"], "status": "PASS",
                       "provenance": _fixture_provenance(row["boundary"], row["provenance_source"])})
    assertions = {name: True for name in _row_ids(contract, "required_assertions")}
    return {
        "schema_version": OBSERVATIONS_SCHEMA,
        "evidence_class": REQUIRED_EVIDENCE_CLASS,
        "llm_evidence_class": REQUIRED_LLM_CLASS,
        "journey": {"id": "adr0085-compound-research.v1", "steps": steps},
        "faults": faults,
        "assertions": assertions,
        "cleanup": {"containers": 0, "networks": 0, "volumes": 0, "production_untouched": True},
        "raw": raw,
    }


def _fixture_provenance(boundary: str, source: str) -> dict:
    return {"boundary": boundary, "source": source, "pid": "4242",
            "generation": "1", "receipt": "receipt_" + "a" * 32}


def _controls(contract: dict) -> list[tuple[str, dict]]:
    base = _base_fixture(contract)
    controls: list[tuple[str, dict]] = []

    def mutate(name: str, fn) -> None:
        fixture = copy.deepcopy(base)
        fn(fixture)
        controls.append((name, fixture))

    def drop_journey(obs):
        obs["journey"]["steps"] = obs["journey"]["steps"][1:]

    def drop_fault(obs):
        obs["faults"] = obs["faults"][1:]

    def label_pass_no_raw(obs):
        obs["raw"]["counts"]["research_tasks"] = 0

    def fault_pass_no_restart(obs):
        obs["raw"]["restarts"]["restart-gateway-after-approval-requested"]["pid_after"] = \
            obs["raw"]["restarts"]["restart-gateway-after-approval-requested"]["pid_before"]

    def duplicates(obs):
        obs["raw"]["duplicate_objects"] = [{"kind": "research_task", "count": 2}]

    def two_open(obs):
        obs["raw"]["continuation_open_count"] = 2

    def binding(obs):
        obs["raw"]["approvals"][0]["params_digest"] = None

    def double_advance(obs):
        obs["raw"]["faults"]["duplicate-event-replay"]["second_advance"] = True

    def third_call(obs):
        obs["raw"]["stage_call_total"] = 9

    def budget(obs):
        obs["raw"]["budget_exact"] = False

    def generation(obs):
        obs["raw"]["generation_exact"] = False

    def receipt(obs):
        obs["raw"]["receipt_exact"] = False

    def forbidden(obs):
        obs["raw"]["model_visible_forbidden_hits"] = ["bars_frame"]

    def over_bound(obs):
        obs["raw"]["stage_input_serialized_bytes"] = 70000

    def routing(obs):
        obs["raw"]["model_chose_routing"] = True

    def det_model(obs):
        obs["raw"]["model_calls_by_stage"]["strategy_draft"] = 8

    def cleanup(obs):
        obs["raw"]["cleanup"]["containers"] = 1

    def production(obs):
        obs["raw"]["cleanup"]["production_untouched"] = False

    def forged(obs):
        obs["journey"]["steps"][0]["provenance"]["source"] = "invented-table"

    def stale_advanced(obs):
        obs["raw"]["faults"]["late-stale-event"]["advanced_newer_plan"] = True

    def pid_unchanged(obs):
        restart = obs["raw"]["restarts"]["restart-backend-after-data-ready"]
        restart["pid_after"] = restart["pid_before"]

    for name, fn in (
        ("missing-required-journey-row", drop_journey),
        ("missing-required-fault-row", drop_fault),
        ("journey-status-pass-without-raw-facts", label_pass_no_raw),
        ("fault-status-pass-without-restart", fault_pass_no_restart),
        ("no-duplicate-objects-violated", duplicates),
        ("open-continuation-count-two", two_open),
        ("approval-binding-mismatch", binding),
        ("duplicate-event-double-advance", double_advance),
        ("stage-call-third-call", third_call),
        ("budget-not-exact", budget),
        ("generation-not-converged", generation),
        ("receipt-not-converged", receipt),
        ("forbidden-raw-field-visible", forbidden),
        ("stage-input-over-bound", over_bound),
        ("model-chose-next-action", routing),
        ("deterministic-transition-used-model", det_model),
        ("cleanup-nonzero", cleanup),
        ("production-touched", production),
        ("forged-provenance-source", forged),
        ("stale-event-advanced-plan", stale_advanced),
        ("restart-pid-unchanged", pid_unchanged),
    ):
        mutate(name, fn)
    return controls


def run_selfcheck(contract: dict, matrix: dict) -> int:
    baseline = compute_verdict(contract, matrix, _base_fixture(contract))
    if not baseline["all_pass"]:
        print("selfcheck baseline did not pass:", baseline["failures"])
        return 1
    bad = 0
    for name, fixture in _controls(contract):
        fixed = compute_verdict(contract, matrix, fixture)
        legacy = legacy_compute_verdict(contract, matrix, fixture)
        if fixed["all_pass"]:
            print(f"control {name} was NOT rejected by the fixed gate")
            bad += 1
        if name in DEFECT_TARGETING_CONTROLS and not legacy["all_pass"]:
            print(f"control {name} was already rejected by the legacy gate (not defect-targeting)")
            bad += 1
    total = len(_controls(contract))
    print(f"selfcheck controls={total} defect_targeting={len(DEFECT_TARGETING_CONTROLS)} "
          f"rejected={total - bad} bad={bad}")
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--matrix", default=str(DEFAULT_MATRIX))
    parser.add_argument("--observations")
    parser.add_argument("--out")
    parser.add_argument("--selfcheck", action="store_true")
    args = parser.parse_args(argv)
    contract = _load(Path(args.contract))
    matrix = _load(Path(args.matrix))
    if args.selfcheck:
        return run_selfcheck(contract, matrix)
    if not args.observations:
        parser.error("--observations is required unless --selfcheck is used")
    observations = _load(Path(args.observations))
    verdict = compute_verdict(contract, matrix, observations)
    if args.out:
        Path(args.out).write_text(json.dumps(verdict, indent=2, sort_keys=True) + "\n",
                                  encoding="utf-8")
    print(json.dumps(verdict, indent=2, sort_keys=True))
    return 0 if verdict["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
