#!/usr/bin/env python3
"""Fail-able final 0.9 development closeout observer/verdict.

This observer produces the machine-readable, fail-able final matrix for the
independent BeyondQuant 0.9 development closeout. It:

* independently derives every required 0.9 development item from the original
  merged evidence (not from a PASS label) and verifies the recorded provenance
  hashes;
* re-runs the D15 superseding observer (with provenance verification) and maps
  its eleven components into the closeout matrix instead of trusting the
  committed superseding verdict text;
* re-runs the fail-closed full-interface auditor on the current tree;
* enforces the boundary constraints (repository default vs production
  deployment, no release/tag, Phase 100 frozen, 0.10 not started, ``R3_RESUME =
  NO``, B1/B2 not downgraded) and the required/forbidden STATUS markers;
* declares ``V090_DEVELOPMENT_CLOSEOUT_COMPLETE`` only when every required item
  equals its evidence-derived expected truth and every constraint holds,
  otherwise ``V090_DEVELOPMENT_CLOSEOUT_BLOCKED``.

Separation of concerns:

* ``format_valid`` — the assessment artifact is well formed, every required
  source evidence file exists and matches its recorded provenance hash, and the
  live interface audit is readable and complete.
* ``honest`` — every claimed item status and the claimed constraints equal the
  values the observer independently derives.
* ``complete`` / ``decision`` — the independently derived closeout decision.
  ``all_pass`` is ``format_valid`` and ``honest`` and ``complete``.

External blockers B1/B2 stay ``BLOCKED_EXTERNAL`` and the native independent
child resume stays ``NOT_IMPLEMENTED``; they are recorded scoped limitations
that do **not** gate the development closeout (ADR-0084 section 3). The formal
0.9.0 release manifest gate remains open and is not attempted here.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DEFAULT_CONTRACT = HERE / "contract.v1.json"
SUPERSEDING_REL = "scripts/d15/superseding_assessment"
RELIABILITY_AUDITOR_REL = "scripts/ci/check-reliability-review.py"
LIMITATION_IDS = [
    "b1_subagent_child_crash",
    "b2_subagent_byq_adapter_restart",
    "native_independent_child_resume",
    "r3_resume",
]


class Failure(Exception):
    """Raised only for an unreadable contract/assessment/provenance artifact."""


def _load(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise Failure(f"missing artifact: {path}") from exc
    except json.JSONDecodeError as exc:
        raise Failure(f"malformed artifact: {path}: {exc}") from exc


def _load_text(path: Path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise Failure(f"missing artifact: {path}") from exc


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _is_nonempty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def load_superseding_module(root: Path = ROOT):
    path = root / SUPERSEDING_REL / "observer.py"
    if not path.is_file():
        raise Failure(f"missing D15 superseding observer: {path}")
    spec = importlib.util.spec_from_file_location("v090_final_closeout_superseding", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["v090_final_closeout_superseding"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_sources(contract: dict, root: Path, *, superseding_module=None) -> dict:
    sources: dict[str, Any] = {}
    for artifact in contract.get("source_artifacts", []):
        path = root / artifact["path"]
        if artifact.get("kind") == "text":
            sources[artifact["id"]] = _load_text(path)
        else:
            sources[artifact["id"]] = _load(path)
    if superseding_module is not None:
        superseding_contract = _load(root / SUPERSEDING_REL / "contract.v1.json")
        sources["_superseding_contract"] = superseding_contract
        sources["_superseding_sources"] = superseding_module.load_sources(
            superseding_contract, root)
    snapshot_path = contract.get("interface_audit_snapshot_path")
    if snapshot_path:
        # The committed auditor snapshot is not a provenance-verified source
        # artifact (it is produced by this batch); its integrity is enforced by
        # the observer comparing it to the live deterministic auditor output.
        sources["interface_audit_snapshot"] = _load(root / snapshot_path)
    return sources


def _no_release_manifest(root: Path) -> bool:
    for candidate in (root / "config").rglob("*.json"):
        try:
            text = candidate.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if '"schema": "byq-release.v1"' in text or '"schema":"byq-release.v1"' in text:
            return False
    return True


def gather_live(root: Path = ROOT) -> dict:
    auditor = root / RELIABILITY_AUDITOR_REL
    if not auditor.is_file():
        raise Failure(f"missing reliability auditor: {auditor}")
    result = subprocess.run(["python3", str(auditor)], cwd=root,
                            capture_output=True, text=True)
    try:
        audit = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise Failure(f"unreadable reliability auditor stdout: {exc}") from exc
    return {"interface_audit": audit, "release_manifest_present": not _no_release_manifest(root)}


# ---------------------------------------------------------------------------
# Contract-authoritative derivation from the committed source evidence.
# ---------------------------------------------------------------------------

def _derive_closeout_audit(sources: dict) -> str:
    ledger = sources.get("closeout_ledger")
    matrix = sources.get("closeout_matrix")
    if not isinstance(ledger, dict) or not isinstance(matrix, dict):
        return "MISSING"
    ok = (
        ledger.get("schema_version") == "byq-v090-closeout-gap-ledger.v1"
        and ledger.get("snapshot") is True
        and ledger.get("snapshot_kind") == "historical-audit-snapshot"
        and matrix.get("schema_version") == "byq-v090-closeout-acceptance-matrix.v1"
        and matrix.get("snapshot") is True
        and matrix.get("snapshot_kind") == "historical-audit-snapshot"
    )
    return "COMPLETE" if ok else "MISSING"


def _audit_payload_complete(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    return (
        payload.get("complete") is True
        and payload.get("discovered") == payload.get("reviewed") == payload.get("verified")
        and isinstance(payload.get("discovered"), int)
        and payload.get("missing") == 0
        and payload.get("stale") == 0
        and payload.get("fake_pass") == 0
        and not payload.get("unresolved")
        and not payload.get("manual_pending")
        and not payload.get("errors")
    )


def _audit_core(payload: dict) -> dict:
    return {key: payload.get(key) for key in
            ("discovered", "reviewed", "verified", "missing", "stale", "fake_pass",
             "complete")}


def _derive_f2(sources: dict, live: dict) -> str:
    ledger = sources.get("closeout_ledger")
    if not isinstance(ledger, dict):
        return "MISSING"
    items = ledger.get("items")
    if not isinstance(items, list):
        return "MISSING"
    f2 = next((item for item in items if isinstance(item, dict) and item.get("id") == "F2"), None)
    if not isinstance(f2, dict):
        return "MISSING"
    named_ok = all(_is_nonempty_str(sources.get(key))
                   for key in ("f2_research_watch", "f2_interface_audit"))
    live_ok = _audit_payload_complete(live.get("interface_audit"))
    reason_evidence = list(f2.get("open_reason_evidence") or []) + list(f2.get("evidence") or [])
    stale_ledger_reason = any("check-reliability-review.py" in str(entry)
                              for entry in reason_evidence)
    if f2.get("status") == "covered" and named_ok:
        return "COVERED"
    if f2.get("status") == "open" and named_ok and stale_ledger_reason and live_ok:
        return "COVERED"
    return "NOT_COVERED"


def _derive_full_interface(sources: dict, live: dict) -> str:
    snapshot = sources.get("interface_audit_snapshot")
    live_audit = live.get("interface_audit")
    if not isinstance(snapshot, dict) or not isinstance(live_audit, dict):
        return "MISSING"
    if not _audit_payload_complete(snapshot) or not _audit_payload_complete(live_audit):
        return "FAIL"
    if _audit_core(snapshot) != _audit_core(live_audit):
        return "FAIL"
    return "COMPLETE"


def _derive_composite(contract: dict, sources: dict) -> str:
    verdict = sources.get("composite_verdict")
    matrix = sources.get("composite_matrix")
    if not isinstance(verdict, dict) or not isinstance(matrix, dict):
        return "MISSING"
    scenarios = verdict.get("scenario_results")
    if not isinstance(scenarios, dict) or not scenarios:
        return "MISSING"
    if verdict.get("format_valid") is not True or verdict.get("journey_result") != "PASS":
        return "NOT_SCOPED"
    expected_blocked = sorted(contract.get("composite_non_gating_rows", []))
    blocked = sorted(key for key, value in scenarios.items() if value == "BLOCKED")
    failed = sorted(key for key, value in scenarios.items() if value == "FAIL")
    gating_pass = all(value == "PASS" for key, value in scenarios.items()
                      if key not in expected_blocked)
    matrix_blocked = sorted((matrix.get("status") or {}).get("blocked_required_rows", []))
    ok = (
        not failed
        and blocked == expected_blocked
        and gating_pass
        and matrix.get("frozen") is True
        and matrix_blocked == expected_blocked
    )
    return "PASS_AS_SCOPED" if ok else "NOT_SCOPED"


def _derive_adr_decision(sources: dict) -> str:
    record = sources.get("adr_decision_record")
    if not isinstance(record, dict):
        return "MISSING"
    adr_82 = record.get("adr_0082") or {}
    adr_83 = record.get("adr_0083") or {}
    ok = (
        adr_82.get("status") == "Accepted"
        and adr_83.get("status") == "Accepted"
        and record.get("implementation") == "none"
        and record.get("github_approval_claimed") is False
    )
    return "RECORDED_ACCEPTED" if ok else "NOT_RECORDED"


def _superseding_state(superseding_module, superseding_contract, superseding_sources,
                       superseding_assessment, superseding_provenance, root):
    verdict = superseding_module.compute_assessment(
        superseding_contract, superseding_sources, superseding_assessment,
        provenance=superseding_provenance, root=root)
    return verdict


def _marker_value(status_text: str, marker_prefix: str) -> str | None:
    match = re.search(re.escape(marker_prefix) + r"([^ ]*) -->", status_text)
    return match.group(1) if match else None


def _status_top(status_text: str) -> str:
    """The current-state region: everything before the single authority table.

    Historical sections below the authority table may keep stale machine markers
    for provenance; the top region is the current state and must not.
    """
    index = status_text.find("| 轨道 | 当前步骤 |")
    return status_text if index < 0 else status_text[:index]


def derive_items(contract: dict, sources: dict, live: dict, superseding_ctx: dict) -> dict[str, str]:
    superseding_module = superseding_ctx["module"]
    sv = superseding_ctx["verdict"]
    d15 = sv.get("derived_components", {})
    superseding_verdict = sources.get("superseding_verdict")
    superseding_input = sources.get("superseding_input")

    derived: dict[str, str] = {}
    derived["closeout_audit"] = _derive_closeout_audit(sources)
    derived["f2_unknown_result_reconciliation"] = _derive_f2(sources, live)
    derived["full_interface_audit"] = _derive_full_interface(sources, live)
    derived["composite_research_fault_regression"] = _derive_composite(contract, sources)
    derived["adr_0082_0083_decision"] = _derive_adr_decision(sources)

    superseding_established = (
        sv.get("format_valid") is True
        and sv.get("honest") is True
        and sv.get("established") is True
        and sv.get("decision") == "SUPERSEDING_ASSESSMENT_ESTABLISHED"
        and isinstance(superseding_verdict, dict)
        and superseding_verdict.get("all_pass") is True
        and superseding_verdict.get("established") is True
        and superseding_verdict.get("decision") == "SUPERSEDING_ASSESSMENT_ESTABLISHED"
        and isinstance(superseding_input, dict)
        and superseding_input.get("decision") == "SUPERSEDING_ASSESSMENT_ESTABLISHED"
    )
    derived["d15_superseding_assessment"] = (
        "ESTABLISHED" if superseding_established else "NOT_ESTABLISHED")

    derived["containment_business_recovery_gate"] = d15.get(
        "replacement_gate_business_recovery", "MISSING")
    derived["coherent_dsh_default_upgrade"] = d15.get(
        "coherent_dsh_default_upgrade", "MISSING")
    derived["historical_d15_g"] = d15.get("historical_d15_g", "MISSING")
    derived["b1_subagent_child_crash"] = d15.get("b1_subagent_child_crash", "MISSING")
    derived["b2_subagent_byq_adapter_restart"] = d15.get(
        "b2_subagent_byq_adapter_restart", "MISSING")
    derived["b3_terminal_adapter_restart"] = d15.get("b3_terminal_adapter_restart", "MISSING")
    derived["b4_terminal_dsh_runtime_restart"] = d15.get(
        "b4_terminal_dsh_runtime_restart", "MISSING")
    derived["native_independent_child_resume"] = d15.get(
        "native_independent_child_resume", "MISSING")
    derived["r3_resume"] = d15.get("r3_resume", "MISSING")
    return derived


def derive_constraints(contract: dict, sources: dict, live: dict, derived: dict) -> dict:
    deployment = sources.get("deployment_config") or {}
    upgrade = sources.get("default_upgrade") or {}
    status_text = sources.get("status_md") or ""
    not_claimed = [str(item).lower() for item in (upgrade.get("not_claimed") or [])]
    release_manifest_present = bool(live.get("release_manifest_present"))
    next_state = _marker_value(status_text, "<!-- byq:v090-next=")
    build_revision = _marker_value(status_text, "<!-- byq:build-revision=")
    b1_b2_downgraded = not (
        derived.get("b1_subagent_child_crash") == "BLOCKED_EXTERNAL"
        and derived.get("b2_subagent_byq_adapter_restart") == "BLOCKED_EXTERNAL")
    return {
        "repository_default_release": deployment.get("default_release"),
        "rollback_candidate": (deployment.get("candidate_releases") or [None])[0],
        "production_deployment": (
            "none" if any("production deployment" in item for item in not_claimed)
            and not release_manifest_present else "claimed_or_released"),
        "release_or_tag_created": release_manifest_present,
        "phase_100_resumed": _marker_value(
            status_text, "<!-- byq:phase-100-p100-c=") != "paused-not-delivery",
        "zero_ten_started": any(
            marker in status_text for marker in contract.get("status_markers_forbidden", [])
            if "zero-ten" in marker),
        "r3_resume": derived.get("r3_resume"),
        "b1_b2_downgraded": b1_b2_downgraded,
        "next_state": next_state,
        "build_revision": build_revision,
    }


def compute_matrix(contract: dict, sources: dict, assessment: dict, *,
                   superseding_ctx: dict, live: dict,
                   provenance: dict | None = None,
                   root: Path | None = None) -> dict:
    failures: list[str] = []
    honesty_failures: list[str] = []

    if not isinstance(assessment, dict):
        raise Failure("assessment must be an object")

    if assessment.get("assessment_id") != contract.get("assessment_id"):
        failures.append(f"assessment_id mismatch: {assessment.get('assessment_id')!r}")

    for forbidden in contract.get("forbidden_assessment_fields", []):
        if forbidden in assessment:
            failures.append(
                f"assessment may not declare its own '{forbidden}' field; the contract is authoritative")

    claimed_decision = assessment.get("decision")
    if claimed_decision not in contract.get("decision_vocabulary", []):
        failures.append(f"invalid decision {claimed_decision!r}")

    required = {item["id"]: item for item in contract["required_items"]}
    derived_components = derive_items(contract, sources, live, superseding_ctx)

    claimed_items = assessment.get("items")
    if not isinstance(claimed_items, dict):
        failures.append("assessment.items must be an object")
        claimed_items = {}
    if set(claimed_items) != set(required):
        missing = sorted(set(required) - set(claimed_items))
        extra = sorted(set(claimed_items) - set(required))
        failures.append(f"item set mismatch: missing={missing} extra={extra} (closed set)")
    for item_id in sorted(set(required) & set(claimed_items)):
        claimed = claimed_items.get(item_id)
        derived = derived_components.get(item_id, "MISSING")
        if claimed not in contract.get("status_vocabulary", []):
            failures.append(f"item {item_id!r} has invalid claimed status {claimed!r}")
        elif claimed != derived:
            honesty_failures.append(
                f"item {item_id!r} claimed {claimed!r} but derived {derived!r}")

    # The scoped limitations are derived; an assessment may not hide one.
    derived_limitations = sorted(contract.get("scoped_limitations_expected", LIMITATION_IDS))
    claimed_limitations = assessment.get("scoped_limitations")
    if claimed_limitations != derived_limitations:
        honesty_failures.append(
            f"scoped_limitations {claimed_limitations!r} does not equal {derived_limitations!r}")

    # Boundary constraints must equal the independently derived facts.
    derived_constraints = derive_constraints(contract, sources, live, derived_components)
    claimed_constraints = assessment.get("constraints")
    if not isinstance(claimed_constraints, dict):
        failures.append("assessment.constraints must be an object")
        claimed_constraints = {}
    constraint_mismatch: dict[str, dict] = {}
    expected_constraints = contract.get("constraint_expected", {})
    for key, expected in expected_constraints.items():
        derived_value = derived_constraints.get(key)
        if derived_value != expected:
            constraint_mismatch[key] = {"expected": expected, "derived": derived_value}
        if claimed_constraints.get(key) != derived_value:
            honesty_failures.append(
                f"constraint {key!r} claimed {claimed_constraints.get(key)!r} but derived {derived_value!r}")

    # STATUS markers: required present, forbidden absent.
    status_text = sources.get("status_md") or ""
    for marker in contract.get("status_markers_required", []):
        if marker not in status_text:
            failures.append(f"required STATUS marker missing: {marker}")
    for marker in contract.get("status_markers_forbidden", []):
        if marker in status_text:
            failures.append(f"forbidden STATUS marker present: {marker}")
    # The current-state region (above the authority table) must not carry a stale
    # superseded "next" marker; historical sections below may keep it.
    status_top = _status_top(status_text)
    for marker in contract.get("status_top_markers_forbidden", []):
        if marker in status_top:
            failures.append(f"stale current-state marker present at top: {marker}")

    # The formal 0.9.0 release gate is explicitly open and must not be claimed.
    release_gate = assessment.get("release_gate")
    contract_release_gate = contract.get("release_gate", {})
    if not isinstance(release_gate, dict) or (
            release_gate.get("formal_0_9_0_release_manifest")
            != contract_release_gate.get("formal_0_9_0_release_manifest")):
        failures.append("assessment.release_gate does not record the open formal 0.9.0 release gate")

    expected_mismatch = {
        item_id: {"expected": item["expected"], "derived": derived_components.get(item_id, "MISSING")}
        for item_id, item in required.items()
        if derived_components.get(item_id, "MISSING") != item["expected"]
    }
    constraints_ok = not constraint_mismatch
    complete = not expected_mismatch and constraints_ok
    derived_decision = ("V090_DEVELOPMENT_CLOSEOUT_COMPLETE" if complete
                        else "V090_DEVELOPMENT_CLOSEOUT_BLOCKED")
    if (claimed_decision in contract.get("decision_vocabulary", [])
            and claimed_decision != derived_decision):
        honesty_failures.append(
            f"decision claims {claimed_decision!r} but the derived decision is {derived_decision!r}")

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
    assessment_valid = format_valid and honest
    all_pass = assessment_valid and complete
    superseding_verdict = superseding_ctx["verdict"]
    return {
        "schema_version": "byq-v090-final-closeout-verdict.v1",
        "assessment_id": contract.get("assessment_id"),
        "all_pass": all_pass,
        "assessment_valid": assessment_valid,
        "format_valid": format_valid,
        "honest": honest,
        "complete": complete,
        "decision": derived_decision,
        "decision_claimed": claimed_decision,
        "decision_vocabulary": list(contract.get("decision_vocabulary", [])),
        "required_item_count": len(required),
        "derived_items": derived_components,
        "claimed_items": {key: claimed_items.get(key) for key in required},
        "expected_items": {key: item["expected"] for key, item in required.items()},
        "expected_item_mismatch": expected_mismatch,
        "derived_constraints": derived_constraints,
        "claimed_constraints": {key: claimed_constraints.get(key)
                                for key in expected_constraints},
        "expected_constraints": expected_constraints,
        "constraint_mismatch": constraint_mismatch,
        "scoped_limitations": derived_limitations,
        "superseding_verdict_established": superseding_verdict.get("established"),
        "release_gate": contract.get("release_gate", {}),
        "failures": failures,
        "honesty_failures": honesty_failures,
        "exit_code": 0 if all_pass else 1,
    }


# ---------------------------------------------------------------------------
# Legacy (pre-fix) algorithm: trusts the report's own decision/claims.
# ---------------------------------------------------------------------------

def legacy_compute_matrix(contract: dict, sources: dict, assessment: dict) -> dict:
    """Pre-fix algorithm: the report's claimed decision and item statuses were trusted."""
    failures: list[str] = []
    if assessment.get("decision") not in contract.get("decision_vocabulary", []):
        failures.append("invalid decision")
    claimed = assessment.get("items")
    if isinstance(claimed, dict):
        for value in claimed.values():
            if value not in contract.get("status_vocabulary", []):
                failures.append(f"invalid claimed status {value!r}")
    else:
        failures.append("missing claimed items")
    all_pass = not failures
    return {"algorithm": "legacy-pre-fix", "all_pass": all_pass,
            "exit_code": 0 if all_pass else 1, "failures": failures}


