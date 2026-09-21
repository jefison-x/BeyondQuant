"""0.9 strict-order step-5 slice 3 (B3): `terminal-adapter-restart` acceptance tests.

These tests assert the truthfulness of the committed real native evidence, the
fail-ability of the observer (including the explicit distinction between a
correct honest ``lost``/``interrupted`` and a not-implemented/label-only PASS),
and that the slice is confined to the candidate/qualification layer: no BYQ PTY
runtime, no DSH fork/patch, no second generic harness/session store, no product
surface, no production selector change and no R4 productization.

Runs under ``unittest`` (the architecture lane has no pytest).

Set ``BYQ_V090_STEP5_B3_RUN_NATIVE=1`` to additionally execute the real isolated
native probe (requires ``npm ci`` in ``scripts/d15/terminal`` and a Node runtime).
"""

from __future__ import annotations

import hashlib
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
TERMINAL = ROOT / "scripts/d15/terminal"
OBSERVER = TERMINAL / "adapter_restart_observer.py"
CONTRACT = TERMINAL / "adapter_restart_contract.v1.json"
HARNESS = TERMINAL / "adapter_restart_harness.mjs"
SCOPE_PROBE = TERMINAL / "adapter_restart_scope_probe.py"
RUNNER = TERMINAL / "run_adapter_restart_probe.sh"
EVIDENCE = ROOT / "docs/evidence/v090-step5-b3-terminal-adapter-restart"
OBSERVATION = EVIDENCE / "native-observations.v1.json"
VERDICT = EVIDENCE / "verdict.v1.json"
CONTROLS = EVIDENCE / "negative-controls.v1.json"
SCOPE = EVIDENCE / "scope-probe.v1.json"
PROVENANCE = EVIDENCE / "provenance.v1.json"
CURRENT_BUILD_REVISION = "dsh-0.1.2rc1-post-u8.198"

B3 = "terminal-adapter-restart"
B3_OWNER = "d15-5-candidate-attachment-layer"


