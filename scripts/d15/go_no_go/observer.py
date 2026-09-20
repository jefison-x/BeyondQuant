#!/usr/bin/env python3
"""Fail-able observer/verdict for the D15-G architecture Go/No-Go decision.

Separation of concerns:

* ``format_valid`` — the decision artifact is well formed and every required
  source evidence artifact exists and matches its recorded provenance hash.
* ``honest`` — the report's claimed verdict, per-capability statuses and blocker
  set equal the values the observer *independently derives* from the D15-2..D15-5
  source evidence. A report may not declare its own coverage.
* ``verdict`` / ``go_granted`` — the independently derived Go/No-Go decision.
  GO is granted only when EVERY required capability is actually PASS. A single
  BLOCKED/NOT_RUN/FAIL required capability forces NO_GO and that capability must
  be named as an actionable blocker.
* ``aggregates`` — display-only capabilities derived from their atomic required
  members; they are never independent actionable blockers.
* ``limitations`` — optional capabilities (host reboot) reported with their
  derived status; they never gate GO and are never blockers.

The observer is the Go-gate and exits non-zero when a report aggregates a partial
PASS into GO, when any required capability is not actually PASS, when a claimed
status (capability, aggregate or limitation) is not the derived status, when a
blocker is missing or non-actionable, when source evidence is
missing/hash-mismatched, or when the report declares its own verdict. A truthful
NO_GO is `decision_valid=true` but `all_pass=false` (NOT-PASS) and still exits
non-zero: D15-G decides, it does not qualify. GO never authorizes a production
cutover.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DEFAULT_CONTRACT = HERE / "contract.v1.json"

VALID_STATUS = {"PASS", "FAIL", "NOT_RUN", "BLOCKED", "MISSING"}


class Failure(Exception):
    """Raised only for an unreadable contract/decision/provenance artifact."""


def _load(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise Failure(f"missing artifact: {path}") from exc
    except json.JSONDecodeError as exc:
        raise Failure(f"malformed artifact: {path}: {exc}") from exc


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _is_nonempty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


# ---------------------------------------------------------------------------
# Contract-authoritative derivation from the D15-2..D15-5 source evidence.
# ---------------------------------------------------------------------------

def _coverage_status(coverage: object, capability: str) -> str:
    if not isinstance(coverage, dict):
        return "MISSING"
    value = coverage.get(capability)
    return value if value in VALID_STATUS else "MISSING"


def _d15_3_row(sources: dict, row_id: str) -> dict | None:
    rows = sources.get("d15_3_results", {}).get("rows")
    if not isinstance(rows, list):
        return None
    for row in rows:
        if isinstance(row, dict) and row.get("id") == row_id:
            return row
    return None


def _derive_root_session_persistence(sources: dict) -> str:
    if sources.get("d15_2_verdict", {}).get("verdict", {}).get("all_pass") is not True:
        return "BLOCKED"
    rows = sources.get("d15_3_results", {}).get("rows")
    if not isinstance(rows, list) or not rows:
        return "MISSING"
    persistence_rows = [r for r in rows if isinstance(r, dict) and r.get("id") != "native-unavailable-control"]
    if not persistence_rows:
        return "MISSING"
    for row in persistence_rows:
        if not (row.get("dsh_session_persisted") is True
                and row.get("native_resume_available") is True
                and row.get("native_resume_same_session_id") is True):
            return "FAIL"
    return "PASS"


def _derive_process_restart_resume(sources: dict) -> str:
    row = _d15_3_row(sources, "adapter-restart")
    if row is None:
        return "MISSING"
    continuity = row.get("classification", {}).get("continuity") if isinstance(row.get("classification"), dict) else None
    if continuity not in {"rehydrated", "reattached"} or row.get("native_resume_available") is not True:
        return "FAIL"
    runtime = sources.get("d15_runtime_verdict", {})
    if runtime.get("all_pass") is not True:
        return "BLOCKED"
    coverage = runtime.get("required_coverage")
    if not isinstance(coverage, dict) or not coverage:
        return "MISSING"
    if any(value != "PASS" for value in coverage.values()):
        return "BLOCKED"
    return "PASS"


def _derive_host_reboot_resume(sources: dict) -> str:
    d4 = sources.get("d15_4_verdict", {}).get("optional_coverage", {}).get("host-reboot", "MISSING")
    d5 = sources.get("d15_5_verdict", {}).get("optional_coverage", {}).get("host-reboot", "MISSING")
    if d4 == "PASS" and d5 == "PASS":
        return "PASS"
    if d4 == "FAIL" or d5 == "FAIL":
        return "FAIL"
    return "NOT_RUN"


def _derive_fork_continuity(sources: dict) -> str:
    scenarios = sources.get("d15_4_verdict", {}).get("scenarios")
    if not isinstance(scenarios, list):
        return "MISSING"
    for scenario in scenarios:
        if isinstance(scenario, dict) and scenario.get("id") == "fork-lineage":
            return "PASS" if scenario.get("result") == "PASS" else "FAIL"
    return "MISSING"


def _derive_subagent_child_crash(sources: dict) -> str:
    return _coverage_status(sources.get("d15_4_verdict", {}).get("required_coverage"), "child-crash")


def _derive_subagent_adapter_restart(sources: dict) -> str:
    return _coverage_status(sources.get("d15_4_verdict", {}).get("required_coverage"), "byq-adapter-restart")


def _derive_terminal_client_reattach(sources: dict) -> str:
    coverage = sources.get("d15_5_verdict", {}).get("required_coverage")
    required = ("page-refresh", "browser-disconnect", "frontend-restart", "gateway-restart")
    statuses = [_coverage_status(coverage, name) for name in required]
    return "PASS" if all(value == "PASS" for value in statuses) else "FAIL"


def _derive_terminal_adapter_restart(sources: dict) -> str:
    return _coverage_status(sources.get("d15_5_verdict", {}).get("required_coverage"), "adapter-restart")


def _derive_terminal_dsh_runtime_restart(sources: dict) -> str:
    return _coverage_status(sources.get("d15_5_verdict", {}).get("required_coverage"), "dsh-runtime-restart")


# Required capabilities only. Aggregate and optional capabilities are never
# derived here: aggregates are computed from their atomic members and options
# from their own optional deriver.
_DERIVERS: dict[str, Callable[[dict], str]] = {
    "root-session-persistence": _derive_root_session_persistence,
    "process-restart-resume": _derive_process_restart_resume,
    "fork-continuity": _derive_fork_continuity,
    "subagent-child-crash": _derive_subagent_child_crash,
    "subagent-byq-adapter-restart": _derive_subagent_adapter_restart,
    "terminal-client-reattach": _derive_terminal_client_reattach,
    "terminal-adapter-restart": _derive_terminal_adapter_restart,
    "terminal-dsh-runtime-restart": _derive_terminal_dsh_runtime_restart,
}

_OPTIONAL_DERIVERS: dict[str, Callable[[dict], str]] = {
    "host-reboot-resume": _derive_host_reboot_resume,
}


def derive_capabilities(contract: dict, sources: dict) -> dict[str, str]:
    derived: dict[str, str] = {}
    for capability in contract["required_capabilities"]:
        deriver = _DERIVERS.get(capability["id"])
        derived[capability["id"]] = deriver(sources) if deriver is not None else "MISSING"
    return derived


def derive_optional(contract: dict, sources: dict) -> dict[str, str]:
    derived: dict[str, str] = {}
    for capability in contract.get("optional_capabilities", []):
        deriver = _OPTIONAL_DERIVERS.get(capability["id"])
        derived[capability["id"]] = deriver(sources) if deriver is not None else "MISSING"
    return derived


def _combine_member_statuses(members: list[str]) -> str:
    if not members:
        return "MISSING"
    if all(value == "PASS" for value in members):
        return "PASS"
    if any(value == "FAIL" for value in members):
        return "FAIL"
    if any(value == "BLOCKED" for value in members):
        return "BLOCKED"
    if any(value == "NOT_RUN" for value in members):
        return "NOT_RUN"
    return "MISSING"


def derive_aggregates(contract: dict, derived_required: dict[str, str]) -> dict[str, str]:
    """Aggregates are display-only, derived from their atomic member capabilities."""
    derived: dict[str, str] = {}
    for capability in contract.get("aggregate_capabilities", []):
        members = [derived_required.get(member, "MISSING") for member in capability["derived_from"]]
        derived[capability["id"]] = _combine_member_statuses(members)
    return derived


def compute_decision(contract: dict, sources: dict, decision: dict, *,
                     provenance: dict | None = None, root: Path | None = None) -> dict:
    failures: list[str] = []
    honesty_failures: list[str] = []

    if not isinstance(decision, dict):
        raise Failure("decision must be an object")

    candidate = contract["candidate"]
    observed_candidate = decision.get("candidate")
    if not isinstance(observed_candidate, dict) or observed_candidate.get("release") != candidate["release"]:
        failures.append(f"candidate mismatch: expected {candidate['release']!r}, got {observed_candidate!r}")

    for forbidden in contract.get("forbidden_decision_fields", []):
        if forbidden in decision:
            failures.append(f"decision may not declare its own '{forbidden}' field; the contract is authoritative")

    claimed_verdict = decision.get("decision")
    if claimed_verdict not in contract.get("decision_vocabulary", []):
        failures.append(f"invalid decision {claimed_verdict!r}")

    required = {item["id"]: item for item in contract["required_capabilities"]}
    derived_capabilities = derive_capabilities(contract, sources)

    claimed_capabilities = decision.get("capabilities")
    if not isinstance(claimed_capabilities, dict):
        failures.append("decision.capabilities must be an object")
        claimed_capabilities = {}
    if set(claimed_capabilities) != set(required):
        missing = sorted(set(required) - set(claimed_capabilities))
        extra = sorted(set(claimed_capabilities) - set(required))
        failures.append(f"capability set mismatch: missing={missing} extra={extra} (closed set)")
    for capability_id in sorted(set(required) & set(claimed_capabilities)):
        claimed = claimed_capabilities.get(capability_id)
        derived = derived_capabilities.get(capability_id, "MISSING")
        if claimed not in VALID_STATUS:
            failures.append(f"capability {capability_id!r} has invalid claimed status {claimed!r}")
        elif claimed != derived:
            honesty_failures.append(
                f"capability {capability_id!r} claimed {claimed!r} but derived {derived!r}")

    derived_verdict = "GO" if all(v == "PASS" for v in derived_capabilities.values()) else "NO_GO"
    derived_blockers = sorted(cap_id for cap_id, status in derived_capabilities.items() if status != "PASS")
    claimed_blockers = decision.get("blockers")
    if not isinstance(claimed_blockers, list) or not all(_is_nonempty_str(item) for item in claimed_blockers):
        failures.append("decision.blockers must be a list of non-empty capability ids")
        claimed_blockers = []
    else:
        claimed_blockers = sorted(claimed_blockers)
        if claimed_blockers != derived_blockers:
            honesty_failures.append(
                f"blocker set {claimed_blockers} does not equal the derived required blockers {derived_blockers}")
        aggregate_ids = {item["id"] for item in contract.get("aggregate_capabilities", [])}
        optional_ids = {item["id"] for item in contract.get("optional_capabilities", [])}
        non_actionable = sorted(set(claimed_blockers) & (aggregate_ids | optional_ids))
        if non_actionable:
            failures.append(
                f"aggregate/optional capabilities listed as independent actionable blockers: {non_actionable}; "
                "aggregates are derived and options are limitations")

    # Aggregate capabilities are display-only and must be derived from their
    # atomic members; a decision may not claim a different aggregate status.
    derived_aggregates = derive_aggregates(contract, derived_capabilities)
    claimed_aggregates = decision.get("aggregates")
    if not isinstance(claimed_aggregates, dict):
        failures.append("decision.aggregates must be an object")
        claimed_aggregates = {}
    if set(claimed_aggregates) != set(derived_aggregates):
        missing = sorted(set(derived_aggregates) - set(claimed_aggregates))
        extra = sorted(set(claimed_aggregates) - set(derived_aggregates))
        failures.append(f"aggregate set mismatch: missing={missing} extra={extra} (closed set)")
    for aggregate_id in sorted(set(claimed_aggregates) & set(derived_aggregates)):
        claimed = claimed_aggregates.get(aggregate_id)
        derived = derived_aggregates.get(aggregate_id)
        if claimed not in VALID_STATUS:
            failures.append(f"aggregate {aggregate_id!r} has invalid claimed status {claimed!r}")
        elif claimed != derived:
            honesty_failures.append(
                f"aggregate {aggregate_id!r} claimed {claimed!r} but derived {derived!r}")

    # Optional capabilities are limitations: every option must be reported with
    # its derived status and never treated as a required blocker.
    derived_optional = derive_optional(contract, sources)
    claimed_limitations = decision.get("limitations")
    if not isinstance(claimed_limitations, list):
        failures.append("decision.limitations must be a list")
        claimed_limitations = []
    limitation_by_id: dict[str, dict] = {}
    for item in claimed_limitations:
        if not isinstance(item, dict) or not _is_nonempty_str(item.get("id")):
            failures.append("each limitation must be an object with a non-empty id")
            continue
        limitation_by_id[item["id"]] = item
    if set(limitation_by_id) != set(derived_optional):
        missing = sorted(set(derived_optional) - set(limitation_by_id))
        extra = sorted(set(limitation_by_id) - set(derived_optional))
        failures.append(f"limitation set mismatch: missing={missing} extra={extra} (closed set)")
    for option_id in sorted(set(limitation_by_id) & set(derived_optional)):
        claimed = limitation_by_id[option_id].get("status")
        derived = derived_optional[option_id]
        if claimed not in VALID_STATUS:
            failures.append(f"limitation {option_id!r} has invalid claimed status {claimed!r}")
        elif claimed != derived:
            honesty_failures.append(
                f"limitation {option_id!r} claimed {claimed!r} but derived {derived!r}")
        if not _is_nonempty_str(limitation_by_id[option_id].get("reason")):
            failures.append(f"limitation {option_id!r} must carry a reason")

    if claimed_verdict in contract.get("decision_vocabulary", []) and claimed_verdict != derived_verdict:
        if claimed_verdict == "GO":
            honesty_failures.append(
                "partial-PASS aggregation rejected: decision claims GO but a required capability is not PASS "
                f"(derived blockers {derived_blockers})")
        else:
            honesty_failures.append(
                f"decision claims NO_GO but the derived verdict is {derived_verdict}")

    # Provenance-verified source evidence (real run only).
    if provenance is not None:
        entries = provenance.get("artifacts")
        by_path = {}
        if isinstance(entries, list):
            by_path = {item.get("path"): item for item in entries if isinstance(item, dict)}
        base = root or ROOT
        for artifact in contract.get("source_artifacts", []):
            path = base / artifact["path"]
            if not path.is_file():
                failures.append(f"missing source evidence: {artifact['path']}")
                continue
            entry = by_path.get(artifact["path"])
            if entry is None:
                failures.append(f"source evidence not provenance-verified: {artifact['path']}")
            elif entry.get("sha256") != _digest(path):
                failures.append(f"source evidence hash mismatch: {artifact['path']}")

    format_valid = not failures
    honest = not honesty_failures
    decision_valid = format_valid and honest
    go_granted = derived_verdict == "GO"
    aggregation_rejected = claimed_verdict == "GO" and not go_granted
    # The observer is the Go-gate: it only passes (exit 0) when the decision is
    # valid and honest AND every required capability is actually PASS (GO).
    # A truthful NO_GO is decision_valid=true but all_pass=false (NOT-PASS).
    all_pass = decision_valid and go_granted
    return {
        "schema_version": "byq-d15-g-verdict.v1",
        "all_pass": all_pass,
        "decision_valid": decision_valid,
        "format_valid": format_valid,
        "honest": honest,
        "verdict": derived_verdict,
        "go_granted": go_granted,
        "go_claimed": claimed_verdict == "GO",
        "aggregation_rejected": aggregation_rejected,
        "required_coverage_ok": all(v == "PASS" for v in derived_capabilities.values()),
        "candidate": candidate,
        "decision_vocabulary": list(contract.get("decision_vocabulary", [])),
        "required_capability_count": len(required),
        "aggregate_capability_count": len(derived_aggregates),
        "optional_capability_count": len(derived_optional),
        "derived_capabilities": derived_capabilities,
        "claimed_capabilities": {key: claimed_capabilities.get(key) for key in required},
        "derived_aggregates": derived_aggregates,
        "claimed_aggregates": {key: claimed_aggregates.get(key) for key in derived_aggregates},
        "derived_optional": derived_optional,
        "derived_blockers": derived_blockers,
        "claimed_blockers": claimed_blockers,
        "constraints": contract.get("constraints", {}),
        "r3_resume": contract.get("constraints", {}).get("r3_resume"),
        "production_selector": contract.get("constraints", {}).get("production_selector"),
        "failures": failures,
        "honesty_failures": honesty_failures,
        "exit_code": 0 if all_pass else 1,
    }


# ---------------------------------------------------------------------------
# Legacy (pre-fix) algorithm: trusts the report's own verdict/claims.
# ---------------------------------------------------------------------------

def legacy_compute_decision(contract: dict, sources: dict, decision: dict) -> dict:
    """Pre-fix algorithm: the report's claimed verdict was trusted.

    It never derived capability status from the source evidence and never gated
    GO on required coverage, so a report claiming GO over a BLOCKED required
    capability passed.
    """
    failures: list[str] = []
    if decision.get("decision") not in contract.get("decision_vocabulary", []):
        failures.append("invalid decision")
    claimed = decision.get("capabilities")
    if isinstance(claimed, dict):
        for value in claimed.values():
            if value not in VALID_STATUS:
                failures.append(f"invalid claimed status {value!r}")
    else:
        failures.append("missing claimed capabilities")
    all_pass = not failures
    return {"algorithm": "legacy-pre-fix", "all_pass": all_pass,
            "exit_code": 0 if all_pass else 1, "failures": failures}


# ---------------------------------------------------------------------------
# Unit fixtures + negative controls (selfcheck).
# ---------------------------------------------------------------------------

_ALL_PASS_D15_4 = {
    "parent-child-identity": "PASS",
    "continuable-descriptor": "PASS",
    "cold-resume": "PASS",
    "fork-lineage": "PASS",
    "inheritance": "PASS",
    "parent-crash": "PASS",
    "child-crash": "PASS",
    "byq-adapter-restart": "PASS",
}

_ALL_PASS_D15_5 = {
    "page-refresh": "PASS",
    "browser-disconnect": "PASS",
    "frontend-restart": "PASS",
    "gateway-restart": "PASS",
    "adapter-restart": "PASS",
    "dsh-runtime-restart": "PASS",
}

_PARTIAL_D15_4 = dict(_ALL_PASS_D15_4, **{"child-crash": "BLOCKED", "byq-adapter-restart": "BLOCKED"})
_PARTIAL_D15_5 = dict(_ALL_PASS_D15_5, **{"adapter-restart": "BLOCKED", "dsh-runtime-restart": "BLOCKED"})


def _sources(d15_4: dict, d15_5: dict, host_reboot_optional: str, *,
             adapter_restart_continuity: str = "rehydrated",
             runtime_all_pass: bool = True, session_all_pass: bool = True) -> dict:
    return {
        "d15_2_verdict": {"verdict": {"all_pass": session_all_pass}},
        "d15_3_results": {"rows": [
            {"id": "adapter-restart", "dsh_session_persisted": True, "native_resume_available": True,
             "native_resume_same_session_id": True,
             "classification": {"continuity": adapter_restart_continuity}},
            {"id": "host-reboot", "dsh_session_persisted": True, "native_resume_available": True,
             "native_resume_same_session_id": True,
             "classification": {"continuity": host_reboot_optional}},
        ]},
        "d15_runtime_verdict": {"all_pass": runtime_all_pass,
                                "required_coverage": {"adapter-process-restart": "PASS"}},
        "d15_4_verdict": {"required_coverage": d15_4, "optional_coverage": {"host-reboot": host_reboot_optional},
                          "scenarios": [{"id": "fork-lineage", "result": d15_4.get("fork-lineage")}]},
        "d15_5_verdict": {"required_coverage": d15_5, "optional_coverage": {"host-reboot": host_reboot_optional}},
    }


def _decision(contract: dict, sources: dict, verdict: str,
              blockers: list[str] | None = None) -> dict:
    derived = derive_capabilities(contract, sources)
    optional = derive_optional(contract, sources)
    return {
        "schema_version": "byq-d15-g-decision-input.v1",
        "candidate": dict(contract["candidate"]),
        "decision": verdict,
        "capabilities": {c["id"]: derived[c["id"]] for c in contract["required_capabilities"]},
        "blockers": blockers if blockers is not None else sorted(
            key for key, value in derived.items() if value != "PASS"),
        "aggregates": derive_aggregates(contract, derived),
        "limitations": [
            {"id": c["id"], "status": optional[c["id"]], "reason": "injected optional limitation"}
            for c in contract.get("optional_capabilities", [])
        ],
        "provenance": "docs/evidence/d15/d15-g/provenance.v1.json",
    }


def good_fixture(contract: dict) -> tuple[dict, dict]:
    """Synthetic ALL-PASS required fixture with an OPTIONAL host-reboot NOT_RUN.

    The optional limitation does not gate GO, proving options never become
    blockers and every required capability PASSes.
    """
    sources = _sources(_ALL_PASS_D15_4, _ALL_PASS_D15_5, "NOT_RUN")
    return sources, _decision(contract, sources, "GO")


def real_fixture(contract: dict) -> tuple[dict, dict]:
    """Synthetic PARTIAL fixture mirroring the real D15 evidence: honest NO_GO."""
    sources = _sources(_PARTIAL_D15_4, _PARTIAL_D15_5, "NOT_RUN")
    return sources, _decision(contract, sources, "NO_GO")


def _mutations(contract: dict) -> list[tuple[str, dict, dict]]:
    good_sources, good = good_fixture(contract)
    partial_sources, partial = real_fixture(contract)
    mutations: list[tuple[str, dict, dict]] = []

    def add_partial(name: str, mutate) -> None:
        value = copy.deepcopy(partial)
        mutate(value)
        mutations.append((name, partial_sources, value))

    def add_good(name: str, mutate, *, sources: dict | None = None) -> None:
        value = copy.deepcopy(good)
        mutate(value)
        mutations.append((name, sources or good_sources, value))

    # The headline defect: a partial-PASS report claiming GO.
    add_partial("claim-go-on-partial-sources", lambda v: v.update({"decision": "GO", "blockers": []}))
    # A required capability marked PASS while its source says BLOCKED.
    add_partial("claim-child-crash-pass", lambda v: v["capabilities"].update({"subagent-child-crash": "PASS"}))
    add_partial("claim-terminal-adapter-restart-pass",
                lambda v: v["capabilities"].update({"terminal-adapter-restart": "PASS"}))
    add_partial("claim-dsh-runtime-restart-pass",
                lambda v: v["capabilities"].update({"terminal-dsh-runtime-restart": "PASS"}))
    # Missing blocker while claiming NO_GO.
    add_partial("drop-named-blocker", lambda v: v.update({"blockers": ["subagent-child-crash"]}))
    # Missing required capability.
    add_partial("drop-required-capability", lambda v: v["capabilities"].pop("fork-continuity"))
    # An aggregate is display-only: claiming it PASS while its atomic members are
    # BLOCKED is rejected, and listing an aggregate as a blocker is rejected.
    add_partial("claim-aggregate-pass", lambda v: v["aggregates"].update({"subagent-resume": "PASS"}))
    add_partial("aggregate-listed-as-blocker",
                lambda v: v.update({"blockers": sorted(v["blockers"] + ["subagent-resume"])}))
    # An optional capability is a limitation: making it a blocker, dropping it, or
    # mis-stating its status is rejected.
    add_partial("optional-listed-as-blocker",
                lambda v: v.update({"blockers": sorted(v["blockers"] + ["host-reboot-resume"])}))
    add_partial("missing-limitation", lambda v: v.pop("limitations"))
    add_partial("limitation-status-mismatch",
                lambda v: v["limitations"][0].update({"status": "PASS"}))
    # A NO_GO decision that disagrees with an all-PASS required source set.
    add_good("no-go-against-all-pass", lambda v: v.update({"decision": "NO_GO", "blockers": ["x"]}))
    # Self-declared verdict/coverage fields.
    add_good("self-declared-verdict", lambda v: v.update({"go_authorized": True}))
    add_good("self-declared-coverage", lambda v: v.update({"coverage": {"all": "PASS"}}))
    # Candidate mismatch.
    add_good("candidate-mismatch", lambda v: v.update({"candidate": {"release": "dsh-0.1.2rc1"}}))
    # Invalid decision string.
    add_good("invalid-decision", lambda v: v.update({"decision": "MAYBE"}))
    # A GO decision over a source set that cannot be derived (missing coverage).
    empty_sources = _sources({}, {}, "NOT_RUN")
    add_good("go-with-missing-coverage", lambda v: None, sources=empty_sources)
    # A required atomic capability in the source is FAIL, claimed GO.
    fail_sources = _sources(dict(_ALL_PASS_D15_4, **{"child-crash": "FAIL"}), _ALL_PASS_D15_5, "NOT_RUN")
    fail_decision = _decision(contract, fail_sources, "GO")
    mutations.append(("claim-go-on-source-fail", fail_sources, fail_decision))
    # MISSING blocker list.
    add_partial("missing-blocker-list", lambda v: v.pop("blockers"))
    return mutations


def selfcheck(contract: dict) -> dict:
    good_sources, good_decision = good_fixture(contract)
    good = compute_decision(contract, good_sources, good_decision)
    partial_sources, partial_decision = real_fixture(contract)
    real = compute_decision(contract, partial_sources, partial_decision)

    controls = []
    for name, sources, decision in _mutations(contract):
        fixed = compute_decision(contract, sources, decision)
        legacy = legacy_compute_decision(contract, sources, decision)
        controls.append({
            "name": name,
            "fixed_all_pass": fixed["all_pass"],
            "fixed_exit_code": fixed["exit_code"],
            "fixed_aggregation_rejected": fixed["aggregation_rejected"],
            "legacy_all_pass": legacy["all_pass"],
        })
    all_controls_rejected = all(not item["fixed_all_pass"] for item in controls)
    defect_targeting = [item for item in controls if item["legacy_all_pass"] and not item["fixed_all_pass"]]
    return {
        "schema_version": "byq-d15-g-negative-controls.v1",
        "known_good_all_pass_fixture_all_pass": good["all_pass"],
        "known_good_all_pass_fixture_verdict": good["verdict"],
        "known_good_all_pass_fixture_optional": good["derived_optional"],
        "real_partial_fixture_all_pass": real["all_pass"],
        "real_partial_fixture_decision_valid": real["decision_valid"],
        "real_partial_fixture_honest": real["honest"],
        "real_partial_fixture_verdict": real["verdict"],
        "real_partial_fixture_blockers": real["derived_blockers"],
        "real_partial_fixture_aggregates": real["derived_aggregates"],
        "real_partial_fixture_optional": real["derived_optional"],
        "control_count": len(controls),
        "controls": controls,
        "all_controls_rejected": all_controls_rejected,
        "defect_targeting_pre_fix_passed_count": len(defect_targeting),
        "defect_targeting_pre_fix_passed": [item["name"] for item in defect_targeting],
    }


def load_sources(contract: dict, root: Path) -> dict:
    sources: dict[str, Any] = {}
    for artifact in contract.get("source_artifacts", []):
        sources[artifact["id"]] = _load(root / artifact["path"])
    return sources


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--decision", type=Path)
    parser.add_argument("--provenance", type=Path)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--selfcheck", action="store_true")
    args = parser.parse_args(argv)

    contract = _load(args.contract)
    if args.selfcheck:
        result = selfcheck(contract)
        code = 0 if result["all_controls_rejected"] and result["known_good_all_pass_fixture_all_pass"] else 1
    else:
        if args.decision is None:
            parser.error("--decision is required unless --selfcheck")
        sources = load_sources(contract, args.root)
        provenance = _load(args.provenance) if args.provenance else None
        result = compute_decision(contract, sources, _load(args.decision),
                                  provenance=provenance, root=args.root)
        code = result["exit_code"]
        print(json.dumps({
            "verdict": result["verdict"],
            "all_pass": result["all_pass"],
            "honest": result["honest"],
            "format_valid": result["format_valid"],
            "go_granted": result["go_granted"],
            "go_claimed": result["go_claimed"],
            "aggregation_rejected": result["aggregation_rejected"],
            "derived_blockers": result["derived_blockers"],
            "derived_aggregates": result["derived_aggregates"],
            "derived_optional": result["derived_optional"],
            "failures": result["failures"],
            "honesty_failures": result["honesty_failures"],
        }, indent=2))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return code


if __name__ == "__main__":
    sys.exit(main())
