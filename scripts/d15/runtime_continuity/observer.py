#!/usr/bin/env python3
"""Fail-able observer/verdict for the D15 runtime-continuity qualification.

Separation of concerns (review fix):

* ``format_valid``  — the observations artifact is well formed and every
  invariant / relationship check that ran has passed. A structurally valid
  "report" can still be an unqualified run.
* ``all_pass``      — the **qualification** passed: every REQUIRED scenario is
  present and PASS, no scenario FAILed and there are no structural violations.
  A REQUIRED scenario left ``NOT_RUN``/``BLOCKED`` therefore makes the verdict
  fail (non-zero exit) even though its status/reason is preserved.

The contract is the only source of truth for ``allowed_continuity`` /
``forbidden_continuity``. Observations may NOT relax or override contract
criteria; any attempt is rejected.

It never inspects implementation internals and never treats missing evidence as
a pass. ``--selfcheck`` mutates a known-good *unit* fixture in every fail-closed
way and asserts each mutation is rejected. That fixture is a unit test only and
is never runtime PASS evidence: runtime evidence must carry
``evidence_class == contract.required_evidence_class`` and real
PID/generation/epoch relationships plus receipt/trace linkage.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_CONTRACT = HERE / "contract.v5.json"

_RUN_ID = re.compile(r"^[0-9a-f]{32}$")


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


def _as_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _require_before_after(block: object, fields: list[str], ctx: str, failures: list[str]) -> dict:
    if not isinstance(block, dict):
        failures.append(f"{ctx}: not an object")
        return {}
    for field in fields:
        if field not in block:
            failures.append(f"{ctx}: missing '{field}'")
    return block


def _check_action_receipts(receipts: object, fields: list[str], ctx: str, failures: list[str],
                           origins: list[str] | None = None) -> bool:
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
        if origins is not None and receipt.get("origin") not in origins:
            failures.append(f"{item_ctx}: unlabeled action origin {receipt.get('origin')!r}")
            ok = False
        # side_effect_count must be measured by the capture layer, never defaulted.
        count = _as_int(receipt.get("side_effect_count"))
        if count is None:
            failures.append(f"{item_ctx}: side_effect_count was not measured")
            ok = False
        elif count != 1:
            failures.append(f"{item_ctx}: duplicate side effect (side_effect_count={count!r})")
            ok = False
        prior = seen.get(str(key))
        if prior is not None and prior != receipt.get("receipt"):
            failures.append(f"{item_ctx}: replay receipt changed for idempotency key {key!r}")
            ok = False
        if _is_nonempty_str(key):
            seen[str(key)] = str(receipt.get("receipt"))
        replay = receipt.get("replay")
        replay_receipt = replay.get("receipt") if isinstance(replay, dict) else None
        if receipt.get("origin") == "agent-mcp":
            # The replay must be a SECOND real tool response for the same domain
            # object: same task id, distinct real tool_call_id, one side effect.
            first = receipt.get("receipt") if isinstance(receipt.get("receipt"), dict) else {}
            second = replay_receipt if isinstance(replay_receipt, dict) else {}
            if not _is_nonempty_str(first.get("task_id")) or first.get("task_id") != second.get("task_id"):
                failures.append(f"{item_ctx}: agent-mcp replay task id does not match the delivery")
                ok = False
            first_call = first.get("tool_call_id")
            second_call = second.get("tool_call_id")
            if not _is_nonempty_str(first_call) or not _is_nonempty_str(second_call) or first_call == second_call:
                failures.append(f"{item_ctx}: agent-mcp replay is not a distinct real tool response")
                ok = False
            if not isinstance(replay, dict) or _as_int(replay.get("side_effect_count")) != 1:
                failures.append(f"{item_ctx}: agent-mcp replay did not report one side effect")
                ok = False
        elif not isinstance(replay, dict) or replay_receipt != receipt.get("receipt") \
                or _as_int(replay.get("side_effect_count")) != 1:
            failures.append(f"{item_ctx}: replay did not deduplicate the side effect")
            ok = False
    return ok


def _check_approval(approval: object, states: list[str], required_trials: list[str],
                    ctx: str, failures: list[str],
                    required_post_fault_trials: list[str] | None = None) -> bool:
    if not isinstance(approval, dict):
        failures.append(f"{ctx}: approval must be an object")
        return False
    ok = True
    if not _is_nonempty_str(approval.get("approval_id")):
        failures.append(f"{ctx}.approval: missing approval_id")
        ok = False
    if approval.get("state") not in states:
        failures.append(f"{ctx}.approval: invalid state {approval.get('state')!r}")
        ok = False
    if not _is_nonempty_str(approval.get("decided_by")):
        failures.append(f"{ctx}.approval: missing decided_by (must come from the persisted approval)")
        ok = False
    if approval.get("state") == "approved" and approval.get("execution_authorized") is not True:
        failures.append(f"{ctx}.approval: approved state without persisted execution_authorized=true")
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

    if not required_trials and "trials" not in approval:
        # Legacy path: the pre-fix algorithm did not know about deny trials.
        return ok
    trials = approval.get("trials")
    if not isinstance(trials, list):
        failures.append(f"{ctx}.approval: missing persisted deny trials")
        return False
    by_kind = {}
    for index, trial in enumerate(trials):
        item_ctx = f"{ctx}.approval.trials[{index}]"
        if not isinstance(trial, dict):
            failures.append(f"{item_ctx}: not an object")
            ok = False
            continue
        kind = trial.get("kind")
        if kind in by_kind:
            failures.append(f"{item_ctx}: duplicate trial kind {kind!r}")
            ok = False
        by_kind[kind] = trial
        if trial.get("denied") is not True:
            failures.append(f"{item_ctx}: deny trial was not denied")
            ok = False
        if trial.get("side_effect_created") is not False:
            failures.append(f"{item_ctx}: deny trial created a side effect (approval bypassed)")
            ok = False
        if trial.get("state") not in states:
            failures.append(f"{item_ctx}: invalid persisted trial state {trial.get('state')!r}")
            ok = False
        if kind in {"invalid_reuse", "protected_operation_blocked"}:
            status = _as_int(trial.get("http_status"))
            if status is None or not 400 <= status < 500:
                failures.append(
                    f"{item_ctx}: denial must be a definitive 4xx client rejection, got {trial.get('http_status')!r}")
                ok = False
            if not _is_nonempty_str(trial.get("domain_code")):
                failures.append(f"{item_ctx}: denial has no domain error code")
                ok = False
            if kind in (required_post_fault_trials or []) and trial.get("phase") != "post-fault":
                failures.append(
                    f"{item_ctx}: a post-fault re-attempt is required, got phase {trial.get('phase')!r}")
                ok = False
        if kind == "protected_operation_blocked":
            before = _as_int(trial.get("before_count"))
            after = _as_int(trial.get("after_count"))
            if before is None or after is None or before != after:
                failures.append(
                    f"{item_ctx}: protected-operation side-effect count changed ({before!r}->{after!r})")
                ok = False
    for kind in required_trials:
        if kind not in by_kind:
            failures.append(f"{ctx}.approval: missing required deny trial {kind!r}")
            ok = False
    return ok


# --------------------------------------------------------------------------
# Recovery relationship / linkage checks (contract-authoritative).
# --------------------------------------------------------------------------

def _pid_changed(before: dict, after: dict) -> bool:
    b, a = _as_int(before.get("adapter_pid")), _as_int(after.get("adapter_pid"))
    return b is not None and a is not None and b > 0 and a > 0 and b != a


def _pid_stable(before: dict, after: dict) -> bool:
    b, a = _as_int(before.get("adapter_pid")), _as_int(after.get("adapter_pid"))
    return b is not None and a is not None and b > 0 and a > 0 and b == a


def _generation_incremented(before: dict, after: dict) -> bool:
    b = _as_int(before.get("generation_index"))
    a = _as_int(after.get("generation_index"))
    if b is None or a is None or b < 1 or a < 1:
        return False
    if a <= b:
        return False
    return _is_nonempty_str(after.get("adapter_generation")) \
        and after.get("adapter_generation") != before.get("adapter_generation")


def _epoch_unchanged(before: dict, after: dict) -> bool:
    b, a = _as_int(before.get("executor_epoch")), _as_int(after.get("executor_epoch"))
    return b is not None and a is not None and b >= 1 and b == a


def _epoch_incremented(before: dict, after: dict) -> bool:
    b, a = _as_int(before.get("executor_epoch")), _as_int(after.get("executor_epoch"))
    return b is not None and a is not None and b >= 1 and a > b


def _goal_receipt_linked(before: dict, after: dict) -> bool:
    goal = after.get("goal") if isinstance(after.get("goal"), dict) else {}
    receipt = goal.get("prompt_receipt") if isinstance(goal.get("prompt_receipt"), dict) else {}
    root = receipt.get("root_run_id")
    if not _is_nonempty_str(receipt.get("content_sha256")) or receipt.get("content_sha256") != goal.get("content_sha256"):
        return False
    if not isinstance(root, str) or _RUN_ID.fullmatch(root) is None:
        return False
    result = after.get("result") if isinstance(after.get("result"), dict) else {}
    if result.get("run_id") == root:
        return True
    for item in after.get("action_receipts", []) if isinstance(after.get("action_receipts"), list) else []:
        payload = item.get("receipt") if isinstance(item, dict) else None
        if isinstance(payload, dict) and root in (payload.get("run_id"), payload.get("root_run_id")):
            return True
    return False


def _domain_receipt_linked(before: dict, after: dict) -> bool:
    receipts = after.get("action_receipts") if isinstance(after.get("action_receipts"), list) else []
    approval_id = (after.get("approval") or {}).get("approval_id") if isinstance(after.get("approval"), dict) else None
    pool_linked = False
    approval_linked = False
    for item in receipts:
        payload = item.get("receipt") if isinstance(item, dict) else None
        if not isinstance(payload, dict):
            continue
        if _is_nonempty_str(payload.get("pool_id")):
            pool_linked = True
        if _is_nonempty_str(payload.get("approval_id")) and payload.get("approval_id") == approval_id:
            approval_linked = True
    return pool_linked and approval_linked


def _sequence_advanced_or_held(before: dict, after: dict) -> bool:
    b = _as_int((before.get("result") or {}).get("sequence")) if isinstance(before.get("result"), dict) else None
    a = _as_int((after.get("result") or {}).get("sequence")) if isinstance(after.get("result"), dict) else None
    return b is not None and a is not None and a >= b


def _result_attributed_to_target_run(before: dict, after: dict) -> bool:
    """The reported result must be the TARGET run's own completion, not any assistant."""
    result = after.get("result") if isinstance(after.get("result"), dict) else {}
    goal = after.get("goal") if isinstance(after.get("goal"), dict) else {}
    receipt = goal.get("prompt_receipt") if isinstance(goal.get("prompt_receipt"), dict) else {}
    target = receipt.get("root_run_id")
    if not isinstance(target, str) or _RUN_ID.fullmatch(target) is None:
        return False
    if result.get("target_run_id") != target or result.get("run_id") != target:
        return False
    if result.get("status") != "completed":
        return False
    if result.get("terminal_kind") != "session.result":
        return False
    if result.get("trace_contiguous") is not True:
        return False
    attributed = _as_int(result.get("attributed_message_sequence"))
    return attributed is not None and attributed > 0