def _load_observer():
    spec = importlib.util.spec_from_file_location("v090_step5_b3_observer", OBSERVER)
    module = importlib.util.module_from_spec(spec)
    sys.modules["v090_step5_b3_observer"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _contract() -> dict:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


class ContractTests(unittest.TestCase):
    def test_contract_names_the_slice_and_owner(self):
        contract = _contract()
        self.assertEqual(contract["schema_version"],
                         "byq-v090-step5-b3-terminal-adapter-restart-contract.v1")
        self.assertEqual(contract["slice"], B3)
        self.assertEqual(contract["owner_node"], B3_OWNER)
        self.assertIn("B3", contract["step"])
        self.assertEqual(contract["required_evidence_class"], "native-runtime-isolated-b3")
        self.assertEqual(contract["llm_evidence_class"], "not-applicable")

    def test_contract_requires_both_real_branches(self):
        contract = _contract()
        scenarios = {item["id"]: item for item in contract["required_scenarios"]}
        self.assertIn("adapter-restart-native-survives", scenarios)
        self.assertIn("adapter-restart-native-lost", scenarios)
        self.assertEqual(scenarios["adapter-restart-native-survives"]["expects"], "reattach")
        self.assertEqual(scenarios["adapter-restart-native-lost"]["expects"], "honest_lost")
        self.assertIn("fake_reattach_rejected", scenarios["adapter-restart-native-lost"]["assertions"])
        self.assertIn("no_loss", scenarios["adapter-restart-native-survives"]["assertions"])

    def test_contract_fixes_the_ownership_boundary(self):
        ownership = _contract()["ownership"]
        self.assertEqual(ownership["dsh"], ["pty_process", "shell", "io"])
        self.assertIn("attachment_identity", ownership["byq"])
        rule = ownership["rule"]
        self.assertIn("must not build a PTY runtime", rule)
        self.assertIn("must not build a second generic harness", rule)


class ObserverFailAbilityTests(unittest.TestCase):
    def test_known_good_fixture_passes_and_pre_fix_gate_fails_closed(self):
        observer = _load_observer()
        contract = _contract()
        qualified = observer._fully_qualified_fixture(contract)
        verdict = observer.compute_verdict(contract, qualified, allow_unit_fixture=True)
        self.assertTrue(verdict["all_pass"], verdict["failures"])
        self.assertTrue(verdict["format_valid"])
        strict = observer._fully_qualified_fixture(contract)
        strict["evidence_class"] = contract["required_evidence_class"]
        verdict = observer.compute_verdict(contract, strict)
        self.assertTrue(verdict["all_pass"], verdict["failures"])

    def test_every_negative_control_fails_and_pre_fix_defects_are_evidenced(self):
        observer = _load_observer()
        result = observer.selfcheck(_contract())
        self.assertTrue(result["all_controls_pass"])
        self.assertTrue(result["known_good_unit_fixture_all_pass"])
        self.assertFalse([item for item in result["controls"] if item["fixed_all_pass"]])
        self.assertGreater(result["defect_targeting_pre_fix_passed_count"], 0)
        names = {item["name"] for item in result["controls"]}
        for expected in ("label-only-pass-positive", "not-implemented-label-pass",
                         "not-implemented-positive-missing", "lost-without-native-failure",
                         "lost-status-not-lost", "fake-reattach-accepted", "durable-not-loaded",
                         "fabricated-reattach-session-drift", "marker-replayed", "marker-lost",
                         "permission-bypass", "wrong-terminal-accepted", "stale-not-fenced",
                         "orphan-left", "close-not-idempotent", "durable-not-byq-minted",
                         "missing-required-scenario", "non-native-evidence-class",
                         "llm-claims-real-quality", "self-declared-coverage"):
            self.assertIn(expected, names)

    def test_not_implemented_and_label_only_pass_are_rejected(self):
        observer = _load_observer()
        contract = _contract()
        fixture = observer._fully_qualified_fixture(contract)
        fixture["evidence_class"] = contract["required_evidence_class"]
        # Remove the positive rebind evidence while both scenarios still claim PASS.
        for name, mutated in observer._mutations(fixture):
            if name in {"not-implemented-label-pass", "label-only-pass-positive",
                        "lost-without-native-failure", "fake-reattach-accepted"}:
                verdict = observer.compute_verdict(contract, mutated)
                self.assertFalse(verdict["all_pass"], f"{name} unexpectedly passed")


class CommittedEvidenceTests(unittest.TestCase):
    def _observation(self) -> dict:
        return json.loads(OBSERVATION.read_text(encoding="utf-8"))

    def test_observation_is_a_real_isolated_candidate_observation(self):
        observation = self._observation()
        self.assertEqual(observation["schema_version"], "byq-v090-step5-b3-native-observations.v1")
        self.assertEqual(observation["evidence_class"], "native-runtime-isolated-b3")
        self.assertFalse(observation["llm"]["real_llm_quality"])
        for key, value in (("release", "dsh-0.1.5rc1"), ("npm_packages", "0.1.5-rc.1"),
                           ("python_sdk", "0.1.5rc1")):
            self.assertEqual(observation["candidate"][key], value)

    def test_survives_branch_really_rebinds_a_durable_attachment(self):
        scenario = next(item for item in self._observation()["scenarios"]
                        if item["id"] == "adapter-restart-native-survives")
        self.assertEqual(scenario["result"], "PASS")
        self.assertTrue(scenario["fault_applied"])
        obs = scenario["observation"]
        self.assertTrue(obs["byqMintedAttachmentId"])
        self.assertTrue(obs["attachmentIdIsNotNativeId"])
        self.assertTrue(obs["durableStoreFilePresent"])
        self.assertTrue(obs["durableRecordsLoadedSameId"])
        self.assertTrue(obs["freshAdapterOsProcess"])
        self.assertTrue(obs["sameAttachment"])
        self.assertTrue(obs["sameSession"])
        self.assertTrue(obs["samePtyPid"])
        self.assertTrue(obs["ptyProcessPresentAtRebind"])
        self.assertTrue(obs["ioRebindOk"])
        self.assertTrue(obs["identityStable"])
        self.assertFalse(obs["fabricatedReattach"])
        self.assertEqual(obs["marker1InFirstViewport"], 1)
        self.assertEqual(obs["marker1InRebindSendDelta"], 0)
        self.assertEqual(obs["marker2InRebindSendDelta"], 1)
        self.assertEqual(obs["marker1InScrollback"], 1)
        self.assertEqual(obs["marker2InScrollback"], 1)
        self.assertNotEqual(obs["adapterAPid"], obs["adapterBPid"])

    def test_lost_branch_is_honest_and_rejects_a_fake_reattach(self):
        scenario = next(item for item in self._observation()["scenarios"]
                        if item["id"] == "adapter-restart-native-lost")
        self.assertEqual(scenario["result"], "PASS")
        self.assertTrue(scenario["fault_applied"])
        obs = scenario["observation"]
        self.assertTrue(obs["durableRecordsLoadedSameId"])
        self.assertTrue(obs["freshAdapterOsProcess"])
        self.assertTrue(obs["reattachAttempted"])
        self.assertFalse(obs["reattachOk"])
        self.assertIn(obs["reattachStatus"], {"lost", "interrupted"})
        self.assertEqual(obs["rebindError"], "NATIVE_SESSION_UNAVAILABLE")
        self.assertFalse(obs["oldPidAliveAfterLoss"])
        self.assertFalse(obs["nativeSessionPresent"])
        self.assertEqual(obs["nativeSessionsInNewRuntime"], 0)
        self.assertTrue(obs["fakeReattachRejected"])

    def test_cross_checks_and_negatives_are_recorded(self):
        observation = self._observation()
        checks = {item["id"]: item for item in observation["cross_checks"]}
        for expected in ("durable-attachment-lifecycle", "permission-boundary",
                         "stale-generation-fenced", "wrong-terminal-rejected",
                         "idempotent-transitions", "cleanup-no-orphans"):
            self.assertIn(expected, checks)
            self.assertEqual(checks[expected]["result"], "PASS", expected)
        negatives = {item["kind"]: item for item in observation["negatives"]}
        self.assertIn("fake-reattach-after-native-loss", negatives)
        self.assertTrue(all(item["rejected"] for item in observation["negatives"]))

    def test_committed_verdict_passes(self):
        verdict = json.loads(VERDICT.read_text(encoding="utf-8"))
        self.assertTrue(verdict["format_valid"])
        self.assertTrue(verdict["all_pass"])
        self.assertTrue(verdict["qualification_passed"])
        self.assertEqual(verdict["exit_code"], 0)
        self.assertEqual(verdict["required_coverage"],
                         {"adapter-restart-native-survives": "PASS",
                          "adapter-restart-native-lost": "PASS"})
        self.assertTrue(verdict["cross_checks_ok"])
        self.assertTrue(verdict["negatives_ok"])
        self.assertEqual(verdict["failures"], [])

    def test_negative_controls_evidence_is_recorded(self):
        controls = json.loads(CONTROLS.read_text(encoding="utf-8"))
        self.assertTrue(controls["all_controls_pass"])
        self.assertGreater(controls["control_count"], 0)
        self.assertGreater(controls["defect_targeting_pre_fix_passed_count"], 0)

    def test_scope_probe_confines_the_slice_and_keeps_browsers_off_raw_schema(self):
        scope = json.loads(SCOPE.read_text(encoding="utf-8"))
        self.assertTrue(scope["candidate_layer_only"]["confined_to_candidate_layer"])
        self.assertEqual(scope["candidate_layer_only"]["missing_b3_files"], [])
        self.assertFalse(
            scope["byq_product_surface"]["byq_exposes_persistent_terminal_product_surface"])
        self.assertEqual(scope["byq_product_surface"]["runtime_adapter_persistent_terminal_route_count"], 0)
        self.assertFalse(scope["browser_boundary"]["frontend_touches_raw_dsh_schema"])
        self.assertEqual(scope["browser_boundary"]["frontend_raw_dsh_schema_refs"], 0)
        self.assertFalse(scope["ownership"]["byq_builds_pty_runtime"])
        self.assertTrue(scope["ownership"]["uses_native_ctx_terminals_seam"])
        self.assertEqual(scope["forbidden_substitutions_present"], {})
        self.assertFalse(scope["production"]["production_selector_changed"])
        self.assertFalse(scope["production"]["r4_productization"])
        self.assertEqual(scope["production"]["default_release"], "dsh-0.1.2rc1")

    def test_evidence_does_not_change_the_d15_g_blocker(self):
        capability = json.loads(
            (ROOT / "docs/evidence/d15/d15-g/capability-matrix.v1.json").read_text(encoding="utf-8"))
        self.assertIn(B3, capability["primary_named_blockers"])
        verdict = json.loads(
            (ROOT / "docs/evidence/d15/d15-g/verdict.v1.json").read_text(encoding="utf-8"))
        self.assertEqual(verdict["verdict"], "NO_GO")
        self.assertEqual(verdict["derived_capabilities"][B3], "BLOCKED")


class ProvenanceTests(unittest.TestCase):
    def test_provenance_hashes_match_the_committed_artifacts(self):
        provenance = json.loads(PROVENANCE.read_text(encoding="utf-8"))
        self.assertEqual(provenance["schema_version"], "byq-v090-step5-b3-provenance.v1")
        artifacts = provenance["artifacts"]
        self.assertEqual(artifacts["harness"]["sha256"], _sha256(HARNESS))
        self.assertEqual(artifacts["observer"]["sha256"], _sha256(OBSERVER))
        self.assertEqual(artifacts["contract"]["sha256"], _sha256(CONTRACT))
        self.assertEqual(artifacts["scope_probe"]["sha256"], _sha256(SCOPE_PROBE))
        self.assertEqual(artifacts["runner"]["sha256"], _sha256(RUNNER))
        self.assertFalse(provenance["isolation"]["production_selector_changed"])
        self.assertFalse(provenance["isolation"]["fork_or_patch_of_dsh"])
        self.assertFalse(provenance["isolation"]["docker_image_used"])
        self.assertEqual(provenance["isolation"]["r3_resume"], "NO")


class NoSubstitutionTests(unittest.TestCase):
    def test_no_byq_pty_runtime_or_forbidden_substitution(self):
        for path in (HARNESS, OBSERVER, RUNNER):
            text = path.read_text(encoding="utf-8", errors="ignore")
            for token in ("node-pty", "forkpty", "openpty", "resume_delegated_child",
                          "byq_child_resume_bridge"):
                self.assertNotIn(token, text, str(path))

    def test_production_selector_is_unchanged(self):
        deployment = json.loads((ROOT / "config/dsh/deployment.json").read_text(encoding="utf-8"))
        self.assertEqual(deployment["default_release"], "dsh-0.1.2rc1")

    def test_build_revision_is_the_next_unused_id(self):
        from scripts.dsh import build_revision as builds
        self.assertEqual(builds.selected_build_id("dsh-0.1.2rc1"), CURRENT_BUILD_REVISION)
        self.assertTrue((ROOT / "config/dsh/builds" / f"{CURRENT_BUILD_REVISION}.json").is_file())
        dockerfile = (ROOT / "services/runtime-adapter/Dockerfile.post-u8-candidate").read_text()
        self.assertIn(CURRENT_BUILD_REVISION, dockerfile)


@unittest.skipUnless(os.environ.get("BYQ_V090_STEP5_B3_RUN_NATIVE") == "1",
                     "set BYQ_V090_STEP5_B3_RUN_NATIVE=1 to run the real native probe")
class NativeProbeIntegrationTests(unittest.TestCase):
    def test_real_probe_passes(self):
        if shutil.which("node") is None:
            self.skipTest("node not available")
        if not (TERMINAL / "node_modules").is_dir():
            self.skipTest("native harness dependencies not installed")
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                ["bash", str(RUNNER), tmp],
                capture_output=True, text=True, timeout=1800)
            self.assertEqual(result.returncode, 0, result.stdout[-4000:] + result.stderr[-4000:])
            verdict = json.loads((Path(tmp) / "verdict.v1.json").read_text(encoding="utf-8"))
        self.assertTrue(verdict["all_pass"])
        self.assertEqual(verdict["exit_code"], 0)


if __name__ == "__main__":
    unittest.main()
