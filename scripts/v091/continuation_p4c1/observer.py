#!/usr/bin/env python3
"""ADR-0085 P4-C1 fail-able observer for Adapter/DSH fault-safe convergence.

The observer NEVER trusts a PASS label. It re-derives every fault/boundary row and
every assertion from the RAW boundary facts captured by the fault driver, rejects a
missing/forged provenance source, rejects any fabricated recovery/needs_attention
state, and only reports ``all_pass`` when every required row genuinely holds.

``--selfcheck`` proves the gate is breakable: it builds a synthetic known-good
observation set, mutates it for each defect-targeting control, and requires the
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
    ROOT / "docs/evidence/adr-0085-p4c1-adapter-fault-safe/observations.v1.json")

OBSERVATIONS_SCHEMA = "byq-v091-continuation-p4c1-observations.v1"
REQUIRED_EVIDENCE_CLASS = "runtime-isolated-stack"
REQUIRED_LLM_CLASS = "scripted-keyless"
IN_PROGRESS_CODE = "research_judgment_in_progress"
FAIL_CLOSED_CODE = "research_judgment_failed_closed"
PENDING_TASK_STATUSES = {"planned", "running"}

DEFECT_TARGETING_CONTROLS = (
    "F1-adapter-not-restarted", "F1-retry-resent-model", "F1-duplicate-stage-call",
    "F1-plan-mutated", "F1-task-completed", "F1-fabricated-receipt",
    "F1-business-object-duplicated", "F1-no-provider-inflight-at-kill",
    "F2-adapter-restarted-too", "F2-turn-did-not-fail-closed", "F2-result-submitted",
    "F2-retry-resent-model", "F2-stage-call-completed", "F2-plan-advanced",
    "F3-retry-resent-model", "F3-second-stage-call", "F3-retry-returned-receipt",
    "F4-old-attempt-ran-model", "F4-old-attempt-not-replay", "F4-plan-changed-by-late",
    "F5-old-result-second-write", "F5-old-result-not-isolated", "F5-forged-result-accepted",
    "F5-plan-changed-by-late-result", "F6-killed-and-stuck-diverge",
    "F6-auto-fenced-live-attempt", "F6-recovery-claimed", "F6-fabricated-completed",
    "F7-normal-run-failed", "F7-duplicate-preempted-original", "F7-wrong-provider-count",
    "F7-multiple-completed-stage-calls", "F7-duplicate-business-object",
    "F8-completed-instead-of-needs-attention", "F8-wrong-reason",
    "F8-plan-task-disagree", "F8-multiple-completed-stage-calls",
    "F9-duplicate-business-object", "F9-wrong-task-count",
    "B1-no-token-allowed", "B1-forged-token-allowed", "B1-forged-attempt-accepted",
    "B1-control-reached-provider", "B1-control-created-stage-call",
    "B2-cleanup-nonzero", "B2-production-touched",
    "B3-identity-mismatch", "B3-duplicate-call-index", "B3-generation-inconsistent",
    "B4-model-supplied-identity", "B4-non-none-durable-evidence-accepted",
    "B4-forbidden-result-field", "B5-fabricated-completed-state",
    "B5-state-outside-vocabulary", "native-recovery-claimed",
)


class Failure(Exception):
    pass


def _load(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Failure(message)


def _scn(raw: dict, key: str) -> dict:
    scenarios = raw.get("scenarios")
    return scenarios.get(key) if isinstance(scenarios, dict) and isinstance(
        scenarios.get(key), dict) else {}


def _pos_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _stage_rows(scenario: dict) -> list:
    rows = scenario.get("stage_calls")
    return rows if isinstance(rows, list) else []


def _is_inprogress(response: object) -> bool:
    return (isinstance(response, dict) and response.get("status") == 409
            and response.get("code") == IN_PROGRESS_CODE)


def _plan_equal(a: object, b: object) -> bool:
    if not isinstance(a, dict) or not isinstance(b, dict):
        return False
    keys = ("plan_version", "stage", "iteration", "status")
    return all(a.get(k) == b.get(k) for k in keys)


def _counts_equal(a: object, b: object) -> bool:
    return isinstance(a, dict) and a == b


# --------------------------------------------------------------------------- #
# Fault rows
# --------------------------------------------------------------------------- #

def _f1(raw: dict) -> bool:
    s = _scn(raw, "F1")
    inj = raw.get("fault_injection", {}).get("adapter_kill", {})
    if inj.get("killed_while_provider_inflight") is not True:
        return False
    if not (_pos_int(inj.get("adapter_pid_before")) and _pos_int(inj.get("adapter_pid_after"))
            and inj["adapter_pid_before"] != inj["adapter_pid_after"]):
        return False
    if not _is_inprogress(s.get("retry")):
        return False
    if s.get("retry", {}).get("provider_calls_delta") != 0:
        return False
    if s.get("retry", {}).get("receipt_present") is not False:
        return False
    rows = _stage_rows(s)
    if len(rows) != 1 or rows[0].get("status") != "admitted" or rows[0].get("call_index") != 1:
        return False
    if not _plan_equal(s.get("plan_before"), s.get("plan_after")):
        return False
    if (s.get("plan_after") or {}).get("stage") != "strategy_draft":
        return False
    if s.get("task_status_after") not in PENDING_TASK_STATUSES:
        return False
    if not _counts_equal(s.get("counts_before"), s.get("counts_after")):
        return False
    return not s.get("duplicate_objects")


def _f2(raw: dict) -> bool:
    s = _scn(raw, "F2")
    inj = raw.get("fault_injection", {}).get("dsh_child_kill", {})
    if inj.get("dsh_child_dead") is not True or inj.get("adapter_alive") is not True:
        return False
    if inj.get("adapter_pid_before") != inj.get("adapter_pid_after"):
        return False
    if not _pos_int(inj.get("dsh_pid")):
        return False
    turn = s.get("turn") or {}
    if turn.get("status") != 503 or turn.get("code") != FAIL_CLOSED_CODE:
        return False
    if s.get("result_submitted") is not False:
        return False
    if not _is_inprogress(s.get("retry")) or s.get("retry", {}).get(
            "provider_calls_delta") != 0:
        return False
    rows = _stage_rows(s)
    if len(rows) != 1 or rows[0].get("status") != "admitted":
        return False
    if not _plan_equal(s.get("plan_before"), s.get("plan_after")):
        return False
    return not s.get("duplicate_objects")


def _f3(raw: dict) -> bool:
    s = _scn(raw, "F3")
    retries = s.get("retries")
    if not isinstance(retries, list) or len(retries) < 2:
        return False
    if not all(_is_inprogress(r) and r.get("provider_calls_delta") == 0
               and r.get("receipt_present") is False for r in retries):
        return False
    if s.get("stage_calls_count") != 1:
        return False
    return s.get("receipt_returned") is False


def _f4(raw: dict) -> bool:
    s = _scn(raw, "F4")
    late = s.get("late_request") or {}
    if late.get("status") != 200:
        return False
    if late.get("replayed") is not True or late.get("model_turn_skipped") is not True:
        return False
    if late.get("provider_calls_delta") != 0:
        return False
    if s.get("stage_calls_count_unchanged") is not True:
        return False
    if not _plan_equal(s.get("plan_before"), s.get("plan_after")):
        return False
    return (s.get("plan_after") or {}).get("stage") == "waiting_for_strategy_approval"


def _f5(raw: dict) -> bool:
    s = _scn(raw, "F5")
    old = s.get("old_result") or {}
    if old.get("second_write") is not False:
        return False
    if not (old.get("replayed") is True or old.get("rejected") is True):
        return False
    if s.get("forged_result_rejected") is not True:
        return False
    if not _plan_equal(s.get("plan_before"), s.get("plan_after")):
        return False
    return _counts_equal(s.get("counts_before"), s.get("counts_after"))


def _f6(raw: dict) -> bool:
    s = _scn(raw, "F6")
    killed = s.get("killed_retry") or {}
    stuck = s.get("stuck_retry") or {}
    if not _is_inprogress(killed) or not _is_inprogress(stuck):
        return False
    if killed.get("receipt_present") is not False or stuck.get("receipt_present") is not False:
        return False
    if killed.get("code") != stuck.get("code"):
        return False
    if s.get("same_outcome") is not True:
        return False
    if s.get("auto_fenced_live_attempt") is not False:
        return False
    if s.get("recovery_claimed") is not False:
        return False
    return s.get("fabricated_completed") is False


def _f7(raw: dict) -> bool:
    s = _scn(raw, "F7")
    if (s.get("turn") or {}).get("status") != 200:
        return False
    if s.get("plan_advanced_once") is not True:
        return False
    dup = s.get("duplicate_concurrent") or {}
    if dup.get("status") != 409 or dup.get("code") != IN_PROGRESS_CODE:
        return False
    if dup.get("preempted_original") is not False:
        return False
    if s.get("provider_calls_delta_total") != s.get("expected_provider_calls"):
        return False
    if not _pos_int(s.get("expected_provider_calls")):
        return False
    if s.get("completed_stage_calls") != 1:
        return False
    return not s.get("duplicate_objects")


def _f8(raw: dict) -> bool:
    s = _scn(raw, "F8")
    plan = s.get("plan_after") or {}
    progress = s.get("task_progress_after") or {}
    if plan.get("stage") != "needs_attention" or plan.get("status") != "blocked":
        return False
    if progress.get("stage") != "blocked" or progress.get("next_action") != "needs_attention":
        return False
    if "no_durable_progress" not in str(progress.get("blocked_reason") or ""):
        return False
    if s.get("completed_stage_calls") != 1:
        return False
    if s.get("stage_call_outcome") != "needs_attention":
        return False
    if s.get("task_status_after") == "completed":
        return False
    if s.get("duplicate_objects"):
        return False
    return s.get("no_over_limit_calls") is True


def _f9(raw: dict) -> bool:
    s = _scn(raw, "F9")
    expected = s.get("expected_counts")
    observed = s.get("observed_counts")
    if not isinstance(expected, dict) or not isinstance(observed, dict):
        return False
    if observed.get("research_tasks") != expected.get("research_tasks"):
        return False
    if any(observed.get(k) != v for k, v in expected.items() if k != "scenarios"):
        return False
    return not s.get("duplicate_objects")


# --------------------------------------------------------------------------- #
# Boundary rows
# --------------------------------------------------------------------------- #

def _b1(raw: dict) -> bool:
    c = raw.get("boundary_controls") or {}
    if c.get("no_token_status") != 401 or c.get("forged_token_status") != 401:
        return False
    if not isinstance(c.get("forged_attempt_status"), int) or c["forged_attempt_status"] < 400:
        return False
    if c.get("provider_calls_delta") != 0 or c.get("stage_calls_delta") != 0:
        return False
    return c.get("adapter_identity_unchanged") is True


def _b2(raw: dict) -> bool:
    cleanup = raw.get("cleanup") or {}
    return (cleanup.get("containers") == 0 and cleanup.get("networks") == 0
            and cleanup.get("volumes") == 0 and cleanup.get("production_untouched") is True)


def _b3(raw: dict) -> bool:
    b = raw.get("durable_identity") or {}
    if not (isinstance(b.get("adapter_call_identity"), str)
            and b.get("adapter_call_identity") == b.get("stage_call_identity")
            and b.get("adapter_call_identity") == b.get("receipt_call_identity")):
        return False
    if b.get("call_index") != 1:
        return False
    if b.get("duplicate_call_index") is True:
        return False
    return b.get("generation_consistent") is True


def _b4(raw: dict) -> bool:
    b = raw.get("adapter_binding") or {}
    if b.get("derives_identity_server_side") is not True:
        return False
    if b.get("result_closed_fields") is not True:
        return False
    if b.get("rejects_non_none_durable_evidence") is not True:
        return False
    return not b.get("forbidden_result_fields")


def _b5(raw: dict) -> bool:
    b = raw.get("convergence") or {}
    if b.get("fabricated_completed_state") is not False:
        return False
    vocabulary = set(b.get("terminal_states_observed") or [])
    allowed = {"pending_admitted", "needs_attention_no_durable_progress"}
    return bool(vocabulary) and vocabulary <= allowed


_FAULT_ROWS = {
    "F1-adapter-process-killed-inflight": _f1,
    "F2-dsh-child-killed-adapter-alive": _f2,
    "F3-pending-not-auto-resent-after-restart": _f3,
    "F4-late-old-attempt-request-isolated": _f4,
    "F5-late-old-attempt-result-isolated": _f5,
    "F6-unprovable-owner-termination-stays-pending": _f6,
    "F7-normal-long-run-completes-once": _f7,
    "F8-no-durable-progress-converges-needs-attention": _f8,
    "F9-no-duplicate-business-objects": _f9,
}
_BOUNDARY_ROWS = {
    "B1-boundary-auth-and-forged-attempt-fail-closed": _b1,
    "B2-cleanup-zero-and-production-untouched": _b2,
    "B3-durable-identity-call-index-exact": _b3,
    "B4-model-cannot-decide-recovery-identity": _b4,
    "B5-convergence-is-contract-allowed": _b5,
}


def _derive_fault(raw: dict) -> dict:
    return {name: fn(raw) for name, fn in _FAULT_ROWS.items()}


def _derive_boundary(raw: dict) -> dict:
    return {name: fn(raw) for name, fn in _BOUNDARY_ROWS.items()}


def _derive_assertions(raw: dict) -> dict:
    fault, boundary = _derive_fault(raw), _derive_boundary(raw)
    native = raw.get("non_claims") or {}
    return {
        "no_auto_resend_of_pending_attempt":
            fault["F1-adapter-process-killed-inflight"]
            and fault["F2-dsh-child-killed-adapter-alive"]
            and fault["F3-pending-not-auto-resent-after-restart"],
        "late_result_isolated_or_rejected":
            fault["F4-late-old-attempt-request-isolated"]
            and fault["F5-late-old-attempt-result-isolated"],
        "durable_attempt_identity_call_index_exact":
            boundary["B3-durable-identity-call-index-exact"],
        "no_duplicate_provider_calls":
            fault["F7-normal-long-run-completes-once"]
            and fault["F1-adapter-process-killed-inflight"]
            and fault["F3-pending-not-auto-resent-after-restart"],
        "no_duplicate_business_objects": fault["F9-no-duplicate-business-objects"],
        "convergence_is_contract_allowed_and_explainable":
            boundary["B5-convergence-is-contract-allowed"]
            and fault["F6-unprovable-owner-termination-stays-pending"]
            and fault["F8-no-durable-progress-converges-needs-attention"],
        "model_cannot_decide_recovery_identity_or_routing":
            boundary["B4-model-cannot-decide-recovery-identity"],
        "dsh_native_cross_process_recovery_not_claimed":
            native.get("dsh_native_recovery_claimed") is False
            and fault["F6-unprovable-owner-termination-stays-pending"],
        "boundary_auth_and_forged_attempt_fail_closed":
            boundary["B1-boundary-auth-and-forged-attempt-fail-closed"],
        "cleanup_zero_and_production_untouched":
            boundary["B2-cleanup-zero-and-production-untouched"],
    }


# --------------------------------------------------------------------------- #
# Verdict
# --------------------------------------------------------------------------- #

def compute_verdict(contract: dict, observations: dict) -> dict:
    failures: list[str] = []
    try:
        _require(observations.get("schema_version") == OBSERVATIONS_SCHEMA,
                 "observations schema is invalid")
        raw = observations.get("raw")
        _require(isinstance(raw, dict), "observations are missing raw boundary facts")
    except Failure as error:
        return _verdict(False, False, [str(error)], {}, {}, {})
    if observations.get("evidence_class") != REQUIRED_EVIDENCE_CLASS:
        failures.append("evidence_class is not the required runtime-isolated-stack")
    if observations.get("llm_evidence_class") != REQUIRED_LLM_CLASS:
        failures.append("llm_evidence_class is not the required scripted-keyless")
    provenance = raw.get("provenance") or {}
    allowed = (contract.get("provenance_allowed_sources") or {}).get("source") or []
    if provenance.get("source") not in allowed:
        failures.append("raw provenance source is missing or not contract-allowed")

    derived_fault = _derive_fault(raw)
    derived_boundary = _derive_boundary(raw)
    derived_assertions = _derive_assertions(raw)
    for name, ok in {**derived_fault, **derived_boundary}.items():
        if not ok:
            failures.append(f"derived row failed: {name}")
    for assertion in contract.get("required_assertions", []):
        if derived_assertions.get(assertion) is not True:
            failures.append(f"assertion failed: {assertion}")
    if not _b2(raw):
        failures.append("cleanup is not zero or production was touched")
    all_pass = bool(failures) is False
    limitations: list[str] = []
    blocked_rows: dict[str, str] = {}
    for name, ok in derived_fault.items():
        if not ok:
            blocked_rows[name] = "not_observed_or_failed"
            limitations.append(name)
    return _verdict(True, all_pass, failures, derived_fault, derived_boundary,
                    derived_assertions, limitations, blocked_rows)


def _verdict(format_valid, all_pass, failures, fault, boundary, assertions,
             limitations=None, blocked_rows=None) -> dict:
    return {
        "schema_version": "byq-v091-continuation-p4c1-verdict.v1",
        "format_valid": format_valid, "all_pass": all_pass, "failures": failures,
        "limitations": limitations or [],
        "blocked_rows": blocked_rows or {},
        "derived_rows": {**fault, **boundary},
        "derived_assertions": assertions,
    }


def legacy_compute_verdict(contract: dict, observations: dict) -> dict:
    """Pre-fix, label-trusting gate: trusts declared labels, accepts every control."""

    declared = observations.get("assertions") or {}
    labels_ok = observations.get("all_pass") is True and all(
        declared.get(name) is True for name in contract.get("required_assertions", []))
    return {"format_valid": True, "all_pass": bool(labels_ok)}


# --------------------------------------------------------------------------- #
# Synthetic known-good fixture + negative controls
# --------------------------------------------------------------------------- #

_EMPTY_COUNTS = {
    "research_tasks": 1, "research_execution_plans": 1,
    "research_continuation_events": 0, "research_judgment_stage_calls": 1,
    "agent_approvals": 0, "artifacts": 0, "signal_producer_jobs": 0,
    "backtest_jobs": 0, "paper_accounts": 0, "paper_orders": 0,
    "paper_positions": 0, "paper_fills": 0,
}

_PLAN_DRAFT = {"plan_version": 3, "stage": "strategy_draft", "iteration": 1, "status": "active"}
_PLAN_WAIT = {"plan_version": 4, "stage": "waiting_for_strategy_approval",
              "iteration": 1, "status": "waiting"}


def _known_good() -> dict:
    return {
        "schema_version": OBSERVATIONS_SCHEMA,
        "evidence_class": REQUIRED_EVIDENCE_CLASS,
        "llm_evidence_class": REQUIRED_LLM_CLASS,
        "raw": {
            "provenance": {"boundary": "real-isolated-services",
                           "source": "real-isolated-services"},
            "fault_injection": {
                "adapter_kill": {"killed_while_provider_inflight": True,
                                 "adapter_pid_before": 101, "adapter_pid_after": 202},
                "dsh_child_kill": {"dsh_child_dead": True, "adapter_alive": True,
                                   "adapter_pid_before": 303, "adapter_pid_after": 303,
                                   "dsh_pid": 404},
            },
            "adapter_binding": {"derives_identity_server_side": True,
                                "result_closed_fields": True,
                                "rejects_non_none_durable_evidence": True,
                                "forbidden_result_fields": []},
            "non_claims": {"dsh_native_recovery_claimed": False},
            "convergence": {
                "fabricated_completed_state": False,
                "terminal_states_observed": ["pending_admitted", "needs_attention_no_durable_progress"],
            },
            "durable_identity": {
                "adapter_call_identity": "byq-judgment-" + "a" * 32,
                "stage_call_identity": "byq-judgment-" + "a" * 32,
                "receipt_call_identity": "byq-judgment-" + "a" * 32,
                "call_index": 1, "duplicate_call_index": False,
                "generation_consistent": True,
            },
            "boundary_controls": {
                "no_token_status": 401, "forged_token_status": 401,
                "forged_attempt_status": 422, "provider_calls_delta": 0,
                "stage_calls_delta": 0, "adapter_identity_unchanged": True,
            },
            "scenarios": {
                "F1": {
                    "retry": {"status": 409, "code": IN_PROGRESS_CODE,
                              "provider_calls_delta": 0, "receipt_present": False},
                    "stage_calls": [{"status": "admitted", "call_index": 1}],
                    "plan_before": _PLAN_DRAFT, "plan_after": copy.deepcopy(_PLAN_DRAFT),
                    "task_status_after": "planned",
                    "counts_before": copy.deepcopy(_EMPTY_COUNTS),
                    "counts_after": copy.deepcopy(_EMPTY_COUNTS),
                    "duplicate_objects": [],
                },
                "F2": {
                    "turn": {"status": 503, "code": FAIL_CLOSED_CODE},
                    "result_submitted": False,
                    "retry": {"status": 409, "code": IN_PROGRESS_CODE,
                              "provider_calls_delta": 0},
                    "stage_calls": [{"status": "admitted"}],
                    "plan_before": _PLAN_DRAFT, "plan_after": copy.deepcopy(_PLAN_DRAFT),
                    "duplicate_objects": [],
                },
                "F3": {
                    "retries": [{"status": 409, "code": IN_PROGRESS_CODE,
                                 "provider_calls_delta": 0, "receipt_present": False},
                                {"status": 409, "code": IN_PROGRESS_CODE,
                                 "provider_calls_delta": 0, "receipt_present": False}],
                    "stage_calls_count": 1, "receipt_returned": False,
                },
                "F4": {
                    "late_request": {"status": 200, "replayed": True,
                                     "model_turn_skipped": True, "provider_calls_delta": 0},
                    "stage_calls_count_unchanged": True,
                    "plan_before": _PLAN_WAIT, "plan_after": copy.deepcopy(_PLAN_WAIT),
                },
                "F5": {
                    "old_result": {"second_write": False, "replayed": True, "rejected": False},
                    "forged_result_rejected": True,
                    "plan_before": _PLAN_WAIT, "plan_after": copy.deepcopy(_PLAN_WAIT),
                    "counts_before": copy.deepcopy(_EMPTY_COUNTS),
                    "counts_after": copy.deepcopy(_EMPTY_COUNTS),
                },
                "F6": {
                    "killed_retry": {"status": 409, "code": IN_PROGRESS_CODE,
                                     "receipt_present": False},
                    "stuck_retry": {"status": 409, "code": IN_PROGRESS_CODE,
                                    "receipt_present": False},
                    "same_outcome": True, "auto_fenced_live_attempt": False,
                    "recovery_claimed": False, "fabricated_completed": False,
                },
                "F7": {
                    "turn": {"status": 200},
                    "plan_advanced_once": True,
                    "duplicate_concurrent": {"status": 409, "code": IN_PROGRESS_CODE,
                                             "preempted_original": False},
                    "provider_calls_delta_total": 3, "expected_provider_calls": 3,
                    "completed_stage_calls": 1, "duplicate_objects": [],
                },
                "F8": {
                    "plan_after": {"stage": "needs_attention", "status": "blocked"},
                    "task_progress_after": {"stage": "blocked", "next_action": "needs_attention",
                                            "blocked_reason": "no_durable_progress"},
                    "completed_stage_calls": 1, "stage_call_outcome": "needs_attention",
                    "task_status_after": "running", "duplicate_objects": [],
                    "no_over_limit_calls": True,
                },
                "F9": {
                    "expected_counts": copy.deepcopy(_EMPTY_COUNTS),
                    "observed_counts": copy.deepcopy(_EMPTY_COUNTS),
                    "duplicate_objects": [],
                },
            },
            "cleanup": {"containers": 0, "networks": 0, "volumes": 0,
                        "production_untouched": True},
        },
    }


def _base_fixture() -> dict:
    fixture = _known_good()
    fixture["assertions"] = {name: True for name in (
        "no_auto_resend_of_pending_attempt", "late_result_isolated_or_rejected",
        "durable_attempt_identity_call_index_exact", "no_duplicate_provider_calls",
        "no_duplicate_business_objects", "convergence_is_contract_allowed_and_explainable",
        "model_cannot_decide_recovery_identity_or_routing",
        "dsh_native_cross_process_recovery_not_claimed",
        "boundary_auth_and_forged_attempt_fail_closed",
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

    # F1
    mutate("F1-adapter-not-restarted", lambda r: r["fault_injection"]["adapter_kill"].update(
        {"adapter_pid_after": 101}))
    mutate("F1-retry-resent-model", lambda r: r["scenarios"]["F1"]["retry"].update(
        {"provider_calls_delta": 1}))
    mutate("F1-duplicate-stage-call", lambda r: r["scenarios"]["F1"]["stage_calls"].append(
        {"status": "admitted", "call_index": 2}))
    mutate("F1-plan-mutated", lambda r: r["scenarios"]["F1"]["plan_after"].update(
        {"plan_version": 99}))
    mutate("F1-task-completed", lambda r: r["scenarios"]["F1"].update(
        {"task_status_after": "completed"}))
    mutate("F1-fabricated-receipt", lambda r: r["scenarios"]["F1"]["retry"].update(
        {"receipt_present": True}))
    mutate("F1-business-object-duplicated", lambda r: r["scenarios"]["F1"]["counts_after"].update(
        {"artifacts": 2}))
    mutate("F1-no-provider-inflight-at-kill", lambda r: r["fault_injection"]["adapter_kill"].update(
        {"killed_while_provider_inflight": False}))
    # F2
    mutate("F2-adapter-restarted-too", lambda r: r["fault_injection"]["dsh_child_kill"].update(
        {"adapter_pid_after": 999}))
    mutate("F2-turn-did-not-fail-closed", lambda r: r["scenarios"]["F2"]["turn"].update(
        {"status": 200}))
    mutate("F2-result-submitted", lambda r: r["scenarios"]["F2"].update(
        {"result_submitted": True}))
    mutate("F2-retry-resent-model", lambda r: r["scenarios"]["F2"]["retry"].update(
        {"provider_calls_delta": 3}))
    mutate("F2-stage-call-completed", lambda r: r["scenarios"]["F2"]["stage_calls"][0].update(
        {"status": "completed"}))
    mutate("F2-plan-advanced", lambda r: r["scenarios"]["F2"]["plan_after"].update(
        {"plan_version": 4}))
    # F3
    mutate("F3-retry-resent-model", lambda r: r["scenarios"]["F3"]["retries"][0].update(
        {"provider_calls_delta": 1}))
    mutate("F3-second-stage-call", lambda r: r["scenarios"]["F3"].update(
        {"stage_calls_count": 2}))
    mutate("F3-retry-returned-receipt", lambda r: r["scenarios"]["F3"].update(
        {"receipt_returned": True}))
    # F4
    mutate("F4-old-attempt-ran-model", lambda r: r["scenarios"]["F4"]["late_request"].update(
        {"provider_calls_delta": 3}))
    mutate("F4-old-attempt-not-replay", lambda r: r["scenarios"]["F4"]["late_request"].update(
        {"replayed": False}))
    mutate("F4-plan-changed-by-late", lambda r: r["scenarios"]["F4"]["plan_after"].update(
        {"plan_version": 5}))
    # F5
    mutate("F5-old-result-second-write", lambda r: r["scenarios"]["F5"]["old_result"].update(
        {"second_write": True}))
    mutate("F5-old-result-not-isolated", lambda r: r["scenarios"]["F5"]["old_result"].update(
        {"replayed": False, "rejected": False}))
    mutate("F5-forged-result-accepted", lambda r: r["scenarios"]["F5"].update(
        {"forged_result_rejected": False}))
    mutate("F5-plan-changed-by-late-result", lambda r: r["scenarios"]["F5"]["plan_after"].update(
        {"stage": "completed"}))
    # F6
    mutate("F6-killed-and-stuck-diverge", lambda r: r["scenarios"]["F6"]["stuck_retry"].update(
        {"status": 503, "code": "other"}))
    mutate("F6-auto-fenced-live-attempt", lambda r: r["scenarios"]["F6"].update(
        {"auto_fenced_live_attempt": True}))
    mutate("F6-recovery-claimed", lambda r: r["scenarios"]["F6"].update(
        {"recovery_claimed": True}))
    mutate("F6-fabricated-completed", lambda r: r["scenarios"]["F6"].update(
        {"fabricated_completed": True}))
    # F7
    mutate("F7-normal-run-failed", lambda r: r["scenarios"]["F7"]["turn"].update({"status": 503}))
    mutate("F7-duplicate-preempted-original", lambda r: r["scenarios"]["F7"][
        "duplicate_concurrent"].update({"preempted_original": True}))
    mutate("F7-wrong-provider-count", lambda r: r["scenarios"]["F7"].update(
        {"provider_calls_delta_total": 6}))
    mutate("F7-multiple-completed-stage-calls", lambda r: r["scenarios"]["F7"].update(
        {"completed_stage_calls": 2}))
    mutate("F7-duplicate-business-object", lambda r: r["scenarios"]["F7"].update(
        {"duplicate_objects": [{"kind": "backtest_job"}]}))
    # F8
    mutate("F8-completed-instead-of-needs-attention", lambda r: r["scenarios"]["F8"][
        "plan_after"].update({"stage": "completed", "status": "completed"}))
    mutate("F8-wrong-reason", lambda r: r["scenarios"]["F8"]["task_progress_after"].update(
        {"blocked_reason": "approval_denied"}))
    mutate("F8-plan-task-disagree", lambda r: r["scenarios"]["F8"]["task_progress_after"].update(
        {"stage": "completed", "next_action": None}))
    mutate("F8-multiple-completed-stage-calls", lambda r: r["scenarios"]["F8"].update(
        {"completed_stage_calls": 2}))
    # F9
    mutate("F9-duplicate-business-object", lambda r: r["scenarios"]["F9"]["observed_counts"].update(
        {"backtest_jobs": 1}))
    mutate("F9-wrong-task-count", lambda r: r["scenarios"]["F9"]["observed_counts"].update(
        {"research_tasks": 2}))
    # B1
    mutate("B1-no-token-allowed", lambda r: r["boundary_controls"].update({"no_token_status": 200}))
    mutate("B1-forged-token-allowed", lambda r: r["boundary_controls"].update(
        {"forged_token_status": 200}))
    mutate("B1-forged-attempt-accepted", lambda r: r["boundary_controls"].update(
        {"forged_attempt_status": 200}))
    mutate("B1-control-reached-provider", lambda r: r["boundary_controls"].update(
        {"provider_calls_delta": 1}))
    mutate("B1-control-created-stage-call", lambda r: r["boundary_controls"].update(
        {"stage_calls_delta": 1}))
    # B2
    mutate("B2-cleanup-nonzero", lambda r: r["cleanup"].update({"containers": 1}))
    mutate("B2-production-touched", lambda r: r["cleanup"].update({"production_untouched": False}))
    # B3
    mutate("B3-identity-mismatch", lambda r: r["durable_identity"].update(
        {"stage_call_identity": "byq-judgment-" + "b" * 32}))
    mutate("B3-duplicate-call-index", lambda r: r["durable_identity"].update(
        {"duplicate_call_index": True}))
    mutate("B3-generation-inconsistent", lambda r: r["durable_identity"].update(
        {"generation_consistent": False}))
    # B4
    mutate("B4-model-supplied-identity", lambda r: r["adapter_binding"].update(
        {"derives_identity_server_side": False}))
    mutate("B4-non-none-durable-evidence-accepted", lambda r: r["adapter_binding"].update(
        {"rejects_non_none_durable_evidence": False}))
    mutate("B4-forbidden-result-field", lambda r: r["adapter_binding"].update(
        {"forbidden_result_fields": ["next_action"]}))
    # B5
    mutate("B5-fabricated-completed-state", lambda r: r["convergence"].update(
        {"fabricated_completed_state": True}))
    mutate("B5-state-outside-vocabulary", lambda r: r["convergence"].update(
        {"terminal_states_observed": ["pending_admitted", "completed_fabricated"]}))
    # native recovery
    mutate("native-recovery-claimed", lambda r: r["non_claims"].update(
        {"dsh_native_recovery_claimed": True}))
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