# ---------------------------------------------------------------------------
# Unit fixtures + negative controls (selfcheck).
# ---------------------------------------------------------------------------

_REQUIRED_STATUS_MARKERS = (
    "<!-- byq:v090-final-closeout=complete -->\n"
    "<!-- byq:v090-development-closeout=complete -->\n"
    "<!-- byq:v090-next=maintainer-testing-and-0.9x-window -->\n"
    "<!-- byq:phase-100-p100-c=paused-not-delivery -->\n"
    "<!-- byq:phase-100-slices-frozen=P100-C,P100-D,P100-E -->\n"
    "<!-- byq:v090-dsh-default-upgrade=promoted -->\n"
    "<!-- byq:v090-d15-superseding-assessment=established -->\n"
    "<!-- byq:build-revision=dsh-0.1.5rc1-post-u8.207 -->\n"
)

_COMPLETE_AUDIT = {
    "schema_version": "h4-review-check.v2",
    "discovered": 569, "reviewed": 569, "verified": 569,
    "missing": 0, "stale": 0, "stale_files": [], "fake_pass": 0,
    "unresolved": [], "manual_pending": [], "errors": [], "complete": True,
}

_COMPOSITE_NON_GATING = [
    "approval-revoked", "timeout-terminal", "data-ready-continuation",
    "runtime-adapter-tool-boundary",
]