def _agent_mcp_at_most_once(before: dict, after: dict) -> bool:
    """The same real Agent->MCP domain object with one side effect across the fault."""

    def find(state: dict) -> dict | None:
        receipts = state.get("action_receipts") if isinstance(state.get("action_receipts"), list) else []
        for item in receipts:
            if isinstance(item, dict) and item.get("origin") == "agent-mcp":
                return item
        return None

    first, second = find(before), find(after)
    if first is None or second is None:
        return False
    if first.get("idempotency_key") != second.get("idempotency_key"):
        return False
    first_task = (first.get("receipt") or {}).get("task_id") if isinstance(first.get("receipt"), dict) else None
    second_task = (second.get("receipt") or {}).get("task_id") if isinstance(second.get("receipt"), dict) else None
    if not _is_nonempty_str(first_task) or first_task != second_task:
        return False
    if _as_int(first.get("side_effect_count")) != 1 or _as_int(second.get("side_effect_count")) != 1:
        return False
    replay = second.get("replay") if isinstance(second.get("replay"), dict) else {}
    replay_receipt = replay.get("receipt") if isinstance(replay.get("receipt"), dict) else {}
    return replay_receipt.get("task_id") == second_task and _as_int(replay.get("side_effect_count")) == 1


def _agent_mcp_two_run_replay(before: dict, after: dict) -> bool:
    """Two real runs, two real tool calls, one domain object, one side effect."""

    def runs(state: dict) -> dict:
        value = state.get("agent_mcp_runs")
        return value if isinstance(value, dict) else {}

    first = runs(before).get("first")
    second = runs(after).get("second")
    if not isinstance(first, dict) or not isinstance(second, dict):
        return False
    if not _is_nonempty_str(first.get("run_id")) or not _is_nonempty_str(second.get("run_id")):
        return False
    if first["run_id"] == second["run_id"]:
        return False
    if not _is_nonempty_str(first.get("tool_call_id")) or not _is_nonempty_str(second.get("tool_call_id")):
        return False
    if first["tool_call_id"] == second["tool_call_id"]:
        return False
    if not _is_nonempty_str(first.get("task_id")) or first["task_id"] != second.get("task_id"):
        return False
    if first.get("mcp_status") != "ok" or second.get("mcp_status") != "ok":
        return False
    if first.get("terminal_kind") != "session.result" or second.get("terminal_kind") != "session.result":
        return False
    for run in (first, second):
        assistant = _as_int(run.get("assistant_sequence"))
        if assistant is None or assistant <= 0:
            return False
        if _as_int(run.get("side_effect_count")) != 1:
            return False
    first_index = _as_int(first.get("call_index"))
    second_index = _as_int(second.get("call_index"))
    return first_index is not None and second_index is not None and second_index > first_index


