"""0.9 strict-order step-5 slice 2 (B2): `subagent-byq-adapter-restart` acceptance tests.

These tests assert the truthfulness of the committed BLOCKED evidence, the
fail-ability of the observer and the absence of any rejected Option-2 bridge /
second harness / DSH fork. They do not implement anything: no provider, no BYQ
child-resume bridge, no second session store, no production selector change, no
deployment/tag/release.

Runs under ``unittest`` (the architecture lane has no pytest).

Set ``BYQ_V090_STEP5_B2_RUN_NATIVE=1`` to additionally execute the real isolated
Docker probe (requires the candidate image ``byq-d15-4-continuable-candidate:local``).
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
SUBAGENT = ROOT / "scripts/d15/subagent"
OBSERVER = SUBAGENT / "byq_adapter_restart_observer.py"
CONTRACT = SUBAGENT / "byq_adapter_restart_contract.v1.json"
PROBE = SUBAGENT / "byq_adapter_restart_probe.py"
RUNNER = SUBAGENT / "run_byq_adapter_restart_probe.sh"
EVIDENCE = ROOT / "docs/evidence/v090-step5-b2-adapter-restart"
OBSERVATION = EVIDENCE / "composition-restart.v1.json"
VERDICT = EVIDENCE / "verdict.v1.json"
BLOCKED = EVIDENCE / "external-blocked.v1.json"
CONTROLS = EVIDENCE / "negative-controls.v1.json"
PROVENANCE = EVIDENCE / "probe-provenance.v1.json"
COMPOSITION_IDENTITY = ROOT / "plugins/dsh-byq/profiles/dsh-0.1.5rc1-continuable/byq-product.identity.json"
CURRENT_BUILD_REVISION = "dsh-0.1.2rc1-post-u8.189"

B2 = "subagent-byq-adapter-restart"
B2_OWNER = "d15-4-candidate-composition-hookup"


def _load_observer():
    spec = importlib.util.spec_from_file_location("v090_step5_b2_observer", OBSERVER)
    module = importlib.util.module_from_spec(spec)
    sys.modules["v090_step5_b2_observer"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _contract() -> dict:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


class ContractTests(unittest.TestCase):
    def test_contract_names_the_external_capability(self):
        contract = _contract()
        self.assertEqual(contract["schema_version"],
                         "byq-v090-step5-b2-adapter-restart-contract.v1")
        self.assertEqual(contract["blocker"], B2)
        self.assertEqual(contract["owner_node"], B2_OWNER)
        self.assertIn("B2", contract["step"])
        self.assertEqual(contract["required_evidence_class"],
                         "real-isolated-candidate-adapter-container")
        self.assertFalse(contract["external_dependency"]["available_in_0_1_5_rc1"])
        self.assertIn("prepareContinuable", contract["external_dependency"]["option_1"])
        self.assertIn("rejected", contract["external_dependency"]["option_2"])

    def test_contract_forbids_the_rejected_substitutions(self):
        forbidden = _contract()["forbidden_substitutions"]
        for item in ("byq-child-resume-bridge", "in-process-child",
                     "root-resume-as-child-rebind", "same-os-process-generation",
                     "owning-process-restart-as-child-rebind", "mock", "label-only-pass"):
            self.assertIn(item, forbidden)


class ObserverFailAbilityTests(unittest.TestCase):
    def test_known_good_fixture_passes_and_blocked_fixture_fails(self):
        observer = _load_observer()
        contract = _contract()
        qualified = observer._fully_qualified_fixture(contract)
        verdict = observer.compute_verdict(contract, qualified)
        self.assertTrue(verdict["all_pass"], verdict["blocked_reasons"])
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
        for expected in ("label-only-claim", "no-rebind-candidates", "same-os-process",
                         "no-child-persistence", "child-not-linked-to-goal",
                         "extra-child-created", "second-session-store", "orphan-left-behind",
                         "duplicate-settlement-on-resume", "rebind-without-message-id",
                         "fencing-not-fail-closed", "stale-epoch-rebind-accepted",
                         "composition-forbids-but-claims-surface",
                         "generation-a-no-startContinuable", "production-selector-changed",
                         "fork-or-patch-of-dsh", "forbidden-substitution-bridge"):
            self.assertIn(expected, names)


class CommittedEvidenceTests(unittest.TestCase):
    def _observation(self) -> dict:
        return json.loads(OBSERVATION.read_text(encoding="utf-8"))

    def test_observation_is_a_real_isolated_candidate_observation(self):
        observation = self._observation()
        self.assertEqual(observation["schema_version"],
                         "byq-v090-step5-b2-adapter-restart-observation.v1")
        self.assertEqual(observation["blocker"], B2)
        self.assertEqual(observation["owner_node"], B2_OWNER)
        self.assertEqual(observation["evidence_class"],
                         "real-isolated-candidate-adapter-container")
        self.assertFalse(observation["llm"]["real_llm_quality"])
        for key, value in (("release", "dsh-0.1.5rc1"), ("npm", "0.1.5-rc.1"),
                           ("python_sdk", "0.1.5rc1")):
            self.assertEqual(observation["candidate"][key], value)

    def test_generation_a_reached_start_continuable_and_persisted_the_child(self):
        gen_a = self._observation()["generation_a"]
        self.assertTrue(gen_a["start_continuable_reached"])
        self.assertEqual(gen_a["delegate_result"]["kind"], "continuable")
        self.assertTrue(gen_a["child_persisted"])
        self.assertTrue(gen_a["child_linked_to_root"])
        self.assertEqual(gen_a["started_child_count"], 1)
        self.assertTrue(gen_a["child_id"])
        self.assertTrue(gen_a["delegation_call_id"])
        self.assertEqual(gen_a["child_parent_session"], gen_a["root_session_id"])
        self.assertEqual(len(gen_a["started_child_links"]), 1)

    def test_generation_b_is_a_fresh_process_with_no_byq_rebind_surface(self):
        observation = self._observation()
        identity = observation["process_identity"]
        self.assertTrue(identity["new_os_process"])
        self.assertTrue(identity["fresh_container"])
        gen_b = observation["generation_b"]
        self.assertEqual(gen_b["status"], "BLOCKED")
        self.assertEqual(gen_b["child_rebind_candidates"], [])
        self.assertFalse(gen_b["child_rebind_via_byq_composition"])
        self.assertFalse(gen_b["child_message_delivered"])
        self.assertIsNone(gen_b["message_id"])
        self.assertFalse(gen_b["child_as_root_resume_attempt"]["ok"])
        self.assertTrue(gen_b["child_persisted_same_id"])
        self.assertFalse(gen_b["extra_child_created"])
        self.assertFalse(gen_b["second_session_store_created"])
        self.assertEqual(gen_b["orphans"], 0)

    def test_composition_forbids_the_native_child_messaging_tools(self):
        forbidden = set(self._observation()["composition"]["forbidden_tools"])
        self.assertTrue({"subagent", "send_message", "list_agents"} <= forbidden)
        gen_b = self._observation()["generation_b"]
        self.assertTrue(gen_b["composition_forbids_messaging_tools"])
        self.assertTrue({"subagent", "send_message", "list_agents"}
                        <= set(gen_b["byq_adapter_surfaces"]["forbidden_tools"]))
        public = set(gen_b["byq_adapter_surfaces"]["adapter_public_surfaces"])
        self.assertIn("resume_session", public)
        self.assertFalse({"resume_child", "child_resume", "subagent_resume", "send_message"}
                         & public)

    def test_committed_verdict_is_truthful_blocked(self):
        verdict = json.loads(VERDICT.read_text(encoding="utf-8"))
        self.assertTrue(verdict["format_valid"])
        self.assertFalse(verdict["all_pass"])
        self.assertFalse(verdict["qualification_passed"])
        self.assertEqual(verdict["result"], "BLOCKED")
        self.assertTrue(verdict["external_blocked"])
        self.assertEqual(verdict["exit_code"], 1)
        self.assertIn("no committed BYQ composition surface",
                      verdict["blocked_reasons"][0])
        self.assertFalse(
            verdict["conclusions"]["byq_composition_child_rebind_surface_present"])
        self.assertTrue(verdict["conclusions"]["generation_a_ok"])
        self.assertTrue(verdict["conclusions"]["fresh_os_process"])

    def test_external_blocked_record_requires_the_upstream_provider(self):
        blocked = json.loads(BLOCKED.read_text(encoding="utf-8"))
        self.assertEqual(blocked["blocker"], B2)
        self.assertEqual(blocked["status"], "BLOCKED")
        self.assertTrue(blocked["is_external"])
        self.assertFalse(blocked["available_in_0_1_5_rc1"])
        self.assertIn("prepareContinuable", blocked["required_provider"])
        self.assertIn("bridge", blocked["rejected_option"])
        self.assertIn("Option 1", blocked["upstream_resolution"])
        for downstream in ("terminal-adapter-restart", "terminal-dsh-runtime-restart",
                           "d15-g-rerun", "r3-thin-supervisor"):
            self.assertIn(downstream, blocked["downstream_not_started"])
        constraints = blocked["constraints"]
        self.assertEqual(constraints["r3_resume"], "NO")
        self.assertEqual(constraints["production_selector"], "dsh-0.1.2rc1")
        self.assertFalse(constraints["fork_or_patch_of_dsh"])
        self.assertFalse(constraints["release_or_tag_created"])
        self.assertEqual(constraints["deployment"], "none")

    def test_negative_controls_evidence_is_recorded(self):
        controls = json.loads(CONTROLS.read_text(encoding="utf-8"))
        self.assertTrue(controls["all_controls_pass"])
        self.assertGreater(controls["control_count"], 0)
        self.assertGreater(controls["defect_targeting_pre_fix_passed_count"], 0)

    def test_evidence_does_not_downgrade_the_blocker(self):
        capability = json.loads(
            (ROOT / "docs/evidence/d15/d15-g/capability-matrix.v1.json").read_text(encoding="utf-8"))
        self.assertIn(B2, capability["primary_named_blockers"])
        verdict = json.loads(
            (ROOT / "docs/evidence/d15/d15-g/verdict.v1.json").read_text(encoding="utf-8"))
        self.assertEqual(verdict["verdict"], "NO_GO")
        self.assertEqual(verdict["derived_capabilities"][B2], "BLOCKED")


class ProvenanceTests(unittest.TestCase):
    def test_provenance_hashes_match_the_committed_artifacts(self):
        provenance = json.loads(PROVENANCE.read_text(encoding="utf-8"))
        self.assertEqual(provenance["schema_version"],
                         "byq-v090-step5-b2-probe-provenance.v1")
        self.assertEqual(provenance["artifacts"]["probe"]["sha256"], _sha256(PROBE))
        self.assertEqual(provenance["artifacts"]["observer"]["sha256"], _sha256(OBSERVER))
        self.assertEqual(provenance["artifacts"]["contract"]["sha256"], _sha256(CONTRACT))
        self.assertEqual(provenance["artifacts"]["composition_identity"]["sha256"],
                         _sha256(COMPOSITION_IDENTITY))
        self.assertFalse(provenance["isolation"]["production_selector_changed"])
        self.assertFalse(provenance["isolation"]["fork_or_patch_of_dsh"])

    def test_provenance_image_matches_the_real_candidate_image(self):
        provenance = json.loads(PROVENANCE.read_text(encoding="utf-8"))
        d15_4 = json.loads(
            (ROOT / "docs/evidence/d15/d15-4/continuable/continuable-adapter-restart.v1.json")
            .read_text(encoding="utf-8"))
        self.assertEqual(provenance["isolation"]["image_id"], d15_4["isolation"]["image_id"])
        self.assertEqual(provenance["isolation"]["image"], d15_4["isolation"]["image"])


class NoSubstitutionTests(unittest.TestCase):
    def test_no_byq_child_resume_bridge_or_second_harness(self):
        for path in list(SUBAGENT.rglob("*")) + list((ROOT / "services").rglob("*")):
            if not path.is_file() or path.suffix not in {".py", ".mjs", ".js", ".ts", ".sh"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            self.assertNotIn("resume_delegated_child", text, str(path))
            self.assertNotIn("byq_child_resume_bridge", text, str(path))

    def test_production_selector_is_unchanged(self):
        deployment = json.loads((ROOT / "config/dsh/deployment.json").read_text(encoding="utf-8"))
        self.assertEqual(deployment["default_release"], "dsh-0.1.2rc1")

    def test_only_one_session_store_in_the_probe(self):
        gen_b = json.loads(OBSERVATION.read_text(encoding="utf-8"))["generation_b"]
        stores = [item for item in gen_b["session_store_dirs"]
                  if item != "byq-lifecycle-evidence"]
        self.assertEqual(len(stores), 1)

    def test_build_revision_is_the_next_unused_id(self):
        from scripts.dsh import build_revision as builds
        self.assertEqual(builds.selected_build_id("dsh-0.1.2rc1"), CURRENT_BUILD_REVISION)
        self.assertTrue((ROOT / "config/dsh/builds" / f"{CURRENT_BUILD_REVISION}.json").is_file())


@unittest.skipUnless(os.environ.get("BYQ_V090_STEP5_B2_RUN_NATIVE") == "1",
                     "set BYQ_V090_STEP5_B2_RUN_NATIVE=1 to run the real isolated Docker probe")
class NativeProbeIntegrationTests(unittest.TestCase):
    def test_real_probe_reproduces_the_blocked_verdict(self):
        if shutil.which("docker") is None:
            self.skipTest("docker not available")
        inspect = subprocess.run(
            ["docker", "image", "inspect", "-f", "{{.Id}}",
             "byq-d15-4-continuable-candidate:local"],
            capture_output=True, text=True)
        if inspect.returncode != 0:
            self.skipTest("isolated candidate image not available")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            result = subprocess.run(
                ["bash", str(RUNNER), str(out)],
                capture_output=True, text=True, timeout=1800)
            self.assertTrue((out / "composition-restart.v1.json").is_file(),
                            result.stdout[-2000:] + result.stderr[-2000:])
            verdict = Path(tmp) / "verdict.json"
            observed = subprocess.run(
                [sys.executable, str(OBSERVER),
                 "--observation", str(out / "composition-restart.v1.json"),
                 "--out", str(verdict)],
                capture_output=True, text=True, timeout=120)
            self.assertEqual(observed.returncode, 1, observed.stdout + observed.stderr)
            payload = json.loads(verdict.read_text(encoding="utf-8"))
        self.assertEqual(payload["result"], "BLOCKED")
        self.assertTrue(payload["external_blocked"])
        self.assertFalse(
            payload["conclusions"]["byq_composition_child_rebind_surface_present"])


if __name__ == "__main__":
    unittest.main()