def _fixture_sources(superseding_contract: dict, superseding_module) -> tuple[dict, dict]:
    superseding_sources = superseding_module._sources()
    good_verdict = superseding_module.compute_assessment(
        superseding_contract, superseding_sources,
        superseding_module._decision(superseding_contract, superseding_sources))
    scenario_results = {
        "response-loss-before-write": "PASS",
        "response-loss-after-write": "PASS",
        "duplicate-delivery": "PASS",
        "process-restart-backend": "PASS",
        "process-restart-gateway": "PASS",
        "process-restart-ml-worker": "PASS",
        "late-success": "PASS",
        "cancel-terminal": "PASS",
        "approval-rejected": "PASS",
        "approval-stale-reuse": "PASS",
        "queue-worker-resume": "PASS",
        "bounded-continuation-exactly-once": "PASS",
        "model-or-domain-failure": "PASS",
        "approval-revoked": "BLOCKED",
        "timeout-terminal": "BLOCKED",
        "data-ready-continuation": "BLOCKED",
        "runtime-adapter-tool-boundary": "BLOCKED",
    }
    sources = {
        "status_md": _REQUIRED_STATUS_MARKERS,
        "closeout_ledger": {
            "schema_version": "byq-v090-closeout-gap-ledger.v1",
            "snapshot": True, "snapshot_kind": "historical-audit-snapshot",
            "items": [{
                "id": "F2", "status": "open",
                "open_reason_evidence": ["scripts/ci/check-reliability-review.py"],
                "evidence": ["docs/evidence/post-u8-f2-research-watch/AUDIT.md"],
            }],
        },
        "closeout_matrix": {
            "schema_version": "byq-v090-closeout-acceptance-matrix.v1",
            "snapshot": True, "snapshot_kind": "historical-audit-snapshot",
        },
        "f2_research_watch": "# F2 research watch (fixture)\n",
        "f2_interface_audit": "# F2 interface audit (fixture)\n",
        "full_interface_rebaseline": {"auditor": dict(_COMPLETE_AUDIT)},
        "interface_audit_snapshot": dict(_COMPLETE_AUDIT),
        "composite_verdict": {
            "schema_version": "byq-v090-composite-research-verdict.v2",
            "format_valid": True, "all_pass": False, "journey_result": "PASS",
            "scenario_results": scenario_results,
        },
        "composite_matrix": {
            "schema_version": "byq-v090-composite-research-acceptance-matrix.v2",
            "frozen": True,
            "status": {"blocked_required_rows": list(_COMPOSITE_NON_GATING)},
        },
        "adr_decision_record": {
            "adr_0082": {"status": "Accepted"},
            "adr_0083": {"status": "Accepted"},
            "implementation": "none", "github_approval_claimed": False,
        },
        "deployment_config": {"default_release": "dsh-0.1.5rc1",
                              "candidate_releases": ["dsh-0.1.2rc1"]},
        "default_upgrade": {"not_claimed": ["production deployment", "release/tag"]},
        "superseding_verdict": {
            "all_pass": True, "established": True,
            "decision": "SUPERSEDING_ASSESSMENT_ESTABLISHED",
        },
        "superseding_input": {"decision": "SUPERSEDING_ASSESSMENT_ESTABLISHED"},
        "_superseding_sources": superseding_sources,
    }
    return sources, good_verdict