RELATIONSHIP_CHECKS = {
    "pid_changed": _pid_changed,
    "agent_mcp_at_most_once": _agent_mcp_at_most_once,
    "agent_mcp_two_run_replay": _agent_mcp_two_run_replay,
    "pid_stable": _pid_stable,
    "generation_incremented": _generation_incremented,
    "epoch_unchanged": _epoch_unchanged,
    "epoch_incremented": _epoch_incremented,
    "goal_receipt_linked": _goal_receipt_linked,
    "domain_receipt_linked": _domain_receipt_linked,
    "sequence_advanced_or_held": _sequence_advanced_or_held,
    "result_attributed_to_target_run": _result_attributed_to_target_run,
}


def _check_relationships(spec: dict, before: dict, after: dict, ctx: str,
                         failures: list[str]) -> dict[str, bool]:
    out: dict[str, bool] = {}
    for name in spec.get("relationships", []):
        check = RELATIONSHIP_CHECKS.get(name)
        if check is None:
            failures.append(f"{ctx}: unknown contract relationship {name!r}")
            out[name] = False
            continue
        ok = bool(check(before, after))
        out[name] = ok
        if not ok:
            failures.append(f"{ctx}: recovery relationship '{name}' violated")
    return out


def _check_scenario(scenario: dict, spec: dict, contract: dict, failures: list[str]) -> dict:
    scenario_id = scenario.get("id")
    ctx = f"scenario[{scenario_id}]"
    result = scenario.get("result")
    if result not in contract["results_vocabulary"]:
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
        "recovery_relationship_truthful": False,
        "evidence_not_fabricated": False,
    }
    row = {"id": scenario_id, "result": result,
           "required": bool(spec.get("required", False)), "invariants": checks}

    # Contract criteria are authoritative. An observation may NOT declare them.
    for forbidden_field in ("allowed_continuity", "forbidden_continuity"):
        if forbidden_field in scenario:
            failures.append(f"{ctx}: observation may not declare '{forbidden_field}'; contract criteria are authoritative")

    if result in {"NOT_RUN", "BLOCKED"}:
        if contract.get("not_run_requires_reason") and not _is_nonempty_str(scenario.get("not_run_reason")):
            failures.append(f"{ctx}: {result} without a reason")
        row["not_run_reason"] = scenario.get("not_run_reason")
        return row

    if result != "PASS":
        failures.append(f"{ctx}: result {result!r} is not PASS")
        return row

    if scenario.get("fault_applied") is not True:
        failures.append(f"{ctx}: fault_applied is not true (scenario was not actually exercised)")

    before = _require_before_after(
        scenario.get("before"), contract["required_before_after_fields"], f"{ctx}.before", failures)
    after = _require_before_after(
        scenario.get("after"), contract["required_before_after_fields"], f"{ctx}.after", failures)

    # No success defaults: the capture layer must report capture_ok and any
    # capture_errors; a missing/failed capture can never be a PASS.
    capture_errors = list(before.get("capture_errors") or []) + list(after.get("capture_errors") or [])
    if before.get("capture_ok") is True and after.get("capture_ok") is True and not capture_errors:
        checks["evidence_not_fabricated"] = True
    else:
        failures.append(f"{ctx}: capture evidence missing or fabricated: {capture_errors or 'capture_ok false'}")

    if _is_nonempty_str(before.get("session_id")) and before.get("session_id") == after.get("session_id") \
            and before.get("trace_id") == after.get("trace_id"):
        checks["identity_stable"] = True
    else:
        failures.append(f"{ctx}: durable session/trace identity changed across the fault")

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

    checks["no_duplicate_side_effect"] = _check_action_receipts(
        after.get("action_receipts"), contract["action_receipt_fields"], f"{ctx}.after", failures,
        origins=contract.get("action_origin_vocabulary"))
    checks["approval_not_bypassed"] = _check_approval(
        after.get("approval"), contract["approval_states"],
        contract.get("required_approval_trials", []), f"{ctx}.after", failures,
        required_post_fault_trials=contract.get("required_post_fault_trials", []))

    after_result = after.get("result") if isinstance(after.get("result"), dict) else {}
    for field in contract["result_fields"]:
        if field not in after_result:
            failures.append(f"{ctx}.after.result: missing '{field}'")
    if _is_nonempty_str(after_result.get("run_id")) and _is_nonempty_str(after_result.get("status")) \
            and after_result.get("trace_contiguous") is True:
        checks["result_traceable"] = True
    else:
        failures.append(f"{ctx}: result was not durably traceable")

    if all(field in before and field in after for field in contract["required_before_after_fields"]):
        checks["before_after_captured"] = True
    else:
        failures.append(f"{ctx}: before/after capture incomplete")

    # Contract-authoritative continuity rules (never from the observation).
    allowed = set(spec.get("allowed_continuity", contract["continuity_vocabulary"]))
    forbidden = set(spec.get("forbidden_continuity", []))
    continuity = after.get("continuity")
    row["continuity"] = continuity
    if continuity not in contract["continuity_vocabulary"]:
        failures.append(f"{ctx}: invalid continuity {continuity!r}")
    elif continuity in forbidden:
        failures.append(f"{ctx}: fabricated continuity {continuity!r} after a fault")
    elif continuity not in allowed:
        failures.append(f"{ctx}: continuity {continuity!r} not in contract allowed set {sorted(allowed)}")
    else:
        checks["continuity_truthful"] = True

    before_result = before.get("result") if isinstance(before.get("result"), dict) else {}
    before_sequence = _as_int(before_result.get("sequence"))
    after_sequence = _as_int(after_result.get("sequence"))
    if before_sequence is not None and after_sequence is not None \
            and after_sequence >= before_sequence and after_result.get("trace_contiguous") is True:
        checks["sequence_contiguous"] = True
    else:
        failures.append(f"{ctx}: result sequence regressed or is not contiguous")

    relationships = _check_relationships(spec, before, after, ctx, failures)
    checks["recovery_relationship_truthful"] = bool(relationships) and all(relationships.values())
    row["relationships"] = relationships
    row["before"] = before
    row["after"] = after
    return row


