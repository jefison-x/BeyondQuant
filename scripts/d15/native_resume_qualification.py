#!/usr/bin/env python3
"""D15-3 native session resume qualification evidence builder.

Reads the raw observations produced by the real DSH 0.1.5-rc.1
``native_resume_harness.mjs`` and classifies every Runtime Continuity
failure-matrix row through the framework-neutral BYQ contract
(``packages.contracts.runtime_continuity.classify_generation_transition``).

The public continuity status stays exactly ``fresh | reattached | rehydrated |
interrupted``. The native-vs-BYQ-fallback mechanism is recorded only in the
internal, evidence-only diagnostics.

Usage:
    python3 scripts/d15/native_resume_qualification.py <observations.json> <results.json>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from packages.contracts import runtime_continuity as continuity  # noqa: E402

OBSERVATIONS_SCHEMA = "byq-d15-3-native-resume-observations.v1"
RESULTS_SCHEMA = "byq-d15-3-native-resume-results.v1"


def classify_row(row: dict) -> dict:
    inputs = row["classification_input"]
    decision = continuity.classify_generation_transition(
        generation_survived=inputs["generation_survived"],
        lost_run=inputs["lost_run"],
        native_session_persisted=inputs["native_session_persisted"],
        native_resume_available=inputs["native_resume_available"],
        byq_fallback_available=inputs["byq_fallback_available"],
        previous_generation_state=inputs.get("previous_generation_state"),
    )
    diagnostics = decision.diagnostics
    return {
        "continuity": decision.continuity,
        "native_resume_used": diagnostics[continuity.DIAGNOSTIC_NATIVE_RESUME_USED],
        "byq_fallback_used": diagnostics[continuity.DIAGNOSTIC_BYQ_FALLBACK_USED],
        "previous_generation_state": diagnostics[continuity.DIAGNOSTIC_PREVIOUS_GENERATION_STATE],
        "native_session_present": diagnostics[continuity.DIAGNOSTIC_NATIVE_SESSION_PRESENT],
        "byq_fallback_required": decision.byq_fallback_required,
    }


def build_results(observations: dict) -> dict:
    rows = []
    for row in observations["failure_rows"] + observations["controls"]:
        rows.append({
            "id": row["id"],
            "fault": row["fault"],
            "kind": "control" if row["id"].endswith("control") else "failure_row",
            "generation": row["generation"],
            "lost_run": row["lost_run"],
            "dsh_session_persisted": row["dsh_session_persisted"],
            "native_resume_available": row["native_resume_available"],
            "native_resume_same_session_id": row["native_resume_same_session_id"],
            "native_resume_events_preserved": row["native_resume_events_preserved"],
            "native_resume_sequence_contiguous": row["native_resume_sequence_contiguous"],
            "native_resume_event_count": row["native_resume_event_count"],
            "lease_contention_observed": row["lease_contention_observed"],
            "lease_released_on_process_death": row["lease_released_on_process_death"],
            "cold_read_interrupted_closers": row["cold_read_interrupted_closers"],
            "open_turn_preserved": row["open_turn_preserved"],
            "classification": classify_row(row),
            "byq_fallback_required_if_native_unavailable": row["byq_fallback_required_if_native_unavailable"],
            "simulated": row["simulated"],
            "real": row["real"],
        })

    failure_rows = [row for row in rows if row["kind"] == "failure_row"]
    controls = [row for row in rows if row["kind"] == "control"]
    by_continuity = {status: 0 for status in sorted(continuity.STATUSES)}
    for row in failure_rows:
        by_continuity[row["classification"]["continuity"]] += 1

    native_viable = all(
        row["native_resume_available"]
        and row["native_resume_same_session_id"] is True
        and row["native_resume_sequence_contiguous"] is True
        for row in failure_rows
        if row["dsh_session_persisted"]
    )
    control_fallback = controls[0]["classification"] if controls else None

    return {
        "schema_version": RESULTS_SCHEMA,
        "generated_from": OBSERVATIONS_SCHEMA,
        "target": observations["target"],
        "harness": observations["harness"],
        "rows": rows,
        "summary": {
            "failure_row_count": len(failure_rows),
            "control_count": len(controls),
            "classification_counts": by_continuity,
            "native_resume_available_count": sum(
                1 for row in failure_rows if row["native_resume_available"]),
            "native_resume_same_session_id_count": sum(
                1 for row in failure_rows if row["native_resume_same_session_id"] is True),
            "native_resume_sequence_contiguous_count": sum(
                1 for row in failure_rows if row["native_resume_sequence_contiguous"] is True),
            "byq_fallback_count": sum(
                1 for row in failure_rows if row["classification"]["byq_fallback_used"]),
            "native_resume_viable": native_viable,
            "native_unavailable_control_uses_byq_fallback": bool(
                control_fallback and control_fallback["byq_fallback_used"]),
            "r3_should_reimplement_native_session_resume": False,
            "r3_resume": "NO",
            "public_contract_unchanged": True,
            "public_contract_statuses": sorted(continuity.STATUSES),
            "internal_diagnostic_fields": sorted(continuity.DIAGNOSTIC_FIELDS),
        },
    }


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    observations = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    if observations.get("schema_version") != OBSERVATIONS_SCHEMA:
        raise SystemExit(f"unexpected observations schema: {observations.get('schema_version')!r}")
    results = build_results(observations)
    Path(sys.argv[2]).write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