def _fixture_live(*, audit: dict | None = None, release_manifest_present: bool = False) -> dict:
    return {"interface_audit": dict(audit or _COMPLETE_AUDIT),
            "release_manifest_present": release_manifest_present}


def _fixture_decision(contract: dict, sources: dict, live: dict, superseding_ctx: dict,
                      *, decision: str | None = None,
                      constraints_override: dict | None = None,
                      items_override: dict | None = None,
                      scoped_limitations_override: list | None = None) -> dict:
    derived = derive_items(contract, sources, live, superseding_ctx)
    derived_constraints = derive_constraints(contract, sources, live, derived)
    items = {item["id"]: derived[item["id"]] for item in contract["required_items"]}
    if items_override:
        items.update(items_override)
    constraints = dict(derived_constraints)
    if constraints_override:
        constraints.update(constraints_override)
    complete = (
        all(items[item["id"]] == item["expected"] for item in contract["required_items"])
        and constraints == contract["constraint_expected"])
    return {
        "schema_version": "byq-v090-final-closeout-assessment-input.v1",
        "assessment_id": contract["assessment_id"],
        "decision": decision or ("V090_DEVELOPMENT_CLOSEOUT_COMPLETE" if complete
                                 else "V090_DEVELOPMENT_CLOSEOUT_BLOCKED"),
        "items": items,
        "constraints": constraints,
        "scoped_limitations": (
            scoped_limitations_override if scoped_limitations_override is not None
            else sorted(contract.get("scoped_limitations_expected", LIMITATION_IDS))),
        "release_gate": contract["release_gate"],
        "provenance": "docs/evidence/v090-final-closeout/provenance.v1.json",
    }


