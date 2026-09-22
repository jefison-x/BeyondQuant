"""0.9 final development closeout acceptance tests (machine-readable final matrix).

Covers the fail-able, machine-readable final closeout matrix and observer:

* every 0.9 development-required item is derived from the original merged
  evidence (not from a PASS label);
* the ADR-0084 replacement gate (BYQ session failure containment and business
  recovery) and the coherent DSH ``0.1.5-rc.1`` repository default upgrade pass;
* B1/B2 remain ``BLOCKED_EXTERNAL`` and only limit native independent child
  resume; historical D15-G stays ``NO_GO``; ``R3_RESUME = NO``;
* the repository default is not a production deployment, no release/tag is
  created, Phase 100 stays frozen and 0.10 is not started;
* the next state is the maintainer testing and 0.9.x minor window.

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
CLOSEOUT = ROOT / "scripts/v090/final_closeout"
OBSERVER = CLOSEOUT / "observer.py"
CONTRACT = CLOSEOUT / "contract.v1.json"
EVIDENCE = ROOT / "docs/evidence/v090-final-closeout"
SUPERSEDING = ROOT / "scripts/d15/superseding_assessment"
SUPERSEDING_CONTRACT = SUPERSEDING / "contract.v1.json"

CURRENT_BUILD_REVISION = "dsh-0.1.5rc1-post-u8.210"
CANDIDATE = "dsh-0.1.5rc1"
ROLLBACK = "dsh-0.1.2rc1"

EXPECTED_ITEMS = {
    "closeout_audit": "COMPLETE",
    "f2_unknown_result_reconciliation": "COVERED",
    "full_interface_audit": "COMPLETE",
    "composite_research_fault_regression": "PASS_AS_SCOPED",
    "adr_0082_0083_decision": "RECORDED_ACCEPTED",
    "containment_business_recovery_gate": "PASS",
    "coherent_dsh_default_upgrade": "PASS",
    "d15_superseding_assessment": "ESTABLISHED",
    "historical_d15_g": "NO_GO_PRESERVED",
    "b1_subagent_child_crash": "BLOCKED_EXTERNAL",
    "b2_subagent_byq_adapter_restart": "BLOCKED_EXTERNAL",
    "b3_terminal_adapter_restart": "PASS_CANDIDATE",
    "b4_terminal_dsh_runtime_restart": "PASS_CANDIDATE",
    "native_independent_child_resume": "NOT_IMPLEMENTED",
    "r3_resume": "NO",
}
EXPECTED_CONSTRAINTS = {
    "repository_default_release": CANDIDATE,
    "rollback_candidate": ROLLBACK,
    "production_deployment": "none",
    "release_or_tag_created": False,
    "phase_100_resumed": False,
    "zero_ten_started": False,
    "r3_resume": "NO",
    "b1_b2_downgraded": False,
    "next_state": "maintainer-testing-and-0.9x-window",
    "build_revision": CURRENT_BUILD_REVISION,
}
SCOPED_LIMITATIONS = [
    "b1_subagent_child_crash",
    "b2_subagent_byq_adapter_restart",
    "native_independent_child_resume",
    "r3_resume",
]
PRIMARY_BLOCKERS = (
    "subagent-child-crash",
    "subagent-byq-adapter-restart",
    "terminal-adapter-restart",
    "terminal-dsh-runtime-restart",
)


def _load_observer():
    spec = importlib.util.spec_from_file_location("v090_final_closeout_observer", OBSERVER)
    module = importlib.util.module_from_spec(spec)
    sys.modules["v090_final_closeout_observer"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _observer_module():
    return _load_observer()


def _superseding_module():
    path = SUPERSEDING / "observer.py"
    spec = importlib.util.spec_from_file_location("v090_closeout_superseding", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["v090_closeout_superseding"] = module
    spec.loader.exec_module(module)
    return module


def _contract() -> dict:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def _superseding_contract() -> dict:
    return json.loads(SUPERSEDING_CONTRACT.read_text(encoding="utf-8"))


def _assessment() -> dict:
    return json.loads((EVIDENCE / "assessment-input.v1.json").read_text(encoding="utf-8"))


def _provenance() -> dict:
    return json.loads((EVIDENCE / "provenance.v1.json").read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


class ContractTests(unittest.TestCase):
    def test_contract_is_closed_and_versioned(self):
        contract = _contract()
        self.assertEqual(contract["schema_version"], "byq-v090-final-closeout-contract.v1")
        self.assertEqual(contract["assessment_id"], "v090-final-closeout.v1")
        self.assertEqual(
            contract["decision_vocabulary"],
            ["V090_DEVELOPMENT_CLOSEOUT_COMPLETE", "V090_DEVELOPMENT_CLOSEOUT_BLOCKED"])
        component_ids = [item["id"] for item in contract["required_items"]]
        self.assertEqual(len(component_ids), len(set(component_ids)))
        self.assertEqual(set(component_ids), set(EXPECTED_ITEMS))
        for item in contract["required_items"]:
            self.assertEqual(item["expected"], EXPECTED_ITEMS[item["id"]], item["id"])
            self.assertTrue(item["derived_from"], item["id"])
        self.assertEqual(contract["constraint_expected"], EXPECTED_CONSTRAINTS)
        self.assertEqual(contract["scoped_limitations_expected"], SCOPED_LIMITATIONS)
        self.assertEqual(
            contract["release_gate"]["formal_0_9_0_release_manifest"], "OPEN_NOT_ATTEMPTED")

    def test_contract_source_artifacts_are_closed_and_exist(self):
        contract = _contract()
        ids = [item["id"] for item in contract["source_artifacts"]]
        self.assertEqual(len(ids), len(set(ids)))
        for artifact in contract["source_artifacts"]:
            self.assertTrue((ROOT / artifact["path"]).is_file(), artifact["path"])

    def test_contract_forbids_self_declared_fields(self):
        forbidden = set(_contract()["forbidden_assessment_fields"])
        for field in ("all_pass", "assessment_valid", "established", "coverage",
                      "production_deployed", "phase_100_resumed", "zero_ten_started"):
            self.assertIn(field, forbidden)


class ObserverDerivationTests(unittest.TestCase):
    def test_known_good_fixture_completes(self):
        observer = _observer_module()
        superseding = _superseding_module()
        contract = _contract()
        superseding_contract = _superseding_contract()
        sources, live, ctx, assessment = observer.good_fixture(
            contract, superseding_contract, superseding)
        verdict = observer.compute_matrix(contract, sources, assessment,
                                          superseding_ctx=ctx, live=live)
        self.assertTrue(verdict["all_pass"], verdict["failures"] + verdict["honesty_failures"])
        self.assertTrue(verdict["complete"])
        self.assertEqual(verdict["decision"], "V090_DEVELOPMENT_CLOSEOUT_COMPLETE")
        self.assertEqual(verdict["derived_items"], EXPECTED_ITEMS)

    def test_overclaiming_blocked_external_and_native_resume_is_rejected(self):
        observer = _observer_module()
        superseding = _superseding_module()
        contract = _contract()
        sources, live, ctx, assessment = observer.good_fixture(
            contract, _superseding_contract(), superseding)
        for component, value in (("b1_subagent_child_crash", "PASS"),
                                 ("b2_subagent_byq_adapter_restart", "PASS"),
                                 ("native_independent_child_resume", "IMPLEMENTED"),
                                 ("r3_resume", "YES"),
                                 ("historical_d15_g", "PASS")):
            fabricated = copy.deepcopy(assessment)
            fabricated["items"][component] = value
            verdict = observer.compute_matrix(contract, sources, fabricated,
                                              superseding_ctx=ctx, live=live)
            self.assertFalse(verdict["all_pass"], component)
            self.assertTrue(any(component in failure for failure in verdict["honesty_failures"]),
                            component)

    def test_boundary_overclaims_are_rejected(self):
        observer = _observer_module()
        superseding = _superseding_module()
        contract = _contract()
        sources, live, ctx, assessment = observer.good_fixture(
            contract, _superseding_contract(), superseding)
        for key, value in EXPECTED_CONSTRAINTS.items():
            if isinstance(value, bool):
                fabricated_value = not value
            elif value == CANDIDATE:
                fabricated_value = ROLLBACK
            elif value == "NO":
                fabricated_value = "YES"
            else:
                fabricated_value = "wrong"
            fabricated = copy.deepcopy(assessment)
            fabricated["constraints"][key] = fabricated_value
            verdict = observer.compute_matrix(contract, sources, fabricated,
                                              superseding_ctx=ctx, live=live)
            self.assertFalse(verdict["all_pass"], key)

    def test_self_declared_fields_and_closed_set_are_rejected(self):
        observer = _observer_module()
        superseding = _superseding_module()
        contract = _contract()
        sources, live, ctx, assessment = observer.good_fixture(
            contract, _superseding_contract(), superseding)
        for field in ("all_pass", "assessment_valid", "established", "coverage"):
            fabricated = copy.deepcopy(assessment)
            fabricated[field] = True
            verdict = observer.compute_matrix(contract, sources, fabricated,
                                              superseding_ctx=ctx, live=live)
            self.assertFalse(verdict["all_pass"], field)
            self.assertTrue(any("may not declare" in failure for failure in verdict["failures"]),
                            field)
        dropped = copy.deepcopy(assessment)
        dropped["items"].pop("r3_resume")
        self.assertFalse(observer.compute_matrix(contract, sources, dropped,
                                                 superseding_ctx=ctx, live=live)["all_pass"])

    def test_every_negative_control_is_rejected_and_pre_fix_defects_are_evidenced(self):
        observer = _observer_module()
        result = observer.selfcheck(_contract(), _superseding_contract(), _superseding_module())
        self.assertTrue(result["all_controls_rejected"])
        self.assertTrue(result["known_good_fixture_all_pass"])
        self.assertEqual(result["known_good_fixture_decision"],
                         "V090_DEVELOPMENT_CLOSEOUT_COMPLETE")
        self.assertFalse([item for item in result["controls"] if item["fixed_all_pass"]])
        self.assertGreater(result["defect_targeting_pre_fix_passed_count"], 0)
        names = set(result["defect_targeting_pre_fix_passed"])
        for required in ("claim-b1-pass", "claim-b2-pass",
                         "claim-native-child-resume-implemented",
                         "claim-r3-resume-yes", "claim-composite-all-pass",
                         "claim-full-interface-complete-when-incomplete",
                         "claim-d15-superseding-established",
                         "rewrite-historical-d15-g",
                         "claim-production-deployment", "claim-release-tag-created",
                         "claim-phase-100-resumed", "claim-zero-ten-started",
                         "wrong-next-state", "wrong-build-revision",
                         "stale-current-next-marker-at-top"):
            self.assertIn(required, names, required)

    def test_stale_current_next_marker_is_rejected_at_top_but_allowed_in_body(self):
        observer = _observer_module()
        superseding = _superseding_module()
        contract = _contract()
        sources, live, ctx, assessment = observer.good_fixture(
            contract, _superseding_contract(), superseding)
        stale = "<!-- byq:session-failure-containment-next=v090-final-development-closeout -->"
        # Top region (no authority table yet) -> structural rejection.
        top_sources = copy.deepcopy(sources)
        top_sources["status_md"] = sources["status_md"] + stale + "\n"
        verdict = observer.compute_matrix(contract, top_sources, assessment,
                                          superseding_ctx=ctx, live=live)
        self.assertFalse(verdict["format_valid"])
        self.assertTrue(any("stale current-state marker" in failure
                            for failure in verdict["failures"]))
        # Historical body below the authority table -> accepted.
        body_sources = copy.deepcopy(sources)
        body_sources["status_md"] = (
            sources["status_md"] + "| 轨道 | 当前步骤 |\n| x |\n" + stale + "\n")
        self.assertNotIn(stale, observer._status_top(body_sources["status_md"]))
        verdict = observer.compute_matrix(contract, body_sources, assessment,
                                          superseding_ctx=ctx, live=live)
        self.assertTrue(verdict["all_pass"],
                        verdict["failures"] + verdict["honesty_failures"])


class CommittedEvidenceTests(unittest.TestCase):
    def test_committed_verdict_is_complete(self):
        verdict = json.loads((EVIDENCE / "verdict.v1.json").read_text(encoding="utf-8"))
        self.assertTrue(verdict["all_pass"])
        self.assertTrue(verdict["assessment_valid"])
        self.assertTrue(verdict["complete"])
        self.assertTrue(verdict["format_valid"])
        self.assertTrue(verdict["honest"])
        self.assertEqual(verdict["decision"], "V090_DEVELOPMENT_CLOSEOUT_COMPLETE")
        self.assertEqual(verdict["derived_items"], EXPECTED_ITEMS)
        self.assertEqual(verdict["claimed_items"], verdict["derived_items"])
        self.assertEqual(verdict["derived_constraints"], EXPECTED_CONSTRAINTS)
        self.assertEqual(verdict["scoped_limitations"], SCOPED_LIMITATIONS)
        self.assertEqual(verdict["release_gate"]["formal_0_9_0_release_manifest"],
                         "OPEN_NOT_ATTEMPTED")
        self.assertEqual(verdict["exit_code"], 0)

    def test_committed_assessment_claims_the_derived_state(self):
        assessment = _assessment()
        self.assertEqual(assessment["assessment_id"], "v090-final-closeout.v1")
        self.assertEqual(assessment["decision"], "V090_DEVELOPMENT_CLOSEOUT_COMPLETE")
        self.assertEqual(assessment["items"], EXPECTED_ITEMS)
        self.assertEqual(assessment["constraints"], EXPECTED_CONSTRAINTS)
        self.assertEqual(assessment["scoped_limitations"], SCOPED_LIMITATIONS)

    def test_provenance_hashes_match_every_source_artifact(self):
        provenance = _provenance()
        entries = {item["path"]: item for item in provenance["artifacts"]}
        contract_paths = [item["path"] for item in _contract()["source_artifacts"]]
        self.assertEqual(set(entries), set(contract_paths))
        for path, entry in entries.items():
            self.assertEqual(entry["sha256"], _sha256(ROOT / path), path)
            self.assertRegex(entry["introduced_by"], r"^[0-9a-f]{40}$")

    def test_observer_verifies_committed_assessment_against_real_provenance(self):
        observer = _observer_module()
        module = observer.load_superseding_module(ROOT)
        contract = _contract()
        sources = observer.load_sources(contract, ROOT)
        live = observer.gather_live(ROOT)
        ctx = observer.build_superseding_context(contract, sources, ROOT)
        verdict = observer.compute_matrix(contract, sources, _assessment(),
                                          superseding_ctx=ctx, live=live,
                                          provenance=_provenance(), root=ROOT)
        self.assertTrue(verdict["format_valid"], verdict["failures"])
        self.assertTrue(verdict["all_pass"], verdict["honesty_failures"])
        self.assertEqual(verdict["claimed_items"], verdict["derived_items"])
        self.assertTrue(module)  # superseding module loads

    def test_committed_negative_controls_evidence(self):
        controls = json.loads((EVIDENCE / "negative-controls.v1.json").read_text(encoding="utf-8"))
        self.assertTrue(controls["all_controls_rejected"])
        self.assertTrue(controls["known_good_fixture_all_pass"])
        self.assertFalse([item for item in controls["controls"] if item["fixed_all_pass"]])
        for required in ("claim-b1-pass", "claim-native-child-resume-implemented",
                         "rewrite-historical-d15-g", "claim-r3-resume-yes"):
            self.assertIn(required, controls["defect_targeting_pre_fix_passed"])

    def test_interface_audit_snapshot_is_complete(self):
        audit = json.loads((EVIDENCE / "interface-audit.v1.json").read_text(encoding="utf-8"))
        self.assertTrue(audit["complete"])
        self.assertEqual(audit["discovered"], audit["reviewed"])
        self.assertEqual(audit["reviewed"], audit["verified"])
        self.assertEqual(audit["missing"], 0)
        self.assertEqual(audit["stale"], 0)
        self.assertEqual(audit["fake_pass"], 0)

    def test_committed_interface_snapshot_matches_the_live_auditor(self):
        observer = _observer_module()
        contract = _contract()
        snapshot = json.loads(
            (ROOT / contract["interface_audit_snapshot_path"]).read_text(encoding="utf-8"))
        live = observer.gather_live(ROOT)["interface_audit"]
        for key in ("discovered", "reviewed", "verified", "missing", "stale",
                    "fake_pass", "complete"):
            self.assertEqual(snapshot[key], live[key], key)

    def test_historical_d15_verdicts_are_referenced_not_rewritten(self):
        verdict = json.loads((ROOT / "docs/evidence/d15/d15-g/verdict.v1.json").read_text())
        self.assertEqual(verdict["verdict"], "NO_GO")
        self.assertFalse(verdict["all_pass"])
        self.assertEqual(sorted(verdict["derived_blockers"]), sorted(PRIMARY_BLOCKERS))
        d15_5 = json.loads((ROOT / "docs/evidence/d15/d15-5/verdict.v1.json").read_text())
        self.assertFalse(d15_5["all_pass"])


class BoundaryTests(unittest.TestCase):
    def _status(self) -> str:
        return (ROOT / "docs/roadmap/STATUS.md").read_text(encoding="utf-8")

    def test_status_markers_record_the_final_closeout(self):
        status = self._status()
        for marker in (
            "<!-- byq:v090-final-closeout=complete -->",
            "<!-- byq:v090-development-closeout=complete -->",
            "<!-- byq:v090-next=maintainer-testing-and-0.9x-window -->",
            "<!-- byq:session-failure-containment=real-recovery-acceptance-passed -->",
            "<!-- byq:phase-100-p100-c=paused-not-delivery -->",
            "<!-- byq:phase-100-slices-frozen=P100-C,P100-D,P100-E -->",
            "<!-- byq:v090-dsh-default-upgrade=promoted -->",
            "<!-- byq:v090-d15-superseding-assessment=established -->",
            f"<!-- byq:build-revision={CURRENT_BUILD_REVISION} -->",
        ):
            self.assertIn(marker, status)
        for stale in ("<!-- byq:session-failure-containment=in-progress-blocked-internal -->",
                      "<!-- byq:v090-closeout-audit=active -->",
                      "<!-- byq:v090-full-interface-rebaseline=active -->",
                      "<!-- byq:zero-ten=started -->"):
            self.assertNotIn(stale, status)
        # The superseded "next" marker may survive only in the historical body,
        # never in the current-state (top) region.
        top = status.split("| 轨道 | 当前步骤 |")[0]
        self.assertNotIn("<!-- byq:session-failure-containment-next=", top)
        self.assertIn("<!-- byq:session-failure-containment-next=", status)
        self.assertEqual(
            [line for line in top.splitlines() if line.startswith("<!-- byq:v090-next=")],
            ["<!-- byq:v090-next=maintainer-testing-and-0.9x-window -->"])

    def test_status_authority_table_records_the_next_state(self):
        lines = self._status().splitlines()
        header = next(i for i, line in enumerate(lines) if line.startswith("| 轨道 |"))
        table_lines = []
        index = header
        while index < len(lines) and lines[index].startswith("|"):
            table_lines.append(lines[index])
            index += 1
        table = "\n".join(table_lines)
        self.assertIn("维护者测试与 0.9.x 小版本", table)
        self.assertIn("v090-final-closeout=complete", table)
        self.assertIn("Phase 100 **仍 `PAUSED`**", table)
        self.assertIn("恢复未授权", table)
        for token in ("IN_PROGRESS", "BLOCKED_INTERNAL"):
            self.assertNotIn(token, table, token)

    def test_promotion_is_repository_default_only_and_not_a_deployment(self):
        deployment = json.loads((ROOT / "config/dsh/deployment.json").read_text(encoding="utf-8"))
        self.assertEqual(deployment["default_release"], CANDIDATE)
        self.assertEqual(deployment["candidate_releases"], [ROLLBACK])
        upgrade = json.loads(
            (ROOT / "docs/evidence/v090-dsh-015rc1-default-upgrade/default-upgrade.v1.json")
            .read_text(encoding="utf-8"))
        self.assertIn("production deployment", upgrade["not_claimed"])
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
        self.assertTrue(payload["complete"])
        self.assertEqual(payload["decision"], "V090_DEVELOPMENT_CLOSEOUT_COMPLETE")

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