def compute_verdict(contract: dict, observations: dict, *, allow_unit_fixture: bool = False) -> dict:
    failures: list[str] = []
    coverage_failures: list[str] = []
    candidate = contract["candidate"]

    if not isinstance(observations, dict):
        raise Failure("observations must be an object")

    observed_candidate = observations.get("candidate")
    if not isinstance(observed_candidate, dict) or observed_candidate.get("release") != candidate["release"]:
        failures.append(f"candidate mismatch: expected {candidate['release']!r}, got {observed_candidate!r}")

    required_class = contract.get("required_evidence_class")
    observed_class = observations.get("evidence_class")
    if allow_unit_fixture:
        if not _is_nonempty_str(observed_class):
            failures.append("evidence_class must be declared")
    elif observed_class != required_class:
        failures.append(
            f"evidence_class {observed_class!r} is not runtime evidence {required_class!r}; "
            "a synthetic/unit fixture is not runtime PASS evidence")

    llm = observations.get("llm")
    if not isinstance(llm, dict) or llm.get("class") != contract["llm_evidence_class"] \
            or llm.get("real_llm_quality") is not False:
        failures.append("LLM evidence class must be explicitly keyless/scripted with real_llm_quality=false")

    scenarios_value = observations.get("scenarios")
    if not isinstance(scenarios_value, list):
        failures.append("scenarios must be a list")
        scenarios_value = []

    required = {item["id"]: item for item in contract.get("required_scenarios", [])}
    optional = {item["id"]: item for item in contract.get("optional_scenarios", [])}
    specs = {**required, **optional}

    observed_ids = [item.get("id") if isinstance(item, dict) else None for item in scenarios_value]
    if len(observed_ids) != len(set(map(str, observed_ids))):
        failures.append("duplicate scenario id in observations")
    if contract.get("closed_scenario_set"):
        for scenario_id in observed_ids:
            if scenario_id not in specs:
                failures.append(f"unknown scenario id {scenario_id!r} (closed set)")

    scenario_results = []
    for item in scenarios_value:
        if not isinstance(item, dict):
            failures.append("scenario entry is not an object")
            continue
        spec = specs.get(item.get("id"), {"required": False})
        scenario_results.append(_check_scenario(item, spec, contract, failures))

    seen_ids = set(observed_ids)
    for scenario_id in required:
        if scenario_id not in seen_ids:
            failures.append(f"missing required scenario {scenario_id!r}")

    rows = {row["id"]: row for row in scenario_results}
    required_coverage: dict[str, str] = {}
    for scenario_id in required:
        row = rows.get(scenario_id)
        required_coverage[scenario_id] = row["result"] if row is not None else "MISSING"
        if row is None or row["result"] != "PASS":
            coverage_failures.append(
                f"required scenario {scenario_id!r} is not covered by a PASS "
                f"(observed {required_coverage[scenario_id]})")
    optional_coverage: dict[str, str] = {}
    for scenario_id in optional:
        row = rows.get(scenario_id)
        optional_coverage[scenario_id] = row["result"] if row is not None else "MISSING"

    required_coverage_ok = contract.get("required_coverage_gates_qualification", True) \
        and all(value == "PASS" for value in required_coverage.values()) \
        and len(required_coverage) == len(required)

    failed = [row["id"] for row in scenario_results if row["result"] == "FAIL"]
    pass_scenarios = [row for row in scenario_results if row["result"] == "PASS"]
    uncovered = [row["id"] for row in scenario_results if row["result"] in {"NOT_RUN", "BLOCKED"}]

    format_valid = not failures
    all_pass = format_valid and not failed and required_coverage_ok
    return {
        "schema_version": "byq-d15-runtime-verdict.v2",
        "all_pass": all_pass,
        "format_valid": format_valid,
        "qualification_passed": all_pass,
        "exit_code": 0 if all_pass else 1,
        "candidate": candidate,
        "evidence_class": observed_class,
        "llm_evidence_class": contract["llm_evidence_class"],
        "required_scenario_count": len(required),
        "optional_scenario_count": len(optional),
        "required_coverage": required_coverage,
        "required_coverage_ok": required_coverage_ok,
        "optional_coverage": optional_coverage,
        "pass_scenarios": [row["id"] for row in pass_scenarios],
        "failed_scenarios": failed,
        "uncovered_scenarios": uncovered,
        "scenarios": scenario_results,
        "failures": failures,
        "coverage_failures": coverage_failures,
        "invariant_coverage": {
            invariant: all(row["invariants"][invariant] for row in pass_scenarios
                           if invariant in row["invariants"])
            for invariant in contract["invariants"]
        } if pass_scenarios else {invariant: False for invariant in contract["invariants"]},
    }


