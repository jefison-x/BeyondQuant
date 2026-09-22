"""Named D15 superseding assessment acceptance tests (ADR-0084 gate reclassification).

Covers the fail-able, machine-readable superseding assessment and observer:

* ADR-0084 replaces the *global* blocking role of the historical D15-G verdict with
  the current required gate (BYQ session failure containment and business
  recovery); this assessment references D15-4/D15-5/D15-G without rewriting them.
* It independently derives the current overlay (B1/B2 ``BLOCKED_EXTERNAL``,
  B3/B4 candidate-layer ``PASS``), the replacement-gate and coherent-upgrade
  status, candidate compatibility/promotion for the actually adopted scope, and
  the bounded R3 scope (``R3_RESUME = NO``).
* Native independent child resume is never reported as implemented.

Runs under ``unittest`` (the architecture lane has no pytest).
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUPERSEDING = ROOT / "scripts/d15/superseding_assessment"
OBSERVER = SUPERSEDING / "observer.py"
CONTRACT = SUPERSEDING / "contract.v1.json"
EVIDENCE = ROOT / "docs/evidence/d15/d15-superseding"

CURRENT_BUILD_REVISION = "dsh-0.1.5rc1-post-u8.206"
CANDIDATE = "dsh-0.1.5rc1"
ROLLBACK = "dsh-0.1.2rc1"

EXPECTED_COMPONENTS = {
    "historical_d15_g": "NO_GO_PRESERVED",
    "replacement_gate_business_recovery": "PASS",
    "coherent_dsh_default_upgrade": "PASS",
    "b1_subagent_child_crash": "BLOCKED_EXTERNAL",
    "b2_subagent_byq_adapter_restart": "BLOCKED_EXTERNAL",
    "b3_terminal_adapter_restart": "PASS_CANDIDATE",
    "b4_terminal_dsh_runtime_restart": "PASS_CANDIDATE",
    "native_independent_child_resume": "NOT_IMPLEMENTED",
    "candidate_compatibility_actual_scope": "PASS",
    "candidate_promotion_actual_scope": "REPO_DEFAULT_PROMOTED",
    "r3_resume": "NO",
}
BOUNDED_R3_SCOPE = ["safe_failure", "observation", "cleanup", "new_generation_recovery"]
PRIMARY_BLOCKERS = (
    "subagent-child-crash",
    "subagent-byq-adapter-restart",
    "terminal-adapter-restart",
    "terminal-dsh-runtime-restart",
)


def _load_observer():
    spec = importlib.util.spec_from_file_location("d15_superseding_observer", OBSERVER)
    module = importlib.util.module_from_spec(spec)
    sys.modules["d15_superseding_observer"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _contract() -> dict:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def _assessment() -> dict:
    return json.loads((EVIDENCE / "assessment-input.v1.json").read_text(encoding="utf-8"))


def _provenance() -> dict:
    return json.loads((EVIDENCE / "provenance.v1.json").read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


class ContractTests(unittest.TestCase):
    def test_contract_is_closed_and_versioned(self):
        contract = _contract()
        self.assertEqual(contract["schema_version"], "byq-d15-superseding-contract.v1")
        self.assertEqual(contract["assessment_id"], "d15-superseding-assessment.v1")
        self.assertEqual(
            contract["decision_vocabulary"],
            ["SUPERSEDING_ASSESSMENT_ESTABLISHED", "SUPERSEDING_ASSESSMENT_NOT_ESTABLISHED"])
        self.assertEqual(contract["candidate"]["release"], CANDIDATE)
        self.assertEqual(contract["candidate"]["python_sdk"], "0.1.5rc1")
        self.assertEqual(contract["candidate"]["npm_packages"], "0.1.5-rc.1")
        component_ids = [item["id"] for item in contract["required_components"]]
        self.assertEqual(len(component_ids), len(set(component_ids)))
        self.assertEqual(set(component_ids), set(EXPECTED_COMPONENTS))
        for item in contract["required_components"]:
            self.assertEqual(item["expected"], EXPECTED_COMPONENTS[item["id"]], item["id"])
            self.assertTrue(item["description"], item["id"])
            self.assertTrue(item["derived_from"], item["id"])
        self.assertEqual(contract["r3_permitted_scope_expected"], BOUNDED_R3_SCOPE)

    def test_constraints_keep_r3_bounded_and_production_unchanged(self):
        constraints = _contract()["constraints"]
        self.assertEqual(constraints["r3_resume"], "NO")
        self.assertEqual(constraints["r3_bounded_scope"], BOUNDED_R3_SCOPE)
        self.assertEqual(constraints["native_independent_child_resume"], "NOT_IMPLEMENTED")
        self.assertEqual(constraints["production_deployment"], "none")
        self.assertFalse(constraints["release_or_tag_created"])
        self.assertFalse(constraints["phase_100_resumed"])
        self.assertFalse(constraints["zero_ten_started"])
        self.assertFalse(constraints["b1_b2_downgraded"])

    def test_contract_source_artifacts_are_closed_and_exist(self):
        contract = _contract()
        ids = [item["id"] for item in contract["source_artifacts"]]
        self.assertEqual(len(ids), len(set(ids)))
        for artifact in contract["source_artifacts"]:
            self.assertTrue((ROOT / artifact["path"]).is_file(), artifact["path"])


class ObserverDerivationTests(unittest.TestCase):
    def test_known_good_fixture_is_established(self):
        observer = _load_observer()
        contract = _contract()
        sources, assessment = observer.good_fixture(contract)
        verdict = observer.compute_assessment(contract, sources, assessment)
        self.assertTrue(verdict["all_pass"], verdict["failures"] + verdict["honesty_failures"])
        self.assertTrue(verdict["established"])
        self.assertTrue(verdict["format_valid"])
        self.assertTrue(verdict["honest"])
        self.assertEqual(verdict["decision"], "SUPERSEDING_ASSESSMENT_ESTABLISHED")
        self.assertEqual(verdict["derived_components"], EXPECTED_COMPONENTS)
        self.assertEqual(verdict["derived_r3_permitted_scope"], BOUNDED_R3_SCOPE)

    def test_overclaiming_native_child_resume_is_rejected(self):
        observer = _load_observer()
        contract = _contract()
        sources, assessment = observer.good_fixture(contract)
        fabricated = copy.deepcopy(assessment)
        fabricated["components"]["native_independent_child_resume"] = "IMPLEMENTED"
        verdict = observer.compute_assessment(contract, sources, fabricated)
        self.assertFalse(verdict["all_pass"])
        self.assertTrue(any("native_independent_child_resume" in failure
                            for failure in verdict["honesty_failures"]))

    def test_blocked_external_capability_reported_as_pass_is_rejected(self):
        observer = _load_observer()
        contract = _contract()
        sources, assessment = observer.good_fixture(contract)
        for component in ("b1_subagent_child_crash", "b2_subagent_byq_adapter_restart"):
            fabricated = copy.deepcopy(assessment)
            fabricated["components"][component] = "PASS"
            verdict = observer.compute_assessment(contract, sources, fabricated)
            self.assertFalse(verdict["all_pass"], component)
            self.assertTrue(any(component in failure for failure in verdict["honesty_failures"]),
                            component)

    def test_rewritten_historical_verdict_and_full_r3_resume_are_rejected(self):
        observer = _load_observer()
        contract = _contract()
        sources, assessment = observer.good_fixture(contract)
        # Claiming R3 full resume is rejected.
        fabricated = copy.deepcopy(assessment)
        fabricated["components"]["r3_resume"] = "YES"
        verdict = observer.compute_assessment(contract, sources, fabricated)
        self.assertFalse(verdict["all_pass"])
        # Widening or dropping the bounded R3 scope is rejected.
        for scope in (BOUNDED_R3_SCOPE + ["full_runtime_continuity"], []):
            fabricated = copy.deepcopy(assessment)
            fabricated["r3_permitted_scope"] = scope
            verdict = observer.compute_assessment(contract, sources, fabricated)
            self.assertFalse(verdict["all_pass"], scope)
        # Rewriting the historical D15-G verdict is rejected.
        rewritten = copy.deepcopy(sources)
        rewritten["d15_g_verdict"] = {"verdict": "GO", "all_pass": True, "derived_blockers": []}
        rewritten["d15_g_capability_matrix"] = {"primary_named_blockers": []}
        verdict = observer.compute_assessment(contract, rewritten, assessment)
        self.assertFalse(verdict["all_pass"])
        self.assertFalse(verdict["established"])

    def test_self_declared_fields_and_candidate_mismatch_are_rejected(self):
        observer = _load_observer()
        contract = _contract()
        sources, assessment = observer.good_fixture(contract)
        for field in ("all_pass", "assessment_established", "assessment_valid",
                      "coverage", "native_child_resume_implemented_in_memory",
                      "production_deployed"):
            fabricated = copy.deepcopy(assessment)
            fabricated[field] = True
            verdict = observer.compute_assessment(contract, sources, fabricated)
            self.assertFalse(verdict["all_pass"], field)
            self.assertTrue(any("may not declare" in failure for failure in verdict["failures"]),
                            field)
        mismatched = copy.deepcopy(assessment)
        mismatched["candidate"] = {"release": ROLLBACK}
        verdict = observer.compute_assessment(contract, sources, mismatched)
        self.assertFalse(verdict["all_pass"])

    def test_every_negative_control_is_rejected_and_pre_fix_defects_are_evidenced(self):
        observer = _load_observer()
        result = observer.selfcheck(_contract())
        self.assertTrue(result["all_controls_rejected"])
        self.assertTrue(result["known_good_fixture_all_pass"])
        self.assertEqual(result["known_good_fixture_decision"],
                         "SUPERSEDING_ASSESSMENT_ESTABLISHED")
        self.assertFalse([item for item in result["controls"] if item["fixed_all_pass"]])
        self.assertGreater(result["defect_targeting_pre_fix_passed_count"], 0)
        names = set(result["defect_targeting_pre_fix_passed"])
        for required in ("claim-b1-pass", "claim-b2-pass",
                         "claim-native-child-resume-implemented",
                         "claim-replacement-gate-pass-when-source-failed",
                         "claim-upgrade-pass-when-source-incoherent",
                         "rewrite-historical-d15-g", "claim-r3-resume-yes",
                         "widen-r3-scope", "self-declared-verdict"):
            self.assertIn(required, names, required)


class CommittedEvidenceTests(unittest.TestCase):
    def test_committed_verdict_is_established(self):
        verdict = json.loads((EVIDENCE / "verdict.v1.json").read_text(encoding="utf-8"))
        self.assertTrue(verdict["all_pass"])
        self.assertTrue(verdict["assessment_valid"])
        self.assertTrue(verdict["established"])
        self.assertTrue(verdict["format_valid"])
        self.assertTrue(verdict["honest"])
        self.assertEqual(verdict["decision"], "SUPERSEDING_ASSESSMENT_ESTABLISHED")
        self.assertEqual(verdict["derived_components"], EXPECTED_COMPONENTS)
        self.assertEqual(verdict["claimed_components"], verdict["derived_components"])
        self.assertEqual(verdict["derived_r3_permitted_scope"], BOUNDED_R3_SCOPE)
        self.assertEqual(verdict["r3_resume"], "NO")
        self.assertEqual(verdict["native_independent_child_resume"], "NOT_IMPLEMENTED")
        self.assertEqual(verdict["exit_code"], 0)

    def test_committed_assessment_claims_the_derived_state(self):
        assessment = _assessment()
        self.assertEqual(assessment["assessment_id"], "d15-superseding-assessment.v1")
        self.assertEqual(assessment["decision"], "SUPERSEDING_ASSESSMENT_ESTABLISHED")
        self.assertEqual(assessment["components"], EXPECTED_COMPONENTS)
        self.assertEqual(assessment["r3_permitted_scope"], BOUNDED_R3_SCOPE)
        self.assertEqual(assessment["constraints"]["r3_resume"], "NO")
        self.assertEqual(assessment["constraints"]["native_independent_child_resume"],
                         "NOT_IMPLEMENTED")

    def test_provenance_hashes_match_every_source_artifact(self):
        provenance = _provenance()
        entries = {item["path"]: item for item in provenance["artifacts"]}
        contract_paths = [item["path"] for item in _contract()["source_artifacts"]]
        self.assertEqual(set(entries), set(contract_paths))
        for path, entry in entries.items():
            self.assertEqual(entry["sha256"], _sha256(ROOT / path), path)
            self.assertRegex(entry["introduced_by"], r"^[0-9a-f]{40}$")

    def test_observer_verifies_committed_assessment_against_real_provenance(self):
        observer = _load_observer()
        contract = _contract()
        sources = observer.load_sources(contract, ROOT)
        verdict = observer.compute_assessment(contract, sources, _assessment(),
                                              provenance=_provenance(), root=ROOT)
        self.assertTrue(verdict["format_valid"], verdict["failures"])
        self.assertTrue(verdict["all_pass"], verdict["honesty_failures"])
        self.assertEqual(verdict["claimed_components"], verdict["derived_components"])
        self.assertEqual(verdict["derived_r3_permitted_scope"], BOUNDED_R3_SCOPE)

    def test_committed_negative_controls_evidence(self):
        controls = json.loads((EVIDENCE / "negative-controls.v1.json").read_text(encoding="utf-8"))
        self.assertTrue(controls["all_controls_rejected"])
        self.assertTrue(controls["known_good_fixture_all_pass"])
        self.assertFalse([item for item in controls["controls"] if item["fixed_all_pass"]])
        for required in ("claim-b1-pass", "claim-native-child-resume-implemented",
                         "rewrite-historical-d15-g", "claim-r3-resume-yes"):
            self.assertIn(required, controls["defect_targeting_pre_fix_passed"])

    def test_historical_d15_verdicts_are_referenced_not_rewritten(self):
        provenance = {item["path"]: item for item in _provenance()["artifacts"]}
        verdict = json.loads((ROOT / "docs/evidence/d15/d15-g/verdict.v1.json").read_text())
        self.assertEqual(verdict["verdict"], "NO_GO")
        self.assertFalse(verdict["all_pass"])
        self.assertEqual(sorted(verdict["derived_blockers"]), sorted(PRIMARY_BLOCKERS))
        for historical in ("docs/evidence/d15/d15-g/verdict.v1.json",
                           "docs/evidence/d15/d15-4/verdict.v2.json",
                           "docs/evidence/d15/d15-5/verdict.v1.json"):
            self.assertIn(historical, provenance)
            self.assertEqual(provenance[historical]["sha256"], _sha256(ROOT / historical))
        # The B3/B4 candidate overlays do not change the historical D15-5 status.
        d15_5 = json.loads((ROOT / "docs/evidence/d15/d15-5/verdict.v1.json").read_text())
        self.assertFalse(d15_5["all_pass"])


class BoundaryTests(unittest.TestCase):
    def _status(self) -> str:
        return (ROOT / "docs/roadmap/STATUS.md").read_text(encoding="utf-8")

    def test_status_markers_record_the_superseding_assessment(self):
        status = self._status()
        for marker in (
            "<!-- byq:v090-d15-superseding-assessment=established -->",
            "<!-- byq:v090-step5-b1-subagent-child-crash=blocked-external -->",
            "<!-- byq:v090-step5-b2-adapter-restart=blocked-external -->",
            "<!-- byq:build-revision=dsh-0.1.5rc1-post-u8.206 -->",
        ):
            self.assertIn(marker, status)
        self.assertIn("具名 D15 superseding assessment", status)
        self.assertIn("0.9 未关闭", status)

    def test_dsh_vocabulary_is_not_reported_as_native_child_resume(self):
        status = self._status()
        self.assertIn("原生独立 child 恢复", status)
        joined = status.replace("\n", "")
        # Guard against a future edit claiming the native independent child resume
        # is implemented.
        self.assertNotIn("原生独立 child resume 已实现", joined)

    def test_promotion_is_repository_default_only(self):
        deployment = json.loads((ROOT / "config/dsh/deployment.json").read_text(encoding="utf-8"))
        self.assertEqual(deployment["default_release"], CANDIDATE)
        self.assertEqual(deployment["candidate_releases"], [ROLLBACK])
        for candidate in Path(ROOT / "config").rglob("*.json"):
            text = candidate.read_text(encoding="utf-8", errors="ignore")
            if '"schema": "byq-release.v1"' in text or '"schema":"byq-release.v1"' in text:
                self.fail(f"unexpected committed release manifest: {candidate}")

    def test_build_revision_is_the_next_unused_id(self):
        from scripts.dsh import build_revision as builds
        self.assertEqual(builds.selected_build_id(CANDIDATE), CURRENT_BUILD_REVISION)
        self.assertTrue((ROOT / "config/dsh/builds" / f"{CURRENT_BUILD_REVISION}.json").is_file())
        dockerfile = (ROOT / "services/runtime-adapter/Dockerfile.post-u8-candidate").read_text()
        self.assertIn(CURRENT_BUILD_REVISION, dockerfile)

    def test_observer_cli_exit_code_is_zero_on_the_committed_assessment(self):
        result = subprocess.run(
            ["python3", str(OBSERVER),
             "--assessment", str(EVIDENCE / "assessment-input.v1.json"),
             "--provenance", str(EVIDENCE / "provenance.v1.json")],
            cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["all_pass"])
        self.assertEqual(payload["decision"], "SUPERSEDING_ASSESSMENT_ESTABLISHED")

    def test_adr_0084_is_accepted_and_scopes_the_reclassification(self):
        text = (ROOT / "docs/architecture/adr"
                / "ADR-0084-gate-classification-and-external-dependencies.md").read_text(
                    encoding="utf-8")
        self.assertIn("- Status: Accepted", text)
        self.assertIn("BYQ session failure containment and business recovery", text)
        for phrase in ("subagent-child-crash", "subagent-byq-adapter-restart", "BLOCKED_EXTERNAL"):
            self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