def good_fixture(contract: dict, superseding_contract: dict, superseding_module):
    sources, _ = _fixture_sources(superseding_contract, superseding_module)
    live = _fixture_live()
    superseding_ctx = _fixture_context(superseding_contract, superseding_module)
    assessment = _fixture_decision(contract, sources, live, superseding_ctx)
    return sources, live, superseding_ctx, assessment


def _fixture_context(superseding_contract: dict, superseding_module) -> dict:
    superseding_sources = superseding_module._sources()
    superseding_assessment = superseding_module._decision(superseding_contract, superseding_sources)
    verdict = superseding_module.compute_assessment(
        superseding_contract, superseding_sources, superseding_assessment)
    return {"module": superseding_module, "contract": superseding_contract,
            "sources": superseding_sources, "assessment": superseding_assessment,
            "provenance": None, "verdict": verdict}


def _mutations(contract, superseding_contract, superseding_module):
    good_sources, good_live, good_ctx, good = good_fixture(
        contract, superseding_contract, superseding_module)
    mutations = []

    def add(name, mutate, *, sources=None, live=None, ctx=None):
        value = copy.deepcopy(good)
        mutate(value)
        mutations.append((name, sources or good_sources, live or good_live, ctx or good_ctx, value))

    # A superseding source set where B1/B2 stop being external blockers (e.g. an
    # out-of-process provider landed): the superseding assessment is no longer
    # established, so the closeout cannot claim it is.
    superseding_broken = superseding_module._sources(
        d15_4_child_crash="PASS", d15_4_adapter_restart="PASS", provider_blocked=False)
    broken_ctx = dict(good_ctx)
    broken_ctx["sources"] = superseding_broken
    broken_ctx["verdict"] = superseding_module.compute_assessment(
        superseding_contract, superseding_broken,
        superseding_module._decision(superseding_contract, superseding_broken))

    add("claim-b1-pass",
        lambda v: v["items"].update({"b1_subagent_child_crash": "PASS"}))
    add("claim-b2-pass",
        lambda v: v["items"].update({"b2_subagent_byq_adapter_restart": "PASS"}))
    add("claim-native-child-resume-implemented",
        lambda v: v["items"].update({"native_independent_child_resume": "IMPLEMENTED"}))
    add("claim-r3-resume-yes", lambda v: v["items"].update({"r3_resume": "YES"}))
    add("claim-composite-all-pass",
        lambda v: v["items"].update({"composite_research_fault_regression": "PASS"}))
    add("claim-historical-d15-g-pass",
        lambda v: v["items"].update({"historical_d15_g": "PASS"}))
    add("claim-d15-superseding-established",
        lambda v: v["items"].update({"d15_superseding_assessment": "ESTABLISHED"}),
        ctx=broken_ctx)

    # Full-interface audit not complete -> F2 and the audit item fail closed.
    incomplete = dict(_COMPLETE_AUDIT, complete=False, missing=3)
    add("claim-full-interface-complete-when-incomplete",
        lambda v: v["items"].update({"full_interface_audit": "COMPLETE"}),
        live=_fixture_live(audit=incomplete))
    add("claim-f2-covered-when-ledger-incomplete",
        lambda v: v["items"].update({"f2_unknown_result_reconciliation": "COVERED"}),
        live=_fixture_live(audit=incomplete))
    # Snapshot/live divergence is a structural failure.
    add("claim-full-interface-complete-when-snapshot-diverges",
        lambda v: v["items"].update({"full_interface_audit": "COMPLETE"}),
        live=_fixture_live(audit=dict(_COMPLETE_AUDIT, discovered=570, reviewed=570,
                                      verified=570)))

    # Superseding assessment not established (B1 provider became available).
    add("claim-closeout-complete-when-superseding-not-established",
        lambda v: None, ctx=broken_ctx)

    # Rewritten historical D15-G verdict.
    rewritten = copy.deepcopy(good_ctx["sources"])
    rewritten["d15_g_verdict"] = {"verdict": "GO", "all_pass": True, "derived_blockers": []}
    rewritten["d15_g_capability_matrix"] = {"primary_named_blockers": []}
    rewritten_ctx = dict(good_ctx)
    rewritten_ctx["sources"] = rewritten
    rewritten_ctx["verdict"] = superseding_module.compute_assessment(
        superseding_contract, rewritten,
        superseding_module._decision(superseding_contract, rewritten))
    add("rewrite-historical-d15-g", lambda v: None, ctx=rewritten_ctx)

    # ADR decision record missing acceptance.
    bad_adr = copy.deepcopy(good_sources)
    bad_adr["adr_decision_record"] = {"adr_0082": {"status": "Proposed"},
                                      "adr_0083": {"status": "Accepted"},
                                      "implementation": "none",
                                      "github_approval_claimed": False}
    add("claim-adr-recorded-when-not",
        lambda v: v["items"].update({"adr_0082_0083_decision": "RECORDED_ACCEPTED"}),
        sources=bad_adr)

    # Missing evidence -> MISSING.
    missing_source = copy.deepcopy(good_sources)
    missing_source["composite_verdict"] = {}
    add("claim-composite-pass-when-evidence-missing",
        lambda v: v["items"].update({"composite_research_fault_regression": "PASS_AS_SCOPED"}),
        sources=missing_source)

    # Boundary overclaims.
    add("claim-production-deployment",
        lambda v: v["constraints"].update({"production_deployment": "verified"}),
        live=_fixture_live(release_manifest_present=True))
    add("claim-release-tag-created",
        lambda v: v["constraints"].update({"release_or_tag_created": True}),
        live=_fixture_live(release_manifest_present=True))
    add("claim-phase-100-resumed",
        lambda v: v["constraints"].update({"phase_100_resumed": True}))
    add("claim-zero-ten-started",
        lambda v: v["constraints"].update({"zero_ten_started": True}))
    add("wrong-next-state",
        lambda v: v["constraints"].update({"next_state": "phase-100-resume"}))
    add("wrong-build-revision",
        lambda v: v["constraints"].update({"build_revision": "dsh-0.1.5rc1-post-u8.202"}))
    add("hide-scoped-limitation",
        lambda v: v.update({"scoped_limitations": ["b1_subagent_child_crash"]}))

    # Self-declared fields / invalid decision / closed set.
    add("self-declared-verdict", lambda v: v.update({"all_pass": True}))
    add("self-declared-established", lambda v: v.update({"established": True}))
    add("self-declared-coverage", lambda v: v.update({"coverage": {"all": "PASS"}}))
    add("invalid-decision", lambda v: v.update({"decision": "MAYBE"}))
    add("drop-required-item", lambda v: v["items"].pop("r3_resume"))
    add("extra-item", lambda v: v["items"].update({"unknown": "PASS"}))
    add("missing-release-gate",
        lambda v: v.update({"release_gate": {"formal_0_9_0_release_manifest": "SATISFIED"}}))

    # Forbidden / missing STATUS markers are structural failures.
    bad_status = copy.deepcopy(good_sources)
    bad_status["status_md"] = _REQUIRED_STATUS_MARKERS.replace(
        "<!-- byq:v090-next=maintainer-testing-and-0.9x-window -->\n",
        "<!-- byq:zero-ten=started -->\n")
    add("forbidden-status-marker", lambda v: None, sources=bad_status)

    # A stale superseded "next" marker in the current-state (top) region.
    stale_top = copy.deepcopy(good_sources)
    stale_top["status_md"] = (
        _REQUIRED_STATUS_MARKERS
        + "<!-- byq:session-failure-containment-next=v090-final-development-closeout -->\n")
    add("stale-current-next-marker-at-top", lambda v: None, sources=stale_top)
    return mutations