# --------------------------------------------------------------------------
# Legacy (pre-fix) algorithm, executed only to prove the pre-fix behaviour.
# --------------------------------------------------------------------------

def _legacy_check_scenario(scenario: dict, spec: dict, contract: dict, failures: list[str]) -> dict:
    """Pre-fix scenario check: observed allowed/forbidden override, no relationships."""
    scenario_id = scenario.get("id")
    ctx = f"scenario[{scenario_id}]"
    result = scenario.get("result")
    if result not in contract["results_vocabulary"]:
        failures.append(f"{ctx}: invalid result {result!r}")
    if result in {"NOT_RUN", "BLOCKED"}:
        if contract.get("not_run_requires_reason") and not _is_nonempty_str(scenario.get("not_run_reason")):
            failures.append(f"{ctx}: {result} without a reason")
        return {"id": scenario_id, "result": result}
    if result != "PASS":
        failures.append(f"{ctx}: result {result!r} is not PASS")
        return {"id": scenario_id, "result": result}
    if scenario.get("fault_applied") is not True:
        failures.append(f"{ctx}: fault_applied is not true")
    before = scenario.get("before") if isinstance(scenario.get("before"), dict) else {}
    after = scenario.get("after") if isinstance(scenario.get("after"), dict) else {}
    if before.get("session_id") != after.get("session_id") or not _is_nonempty_str(before.get("session_id")):
        failures.append(f"{ctx}: identity changed")
    bg = before.get("goal") if isinstance(before.get("goal"), dict) else {}
    ag = after.get("goal") if isinstance(after.get("goal"), dict) else {}
    if not _is_nonempty_str(bg.get("content_sha256")) or bg.get("content_sha256") != ag.get("content_sha256") \
            or ag.get("prompt_receipt") != bg.get("prompt_receipt"):
        failures.append(f"{ctx}: goal drifted")
    # Pre-fix receipt check: replay must equal the delivery (the old algorithm
    # had no concept of a distinct second real tool response).
    for index, receipt in enumerate(after.get("action_receipts", []) if isinstance(
            after.get("action_receipts"), list) else []):
        item_ctx = f"{ctx}.after.action_receipts[{index}]"
        if not isinstance(receipt, dict):
            failures.append(f"{item_ctx}: not an object")
            continue
        for field in contract["action_receipt_fields"]:
            if field not in receipt:
                failures.append(f"{item_ctx}: missing '{field}'")
        if receipt.get("side_effect_count") != 1:
            failures.append(f"{item_ctx}: side effect count")
        replay = receipt.get("replay")
        if not isinstance(replay, dict) or replay.get("receipt") != receipt.get("receipt") \
                or replay.get("side_effect_count") != 1:
            failures.append(f"{item_ctx}: replay did not deduplicate")
    _check_approval(after.get("approval"), contract["approval_states"], [], f"{ctx}.after", failures)
    ar = after.get("result") if isinstance(after.get("result"), dict) else {}
    if ar.get("trace_contiguous") is not True or not _is_nonempty_str(ar.get("run_id")):
        failures.append(f"{ctx}: result not traceable")
    allowed = set(scenario.get("allowed_continuity", contract["continuity_vocabulary"]))
    forbidden = set(scenario.get("forbidden_continuity", []))
    continuity = after.get("continuity")
    if continuity not in contract["continuity_vocabulary"] or continuity in forbidden or continuity not in allowed:
        failures.append(f"{ctx}: continuity not truthful")
    return {"id": scenario_id, "result": result}


def legacy_compute_verdict(contract: dict, observations: dict) -> dict:
    """Execute the pre-fix algorithm to record its (incorrect) behaviour.

    This is a real execution of the historical logic, not a fabricated claim:
    required NOT_RUN/BLOCKED did not gate PASS and observations could relax the
    contract continuity rules via ``setdefault``.
    """
    failures: list[str] = []
    required = {item["id"]: item for item in contract.get("required_scenarios", [])}
    # The pre-fix algorithm had no concept of a distinct second real tool
    # response; normalize the new-shape agent-mcp receipts to its world view.
    observations = copy.deepcopy(observations) if isinstance(observations, dict) else observations
    for item in observations.get("scenarios", []) if isinstance(observations.get("scenarios"), list) else []:
        after = item.get("after") if isinstance(item, dict) and isinstance(item.get("after"), dict) else {}
        for receipt in after.get("action_receipts", []) if isinstance(after.get("action_receipts"), list) else []:
            if isinstance(receipt, dict) and receipt.get("origin") == "agent-mcp" \
                    and isinstance(receipt.get("replay"), dict):
                receipt["replay"]["receipt"] = receipt.get("receipt")
    scenarios = observations.get("scenarios") if isinstance(observations.get("scenarios"), list) else []
    rows = []
    for item in scenarios:
        if not isinstance(item, dict):
            continue
        merged = dict(item)
        spec = required.get(item.get("id"))
        if spec is not None:
            merged.setdefault("allowed_continuity", spec["allowed_continuity"])
            merged.setdefault("forbidden_continuity", spec["forbidden_continuity"])
        rows.append(_legacy_check_scenario(merged, spec or {"required": False}, contract, failures))
    seen = {row["id"] for row in rows}
    for scenario_id in required:
        if scenario_id not in seen:
            failures.append(f"missing required scenario {scenario_id!r}")
    failed = [row["id"] for row in rows if row["result"] == "FAIL"]
    all_pass = not failures and not failed
    return {"algorithm": "legacy-pre-fix", "all_pass": all_pass, "exit_code": 0 if all_pass else 1,
            "failures": failures}


# --------------------------------------------------------------------------
# Unit fixture + negative controls.
# --------------------------------------------------------------------------

_APPROVAL_ID = "agent_approval_" + "b" * 32


