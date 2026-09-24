#!/usr/bin/env python3
"""ADR-0085 P4-B fail-able observer for the NORMAL three-round journey.

The observer NEVER trusts a PASS label. It re-derives every journey/gate row and
every assertion from the RAW boundary facts captured by the driver, rejects a
missing/forged provenance source, rejects any model-visible raw execution field
and only reports ``all_pass`` when every required row/assertion genuinely holds.

``--selfcheck`` proves the gate is breakable: it takes the committed known-good
observations, mutates them for each defect-targeting control, and requires the
FIXED gate to reject every mutation while a legacy label-trusting gate accepts it.
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
DEFAULT_OBSERVATIONS = (
    ROOT / "docs/evidence/adr-0085-p4b-normal-journey/observations.v1.json")

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
try:  # The trusted per-stage profile registry is the single source of truth.
    from packages.contracts.research_request_budget import REQUEST_PROFILES
except Exception:  # noqa: BLE001
    REQUEST_PROFILES = {}

OBSERVATIONS_SCHEMA = "byq-v091-continuation-p4b-observations.v1"
REQUIRED_EVIDENCE_CLASS = "runtime-isolated-stack"
REQUIRED_LLM_CLASS = "scripted-keyless"
JUDGMENT_STAGES = ("strategy_draft", "backtest_analysis", "iteration_comparison", "final_selection")

DEFECT_TARGETING_CONTROLS = (
    "task-not-created", "plan-not-created", "strategy-approval-missing",
    "data-ready-missing", "rounds-incomplete", "task-not-completed",
    "duplicate-business-object", "approval-binding-missing",
    "forbidden-raw-field-visible", "projection-over-bound", "child-tool-not-read-only",
    "deterministic-stage-used-model", "gate-limits-missing", "gate-profile-missing",
    "gate-profile-forged-evidence", "gate-profile-forged-limit",
    "gate-child-not-covered",
    "gate-blocked-receipt-present", "gate-shared-request-budget",
    "gate-negative-controls-not-blocked", "paper-account-without-approval",
    "paper-account-approval-missing", "paper-account-binding-wrong-resource",
    "paper-account-replay-second-account", "paper-account-params-digest-mismatch",
    "paper-account-params-key-mismatch", "paper-account-created-order",
    "paper-account-used-model",
    "gate-actual-usage-missing",
    "gate-declared-as-actual", "gate-actual-over-ceiling-forwarded",
    "gate-not-forwarded-result", "gate-unknown-usage-forwarded",
    "cleanup-nonzero", "production-touched",
)


class Failure(Exception):
    pass


def _load(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Failure(message)


def _turn_stage(turn: dict) -> str:
    attempt = turn.get("attempt") or ""
    parts = attempt.split(":")
    return parts[1] if len(parts) == 3 else ""


def _approved(approvals: list) -> list:
    return [a for a in approvals if a.get("status") == "approved"]


# --------------------------------------------------------------------------- #
# Raw-fact re-derivation
# --------------------------------------------------------------------------- #

def _derive_journey(raw: dict) -> dict:
    counts = raw.get("counts") or {}
    plan = raw.get("plan") or {}
    turns = raw.get("turns") or []
    approvals = raw.get("approvals") or []
    events = raw.get("events") or []
    rounds = raw.get("rounds") or []
    approved = {a.get("action") for a in _approved(approvals)}

    def turn_ok(stage: str) -> bool:
        return any(_turn_stage(t) == stage and t.get("status") == 200 for t in turns)

    def event_ok(event_type: str) -> bool:
        return any(e.get("event_type") == event_type and e.get("status") == "advanced"
                   for e in events)

    return {
        "task-created": counts.get("research_tasks") == 1
        and raw.get("task_status") in {"running", "completed"},
        "continuation-grant": counts.get("research_execution_plans") == 1 and bool(plan),
        "strategy-draft-turn": turn_ok("strategy_draft"),
        "strategy-approval": "byq_strategy_approve" in approved,
        "task-create-approval": "byq_backtest_task_create" in approved,
        "backtest-task-create": int(counts.get("signal_producer_jobs", 0)) >= 1,
        "data-ready": event_ok("data_ready"),
        "execute-approval": "byq_backtest_task_execute" in approved,
        "backtest-execute": int(counts.get("backtest_jobs", 0)) >= 1,
        "backtest-completed": event_ok("backtest_completed"),
        "round-analysis": sum(1 for t in turns
                              if _turn_stage(t) == "backtest_analysis" and t.get("status") == 200) == 3,
        "rounds-2-3": plan.get("iteration") == 3
        and {r.get("iteration") for r in rounds} == {1, 2, 3},
        "final-selection": turn_ok("final_selection") and plan.get("stage") in {
            "waiting_for_paper_account_approval", "ready_to_create_paper_account",
            "completed"},
        # Honest fail-closed: the current closed plan/approval contracts have NO
        # paper-account gate/approval action, so an account with no exact bound
        # approval can never be reported PASS.
        "paper-account": _paper_account_bound(raw),
        "task-completed": raw.get("task_status") == "completed"
        and plan.get("status") == "completed" and plan.get("stage") == "completed",
    }


def _paper_account_bound(raw: dict) -> bool:
    account = raw.get("paper_account") or {}
    if int((raw.get("counts") or {}).get("paper_accounts", 0)) != 1:
        return False
    if account.get("approval_object_present") is not True:
        return False
    approval_id = account.get("approval_id")
    approvals = raw.get("approvals") or []
    paper = [a for a in approvals if a.get("action") == "byq_paper_account_create"
             and a.get("status") == "approved" and a.get("approval_id") == approval_id]
    if not paper:
        return False
    pa = paper[0]
    if (pa.get("plan_action") != "create_paper_account"
            or pa.get("plan_resource_kind") != "research_task"
            or pa.get("plan_resource_id") != raw.get("task_id")):
        return False
    if not (isinstance(pa.get("plan_params_digest"), str)
            and pa["plan_params_digest"].startswith("sha256:")):
        return False
    if not (isinstance(pa.get("plan_command_key_sha256"), str)
            and pa["plan_command_key_sha256"].startswith("sha256:")):
        return False
    if not (isinstance(pa.get("plan_command_alias"), str)
            and pa["plan_command_alias"].startswith("plancmd-audit-")):
        return False
    if not (pa.get("plan_version") and pa.get("plan_task_version")):
        return False
    # ADR-0087 exact freeze: the executed params digest/key MUST equal the frozen
    # approved binding; a different-but-valid digest/key fails.
    params = account.get("params") or {}
    if params.get("action") != "create_paper_account":
        return False
    if params.get("resource_kind") != "research_task" or params.get("resource_id") != raw.get("task_id"):
        return False
    if params.get("params_digest") != pa.get("plan_params_digest"):
        return False
    if account.get("params_idempotency_key_sha256") != pa.get("plan_command_key_sha256"):
        return False
    approval_plan_version = account.get("approval_plan_version")
    if not isinstance(approval_plan_version, int) or \
            params.get("plan_version") != approval_plan_version + 1:
        return False
    account_id = account.get("account_id")
    if not isinstance(account_id, str) or not account_id.startswith("paper_account_"):
        return False
    if account.get("replay_same_account") is not True:
        return False
    if account.get("apply_replay_same_projection") is not True:
        return False
    if account.get("zero_model_calls") is not True:
        return False
    return account.get("orders") == account.get("positions") == account.get("fills") == 0


_PROFILE_FIELDS = ("max_provider_calls", "max_attempts", "max_input_bytes",
                   "max_output_tokens", "max_tool_payload_bytes", "max_concurrent")


def _budget_matches_profile(budget: dict) -> bool:
    """Exact trusted-profile binding: id + stage + evidence + every dimension."""

    profile_id = budget.get("profile_id")
    profile = REQUEST_PROFILES.get(profile_id) if isinstance(profile_id, str) else None
    if profile is None:
        return False
    if budget.get("stage") != profile["stage"] or budget.get("evidence") != profile["evidence"]:
        return False
    if any(budget.get(field) != profile[field] for field in _PROFILE_FIELDS):
        return False
    return isinstance(budget.get("deadline_at_ms"), int) and budget["deadline_at_ms"] > 0


def _derive_gate(raw: dict) -> dict:
    turns = raw.get("turns") or []
    journal = raw.get("gate_journal") or {}
    limits = [((t.get("request_gate") or {}).get("limits")) for t in turns]
    limits_declared = bool(turns) and all(
        isinstance(budget, dict)
        and _budget_matches_profile(budget)
        for budget in limits)
    receipts = [row for rows in journal.values() for row in rows]
    roles = {row.get("role") for row in receipts}
    root_and_child = roles == {"root", "child"} and bool(receipts) and all(
        row.get("admitted") is True and row.get("reason") == "within_request_budget"
        for row in receipts)
    ids = [budget.get("request_id") for budget in limits if isinstance(budget, dict)]
    request_scoped = (bool(ids) and len(set(ids)) == len(ids)
                      and all(isinstance(budget.get("max_provider_calls"), int)
                              and budget["max_provider_calls"] > 0
                              for budget in limits if isinstance(budget, dict))
                      and all(budget.get("stage") == _turn_stage(turn)
                              for budget, turn in zip(limits, turns)
                              if isinstance(budget, dict)))
    controls = (raw.get("gate_negative_controls") or {}).get("controls") or []
    blocks = bool((raw.get("gate_negative_controls") or {}).get("all_blocked")) \
        and len(controls) >= 6 and all(
            c.get("blocked") is True for c in controls
            if c.get("name") != "request_scoped_fresh_counters")
    return {
        "gate-limits-declared": limits_declared,
        "gate-root-and-child-covered": root_and_child,
        "gate-request-scoped": request_scoped,
        "gate-blocks-over-budget": blocks,
        "gate-usage-actual-vs-ceiling": _gate_usage_ok(raw),
    }


def _gate_usage_ok(raw: dict) -> bool:
    """ADR-0086 §3: receipts record the DECLARED ceiling and the ACTUAL usage.

    Actual usage must come from the provider response (or a structured
    ``unknown``); it is never the declared ceiling. A proven actual output over
    the declared ceiling, or a non-forwarded result, can never be reported PASS.
    """

    turns = raw.get("turns") or []
    if not turns:
        return False
    saw_provider_usage = False
    for turn in turns:
        calls = turn.get("calls") or []
        if not calls:
            return False
        for call in calls:
            declared = call.get("declared_max_output_tokens")
            actual = call.get("actual_output_tokens")
            if not isinstance(declared, int) or not isinstance(call.get("elapsed_ms"), int):
                return False
            if call.get("usage_source") == "provider_response":
                # A proven result must be within the declared ceiling and forwarded.
                saw_provider_usage = True
                if not isinstance(actual, int) or actual > declared:
                    return False
                if call.get("forwarded") is not True:
                    return False
            elif call.get("usage_source") == "unknown":
                # ADR-0086 §3: an unprovable result fails closed, never forwarded.
                if actual != "unknown" or call.get("forwarded") is not False:
                    return False
                if call.get("reason") != "actual_usage_unknown":
                    return False
            else:
                return False
    return saw_provider_usage


def _derive_assertions(raw: dict) -> dict:
    counts = raw.get("counts") or {}
    approvals = raw.get("approvals") or []
    events = raw.get("events") or []
    stage_calls = raw.get("stage_calls") or []
    turns = raw.get("turns") or []
    projections = raw.get("projections") or []
    cleanup = raw.get("cleanup") or {}
    approved = _approved(approvals)
    binding_ok = bool(approved) and all(
        isinstance(a.get("plan_params_digest"), str)
        and a["plan_params_digest"].startswith("sha256:")
        and isinstance(a.get("plan_command_alias"), str)
        and a["plan_command_alias"].startswith("plancmd-audit-")
        and a.get("plan_action") and a.get("plan_resource_kind") and a.get("plan_resource_id")
        and a.get("plan_version") and a.get("plan_task_version")
        for a in approved)
    event_ids = [e.get("event_id") for e in events]
    events_ok = bool(events) and all(
        isinstance(value, str) and value.startswith("continuation_event_")
        for value in event_ids) and len(set(event_ids)) == len(event_ids)
    stage_ok = bool(stage_calls) and len(stage_calls) == len(turns) and all(
        c.get("call_index") == 1 for c in stage_calls)
    projection_ok = bool(projections) and all(
        isinstance(p.get("bounded_input_bytes"), int) and p["bounded_input_bytes"] <= 65536
        and not p.get("forbidden_raw_hits") and p.get("child_tools_read_only") is True
        for p in projections) and not raw.get("model_visible_forbidden_hits")
    deterministic_ok = bool(turns) and all(
        t.get("provider_calls_delta") == 3 and _turn_stage(t) in JUDGMENT_STAGES
        for t in turns)
    return {
        "no_duplicate_business_objects": counts.get("research_tasks") == 1
        and counts.get("research_execution_plans") == 1
        and counts.get("paper_accounts") == 1 and not raw.get("duplicate_objects"),
        "exact_approval_binding": binding_ok,
        "exact_event_identity_and_replay": events_ok,
        "exact_stage_call_admission": stage_ok,
        "model_visible_input_is_bounded_projection_only": projection_ok,
        "deterministic_transitions_use_zero_model_calls": deterministic_ok,
        "request_gate_is_per_request_not_cross_process":
            _derive_gate(raw)["gate-request-scoped"],
        "paper_account_exact_approval_binding_and_idempotent_creation":
            _paper_account_bound(raw),
        "cleanup_zero_and_production_untouched": cleanup.get("containers") == 0
        and cleanup.get("networks") == 0 and cleanup.get("volumes") == 0
        and cleanup.get("production_untouched") is True,
    }


# --------------------------------------------------------------------------- #
# Verdict
# --------------------------------------------------------------------------- #

def compute_verdict(contract: dict, observations: dict) -> dict:
    failures: list[str] = []
    format_valid = True
    try:
        _require(observations.get("schema_version") == OBSERVATIONS_SCHEMA,
                 "observations schema is invalid")
        raw = observations.get("raw")
        _require(isinstance(raw, dict), "observations are missing raw boundary facts")
        _require(isinstance(raw.get("journey"), list) or isinstance(observations.get("journey"), dict),
                 "journey is missing")
    except Failure as error:
        return _verdict(False, False, [str(error)], {}, {})
    if observations.get("evidence_class") != REQUIRED_EVIDENCE_CLASS:
        failures.append("evidence_class is not the required runtime-isolated-stack")
    if observations.get("llm_evidence_class") != REQUIRED_LLM_CLASS:
        failures.append("llm_evidence_class is not the required scripted-keyless")
    provenance = raw.get("provenance") or {}
    allowed = (contract.get("provenance_allowed_sources") or {}).get("source") or []
    if provenance.get("source") not in allowed:
        failures.append("raw provenance source is missing or not contract-allowed")

    derived: dict[str, bool] = {}
    derived.update({f"journey:{k}": v for k, v in _derive_journey(raw).items()})
    derived.update({f"gate:{k}": v for k, v in _derive_gate(raw).items()})
    derived_assertions = _derive_assertions(raw)
    for name, ok in derived.items():
        if not ok:
            failures.append(f"derived row failed: {name}")
    for assertion in contract.get("required_assertions", []):
        if derived_assertions.get(assertion) is not True:
            failures.append(f"assertion failed: {assertion}")
    forbidden = raw.get("model_visible_forbidden_hits") or []
    if forbidden:
        failures.append(f"model-visible forbidden raw fields present: {forbidden}")
    cleanup = raw.get("cleanup") or {}
    if not (cleanup.get("containers") == 0 and cleanup.get("networks") == 0
            and cleanup.get("volumes") == 0 and cleanup.get("production_untouched") is True):
        failures.append("cleanup is not zero or production was touched")
    all_pass = format_valid and not failures
    limitations: list[str] = []
    blocked_rows: dict[str, str] = {}
    if not _paper_account_bound(raw):
        blocked_rows["journey:paper-account"] = (
            "paper_account_approval_binding_missing_or_unproven")
        limitations.append("paper_account_approval_binding_missing_or_unproven")
    return _verdict(format_valid, all_pass, failures, derived, derived_assertions,
                    limitations, blocked_rows)


def _verdict(format_valid: bool, all_pass: bool, failures: list, derived: dict,
             assertions: dict, limitations: list | None = None,
             blocked_rows: dict | None = None) -> dict:
    return {
        "schema_version": "byq-v091-continuation-p4b-verdict.v1",
        "format_valid": format_valid, "all_pass": all_pass, "failures": failures,
        "limitations": limitations or [],
        "blocked_rows": blocked_rows or {},
        "derived_rows": derived, "derived_assertions": assertions,
    }


def legacy_compute_verdict(contract: dict, observations: dict) -> dict:
    """Pre-fix, label-trusting gate: trusts declared labels, accepts every control."""

    declared = observations.get("assertions") or {}
    labels_ok = observations.get("all_pass") is True and all(
        declared.get(name) is True for name in contract.get("required_assertions", []))
    return {"format_valid": True, "all_pass": bool(labels_ok)}


# --------------------------------------------------------------------------- #
# Known-good fixture + negative controls
# --------------------------------------------------------------------------- #

def _base_fixture() -> dict:
    if not DEFAULT_OBSERVATIONS.is_file():
        raise SystemExit("committed observations are required for --selfcheck")
    fixture = copy.deepcopy(_load(DEFAULT_OBSERVATIONS))
    # The legacy gate trusts declared labels; the fixed gate ignores them.
    fixture["assertions"] = {name: True for name in (
        "no_duplicate_business_objects", "exact_approval_binding",
        "exact_event_identity_and_replay", "exact_stage_call_admission",
        "model_visible_input_is_bounded_projection_only",
        "deterministic_transitions_use_zero_model_calls",
        "request_gate_is_per_request_not_cross_process",
        "paper_account_exact_approval_binding_and_idempotent_creation",
        "cleanup_zero_and_production_untouched")}
    fixture["all_pass"] = True
    return fixture


def _controls() -> list[tuple[str, dict]]:
    base = _base_fixture()
    controls: list[tuple[str, dict]] = []

    def mutate(name, fn):
        fixture = copy.deepcopy(base)
        fn(fixture["raw"])
        controls.append((name, fixture))

    mutate("task-not-created", lambda r: r["counts"].__setitem__("research_tasks", 0))
    mutate("plan-not-created", lambda r: r["counts"].__setitem__("research_execution_plans", 0))
    mutate("strategy-approval-missing", lambda r: r["approvals"].__setitem__(
        0, {**r["approvals"][0], "action": "other"}))
    mutate("data-ready-missing", lambda r: r.__setitem__(
        "events", [e for e in r["events"] if e.get("event_type") != "data_ready"]))
    mutate("rounds-incomplete", lambda r: r["plan"].__setitem__("iteration", 2))
    mutate("task-not-completed", lambda r: r.__setitem__("task_status", "running"))
    mutate("duplicate-business-object", lambda r: r.__setitem__(
        "duplicate_objects", [{"kind": "research_task", "count": 2}]))
    mutate("approval-binding-missing", lambda r: r["approvals"][0].__setitem__(
        "plan_params_digest", None))
    mutate("forbidden-raw-field-visible", lambda r: r.__setitem__(
        "model_visible_forbidden_hits", ["bars_frame"]))
    mutate("projection-over-bound", lambda r: r["projections"][0].__setitem__(
        "bounded_input_bytes", 70000))
    mutate("child-tool-not-read-only", lambda r: r["projections"][0].__setitem__(
        "child_tools_read_only", False))
    mutate("deterministic-stage-used-model", lambda r: r["turns"].append(
        {"attempt": "1:waiting_for_data:1", "status": 200, "provider_calls_delta": 3}))
    mutate("gate-limits-missing", lambda r: r["turns"][0].__setitem__("request_gate", {}))
    mutate("gate-profile-missing", lambda r: r["turns"][0]["request_gate"]["limits"].pop(
        "profile_id", None))
    mutate("gate-profile-forged-evidence", lambda r: r["turns"][0]["request_gate"]["limits"].__setitem__(
        "evidence", "forged audit basis"))
    mutate("gate-profile-forged-limit", lambda r: r["turns"][0]["request_gate"]["limits"].__setitem__(
        "max_provider_calls", 99))
    mutate("gate-child-not-covered", lambda r: r.__setitem__(
        "gate_journal", {k: [row for row in rows if row.get("role") != "child"]
                         for k, rows in r["gate_journal"].items()}))
    mutate("gate-blocked-receipt-present", lambda r: r["gate_journal"][
        next(iter(r["gate_journal"]))].append(
        {"role": "root", "admitted": False, "reason": "provider_call_limit"}))
    mutate("gate-shared-request-budget", lambda r: [
        t["request_gate"]["limits"].__setitem__("request_id", "byq-judgment-shared")
        for t in r["turns"]])
    mutate("gate-negative-controls-not-blocked", lambda r: r["gate_negative_controls"].__setitem__(
        "all_blocked", False))
    mutate("paper-account-without-approval", lambda r: r["paper_account"].__setitem__(
        "approval_object_present", False))
    mutate("paper-account-approval-missing", lambda r: r.__setitem__(
        "approvals", [a for a in r["approvals"]
                      if a.get("action") != "byq_paper_account_create"]))
    mutate("paper-account-binding-wrong-resource", lambda r: [
        a.__setitem__("plan_resource_kind", "strategy_version")
        for a in r["approvals"] if a.get("action") == "byq_paper_account_create"])
    mutate("paper-account-replay-second-account", lambda r: r["paper_account"].__setitem__(
        "replay_same_account", False))
    mutate("paper-account-params-digest-mismatch", lambda r: r["paper_account"]["params"].__setitem__(
        "params_digest", "sha256:" + "b" * 64))
    mutate("paper-account-params-key-mismatch", lambda r: r["paper_account"].__setitem__(
        "params_idempotency_key_sha256", "sha256:" + "c" * 64))
    mutate("paper-account-created-order", lambda r: r["paper_account"].__setitem__("orders", 1))
    mutate("paper-account-used-model", lambda r: r["paper_account"].__setitem__(
        "zero_model_calls", False))
    mutate("gate-actual-usage-missing", lambda r: r["turns"][0]["calls"][0].pop(
        "actual_output_tokens", None))
    mutate("gate-declared-as-actual", lambda r: r["turns"][0]["calls"][0].__setitem__(
        "usage_source", "declared_ceiling"))
    mutate("gate-actual-over-ceiling-forwarded", lambda r: r["turns"][0]["calls"][0].update(
        {"actual_output_tokens": r["turns"][0]["calls"][0]["declared_max_output_tokens"] + 1,
         "forwarded": True, "usage_source": "provider_response"}))
    mutate("gate-not-forwarded-result", lambda r: r["turns"][0]["calls"][0].__setitem__(
        "forwarded", False))
    mutate("gate-unknown-usage-forwarded", lambda r: r["turns"][0]["calls"][0].update(
        {"usage_source": "unknown", "actual_output_tokens": "unknown",
         "forwarded": True, "reason": "within_request_budget"}))
    mutate("cleanup-nonzero", lambda r: r["cleanup"].__setitem__("containers", 1))
    mutate("production-touched", lambda r: r["cleanup"].__setitem__("production_untouched", False))
    return controls


def run_selfcheck(contract: dict) -> int:
    baseline = compute_verdict(contract, _base_fixture())
    if not baseline["all_pass"]:
        print("selfcheck baseline did not pass:", baseline["failures"])
        return 1
    bad = 0
    controls = _controls()
    for name, fixture in controls:
        fixed = compute_verdict(contract, fixture)
        legacy = legacy_compute_verdict(contract, fixture)
        if fixed["all_pass"]:
            print(f"control {name} was NOT rejected by the fixed gate")
            bad += 1
        if name in DEFECT_TARGETING_CONTROLS and not legacy["all_pass"]:
            print(f"control {name} was already rejected by the legacy gate (not defect-targeting)")
            bad += 1
    print(f"selfcheck controls={len(controls)} "
          f"defect_targeting={len(DEFECT_TARGETING_CONTROLS)} rejected={len(controls) - bad} bad={bad}")
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--observations", default=str(DEFAULT_OBSERVATIONS))
    parser.add_argument("--out")
    parser.add_argument("--selfcheck", action="store_true")
    args = parser.parse_args(argv)
    contract = _load(Path(args.contract))
    if args.selfcheck:
        return run_selfcheck(contract)
    observations = _load(Path(args.observations))
    verdict = compute_verdict(contract, observations)
    if args.out:
        Path(args.out).write_text(json.dumps(verdict, indent=2, sort_keys=True) + "\n",
                                  encoding="utf-8")
    print(json.dumps(verdict, indent=2, sort_keys=True))
    return 0 if verdict["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