def selfcheck(contract, superseding_contract, superseding_module) -> dict:
    good_sources, good_live, good_ctx, good_decision = good_fixture(
        contract, superseding_contract, superseding_module)
    good = compute_matrix(contract, good_sources, good_decision,
                          superseding_ctx=good_ctx, live=good_live)
    controls = []
    for name, sources, live, ctx, assessment in _mutations(
            contract, superseding_contract, superseding_module):
        fixed = compute_matrix(contract, sources, assessment,
                               superseding_ctx=ctx, live=live)
        legacy = legacy_compute_matrix(contract, sources, assessment)
        controls.append({
            "name": name,
            "fixed_all_pass": fixed["all_pass"],
            "fixed_exit_code": fixed["exit_code"],
            "fixed_decision": fixed["decision"],
            "legacy_all_pass": legacy["all_pass"],
        })
    all_controls_rejected = all(not item["fixed_all_pass"] for item in controls)
    defect_targeting = [item for item in controls
                        if item["legacy_all_pass"] and not item["fixed_all_pass"]]
    return {
        "schema_version": "byq-v090-final-closeout-negative-controls.v1",
        "known_good_fixture_all_pass": good["all_pass"],
        "known_good_fixture_decision": good["decision"],
        "known_good_fixture_items": good["derived_items"],
        "control_count": len(controls),
        "controls": controls,
        "all_controls_rejected": all_controls_rejected,
        "defect_targeting_pre_fix_passed_count": len(defect_targeting),
        "defect_targeting_pre_fix_passed": [item["name"] for item in defect_targeting],
    }