def _state(*, run_id: str, pid: int, generation: str, generation_index: int, epoch: int,
           sequence: int, continuity: str) -> dict:
    pool_id = "stock_pool_" + "c" * 32
    return {
        "session_id": "byq-session-d15-runtime-0001",
        "trace_id": "byq-trace-d15-runtime-0001",
        "adapter_pid": pid,
        "adapter_generation": generation,
        "generation_index": generation_index,
        "executor_epoch": epoch,
        "continuity": continuity,
        "capture_ok": True,
        "capture_errors": [],
        "goal": {
            "content_sha256": "a" * 64,
            "prompt_receipt": {"root_run_id": run_id, "content_sha256": "a" * 64},
        },
        "approval": {
            "approval_id": _APPROVAL_ID, "state": "approved", "bypassed": False,
            "decided_by": "human-owner", "execution_authorized": True,
            "trials": [
                {"kind": "rejected", "state": "rejected", "denied": True, "side_effect_created": False,
                 "http_status": 201, "phase": "durable"},
                {"kind": "invalid_reuse", "state": "rejected", "denied": True, "side_effect_created": False,
                 "http_status": 409, "domain_code": "artifact idempotency key was reused",
                 "phase": "post-fault"},
                {"kind": "protected_operation_blocked", "state": "rejected", "denied": True,
                 "side_effect_created": False, "http_status": 422,
                 "domain_code": "strategy version is not approved for execution",
                 "before_count": 0, "after_count": 0, "phase": "post-fault"},
            ],
        },
        "action_receipts": [
            {"tool": "runtime.prompt.idempotent", "origin": "product-api-manual",
             "idempotency_key": "d15-runtime-idem-0001",
             "receipt": {"state": "accepted", "run_id": run_id}, "side_effect_count": 1,
             "replay": {"receipt": {"state": "accepted", "run_id": run_id}, "side_effect_count": 1}},
            {"tool": "byq_paper_pool_create", "origin": "product-api-manual",
             "idempotency_key": "d15-runtime-pool-0001",
             "receipt": {"state": "accepted", "pool_id": pool_id}, "side_effect_count": 1,
             "replay": {"receipt": {"state": "accepted", "pool_id": pool_id}, "side_effect_count": 1}},
            {"tool": "byq_strategy_approval", "origin": "product-api-manual",
             "idempotency_key": "d15-runtime-approval-0001",
             "receipt": {"state": "approved", "approval_id": _APPROVAL_ID}, "side_effect_count": 1,
             "replay": {"receipt": {"state": "approved", "approval_id": _APPROVAL_ID}, "side_effect_count": 1}},
        ],
        "result": {
            "run_id": run_id, "status": "completed", "sequence": sequence, "trace_contiguous": True,
            "target_run_id": run_id, "terminal_kind": "session.result",
            "attributed_message_sequence": sequence,
        },
    }


def _agent_mcp_state(*, run_id: str, task_id: str, pid: int, generation: str, generation_index: int,
                     epoch: int, sequence: int, continuity: str, include_second: bool = False) -> dict:
    trace = "byq-trace-d15-agentmcp-0001"
    first_run = {"run_id": run_id, "message_id": "message-first", "tool_call_id": "d15-tool-1",
                 "call_index": 1, "task_id": task_id, "mcp_status": "ok",
                 "terminal_kind": "session.result", "terminal_sequence": sequence,
                 "assistant_sequence": sequence - 2, "side_effect_count": 1}
    runs = {"first": first_run}
    second_run_id = "7" * 32
    if include_second:
        runs["second"] = {"run_id": second_run_id, "message_id": "message-second",
                          "tool_call_id": "d15-tool-2", "call_index": 2, "task_id": task_id,
                          "mcp_status": "ok", "terminal_kind": "session.result",
                          "terminal_sequence": sequence, "assistant_sequence": sequence - 1,
                          "side_effect_count": 1}
    replay_call = "d15-tool-2" if include_second else "d15-tool-1"
    return {
        "session_id": "byq-session-d15-agentmcp-0001",
        "trace_id": trace,
        "adapter_pid": pid,
        "adapter_generation": generation,
        "generation_index": generation_index,
        "executor_epoch": epoch,
        "continuity": continuity,
        "capture_ok": True,
        "capture_errors": [],
        "goal": {
            "content_sha256": "d" * 64,
            "prompt_receipt": {"root_run_id": run_id, "content_sha256": "d" * 64},
        },
        "approval": {
            "approval_id": _APPROVAL_ID, "state": "approved", "bypassed": False,
            "decided_by": "human-owner", "execution_authorized": True,
            "trials": [
                {"kind": "rejected", "state": "rejected", "denied": True, "side_effect_created": False,
                 "http_status": 201, "phase": "durable"},
                {"kind": "invalid_reuse", "state": "rejected", "denied": True, "side_effect_created": False,
                 "http_status": 409, "domain_code": "artifact idempotency key was reused",
                 "phase": "post-fault"},
                {"kind": "protected_operation_blocked", "state": "rejected", "denied": True,
                 "side_effect_created": False, "http_status": 422,
                 "domain_code": "strategy version is not approved for execution",
                 "before_count": 0, "after_count": 0, "phase": "post-fault"},
            ],
        },
        "action_receipts": [
            {"tool": "mcp__byq__byq_research_task_create", "origin": "agent-mcp",
             "idempotency_key": "d15-mcp-key-0001",
             "receipt": {"state": "accepted", "task_id": task_id, "tool_call_id": "d15-tool-1",
                         "trace_id": trace},
             "side_effect_count": 1,
             "replay": {"receipt": {"state": "accepted", "task_id": task_id, "tool_call_id": replay_call,
                                    "trace_id": trace},
                        "side_effect_count": 1}},
        ],
        "agent_mcp_runs": runs,
        "result": {
            "run_id": run_id, "status": "completed", "sequence": sequence, "trace_contiguous": True,
            "target_run_id": run_id, "terminal_kind": "session.result",
            "attributed_message_sequence": sequence,
        },
    }


def _scenario(scenario_id: str, run_id: str, *, before: dict, after: dict) -> dict:
    return {
        "id": scenario_id,
        "result": "PASS",
        "fault_applied": True,
        "before": before,
        "after": after,
        "evidence": [f"docs/evidence/d15/d15-runtime/scenarios/{scenario_id}.v2.json"],
    }


