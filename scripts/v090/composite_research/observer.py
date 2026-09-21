#!/usr/bin/env python3
"""Fail-able observer/verdict for the 0.9 composite research fault regression (v2).

Separation of concerns:

* ``format_valid``  — the observations artifact is well formed and every
  structural check that ran has passed. A structurally valid "report" can still
  be an unqualified run.
* ``all_pass``      — the qualification passed: every REQUIRED journey step and
  every REQUIRED fault scenario is present and PASS, no structural failure
  exists, all required assertions hold, every scenario carries authoritative
  provenance (or an explicit ``not_applicable`` + reason) and cleanup left no
  orphan. A REQUIRED scenario left ``NOT_RUN``/``BLOCKED`` therefore makes the
  verdict fail (non-zero exit) while preserving its status/reason.

The contract is the only source of truth for the allowed/forbidden final states,
required assertions, required coverage, per-scenario service boundary and the
allowed provenance sources. Observations may NOT relax or override contract
criteria; any attempt is rejected.

Provenance: every scenario must carry a ``provenance`` block for trace/run/
generation/epoch/pid. A value is either a real value with a source drawn from
``contract.provenance_allowed_sources`` (and, for trace, associated with the
scenario's receipt object) or the literal ``not_applicable`` with a non-empty
reason. Hardcoded generation/epoch numbers without a contract-allowed source are
rejected, so a fabricated ``1 -> 2`` cannot pass.
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
DEFAULT_CONTRACT = HERE / "contract.v2.json"

OBSERVATIONS_SCHEMA = "byq-v090-composite-research-observations.v2"
VERDICT_SCHEMA = "byq-v090-composite-research-verdict.v2"

_OVERRIDE_KEYS = ("allowed_final_states", "forbidden_final_states",
                  "required_assertions", "required",
                  "evidence_class_override", "provenance_allowed_sources")
_NA = "not_applicable"


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


def _pattern(contract: dict, key: str) -> re.Pattern[str]:
    return re.compile(contract["identity"][key])


def _counts_ok(block: object, ctx: str, failures: list[str]) -> None:
    if not isinstance(block, dict) or not block:
        failures.append(f"{ctx}: authoritative counts must be a non-empty object")
        return
    for key, value in block.items():
        if _as_int(value) is None or value < 0:
            failures.append(f"{ctx}: count {key!r} was not measured as a non-negative int")


def _check_receipt(receipt: object, ctx: str, failures: list[str]) -> dict:
    if not isinstance(receipt, dict):
        failures.append(f"{ctx}: missing receipt")
        return {}
    for field in ("receipt_id", "object_id", "task_id", "idempotency_key"):
        if not _is_nonempty_str(receipt.get(field)):
            failures.append(f"{ctx}: receipt.{field} is empty")
    return receipt


def _check_journey(contract: dict, journey: object, failures: list[str], coverage: list[str]) -> dict:
    if not isinstance(journey, dict):
        failures.append("journey: missing or not an object")
        return {}
    expected = contract["composite_journey"]
    if journey.get("id") != expected["id"]:
        failures.append(f"journey: id {journey.get('id')!r} != contract {expected['id']!r}")
    owner = journey.get("owner")
    workspace = journey.get("workspace_id")
    task_id = journey.get("task_id")
    original_key = journey.get("original_key")
    if not _is_nonempty_str(owner):
        failures.append("journey: owner is empty")
    if not _is_nonempty_str(workspace):
        failures.append("journey: workspace_id is empty")
    if not _is_nonempty_str(task_id) or not _pattern(contract, "task_id_pattern").match(str(task_id)):
        failures.append("journey: canonical task_id required")
    if not _is_nonempty_str(original_key):
        failures.append("journey: original_key is empty")

    steps = journey.get("steps")
    if not isinstance(steps, list):
        failures.append("journey: steps must be a list")
        steps = []
    by_id = {step.get("id"): step for step in steps if isinstance(step, dict)}

    for spec in expected["required_steps"]:
        step = by_id.get(spec["id"])
        if step is None:
            failures.append(f"journey.{spec['id']}: required step missing")
            continue
        result = step.get("result")
        if result in {"NOT_RUN", "BLOCKED"}:
            coverage.append(f"journey.{spec['id']}: {result} "
                            f"({step.get('not_run_reason') or 'no reason'})")
            continue
        if result != "PASS":
            failures.append(f"journey.{spec['id']}: result {result!r} is not PASS")
            continue
        if step.get("owner") != owner:
            failures.append(f"journey.{spec['id']}: owner attribution mismatch")
        if step.get("workspace_id") != workspace:
            failures.append(f"journey.{spec['id']}: workspace attribution mismatch")
        if step.get("task_id") != task_id:
            failures.append(f"journey.{spec['id']}: task attribution mismatch")
        if spec.get("requires_object"):
            object_id = step.get("object_id")
            pattern = _pattern(contract, spec["requires_object"] + "_id_pattern")
            if not _is_nonempty_str(object_id) or not pattern.match(str(object_id)):
                failures.append(f"journey.{spec['id']}: canonical {spec['requires_object']} id required")
        if spec.get("requires_receipt"):
            receipt = _check_receipt(step.get("receipt"), f"journey.{spec['id']}", failures)
            if receipt and receipt.get("object_id") != step.get("object_id"):
                failures.append(f"journey.{spec['id']}: receipt object does not match the step object")
            if receipt and receipt.get("task_id") != task_id:
                failures.append(f"journey.{spec['id']}: receipt task does not match the original task")
        if spec.get("requires_original_key"):
            if step.get("original_key") != original_key:
                failures.append(f"journey.{spec['id']}: original idempotency key was not preserved")
            receipt = step.get("receipt") if isinstance(step.get("receipt"), dict) else {}
            if receipt.get("idempotency_key") != original_key:
                failures.append(f"journey.{spec['id']}: receipt idempotency key != original key")
        if spec.get("requires_approval"):
            approval = step.get("approval")
            if not isinstance(approval, dict) or approval.get("decision") != "approved" \
                    or approval.get("execution_authorized") is not True:
                failures.append(f"journey.{spec['id']}: authorized approval required")
        if not _is_nonempty_str(step.get("run_id")) or not _pattern(contract, "run_id_pattern").match(str(step.get("run_id"))):
            failures.append(f"journey.{spec['id']}: canonical run_id required for traceability")

    report = journey.get("report")
    if not isinstance(report, dict):
        failures.append("journey.report: missing comparison report")
    else:
        if report.get("status") != "validated":
            failures.append("journey.report: validated report required")
        if report.get("task_id") != task_id:
            failures.append("journey.report: report does not belong to the original task")
        candidates = report.get("candidates")
        if not isinstance(candidates, list) or len(candidates) < 2:
            failures.append("journey.report: at least baseline and improved candidates required")
            candidates = []
        candidate_jobs = {row.get("job_id") for row in candidates if isinstance(row, dict)}
        if report.get("selected_job_id") not in candidate_jobs:
            failures.append("journey.report: selected job is not one of the measured candidates")
        if report.get("baseline_job_id") not in candidate_jobs:
            failures.append("journey.report: baseline job is not one of the measured candidates")
        for row in candidates:
            if not isinstance(row, dict):
                failures.append("journey.report: candidate is not an object")
                continue
            if not _is_nonempty_str(row.get("strategy_version_artifact_id")):
                failures.append("journey.report: candidate is missing a strategy version identity")
            if _as_int(row.get("total_return_micros")) is None:
                failures.append("journey.report: candidate total return was not measured")

    terminal = journey.get("terminal")
    if not isinstance(terminal, dict):
        failures.append("journey.terminal: missing original-task terminal state")
    else:
        if terminal.get("task_id") != task_id or terminal.get("status") != "completed":
            failures.append("journey.terminal: original task must be completed")
        if not isinstance(report, dict) or terminal.get("completion_evidence_artifact_id") != report.get("object_id"):
            failures.append("journey.terminal: completion evidence must be the comparison report")

    if journey.get("result") in {"NOT_RUN", "BLOCKED"}:
        coverage.append(f"journey: {journey.get('result')} ({journey.get('not_run_reason') or 'no reason'})")
    elif journey.get("result") != "PASS":
        failures.append(f"journey: result {journey.get('result')!r} is not PASS")
    return journey


def _check_provenance(contract: dict, scenario: dict, spec: dict, receipt_ids: list[str],
                      ctx: str, failures: list[str]) -> None:
    provenance = scenario.get("provenance")
    if not isinstance(provenance, dict):
        failures.append(f"{ctx}: missing provenance block")
        return
    allowed_sources = contract["provenance_allowed_sources"]
    for field in contract["provenance_required_fields"]:
        if field == "pid":
            continue
        item = provenance.get(field)
        if not isinstance(item, dict) or "value" not in item:
            failures.append(f"{ctx}.provenance.{field}: missing value")
            continue
        value = item.get("value")
        if value == _NA:
            if not _is_nonempty_str(item.get("reason")):
                failures.append(f"{ctx}.provenance.{field}: not_applicable requires a reason")
            continue
        source = item.get("source")
        if not _is_nonempty_str(source):
            failures.append(f"{ctx}.provenance.{field}: a real value requires a source")
        elif source not in allowed_sources.get(field, []):
            failures.append(f"{ctx}.provenance.{field}: source {source!r} is not contract-allowed")
        if field == "trace":
            object_id = item.get("object_id")
            if not _is_nonempty_str(object_id) or object_id not in receipt_ids:
                failures.append(f"{ctx}.provenance.trace: trace is not associated with the scenario receipt")
    # pid provenance must be explicit and agree with the recorded pids
    pid = provenance.get("pid")
    if not isinstance(pid, dict) or "value" not in pid:
        failures.append(f"{ctx}.provenance.pid: missing value")
    elif pid.get("value") == _NA:
        if not _is_nonempty_str(pid.get("reason")):
            failures.append(f"{ctx}.provenance.pid: not_applicable requires a reason")
    else:
        before, after = _as_int(pid.get("before")), _as_int(pid.get("after"))
        if before is None or after is None:
            failures.append(f"{ctx}.provenance.pid: before/after must be measured")
        if not isinstance(pid.get("service"), str) or not pid["service"].strip():
            failures.append(f"{ctx}.provenance.pid: service required")
        changed = pid.get("changed")
        if not isinstance(changed, bool):
            failures.append(f"{ctx}.provenance.pid: changed must be a boolean")
        elif changed != (before != after):
            failures.append(f"{ctx}.provenance.pid: changed flag disagrees with before/after")
        if _as_int(scenario.get("pid_before")) != before or _as_int(scenario.get("pid_after")) != after:
            failures.append(f"{ctx}.provenance.pid: disagrees with recorded pids")
    if spec.get("requires_pid_change"):
        if _as_int(scenario.get("pid_before")) == _as_int(scenario.get("pid_after")):
            failures.append(f"{ctx}: a restart scenario requires an actual pid change")
        if not isinstance(pid, dict) or pid.get("changed") is not True:
            failures.append(f"{ctx}: a restart scenario requires provenance.pid.changed=true")


def _check_scenarios(contract: dict, scenarios: object, failures: list[str], coverage: list[str]) -> dict:
    if not isinstance(scenarios, list):
        failures.append("scenarios: must be a list")
        return {}
    by_id: dict[str, dict] = {}
    for scenario in scenarios:
        if not isinstance(scenario, dict) or not _is_nonempty_str(scenario.get("id")):
            failures.append("scenarios: every scenario needs a string id")
            continue
        if scenario["id"] in by_id:
            failures.append(f"scenarios.{scenario['id']}: duplicate scenario id")
        by_id[scenario["id"]] = scenario
        for override in _OVERRIDE_KEYS:
            if override in scenario:
                failures.append(f"scenarios.{scenario['id']}: observations may not override contract {override!r}")

    results: dict[str, str] = {}
    for spec in contract["required_scenarios"]:
        scenario = by_id.get(spec["id"])
        if scenario is None:
            failures.append(f"scenarios.{spec['id']}: required scenario missing")
            results[spec["id"]] = "MISSING"
            continue
        result = scenario.get("result")
        results[spec["id"]] = str(result)
        if result in {"NOT_RUN", "BLOCKED"}:
            coverage.append(f"scenarios.{spec['id']}: {result} "
                            f"({scenario.get('not_run_reason') or 'no reason'})")
            continue
        if result != "PASS":
            failures.append(f"scenarios.{spec['id']}: result {result!r} is not PASS")
            continue
        ctx = f"scenarios.{spec['id']}"
        if scenario.get("boundary") != spec["boundary"]:
            failures.append(f"{ctx}: boundary {scenario.get('boundary')!r} != contract {spec['boundary']!r}")
        mode = scenario.get("mode")
        if not _is_nonempty_str(mode):
            failures.append(f"{ctx}: mode is required")
        elif spec["id"] != "data-ready-continuation" and ("waiting_for_data" in mode or "data_ready" in mode):
            failures.append(f"{ctx}: mode {mode!r} impersonates the ADR-0077 data-ready path")
        for field in ("fault_timing", "recovery_action", "final_state", "terminal_recheck"):
            if not _is_nonempty_str(scenario.get(field)):
                failures.append(f"{ctx}: missing {field}")
        if not _pattern(contract, "task_id_pattern").match(str(scenario.get("task_id"))):
            failures.append(f"{ctx}: canonical original task id required")
        if not _is_nonempty_str(scenario.get("owner")) or not _is_nonempty_str(scenario.get("workspace_id")):
            failures.append(f"{ctx}: owner/workspace attribution required")
        _counts_ok(scenario.get("db_counts_before"), f"{ctx}.db_counts_before", failures)
        _counts_ok(scenario.get("db_counts_after"), f"{ctx}.db_counts_after", failures)
        if not isinstance(scenario.get("receipt_ids"), list) or not scenario["receipt_ids"] \
                or not all(_is_nonempty_str(item) for item in scenario["receipt_ids"]):
            failures.append(f"{ctx}: receipt_ids must be a non-empty list of ids")
        final_state = scenario.get("final_state")
        if final_state in (spec.get("forbidden_final_states") or []):
            failures.append(f"{ctx}: forbidden final state {final_state!r}")
        if final_state not in (spec.get("allowed_final_states") or []):
            failures.append(f"{ctx}: final state {final_state!r} is not allowed by the contract")
        if scenario.get("terminal_recheck") != final_state:
            failures.append(f"{ctx}: terminal_recheck disagrees with the final state")
        if spec.get("required_terminal_status") is not None \
                and scenario.get("terminal_status_raw") != spec["required_terminal_status"]:
            failures.append(f"{ctx}: authoritative terminal status is "
                            f"{scenario.get('terminal_status_raw')!r}, expected "
                            f"{spec['required_terminal_status']!r}")
        assertions = scenario.get("assertions")
        if not isinstance(assertions, dict):
            failures.append(f"{ctx}: assertions must be an object")
            assertions = {}
        for assertion in spec.get("required_assertions") or contract["required_assertions"]:
            if assertions.get(assertion) is not True:
                failures.append(f"{ctx}: required assertion {assertion!r} did not hold")
        orphans = _as_int(scenario.get("active_or_pending_orphans"))
        if orphans is None:
            failures.append(f"{ctx}: active_or_pending_orphans was not measured")
        elif orphans != 0:
            failures.append(f"{ctx}: {orphans} active/pending orphan(s) remain")
        before = scenario.get("db_counts_before") if isinstance(scenario.get("db_counts_before"), dict) else {}
        after = scenario.get("db_counts_after") if isinstance(scenario.get("db_counts_after"), dict) else {}
        for key, value in after.items():
            prior = _as_int(before.get(key))
            if prior is not None and _as_int(value) is not None and value - prior > 1:
                failures.append(f"{ctx}: duplicate side effect on {key!r} ({prior} -> {value})")
        for key in spec.get("forbid_next_step_delta") or []:
            prior, current = _as_int(before.get(key)), _as_int(after.get(key))
            if prior is not None and current is not None and current - prior != 0:
                failures.append(f"{ctx}: next-step key {key!r} changed ({prior} -> {current})")
        _check_provenance(contract, scenario, spec, [str(item) for item in scenario["receipt_ids"]],
                          ctx, failures)
    return results


def _check_cleanup(contract: dict, cleanup: object, failures: list[str]) -> None:
    if not isinstance(cleanup, dict):
        failures.append("cleanup: missing")
        return
    for key, expected in contract["required_cleanup"].items():
        actual = cleanup.get(key)
        if key == "production_untouched":
            if actual is not True:
                failures.append("cleanup: production_untouched must be true")
        elif actual != expected:
            failures.append(f"cleanup: {key} is {actual!r}, expected {expected!r}")


def compute_verdict(contract: dict, observations: object, *, allow_unit_fixture: bool = False) -> dict:
    failures: list[str] = []
    coverage: list[str] = []
    if not isinstance(observations, dict):
        raise Failure("observations must be an object")
    if observations.get("schema_version") != OBSERVATIONS_SCHEMA:
        failures.append(f"observations: schema_version {observations.get('schema_version')!r} is not {OBSERVATIONS_SCHEMA!r}")
    if not allow_unit_fixture:
        if observations.get("evidence_class") != contract["required_evidence_class"]:
            failures.append("observations: runtime evidence_class required")
        llm = observations.get("llm")
        if not isinstance(llm, dict) or llm.get("class") != contract["llm_evidence_class"]:
            failures.append("observations: scripted-keyless llm evidence class required")
        elif llm.get("real_llm_quality") is not False:
            failures.append("observations: scripted provider must declare real_llm_quality=false")
    journey = _check_journey(contract, observations.get("journey"), failures, coverage)
    scenario_results = _check_scenarios(contract, observations.get("scenarios"), failures, coverage)
    _check_cleanup(contract, observations.get("cleanup"), failures)

    format_valid = not failures
    all_pass = format_valid and not coverage and bool(journey)
    return {
        "schema_version": VERDICT_SCHEMA,
        "format_valid": format_valid,
        "all_pass": all_pass,
        "failures": failures,
        "coverage_failures": coverage,
        "scenario_results": scenario_results,
        "journey_result": (journey or {}).get("result"),
        "unit_fixture": allow_unit_fixture,
        "exit_code": 0 if all_pass else 1,
    }


def legacy_compute_verdict(contract: dict, observations: object) -> dict:
    """Pre-fix algorithm: trust declared results, ignore attribution/provenance."""
    declared = True
    journey = observations.get("journey") if isinstance(observations, dict) else None
    if not isinstance(journey, dict) or journey.get("result") != "PASS":
        declared = False
    for scenario in (observations or {}).get("scenarios", []):
        if not isinstance(scenario, dict) or scenario.get("result") != "PASS":
            declared = False
    return {"all_pass": declared, "legacy": True, "exit_code": 0 if declared else 1}


def valid_fixture(contract: dict) -> dict:
    """Known-good unit fixture. NOT runtime qualification evidence."""
    task = "task_" + "a" * 32
    owner = "v090-composite-user"
    workspace = "workspace_v090_composite"
    original_key = "v090-composite-original-key"
    run_id = "b" * 32
    training_run_id = "mlrun_" + "8" * 32

    def artifact(tag: str) -> str:
        return "artifact_" + (tag * 32)[:32]

    def job(tag: str) -> str:
        return "backtest_" + (tag * 32)[:32]

    report_id = artifact("c")
    baseline_job, improved_job = job("d"), job("e")
    baseline_version, improved_version = artifact("f"), artifact("1")

    def step(step_id: str, object_kind: str, object_id: str, *, original: bool = False,
             approval: bool = False) -> dict:
        value = {
            "id": step_id, "result": "PASS", "object_kind": object_kind, "object_id": object_id,
            "owner": owner, "workspace_id": workspace, "task_id": task, "original_key": original_key,
            "run_id": run_id,
            "receipt": {"receipt_id": f"receipt-{step_id}", "object_id": object_id,
                        "task_id": task, "idempotency_key": original_key if original else f"key-{step_id}"},
        }
        if approval:
            value["approval"] = {"decision": "approved", "execution_authorized": True,
                                 "approval_artifact_id": artifact("2")}
        return value

    journey = {
        "id": contract["composite_journey"]["id"], "result": "PASS", "owner": owner,
        "workspace_id": workspace, "task_id": task, "original_key": original_key,
        "steps": [
            step("strategy-improve-proposal", "artifact", artifact("3")),
            step("approval-required-action", "artifact", artifact("4")),
            step("execute-original-key-after-approval", "training_run", training_run_id,
                 original=True, approval=True),
            step("training", "training_run", training_run_id),
            step("out-of-sample-prediction", "artifact", artifact("6")),
            step("frozen-signal", "artifact", artifact("7")),
            step("native-backtest", "job", improved_job),
            step("old-vs-new-comparison", "artifact", report_id),
            step("report-original-task-terminal", "task", task),
        ],
        "report": {
            "object_id": report_id, "task_id": task, "status": "validated",
            "selected_job_id": improved_job, "baseline_job_id": baseline_job,
            "candidates": [
                {"job_id": baseline_job, "strategy_version_artifact_id": baseline_version,
                 "total_return_micros": 33502},
                {"job_id": improved_job, "strategy_version_artifact_id": improved_version,
                 "total_return_micros": 41230},
            ],
        },
        "terminal": {"task_id": task, "status": "completed", "completion_evidence_artifact_id": report_id},
    }

    def scenario(spec: dict) -> dict:
        receipt = f"receipt-{spec['id']}"
        pid_before = 1000
        pid_after = 2000 if spec.get("requires_pid_change") else 1000
        value = {
            "id": spec["id"], "result": "PASS", "boundary": spec["boundary"],
            "mode": f"{spec['id']}-mode", "fault_timing": f"injected for {spec['id']}",
            "pid_before": pid_before, "pid_after": pid_after,
            "db_counts_before": {"ml_training_runs": 0},
            "db_counts_after": {"ml_training_runs": 1},
            "receipt_ids": [receipt], "trace_id": f"trace-{spec['id']}", "run_id": run_id,
            "task_id": task, "owner": owner, "workspace_id": workspace,
            "recovery_action": f"recovered {spec['id']} by original key",
            "final_state": spec["allowed_final_states"][0],
            "terminal_recheck": spec["allowed_final_states"][0],
            "terminal_status_raw": spec.get("required_terminal_status", "not_applicable"),
            "assertions": {name: True for name in contract["required_assertions"]},
            "active_or_pending_orphans": 0,
            "provenance": {
                "trace": {"value": f"trace-{spec['id']}", "source": "ml_training_runs.trace_id",
                          "object_id": receipt},
                "run": {"value": _NA, "reason": "unit fixture: manual Product action creates no agent run"},
                "generation": {"value": _NA, "reason": "unit fixture: no runtime generation ledger"},
                "epoch": {"value": _NA, "reason": "unit fixture: no executor epoch at this boundary"},
                "pid": ({"value": "measured", "service": "backend", "before": pid_before,
                         "after": pid_after, "changed": pid_before != pid_after}
                        if spec.get("requires_pid_change")
                        else {"value": _NA, "reason": "unit fixture: no process restart"}),
            },
        }
        return value

    return {
        "schema_version": OBSERVATIONS_SCHEMA,
        "evidence_class": contract["required_evidence_class"],
        "generated_at": "2026-09-21T00:00:00Z",
        "llm": {"class": contract["llm_evidence_class"], "real_llm_quality": False},
        "journey": journey,
        "scenarios": [scenario(spec) for spec in contract["required_scenarios"]],
        "cleanup": {"containers_remaining": 0, "networks_remaining": 0,
                    "volumes_remaining": 0, "production_untouched": True},
    }


def _controls(contract: dict) -> list[tuple[str, dict]]:
    base = valid_fixture(contract)

    def mutate(name: str, fn) -> tuple[str, dict]:
        value = copy.deepcopy(base)
        fn(value)
        return name, value

    def scenario(v: dict, sid: str) -> dict:
        return next(s for s in v["scenarios"] if s["id"] == sid)

    def step(v: dict, sid: str) -> dict:
        return next(s for s in v["journey"]["steps"] if s["id"] == sid)

    # journey controls
    def drop_step(v): v["journey"]["steps"] = [s for s in v["journey"]["steps"] if s["id"] != "frozen-signal"]
    def step_fail(v): step(v, "training")["result"] = "FAIL"
    def step_not_run(v): step(v, "training")["result"] = "NOT_RUN"
    def missing_receipt(v): step(v, "native-backtest").pop("receipt")
    def wrong_owner(v): step(v, "training")["owner"] = "other-user"
    def wrong_workspace(v): step(v, "training")["workspace_id"] = "workspace_other"
    def wrong_task(v): step(v, "training")["task_id"] = "task_" + "9" * 32
    def changed_original_key(v): step(v, "execute-original-key-after-approval")["original_key"] = "different-key"
    def unauthorized_approval(v): step(v, "execute-original-key-after-approval")["approval"]["execution_authorized"] = False
    def report_selected_mismatch(v): v["journey"]["report"]["selected_job_id"] = "backtest_" + "0" * 32
    def terminal_not_completed(v): v["journey"]["terminal"]["status"] = "running"
    def terminal_evidence_mismatch(v): v["journey"]["terminal"]["completion_evidence_artifact_id"] = "artifact_" + "9" * 32

    # scenario structural controls
    def drop_scenario(v): v["scenarios"] = [s for s in v["scenarios"] if s["id"] != "timeout-terminal"]
    def scenario_fail(v): scenario(v, "late-success")["result"] = "FAIL"
    def scenario_not_run(v): scenario(v, "process-restart-gateway")["result"] = "NOT_RUN"
    def scenario_blocked(v): scenario(v, "model-or-domain-failure")["result"] = "BLOCKED"
    def missing_timing(v): scenario(v, "duplicate-delivery").pop("fault_timing")
    def missing_before(v): scenario(v, "response-loss-after-write").pop("db_counts_before")
    def missing_after(v): scenario(v, "response-loss-before-write").pop("db_counts_after")
    def duplicate_side_effect(v):
        s = scenario(v, "duplicate-delivery"); s["db_counts_before"]["ml_training_runs"] = 1; s["db_counts_after"]["ml_training_runs"] = 3
    def at_most_once_false(v): scenario(v, "duplicate-delivery")["assertions"]["at_most_once"] = False
    def rejection_bypassed(v): scenario(v, "approval-rejected")["assertions"]["rejection_not_bypassed"] = False
    def late_result_next_step(v): scenario(v, "late-success")["assertions"]["late_result_no_next_step"] = False
    def fake_completed(v): scenario(v, "model-or-domain-failure")["assertions"]["failure_not_fake_completed"] = False
    def untraceable(v): scenario(v, "process-restart-backend")["assertions"]["traceable_original_goal"] = False
    def orphan_assertion(v): scenario(v, "cancel-terminal")["assertions"]["no_active_pending_orphans"] = False
    def orphan_count(v): scenario(v, "cancel-terminal")["active_or_pending_orphans"] = 1
    def forbidden_final_state(v): scenario(v, "late-success")["final_state"] = "late_result_created_next_step"
    def fabricated_final_state(v): scenario(v, "model-or-domain-failure")["final_state"] = "fabricated_success"
    def missing_cleanup(v): v.pop("cleanup")
    def dirty_cleanup(v): v["cleanup"]["containers_remaining"] = 1
    def wrong_evidence_class(v): v["evidence_class"] = "unit-fixture"
    def real_llm_claim(v): v["llm"]["real_llm_quality"] = True
    def override_contract(v): scenario(v, "late-success")["allowed_final_states"] = ["late_result_created_next_step"]
    def wrong_schema(v): v["schema_version"] = "byq-v090-composite-research-observations.v1"
    def missing_object_id(v): step(v, "native-backtest").pop("object_id")
    def malformed_object_id(v): step(v, "native-backtest")["object_id"] = "not-a-backtest-id"
    def empty_receipt_id(v): step(v, "training")["receipt"]["receipt_id"] = ""
    def missing_run_id(v): step(v, "training").pop("run_id")
    def missing_receipt_ids(v): scenario(v, "process-restart-backend")["receipt_ids"] = []
    def missing_orphan_measure(v): scenario(v, "cancel-terminal").pop("active_or_pending_orphans")

    # v2 provenance / boundary controls (the P1-8 requirement)
    def no_provenance(v): scenario(v, "process-restart-backend").pop("provenance")
    def provenance_value_without_source(v):
        scenario(v, "process-restart-backend")["provenance"]["generation"] = {"value": 2}
    def hardcoded_generation(v):
        scenario(v, "process-restart-backend")["provenance"]["generation"] = {"value": 2, "source": "made.up"}
    def not_applicable_without_reason(v):
        scenario(v, "process-restart-backend")["provenance"]["epoch"] = {"value": _NA}
    def unrelated_trace_object(v):
        scenario(v, "process-restart-backend")["provenance"]["trace"]["object_id"] = "mlrun_" + "0" * 32
    def restart_without_pid_change(v):
        s = scenario(v, "process-restart-backend"); s["pid_after"] = s["pid_before"]
        s["provenance"]["pid"] = {"value": "measured", "service": "backend",
                                  "before": s["pid_before"], "after": s["pid_before"], "changed": False}
    def missing_revoke_scenario(v): v["scenarios"] = [s for s in v["scenarios"] if s["id"] != "approval-revoked"]
    def missing_stale_scenario(v): v["scenarios"] = [s for s in v["scenarios"] if s["id"] != "approval-stale-reuse"]
    def missing_gateway_scenario(v): v["scenarios"] = [s for s in v["scenarios"] if s["id"] != "process-restart-gateway"]
    def missing_adapter_scenario(v): v["scenarios"] = [s for s in v["scenarios"] if s["id"] != "runtime-adapter-tool-boundary"]
    def cancel_actually_completed(v):
        s = scenario(v, "cancel-terminal"); s["terminal_recheck"] = "completed_terminal"
    def cancel_raw_status_completed(v):
        scenario(v, "cancel-terminal")["terminal_status_raw"] = "completed"
    def cancel_completed_final_state(v):
        scenario(v, "cancel-terminal")["final_state"] = "completed_terminal"
    def late_delta_one(v):
        s = scenario(v, "late-success"); s["db_counts_before"]["ml_prediction_runs"] = 1
        s["db_counts_after"]["ml_prediction_runs"] = 2
    def queue_impersonates_data_ready(v):
        scenario(v, "queue-worker-resume")["mode"] = "waiting_for_data"
    def queue_data_ready_final_state(v):
        scenario(v, "queue-worker-resume")["final_state"] = "continued_after_data_ready"
    def wrong_boundary(v): scenario(v, "process-restart-backend")["boundary"] = "gateway"

    controls = [
        mutate("dropped-journey-step", drop_step),
        mutate("journey-step-fail", step_fail),
        mutate("journey-step-not-run", step_not_run),
        mutate("missing-receipt", missing_receipt),
        mutate("wrong-owner-attribution", wrong_owner),
        mutate("wrong-workspace-attribution", wrong_workspace),
        mutate("wrong-task-attribution", wrong_task),
        mutate("changed-original-key", changed_original_key),
        mutate("unauthorized-approval", unauthorized_approval),
        mutate("report-selected-mismatch", report_selected_mismatch),
        mutate("terminal-not-completed", terminal_not_completed),
        mutate("terminal-evidence-mismatch", terminal_evidence_mismatch),
        mutate("dropped-scenario", drop_scenario),
        mutate("scenario-fail", scenario_fail),
        mutate("scenario-not-run", scenario_not_run),
        mutate("scenario-blocked", scenario_blocked),
        mutate("missing-fault-timing", missing_timing),
        mutate("missing-before-counts", missing_before),
        mutate("missing-after-counts", missing_after),
        mutate("duplicate-side-effect", duplicate_side_effect),
        mutate("at-most-once-false", at_most_once_false),
        mutate("rejection-bypassed", rejection_bypassed),
        mutate("late-result-created-next-step", late_result_next_step),
        mutate("failure-fake-completed", fake_completed),
        mutate("untraceable-original-goal", untraceable),
        mutate("orphan-assertion-false", orphan_assertion),
        mutate("orphan-count-nonzero", orphan_count),
        mutate("forbidden-final-state", forbidden_final_state),
        mutate("fabricated-final-state", fabricated_final_state),
        mutate("missing-cleanup", missing_cleanup),
        mutate("dirty-cleanup", dirty_cleanup),
        mutate("wrong-evidence-class", wrong_evidence_class),
        mutate("real-llm-claim", real_llm_claim),
        mutate("observation-overrides-contract", override_contract),
        mutate("wrong-schema-version", wrong_schema),
        mutate("missing-object-id", missing_object_id),
        mutate("malformed-object-id", malformed_object_id),
        mutate("empty-receipt-id", empty_receipt_id),
        mutate("missing-run-id", missing_run_id),
        mutate("missing-receipt-ids", missing_receipt_ids),
        mutate("missing-orphan-measure", missing_orphan_measure),
        mutate("no-provenance", no_provenance),
        mutate("provenance-value-without-source", provenance_value_without_source),
        mutate("hardcoded-generation", hardcoded_generation),
        mutate("not-applicable-without-reason", not_applicable_without_reason),
        mutate("unrelated-trace-object", unrelated_trace_object),
        mutate("restart-without-pid-change", restart_without_pid_change),
        mutate("missing-revoke-scenario", missing_revoke_scenario),
        mutate("missing-stale-reuse-scenario", missing_stale_scenario),
        mutate("missing-gateway-scenario", missing_gateway_scenario),
        mutate("missing-adapter-scenario", missing_adapter_scenario),
        mutate("cancel-actually-completed", cancel_actually_completed),
        mutate("cancel-raw-status-completed", cancel_raw_status_completed),
        mutate("cancel-completed-final-state", cancel_completed_final_state),
        mutate("late-delta-one", late_delta_one),
        mutate("queue-impersonates-data-ready", queue_impersonates_data_ready),
        mutate("queue-data-ready-final-state", queue_data_ready_final_state),
        mutate("wrong-boundary", wrong_boundary),
    ]
    return controls


DEFECT_TARGETING_CONTROLS = (
    "dropped-scenario",
    "missing-receipt",
    "wrong-owner-attribution",
    "wrong-workspace-attribution",
    "wrong-task-attribution",
    "duplicate-side-effect",
    "orphan-count-nonzero",
    "orphan-assertion-false",
    "rejection-bypassed",
    "late-result-created-next-step",
    "failure-fake-completed",
    "no-provenance",
    "hardcoded-generation",
    "unrelated-trace-object",
    "restart-without-pid-change",
    "missing-revoke-scenario",
    "missing-adapter-scenario",
    "cancel-actually-completed",
    "cancel-raw-status-completed",
    "late-delta-one",
    "queue-impersonates-data-ready",
)


def run_selfcheck(contract: dict) -> dict:
    baseline = compute_verdict(contract, valid_fixture(contract))
    controls = []
    for name, observations in _controls(contract):
        verdict = compute_verdict(contract, observations)
        legacy = legacy_compute_verdict(contract, observations)
        controls.append({
            "name": name,
            "observed_all_pass": verdict["all_pass"],
            "observed_exit_code": verdict["exit_code"],
            "first_failure": (verdict["failures"] or verdict["coverage_failures"] or ["<none>"])[0],
            "pre_fix_legacy_all_pass": legacy["all_pass"],
            "defect_targeting": name in DEFECT_TARGETING_CONTROLS,
        })
    targeting = [c for c in controls if c["defect_targeting"]]
    return {
        "schema_version": "byq-v090-composite-research-negative-controls.v2",
        "baseline_all_pass": baseline["all_pass"],
        "control_count": len(controls),
        "all_controls_pass": all(not c["observed_all_pass"] and c["observed_exit_code"] == 1
                                 for c in controls),
        "defect_targeting_pre_fix_passed": bool(targeting) and all(
            c["pre_fix_legacy_all_pass"] and not c["observed_all_pass"] for c in targeting),
        "defect_targeting_count": len(targeting),
        "controls": controls,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--observations", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--selfcheck", action="store_true")
    parser.add_argument("--allow-unit-fixture", action="store_true")
    args = parser.parse_args(argv)

    contract = _load(args.contract)
    if args.selfcheck:
        result = run_selfcheck(contract)
        text = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text, encoding="utf-8")
        print(text)
        return 0 if (result["baseline_all_pass"] and result["all_controls_pass"]
                     and result["defect_targeting_pre_fix_passed"]) else 1

    if args.observations is None:
        parser.error("--observations is required unless --selfcheck is used")
    observations = _load(args.observations)
    verdict = compute_verdict(contract, observations, allow_unit_fixture=args.allow_unit_fixture)
    text = json.dumps(verdict, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text)
    return verdict["exit_code"]


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Failure as error:
        print(json.dumps({"error": str(error), "exit_code": 2}), file=sys.stderr)
        sys.exit(2)