def build_superseding_context(contract: dict, sources: dict, root: Path):
    superseding_module = load_superseding_module(root)
    superseding_contract = sources.get("_superseding_contract")
    if superseding_contract is None:
        superseding_contract = _load(root / SUPERSEDING_REL / "contract.v1.json")
    superseding_sources = sources.get("_superseding_sources")
    if superseding_sources is None:
        superseding_sources = superseding_module.load_sources(superseding_contract, root)
    superseding_assessment = sources["superseding_input"]
    superseding_provenance = sources["superseding_provenance"]
    verdict = _superseding_state(superseding_module, superseding_contract, superseding_sources,
                                 superseding_assessment, superseding_provenance, root)
    return {"module": superseding_module, "contract": superseding_contract,
            "sources": superseding_sources, "assessment": superseding_assessment,
            "provenance": superseding_provenance, "verdict": verdict}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--assessment", type=Path)
    parser.add_argument("--provenance", type=Path)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--selfcheck", action="store_true")
    args = parser.parse_args(argv)

    contract = _load(args.contract)
    root = args.root
    superseding_module = load_superseding_module(root)
    superseding_contract = _load(root / SUPERSEDING_REL / "contract.v1.json")
    if args.selfcheck:
        result = selfcheck(contract, superseding_contract, superseding_module)
        code = 0 if (result["all_controls_rejected"]
                     and result["known_good_fixture_all_pass"]) else 1
    else:
        if args.assessment is None:
            parser.error("--assessment is required unless --selfcheck")
        sources = load_sources(contract, root)
        live = gather_live(root)
        superseding_ctx = build_superseding_context(contract, sources, root)
        provenance = _load(args.provenance) if args.provenance else None
        result = compute_matrix(contract, sources, _load(args.assessment),
                                superseding_ctx=superseding_ctx, live=live,
                                provenance=provenance, root=root)
        code = result["exit_code"]
        print(json.dumps({
            "assessment_id": result["assessment_id"],
            "decision": result["decision"],
            "all_pass": result["all_pass"],
            "complete": result["complete"],
            "honest": result["honest"],
            "format_valid": result["format_valid"],
            "expected_item_mismatch": result["expected_item_mismatch"],
            "constraint_mismatch": result["constraint_mismatch"],
            "failures": result["failures"],
            "honesty_failures": result["honesty_failures"],
        }, indent=2))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8")
    return code


if __name__ == "__main__":
    sys.exit(main())
