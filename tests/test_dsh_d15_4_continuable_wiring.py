"""D15-4 candidate-specific continuable-wiring acceptance tests.

Covers the deterministic candidate profile wiring (candidate continuable vs
production one-shot), the fail-able observer (required BLOCKED/NOT_RUN gating,
contract-authoritative assertions, defect-targeting negative controls), the
committed truthfulness of the native observations/verdict and the real isolated
adapter-restart evidence. Runs under ``unittest`` (the architecture lane has no
pytest).

Set ``BYQ_D15_4_RUN_CONTINUABLE=1`` to additionally execute the real native
continuable probe (requires the pinned ``node_modules`` and a Node runtime).
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUBAGENT = ROOT / "scripts/d15/subagent"
OBSERVER = SUBAGENT / "continuable_wiring_observer.py"
CONTRACT = SUBAGENT / "continuable_wiring_contract.v1.json"
EVIDENCE = ROOT / "docs/evidence/d15/d15-4/continuable"
PROFILE = ROOT / "plugins/dsh-byq/profiles/dsh-0.1.5rc1-continuable"


def _load_observer():
    spec = importlib.util.spec_from_file_location("d15_4_continuable_observer", OBSERVER)
    module = importlib.util.module_from_spec(spec)
    sys.modules["d15_4_continuable_observer"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _contract():
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


class ContinuableWiringContractTests(unittest.TestCase):
    def test_contract_is_closed_and_versioned(self):
        contract = _contract()
        self.assertEqual(contract["schema_version"], "byq-d15-4-continuable-wiring-contract.v1")
        ids = [item["id"] for item in contract["required_scenarios"]]
        self.assertEqual(len(ids), len(set(ids)))
        for expected in ("delegate-result-shape", "child-id-persistence",
                         "settlement-exactly-once", "lease-linked-to-original-goal",
                         "no-orphan-after-parent-end", "adapter-restart-cold-resume",
                         "child-crash", "byq-compose-adapter-restart"):
            self.assertIn(expected, ids)
        optional = [item["id"] for item in contract["optional_scenarios"]]
        self.assertIn("host-reboot", optional)
        self.assertIn("child-run-fault", optional)
        self.assertTrue(set(optional).isdisjoint(ids))
        self.assertTrue(contract["required_coverage_gates_qualification"])
        self.assertTrue(contract["negatives_must_all_be_rejected"])
        self.assertEqual(contract["candidate"]["release"], "dsh-0.1.5rc1")
        self.assertEqual(contract["expected_candidate_wiring"]["provider"], "spawn")
        self.assertEqual(contract["expected_candidate_wiring"]["backgroundMode"], "continuable")
        self.assertIs(contract["expected_candidate_wiring"]["enableRunInBackground"], True)
        self.assertEqual(contract["expected_production_wiring"]["backgroundMode"], "one-shot")

    def test_candidate_wiring_is_continuable_and_production_is_unchanged(self):
        observer = _load_observer()
        wiring = observer.check_wiring(_contract())
        self.assertTrue(wiring["wiring_ok"], wiring["failures"])
        for delegate in _contract()["delegates"]:
            block = wiring["candidate_blocks"][delegate]
            self.assertEqual(block.get("provider"), "spawn")
            self.assertEqual(block.get("backgroundMode"), "continuable")
            self.assertEqual(block.get("enableRunInBackground"), "true")
            production = wiring["production_blocks"][delegate]
            self.assertEqual(production.get("backgroundMode"), "one-shot")
            self.assertEqual(production.get("enableRunInBackground"), "false")
        # Permission/MCP boundaries are identical between the two profiles.
        self.assertEqual(wiring["candidate_allowlists"], wiring["production_allowlists"])
        self.assertTrue(wiring["candidate_allowlists"])

    def test_committed_profiles_are_generated_and_fresh(self):
        for command in ("check", "check-continuable"):
            result = subprocess.run(
                [sys.executable, "scripts/dsh/candidate_profile.py", command],
                cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr[-800:])
        self.assertTrue((PROFILE / "byq-product.patch.yml").is_file())
        identity = json.loads((PROFILE / "byq-product.identity.json").read_text(encoding="utf-8"))
        self.assertEqual(identity["delegate_background_mode"], "continuable")
        self.assertTrue(identity["continuable_wiring"]["isolated_candidate_only"])

    def test_fully_qualified_fixture_passes_and_required_blocked_fails(self):
        observer = _load_observer()
        contract = _contract()
        qualified = observer.valid_fixture(contract)
        verdict = observer.compute_verdict(contract, qualified)
        self.assertTrue(verdict["all_pass"], verdict["failures"])
        self.assertTrue(verdict["format_valid"])
        self.assertTrue(verdict["wiring_ok"])

        blocked = observer.valid_fixture(contract)
        for scenario in blocked["scenarios"]:
            if scenario["id"] in {"child-crash", "byq-compose-adapter-restart"}:
                scenario["result"] = "BLOCKED"
                scenario["not_run_reason"] = "in-process provider / no BYQ child-resume surface"
        verdict = observer.compute_verdict(contract, blocked)
        self.assertFalse(verdict["all_pass"])
        joined = " ".join(verdict["reason_uncovered"])
        self.assertIn("child-crash", joined)
        self.assertIn("byq-compose-adapter-restart", joined)

    def test_every_negative_control_fails_and_pre_fix_defects_are_evidenced(self):
        observer = _load_observer()
        result = observer.selfcheck(_contract())
        self.assertTrue(result["all_controls_pass"])
        self.assertTrue(result["known_good_fixture_all_pass"])
        self.assertFalse([item for item in result["controls"] if item["fixed_all_pass"]])
        self.assertGreater(result["defect_targeting_pre_fix_passed_count"], 0)


class ContinuableWiringEvidenceTests(unittest.TestCase):
    def test_committed_verdict_is_truthful_and_not_a_full_pass(self):
        verdict = json.loads((EVIDENCE / "verdict.v1.json").read_text(encoding="utf-8"))
        self.assertFalse(verdict["all_pass"])
        self.assertTrue(verdict["format_valid"])
        self.assertTrue(verdict["wiring_ok"])
        coverage = verdict["required_coverage"]
        for scenario_id in ("delegate-result-shape", "child-id-persistence",
                            "settlement-exactly-once", "lease-linked-to-original-goal",
                            "no-orphan-after-parent-end", "adapter-restart-cold-resume"):
            self.assertEqual(coverage[scenario_id], "PASS", scenario_id)
        self.assertEqual(coverage["child-crash"], "BLOCKED")
        self.assertEqual(coverage["byq-compose-adapter-restart"], "BLOCKED")
        # The two required blocked items gate the verdict.
        joined = " ".join(verdict["reason_uncovered"])
        self.assertIn("child-crash", joined)
        self.assertIn("byq-compose-adapter-restart", joined)

    def test_native_observations_are_real_and_separate_cold_resume_from_child_crash(self):
        observations = json.loads(
            (EVIDENCE / "continuable-observations.v1.json").read_text(encoding="utf-8"))
        self.assertEqual(observations["evidence_class"], "native-runtime-isolated")
        self.assertIs(observations["llm"]["real_llm_quality"], False)
        by_id = {item["id"]: item for item in observations["scenarios"]}
        resume = by_id["adapter-restart-cold-resume"]["observation"]
        self.assertTrue(resume["newOsProcess"])
        self.assertNotEqual(resume["generationAProcessId"], resume["generationBProcessId"])
        self.assertTrue(resume["sameChildId"])
        self.assertTrue(resume["sequenceContiguous"])
        self.assertEqual(resume["resumedSettlementCount"], 1)
        self.assertFalse(resume["duplicateSettlement"])
        # child-crash is a DIFFERENT capability and is honestly BLOCKED.
        self.assertEqual(by_id["child-crash"]["result"], "BLOCKED")
        self.assertTrue(by_id["child-crash"]["not_run_reason"])
        self.assertEqual(by_id["host-reboot"]["result"], "NOT_RUN")
        # Every same-class delegate was exercised.
        per_tool = observations["per_tool"]
        self.assertEqual(len(per_tool), len(observations["delegates"]))
        for item in per_tool:
            self.assertEqual(item["generationA"]["resultKind"], "continuable")
            self.assertEqual(item["generationA"]["startContinuableCalls"], 1)
            self.assertEqual(item["generationA"]["provider"], "spawn")
            self.assertEqual(item["generationA"]["descriptorMode"], "continuable")
            self.assertTrue(item["generationB"]["sameChildId"])
            self.assertEqual(item["generationB"]["resumedSettlementCount"], 1)

    def test_adapter_restart_evidence_is_truthful_and_byq_surface_is_absent(self):
        adapter = json.loads(
            (EVIDENCE / "continuable-adapter-restart.v1.json").read_text(encoding="utf-8"))
        self.assertEqual(adapter["generation_a"]["status"], "PASS")
        self.assertEqual(adapter["generation_a"]["delegate_result"]["kind"], "continuable")
        self.assertTrue(adapter["generation_a"]["child_session_files"])
        self.assertIn("subagent.started", adapter["generation_a"]["notification_methods"])
        self.assertEqual(adapter["generation_b"]["status"], "BLOCKED")
        self.assertTrue(adapter["generation_b"]["container_restart_observed"])
        self.assertEqual(adapter["generation_b"]["child_resumed_via_byq_surface"], False)
        self.assertFalse(adapter["generation_b"]["child_has_surface"])
        self.assertEqual(adapter["generation_b"]["sdk_child_surfaces"], [])
        self.assertEqual(adapter["generation_b"]["root_only_surfaces"], ["resume_session"])
        self.assertTrue(adapter["generation_b"]["child_persisted_same_id"])
        self.assertEqual(adapter["r3_resume"], "NO")
        self.assertEqual(adapter["independent_child_process"], "BLOCKED")
        self.assertIs(adapter["isolation"]["production_selector_changed"], False)

    def test_wiring_evidence_matches_the_committed_profiles(self):
        wiring = json.loads((EVIDENCE / "continuable-wiring.v1.json").read_text(encoding="utf-8"))
        self.assertTrue(wiring["wiring_ok"])
        self.assertEqual(wiring["production_patch_regenerated"]["returncode"], 0)
        self.assertEqual(len(wiring["candidate_blocks"]), len(_contract()["delegates"]))

    def test_negative_controls_evidence_is_recorded(self):
        controls = json.loads((EVIDENCE / "negative-controls.v1.json").read_text(encoding="utf-8"))
        self.assertTrue(controls["all_controls_pass"])
        self.assertTrue(controls["known_good_fixture_all_pass"])
        self.assertGreater(controls["defect_targeting_pre_fix_passed_count"], 0)


@unittest.skipUnless(os.environ.get("BYQ_D15_4_RUN_CONTINUABLE") == "1",
                     "set BYQ_D15_4_RUN_CONTINUABLE=1 to run the real native probe")
class ContinuableWiringNativeIntegrationTests(unittest.TestCase):
    def test_native_probe_reaches_continuable_for_every_delegate(self):
        if shutil.which("node") is None:
            self.skipTest("node not available")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "continuable-observations.v1.json"
            result = subprocess.run(
                ["node", "continuable_wiring_probe.mjs", "run", "--out", str(out)],
                cwd=SUBAGENT, capture_output=True, text=True, timeout=600)
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])
            observations = json.loads(out.read_text(encoding="utf-8"))
        by_id = {item["id"]: item["result"] for item in observations["scenarios"]}
        for scenario_id in ("delegate-result-shape", "child-id-persistence",
                            "settlement-exactly-once", "lease-linked-to-original-goal",
                            "no-orphan-after-parent-end", "adapter-restart-cold-resume"):
            self.assertEqual(by_id[scenario_id], "PASS", scenario_id)
        self.assertEqual(by_id["child-crash"], "BLOCKED")
        self.assertTrue(observations["runtime_root_cleaned"])


if __name__ == "__main__":
    unittest.main()
