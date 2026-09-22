"""0.9 strict-order step-5 slice 1: `subagent-child-crash` remediation acceptance tests.

These tests assert the truthfulness of the committed BLOCKED evidence and the
fail-ability of the observer. They do not implement anything: no provider, no
BYQ child-resume bridge, no production selector change, no deployment/tag/release.

Runs under ``unittest`` (the architecture lane has no pytest).

Set ``BYQ_V090_D15_CHILD_PROVIDER_RUN_NATIVE=1`` to additionally execute the real
discovery probe (requires ``npm ci`` in ``scripts/d15/subagent`` and Node).
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
OBSERVER = SUBAGENT / "child_provider_remediation_observer.py"
CONTRACT = SUBAGENT / "child_provider_remediation_contract.v1.json"
PROBE = SUBAGENT / "child_provider_discovery.mjs"
EVIDENCE = ROOT / "docs/evidence/v090-d15-child-provider-remediation"
DISCOVERY = EVIDENCE / "capability-discovery.v1.json"
VERDICT = EVIDENCE / "verdict.v1.json"
BLOCKED = EVIDENCE / "external-blocked.v1.json"
CONTROLS = EVIDENCE / "negative-controls.v1.json"


def _load_observer():
    spec = importlib.util.spec_from_file_location("v090_d15_child_observer", OBSERVER)
    module = importlib.util.module_from_spec(spec)
    sys.modules["v090_d15_child_observer"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _contract():
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


class ContractTests(unittest.TestCase):
    def test_contract_names_the_external_capability(self):
        contract = _contract()
        self.assertEqual(contract["schema_version"],
                         "byq-v090-d15-child-provider-remediation-contract.v1")
        self.assertEqual(contract["blocker"], "subagent-child-crash")
        self.assertEqual(contract["owner_node"], "d15-4-child-provider-remediation")
        self.assertFalse(contract["required_capability"]["available_in_0_1_5_rc1"])
        ids = [item["name"] for item in contract["required_providers"]]
        self.assertEqual(sorted(ids), sorted(["spawn", "fork", "acp", "codex", "claude-code"]))
        for forbidden in ("byq-child-resume-bridge", "same-process-provider",
                          "owning-process-sigkill", "label-only-pass"):
            self.assertIn(forbidden, contract["forbidden_substitutions"])


class ObserverFailAbilityTests(unittest.TestCase):
    def test_known_good_fixture_passes_and_blocked_fixture_fails(self):
        observer = _load_observer()
        contract = _contract()
        qualified = observer._fully_qualified_fixture(contract)
        verdict = observer.compute_verdict(contract, qualified)
        self.assertTrue(verdict["all_pass"], verdict["failures"])
        self.assertTrue(verdict["format_valid"])
        self.assertEqual(verdict["result"], "PASS")

        blocked = observer.valid_fixture(contract)
        verdict = observer.compute_verdict(contract, blocked, allow_unit_fixture=True)
        self.assertFalse(verdict["all_pass"])
        self.assertEqual(verdict["result"], "BLOCKED")
        self.assertTrue(verdict["external_blocked"])

    def test_every_negative_control_fails_and_pre_fix_defects_are_evidenced(self):
        observer = _load_observer()
        result = observer.selfcheck(_contract())
        self.assertTrue(result["all_controls_pass"])
        self.assertTrue(result["known_good_unit_fixture_all_pass"])
        self.assertFalse([item for item in result["controls"] if item["fixed_all_pass"]])
        self.assertGreater(result["defect_targeting_pre_fix_passed_count"], 0)
        names = {item["name"] for item in result["controls"]}
        for expected in ("capability-absent-but-claimed", "same-process-provider-substituted",
                         "owning-process-sigkill-as-child-crash", "child-pid-not-dead",
                         "forbidden-substitution-bridge", "archive-mismatch"):
            self.assertIn(expected, names)


class CommittedEvidenceTests(unittest.TestCase):
    def test_discovery_shows_no_out_of_process_continuable_provider(self):
        discovery = json.loads(DISCOVERY.read_text(encoding="utf-8"))
        self.assertEqual(discovery["schema_version"], "byq-v090-d15-child-provider-discovery.v1")
        self.assertEqual(discovery["evidence_class"], "native-runtime-isolated")
        self.assertIsNone(discovery["boot_error"])
        providers = {item["name"]: item for item in discovery["providers"]}
        for name in ("spawn", "fork"):
            self.assertTrue(providers[name]["prepare_continuable_present"], name)
            self.assertEqual(providers[name]["boundary"], "in-process", name)
        for name in ("acp", "codex", "claude-code"):
            self.assertFalse(providers[name]["prepare_continuable_present"], name)
            self.assertEqual(providers[name]["boundary"], "out-of-process", name)
            self.assertEqual(providers[name]["gate"]["errorCode"], "UNSUPPORTED_CAPABILITY", name)
        self.assertFalse(discovery["conclusions"]["out_of_process_continuable_provider_available"])
        self.assertFalse(discovery["conclusions"]["independently_killable_child_available"])
        self.assertEqual(discovery["conclusions"]["in_process_continuable_providers"], ["spawn", "fork"])
        self.assertEqual(discovery["conclusions"]["out_of_process_continuable_providers"], [])

    def test_discovery_records_candidate_provenance_matching_the_declaration(self):
        declaration = json.loads(
            (ROOT / "config/dsh/candidates/dsh-0.1.5rc1/candidate.json").read_text(encoding="utf-8"))
        provenance = json.loads(DISCOVERY.read_text(encoding="utf-8"))["provenance"]
        self.assertEqual(provenance["source_commit"], declaration["upstream"]["source_commit"])
        self.assertEqual(provenance["source_archive_sha256"], declaration["upstream"]["source_archive_sha256"])
        archive = provenance["archive"]
        self.assertTrue(archive["matches_declaration"])
        self.assertEqual(archive["observed_sha256"], archive["expected_sha256"])
        for provider in json.loads(DISCOVERY.read_text(encoding="utf-8"))["providers"]:
            self.assertEqual(provider["version"], "0.1.5-rc.1", provider["name"])

    def test_no_child_crash_substitution_was_recorded(self):
        discovery = json.loads(DISCOVERY.read_text(encoding="utf-8"))
        self.assertIsNone(discovery["child_crash_qualification"])
        self.assertIn("not a child crash", discovery["child_crash_qualification_reason"])
        for forbidden in ("BYQ child-resume bridge", "same-process", "owning-process SIGKILL",
                          "label-only PASS"):
            self.assertTrue(any(forbidden in item for item in discovery["substitutions_rejected"]))

    def test_committed_verdict_is_truthful_blocked(self):
        verdict = json.loads(VERDICT.read_text(encoding="utf-8"))
        self.assertTrue(verdict["format_valid"])
        self.assertFalse(verdict["all_pass"])
        self.assertFalse(verdict["qualification_passed"])
        self.assertEqual(verdict["result"], "BLOCKED")
        self.assertTrue(verdict["external_blocked"])
        self.assertEqual(verdict["exit_code"], 1)
        self.assertIn("no out-of-process provider implements", verdict["blocked_reasons"][0])

    def test_external_blocked_record_requires_a_maintainer_decision(self):
        blocked = json.loads(BLOCKED.read_text(encoding="utf-8"))
        self.assertEqual(blocked["blocker"], "subagent-child-crash")
        self.assertEqual(blocked["status"], "BLOCKED")
        self.assertTrue(blocked["is_external"])
        self.assertFalse(blocked["available_in_0_1_5_rc1"])
        decision = blocked["maintainer_decision_required"]
        self.assertTrue(decision["required"])
        self.assertEqual(sorted(decision["options"]),
                         sorted(["G-keep", "G-split", "G-reorder", "G-reclassify"]))
        for downstream in ("subagent-byq-adapter-restart", "terminal-adapter-restart",
                           "terminal-dsh-runtime-restart", "d15-g-rerun", "r3-thin-supervisor"):
            self.assertIn(downstream, blocked["downstream_not_started"])
        constraints = blocked["constraints"]
        self.assertEqual(constraints["r3_resume"], "NO")
        self.assertEqual(constraints["production_selector"], "dsh-0.1.2rc1")
        self.assertFalse(constraints["fork_or_patch_of_dsh"])
        self.assertFalse(constraints["release_or_tag_created"])

    def test_negative_controls_evidence_is_recorded(self):
        controls = json.loads(CONTROLS.read_text(encoding="utf-8"))
        self.assertTrue(controls["all_controls_pass"])
        self.assertGreater(controls["control_count"], 0)
        self.assertGreater(controls["defect_targeting_pre_fix_passed_count"], 0)

    def test_evidence_does_not_downgrade_the_blocker(self):
        # The slice may not delete/downgrade subagent-child-crash; the D15-G
        # capability matrix and verdict still name it BLOCKED / NO_GO.
        capability = json.loads(
            (ROOT / "docs/evidence/d15/d15-g/capability-matrix.v1.json").read_text(encoding="utf-8"))
        self.assertIn("subagent-child-crash", capability["primary_named_blockers"])
        verdict = json.loads(
            (ROOT / "docs/evidence/d15/d15-g/verdict.v1.json").read_text(encoding="utf-8"))
        self.assertEqual(verdict["verdict"], "NO_GO")
        self.assertEqual(verdict["derived_capabilities"]["subagent-child-crash"], "BLOCKED")


class NoSubstitutionTests(unittest.TestCase):
    def test_no_child_resume_bridge_in_scripts(self):
        for path in SUBAGENT.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".mjs", ".js"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            self.assertNotIn("resume_delegated_child", text, str(path))

    def test_production_selector_is_promoted_with_historical_rollback(self):
        deployment = json.loads((ROOT / "config/dsh/deployment.json").read_text(encoding="utf-8"))
        self.assertEqual(deployment["default_release"], "dsh-0.1.5rc1")
        self.assertIn("dsh-0.1.2rc1", deployment["candidate_releases"])


@unittest.skipUnless(os.environ.get("BYQ_V090_D15_CHILD_PROVIDER_RUN_NATIVE") == "1",
                     "set BYQ_V090_D15_CHILD_PROVIDER_RUN_NATIVE=1 to run the real discovery probe")
class NativeDiscoveryIntegrationTests(unittest.TestCase):
    def test_real_discovery_reproduces_the_blocked_verdict(self):
        if shutil.which("node") is None:
            self.skipTest("node not available")
        with tempfile.TemporaryDirectory() as tmp:
            discovery = Path(tmp) / "capability-discovery.v1.json"
            probe = subprocess.run(
                ["node", "child_provider_discovery.mjs", "run", "--out", str(discovery)],
                cwd=SUBAGENT, capture_output=True, text=True, timeout=300)
            self.assertEqual(probe.returncode, 0, probe.stderr[-2000:])
            verdict = Path(tmp) / "verdict.v1.json"
            blocked = Path(tmp) / "external-blocked.v1.json"
            observed = subprocess.run(
                [sys.executable, "child_provider_remediation_observer.py",
                 "--discovery", str(discovery), "--out", str(verdict), "--blocked-out", str(blocked)],
                cwd=SUBAGENT, capture_output=True, text=True, timeout=120)
            self.assertEqual(observed.returncode, 1, observed.stdout + observed.stderr)
            payload = json.loads(verdict.read_text(encoding="utf-8"))
        self.assertEqual(payload["result"], "BLOCKED")
        self.assertTrue(payload["external_blocked"])
        self.assertFalse(payload["conclusions"]["out_of_process_continuable_provider_available"])


if __name__ == "__main__":
    unittest.main()