def valid_fixture(contract: dict) -> dict:
    """Synthetic UNIT fixture. Never runtime PASS evidence (evidence_class=unit-fixture)."""
    scenarios = [
        _scenario("adapter-process-restart", "1" * 32,
                  before=_state(run_id="1" * 32, pid=2000, generation="generation-g1",
                                generation_index=1, epoch=1, sequence=10, continuity="reattached"),
                  after=_state(run_id="1" * 32, pid=2001, generation="generation-g2",
                               generation_index=2, epoch=1, sequence=11, continuity="rehydrated")),
        _scenario("dsh-process-interruption", "2" * 32,
                  before=_state(run_id="2" * 32, pid=2001, generation="generation-g2",
                                generation_index=2, epoch=1, sequence=11, continuity="reattached"),
                  after=_state(run_id="2" * 32, pid=2001, generation="generation-g3",
                               generation_index=3, epoch=1, sequence=12, continuity="rehydrated")),
        _scenario("gateway-disconnect-reconnect", "3" * 32,
                  before=_state(run_id="3" * 32, pid=2001, generation="generation-g3",
                                generation_index=3, epoch=1, sequence=12, continuity="reattached"),
                  after=_state(run_id="3" * 32, pid=2001, generation="generation-g3",
                               generation_index=3, epoch=1, sequence=12, continuity="reattached")),
        _scenario("generation-replacement", "4" * 32,
                  before=_state(run_id="4" * 32, pid=2001, generation="generation-g3",
                                generation_index=3, epoch=1, sequence=12, continuity="reattached"),
                  after=_state(run_id="4" * 32, pid=2001, generation="generation-g4",
                               generation_index=4, epoch=1, sequence=13, continuity="interrupted")),
        _scenario("executor-takeover", "5" * 32,
                  before=_state(run_id="5" * 32, pid=2001, generation="generation-g4",
                                generation_index=4, epoch=1, sequence=13, continuity="reattached"),
                  after=_state(run_id="5" * 32, pid=2001, generation="generation-g4",
                               generation_index=4, epoch=2, sequence=13, continuity="reattached")),
    ]
    scenarios.append(_scenario(
        "agent-mcp-domain-at-most-once", "6" * 32,
        before=_agent_mcp_state(run_id="6" * 32, task_id="task_" + "7" * 32, pid=2002,
                                generation="generation-g5", generation_index=5, epoch=1,
                                sequence=14, continuity="fresh"),
        after=_agent_mcp_state(run_id="6" * 32, task_id="task_" + "7" * 32, pid=2003,
                               generation="generation-g6", generation_index=6, epoch=1,
                               sequence=15, continuity="rehydrated", include_second=True)))
    scenarios.append({
        "id": "host-reboot", "result": "NOT_RUN",
        "not_run_reason": "not executed: host reboot is not authorized and a container restart is not a host reboot",
    })
    return {
        "schema_version": "byq-d15-runtime-observations.v2",
        "evidence_class": "unit-fixture",
        "candidate": dict(contract["candidate"]),
        "llm": {"class": contract["llm_evidence_class"], "real_llm_quality": False,
                "note": "negative-control unit fixture (not runtime evidence)"},
        "scenarios": scenarios,
    }


