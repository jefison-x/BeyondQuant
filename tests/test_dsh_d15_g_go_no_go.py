"""D15-G architecture Go/No-Go acceptance tests.

Covers the fail-able Go/No-Go decision contract and observer (partial-PASS
aggregation rejection, per-capability derivation, provenance verification,
self-declared-field rejection), the committed evidence (honest NO_GO, named
blockers, provenance), and the unchanged constraints (R3_RESUME=NO, production
selector/default, Proposed ADR-0082/0083 not accepted/implemented).

Runs under ``unittest`` (the architecture lane has no pytest).
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GO_NO_GO = ROOT / "scripts/d15/go_no_go"
OBSERVER = GO_NO_GO / "observer.py"
CONTRACT = GO_NO_GO / "contract.v1.json"
EVIDENCE = ROOT / "docs/evidence/d15/d15-g"

PRIMARY_BLOCKERS = (
    "subagent-child-crash",
    "subagent-byq-adapter-restart",
    "terminal-adapter-restart",
    "terminal-dsh-runtime-restart",
)


def _load_observer():
    spec = importlib.util.spec_from_file_location("d15_g_observer", OBSERVER)
    module = importlib.util.module_from_spec(spec)
    sys.modules["d15_g_observer"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _contract():
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def _decision():
    return json.loads((EVIDENCE / "decision-input.v1.json").read_text(encoding="utf-8"))


def _provenance():
    return json.loads((EVIDENCE / "provenance.v1.json").read_text(encoding="utf-8"))


class D15GoNoGoContractTests(unittest.TestCase):
    def test_contract_is_closed_and_versioned(self):
        contract = _contract()
        self.assertEqual(contract["schema_version"], "byq-d15-g-contract.v1")
        self.assertEqual(contract["decision_vocabulary"], ["GO", "NO_GO"])
        self.assertEqual(contract["candidate"]["release"], "dsh-0.1.5rc1")
        ids = [item["id"] for item in contract["required_capabilities"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), 11)
        for required in ("root-session-persistence", "process-restart-resume",
                         "host-reboot-resume", "fork-continuity", "subagent-resume",
                         "subagent-child-crash", "subagent-byq-adapter-restart",
                         "terminal-client-reattach", "terminal-persistence",
                         "terminal-adapter-restart", "terminal-dsh-runtime-restart"):
            self.assertIn(required, ids)
        # Required items must not pass by deletion.
        by_id = {item["id"]: item for item in contract["required_capabilities"]}
        for required_id in PRIMARY_BLOCKERS:
            self.assertTrue(by_id[required_id]["required"])

    def test_constraints_keep_r3_frozen_and_production_unchanged(self):
        constraints = _contract()["constraints"]
        self.assertEqual(constraints["r3_resume"], "NO")
        self.assertEqual(constraints["production_selector"], "dsh-0.1.2rc1")
        self.assertTrue(constraints["production_default_unchanged"])
        self.assertEqual(constraints["deployment"], "none")
        self.assertIn("not accepted", constraints["adr_0082"])
        self.assertIn("not implemented", constraints["adr_0082"])
        self.assertIn("not accepted", constraints["adr_0083"])
        self.assertIn("not implemented", constraints["adr_0083"])

    def test_go_is_granted_only_when_every_required_capability_passes(self):
        observer = _load_observer()
        contract = _contract()
        sources, decision = observer.good_fixture(contract)
        verdict = observer.compute_decision(contract, sources, decision)
        self.assertTrue(verdict["all_pass"], verdict["failures"])
        self.assertTrue(verdict["format_valid"])
        self.assertEqual(verdict["verdict"], "GO")
        self.assertTrue(verdict["go_granted"])

    def test_partial_sources_force_no_go_and_name_blockers(self):
        observer = _load_observer()
        contract = _contract()
        sources, decision = observer.real_fixture(contract)
        verdict = observer.compute_decision(contract, sources, decision)
        self.assertTrue(verdict["decision_valid"])
        self.assertTrue(verdict["honest"])
        self.assertFalse(verdict["all_pass"])
        self.assertEqual(verdict["verdict"], "NO_GO")
        self.assertFalse(verdict["go_granted"])
        for blocker in PRIMARY_BLOCKERS:
            self.assertIn(blocker, verdict["derived_blockers"])

    def test_partial_pass_aggregation_into_go_is_rejected(self):
        observer = _load_observer()
        contract = _contract()
        sources, decision = observer.real_fixture(contract)
        fabricated = copy.deepcopy(decision)
        fabricated["decision"] = "GO"
        fabricated["blockers"] = []
        verdict = observer.compute_decision(contract, sources, fabricated)
        self.assertFalse(verdict["all_pass"])
        self.assertTrue(verdict["aggregation_rejected"])
        self.assertFalse(verdict["honest"])
        self.assertTrue(any("partial-PASS aggregation rejected" in failure
                            for failure in verdict["honesty_failures"]))

    def test_required_capability_claimed_pass_over_blocked_source_is_rejected(self):
        observer = _load_observer()
        contract = _contract()
        sources, decision = observer.real_fixture(contract)
        fabricated = copy.deepcopy(decision)
        fabricated["capabilities"]["subagent-child-crash"] = "PASS"
        fabricated["blockers"] = [b for b in fabricated["blockers"] if b != "subagent-child-crash"]
        verdict = observer.compute_decision(contract, sources, fabricated)
        self.assertFalse(verdict["all_pass"])
        self.assertTrue(any("claimed 'PASS' but derived 'BLOCKED'" in failure
                            for failure in verdict["honesty_failures"]))

    def test_decision_may_not_declare_its_own_verdict_or_coverage(self):
        observer = _load_observer()
        contract = _contract()
        sources, decision = observer.good_fixture(contract)
        for field in ("go_authorized", "coverage", "all_pass"):
            fabricated = copy.deepcopy(decision)
            fabricated[field] = True
            verdict = observer.compute_decision(contract, sources, fabricated)
            self.assertFalse(verdict["all_pass"], field)
            self.assertTrue(any("may not declare" in failure for failure in verdict["failures"]), field)

    def test_every_negative_control_is_rejected_and_pre_fix_defects_are_evidenced(self):
        observer = _load_observer()
        contract = _contract()
        result = observer.selfcheck(contract)
        self.assertTrue(result["all_controls_rejected"])
        self.assertTrue(result["known_good_all_pass_fixture_all_pass"])
        self.assertEqual(result["known_good_all_pass_fixture_verdict"], "GO")
        self.assertFalse(result["real_partial_fixture_all_pass"])
        self.assertTrue(result["real_partial_fixture_decision_valid"])
        self.assertEqual(result["real_partial_fixture_verdict"], "NO_GO")
        self.assertFalse([item for item in result["controls"] if item["fixed_all_pass"]])
        self.assertGreater(result["defect_targeting_pre_fix_passed_count"], 0)
        defect_names = set(result["defect_targeting_pre_fix_passed"])
        self.assertIn("claim-go-on-partial-sources", defect_names)
        self.assertIn("claim-child-crash-pass", defect_names)


class D15GoNoGoEvidenceTests(unittest.TestCase):
    def test_committed_verdict_is_honest_no_go(self):
        verdict = json.loads((EVIDENCE / "verdict.v1.json").read_text(encoding="utf-8"))
        self.assertFalse(verdict["all_pass"])
        self.assertTrue(verdict["decision_valid"])
        self.assertTrue(verdict["format_valid"])
        self.assertTrue(verdict["honest"])
        self.assertEqual(verdict["verdict"], "NO_GO")
        self.assertFalse(verdict["go_granted"])
        self.assertFalse(verdict["go_claimed"])
        self.assertEqual(verdict["r3_resume"], "NO")
        self.assertEqual(verdict["production_selector"], "dsh-0.1.2rc1")
        for blocker in PRIMARY_BLOCKERS:
            self.assertIn(blocker, verdict["derived_blockers"])
        self.assertIn("host-reboot-resume", verdict["derived_blockers"])

    def test_committed_decision_claims_no_go_and_matches_derived(self):
        decision = _decision()
        self.assertEqual(decision["decision"], "NO_GO")
        self.assertNotEqual(decision["decision"], "GO")
        for blocker in PRIMARY_BLOCKERS:
            self.assertIn(blocker, decision["blockers"])
        self.assertEqual(decision["constraints"]["r3_resume"], "NO")
        self.assertEqual(decision["constraints"]["production_selector"], "dsh-0.1.2rc1")

    def test_provenance_hashes_match_every_reused_evidence_file(self):
        provenance = _provenance()
        entries = {item["path"]: item for item in provenance["artifacts"]}
        for artifact in _contract()["source_artifacts"]:
            path = ROOT / artifact["path"]
            self.assertTrue(path.is_file(), artifact["path"])
            digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertIn(artifact["path"], entries)
            self.assertEqual(entries[artifact["path"]]["sha256"], digest, artifact["path"])
            self.assertRegex(entries[artifact["path"]]["introduced_by"], r"^[0-9a-f]{40}$")

    def test_observer_verifies_committed_decision_against_real_provenance(self):
        observer = _load_observer()
        contract = _contract()
        sources = observer.load_sources(contract, ROOT)
        verdict = observer.compute_decision(contract, sources, _decision(),
                                            provenance=_provenance(), root=ROOT)
        self.assertTrue(verdict["decision_valid"], verdict["failures"])
        self.assertFalse(verdict["all_pass"])
        self.assertEqual(verdict["verdict"], "NO_GO")
        self.assertEqual(verdict["claimed_capabilities"], verdict["derived_capabilities"])

    def test_committed_negative_controls_evidence(self):
        controls = json.loads((EVIDENCE / "negative-controls.v1.json").read_text(encoding="utf-8"))
        self.assertTrue(controls["all_controls_rejected"])
        self.assertTrue(controls["known_good_all_pass_fixture_all_pass"])
        self.assertFalse([item for item in controls["controls"] if item["fixed_all_pass"]])
        self.assertIn("claim-go-on-partial-sources",
                      controls["defect_targeting_pre_fix_passed"])

    def test_capability_matrix_covers_d15_2_through_d15_5(self):
        matrix = json.loads((EVIDENCE / "capability-matrix.v1.json").read_text(encoding="utf-8"))
        stages = {item["stage"] for item in matrix["layer_summary"]}
        self.assertEqual(stages, {"D15-2", "D15-3", "D15-3R", "D15-4", "D15-5"})
        ids = {item["id"] for item in matrix["capabilities"]}
        self.assertEqual(len(ids), 11)
        for item in matrix["capabilities"]:
            for key in ("dsh_native_result", "byq_fallback", "r_series_owner", "result", "evidence"):
                self.assertTrue(item.get(key), item["id"])
        self.assertEqual(set(matrix["primary_named_blockers"]), set(PRIMARY_BLOCKERS))
        self.assertEqual(matrix["constraints"]["r3_resume"], "NO")

    def test_acceptance_matrix_records_d15_g_no_go(self):
        matrix = json.loads((ROOT / "docs/evidence/d15/acceptance-matrix.v1.json").read_text())
        d15_g = next(item for item in matrix["substages"] if item["id"] == "D15-G")
        self.assertEqual(d15_g["result"], "NO_GO")
        self.assertIn("NO_GO", matrix["result_vocabulary"])
        self.assertTrue(d15_g["evidence"])
        self.assertTrue(d15_g["criterion_results"])

    def test_adr_0082_and_0083_remain_proposed_and_unimplemented(self):
        for name in ("ADR-0082-dsh-continuable-child-resume.md",
                     "ADR-0083-terminal-attachment-boundary.md"):
            text = (ROOT / "docs/architecture/adr" / name).read_text(encoding="utf-8")
            self.assertIn("Proposed", text, name)
            self.assertIn("NOT accepted, NOT implemented", text, name)
            self.assertNotIn("Status: Accepted", text, name)


if __name__ == "__main__":
    unittest.main()