def _mutations(fixture: dict) -> list[tuple[str, dict]]:
    mutations: list[tuple[str, dict]] = []
    defect_targeting = {
        "all-required-not-run", "single-required-blocked", "reasoned-not-executed",
        "observation-relaxes-allowed-continuity", "observation-clears-forbidden-continuity",
    }

    def add(name: str, mutate) -> None:
        value = copy.deepcopy(fixture)
        mutate(value)
        mutations.append((name, value))

    add("missing-required-scenario", lambda v: v["scenarios"].pop(0))
    add("duplicate-scenario-id", lambda v: v["scenarios"].append(copy.deepcopy(v["scenarios"][0])))
    add("unknown-scenario-id", lambda v: v["scenarios"][0].update({"id": "invented-scenario"}))
    add("missing-evidence-field", lambda v: v["scenarios"][0]["after"].pop("goal"))
    add("original-goal-drift", lambda v: v["scenarios"][0]["after"]["goal"].update({"content_sha256": "c" * 64}))
    add("duplicate-side-effect", lambda v: v["scenarios"][0]["after"]["action_receipts"][0].update(
        {"side_effect_count": 2}))
    add("replay-did-not-deduplicate", lambda v: v["scenarios"][0]["after"]["action_receipts"][0][
        "replay"].update({"side_effect_count": 2}))
    add("changed-replay-receipt", lambda v: v["scenarios"][0]["after"]["action_receipts"][0][
        "replay"].update({"receipt": {"state": "accepted", "run_id": "9" * 32}}))
    add("approval-bypassed", lambda v: v["scenarios"][0]["after"]["approval"].update({"bypassed": True}))
    add("expired-approval-reuse", lambda v: v["scenarios"][0]["after"]["approval"].update(
        {"state": "expired", "reuse_denied": False}))
    add("initiator-self-approval", lambda v: v["scenarios"][0]["after"]["approval"].update(
        {"decided_by": "byq-product-agent", "initiator": "byq-product-agent"}))
    add("fabricated-fresh-continuity", lambda v: v["scenarios"][0]["after"].update({"continuity": "fresh"}))
    add("sequence-regression", lambda v: v["scenarios"][0]["after"]["result"].update(
        {"sequence": v["scenarios"][0]["before"]["result"]["sequence"] - 1}))
    add("non-contiguous-trace", lambda v: v["scenarios"][0]["after"]["result"].update(
        {"trace_contiguous": False}))
    add("not-run-without-reason", lambda v: v["scenarios"][0].update(
        {"result": "NOT_RUN", "fault_applied": False}))
    add("candidate-mismatch", lambda v: v.update({"candidate": {"release": "dsh-0.1.2rc1"}}))
    add("llm-claims-real-quality", lambda v: v["llm"].update({"class": "real-llm", "real_llm_quality": True}))
    add("fault-not-applied", lambda v: v["scenarios"][0].update({"fault_applied": False}))
    # Recovery relationship negatives.
    add("pid-not-changed-after-restart", lambda v: v["scenarios"][0]["after"].update(
        {"adapter_pid": v["scenarios"][0]["before"]["adapter_pid"]}))
    add("generation-not-incremented", lambda v: v["scenarios"][3]["after"].update(
        {"generation_index": v["scenarios"][3]["before"]["generation_index"],
         "adapter_generation": v["scenarios"][3]["before"]["adapter_generation"]}))
    add("epoch-not-incremented-on-takeover", lambda v: v["scenarios"][4]["after"].update(
        {"executor_epoch": v["scenarios"][4]["before"]["executor_epoch"]}))
    add("broken-receipt-linkage", lambda v: v["scenarios"][0]["after"]["goal"]["prompt_receipt"].update(
        {"root_run_id": "9" * 32}))
    add("unmeasured-side-effect-count", lambda v: v["scenarios"][0]["after"]["action_receipts"][0].update(
        {"side_effect_count": None}))
    add("unlabeled-action-origin", lambda v: v["scenarios"][0]["after"]["action_receipts"][0].pop(
        "origin", None))
    add("approval-trial-side-effect", lambda v: v["scenarios"][0]["after"]["approval"]["trials"][0].update(
        {"side_effect_created": True}))
    add("approval-missing-trials", lambda v: v["scenarios"][0]["after"]["approval"].pop("trials", None))
    add("result-not-attributed-to-target", lambda v: v["scenarios"][0]["after"]["result"].update(
        {"target_run_id": "9" * 32}))
    add("capture-error-present", lambda v: (
        v["scenarios"][0]["after"].update({"capture_ok": False, "capture_errors": ["injected capture loss"]})))
    add("trace-gap-incomplete", lambda v: v["scenarios"][0]["after"]["result"].update(
        {"trace_contiguous": False, "status": "incomplete"}))
    add("only-old-assistant-result", lambda v: v["scenarios"][0]["after"]["result"].update(
        {"attributed_message_sequence": None, "status": "incomplete"}))
    # Defect-targeting negatives.
    add("all-required-not-run", lambda v: [s.update(
        {"result": "NOT_RUN", "not_run_reason": "not executed",
         "before": None, "after": None, "fault_applied": False})
        for s in v["scenarios"] if s["id"] != "host-reboot"])
    add("single-required-blocked", lambda v: next(
        s for s in v["scenarios"] if s["id"] == "generation-replacement").update(
        {"result": "BLOCKED", "not_run_reason": "blocked by environment"}))
    add("reasoned-not-executed", lambda v: next(
        s for s in v["scenarios"] if s["id"] == "executor-takeover").update(
        {"result": "NOT_RUN", "not_run_reason": "not executed in this batch"}))
    add("observation-relaxes-allowed-continuity", lambda v: v["scenarios"][0].update(
        {"allowed_continuity": ["fresh"], "forbidden_continuity": []})
        or v["scenarios"][0]["after"].update({"continuity": "fresh"}))
    add("observation-clears-forbidden-continuity", lambda v: v["scenarios"][0].update(
        {"forbidden_continuity": [], "allowed_continuity": ["fresh"]})
        or v["scenarios"][0]["after"].update({"continuity": "fresh"}))
    # Agent->MCP and approval protected-operation negatives.
    add("agent-mcp-missing", lambda v: v["scenarios"].remove(
        next(s for s in v["scenarios"] if s["id"] == "agent-mcp-domain-at-most-once")))
    add("agent-mcp-not-at-most-once", lambda v: next(
        s for s in v["scenarios"] if s["id"] == "agent-mcp-domain-at-most-once")["after"][
        "action_receipts"][0]["receipt"].update({"task_id": "task_" + "8" * 32}))
    add("agent-mcp-second-no-tool", lambda v: next(
        s for s in v["scenarios"] if s["id"] == "agent-mcp-domain-at-most-once")["after"][
        "agent_mcp_runs"].pop("second", None))
    add("agent-mcp-second-mcp-failed", lambda v: next(
        s for s in v["scenarios"] if s["id"] == "agent-mcp-domain-at-most-once")["after"][
        "agent_mcp_runs"]["second"].update({"mcp_status": "error"}))
    add("agent-mcp-only-first-run", lambda v: next(
        s for s in v["scenarios"] if s["id"] == "agent-mcp-domain-at-most-once")["after"][
        "agent_mcp_runs"]["second"].update({"run_id": "6" * 32, "tool_call_id": "d15-tool-1"}))
    add("approval-invalid-reuse-500", lambda v: v["scenarios"][0]["after"]["approval"]["trials"][1].update(
        {"http_status": 500, "domain_code": "internal error"}))
    add("approval-protected-count-changed", lambda v: v["scenarios"][0]["after"]["approval"]["trials"][2].update(
        {"after_count": 1}))
    return mutations, defect_targeting


def run_selfcheck(contract: dict) -> dict:
    fixture = valid_fixture(contract)
    baseline = compute_verdict(contract, fixture, allow_unit_fixture=True)
    legacy_baseline = legacy_compute_verdict(contract, fixture)
    mutations, defect_targeting = _mutations(fixture)
    controls = []
    for name, mutated in mutations:
        verdict = compute_verdict(contract, mutated, allow_unit_fixture=True)
        legacy = legacy_compute_verdict(contract, mutated)
        controls.append({
            "control": name,
            "defect_targeting": name in defect_targeting,
            "pre_fix_reference": "legacy-algorithm-executed",
            "legacy_algorithm_all_pass": legacy["all_pass"],
            "legacy_algorithm_exit_code": legacy["exit_code"],
            "observed_all_pass": verdict["all_pass"],
            "observed_exit_code": verdict["exit_code"],
            "observed_format_valid": verdict["format_valid"],
            "first_failure": (verdict["failures"] + verdict["coverage_failures"])[0]
            if (verdict["failures"] or verdict["coverage_failures"]) else None,
            "passes": verdict["all_pass"] is False,
        })
    all_controls_pass = all(item["passes"] for item in controls)
    targeting_ok = all(item["legacy_algorithm_all_pass"] is True
                       for item in controls if item["defect_targeting"])
    result = {
        "schema_version": "byq-d15-runtime-negative-controls.v2",
        "baseline_all_pass": baseline["all_pass"],
        "baseline_exit_code": baseline["exit_code"],
        "legacy_baseline_all_pass": legacy_baseline["all_pass"],
        "control_count": len(controls),
        "defect_targeting_controls": sorted(defect_targeting),
        "defect_targeting_pre_fix_passed": targeting_ok,
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
                        help="run negative controls over a known-good unit fixture and fail if any does not fail")
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
        return 0 if result["all_controls_pass"] and result["baseline_all_pass"] \
            and result["defect_targeting_pre_fix_passed"] else 1

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
