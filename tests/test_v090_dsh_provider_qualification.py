"""Independent DSH provider-qualification slice acceptance tests.

These tests assert the truthfulness of the committed monitoring evidence and the
fail-ability of the observer. They do **not** implement anything: no DSH provider,
no DSH fork/patch, no BYQ child-resume bridge, no second session store, no
production selector/default upgrade, no dependency upgrade, no deployment.

Runs under ``unittest`` (the architecture lane has no pytest).

Set ``BYQ_DSH_PROVIDER_QUALIFICATION=1`` and point
``BYQ_DSH_PROVIDER_QUALIFICATION_MODULE_ROOT`` at an already-installed examined
release to additionally execute the real native capability probe.
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
QUALIFICATION = ROOT / "scripts/d15/provider_qualification"
OBSERVER = QUALIFICATION / "provider_qualification_observer.py"
CONTRACT = QUALIFICATION / "contract.v1.json"
PROBE = QUALIFICATION / "capability_inventory.mjs"
PROVENANCE = QUALIFICATION / "version_provenance.py"
EVIDENCE = ROOT / "docs/evidence/v090-dsh-provider-qualification"

REQUIRED_DEFECT_FAMILIES = (
    "fake-provider-claimed",
    "in-process-provider-substituted",
    "one-shot-provider-as-continuable",
    "no-durable-mailbox",
    "double-active-lease",
    "duplicate-settlement",
)


def _load_observer():
    spec = importlib.util.spec_from_file_location("v090_provider_qualification_observer", OBSERVER)
    module = importlib.util.module_from_spec(spec)
    sys.modules["v090_provider_qualification_observer"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _contract():
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def _evidence(name):
    return json.loads((EVIDENCE / name).read_text(encoding="utf-8"))


class ContractTests(unittest.TestCase):
    def test_contract_names_the_capability_and_versions(self):
        contract = _contract()
        self.assertEqual(contract["schema_version"],
                         "byq-v090-dsh-provider-qualification-contract.v1")
        self.assertEqual(contract["slice"], "v090-dsh-provider-qualification")
        self.assertEqual(contract["owner_node"], "d15-4-child-provider-remediation")
        versions = {item["id"]: item for item in contract["examined_versions"]}
        self.assertEqual(versions["rc2"]["npm"], "0.1.5-rc.2")
        self.assertEqual(versions["alpha2"]["npm"], "0.1.6-alpha.2")
        self.assertEqual(contract["required_capability"]["id"],
                         "out-of-process-continuable-provider")
        for forbidden in ("out-of-process.d.ts presence", "subprocessRunHandle symbol",
                          "one-shot ACP child", "same-process in-process provider",
                          "label-only PASS"):
            self.assertIn(forbidden, contract["forbidden_substitutions"])
        self.assertEqual(contract["qualification_switch"], "BYQ_DSH_PROVIDER_QUALIFICATION=1")
        constraints = contract["constraints"]
        self.assertEqual(constraints["r3_resume"], "NO")
        self.assertEqual(constraints["d15_g_verdict"], "NO_GO")
        self.assertEqual(constraints["production_selector"], "dsh-0.1.2rc1")
        self.assertEqual(constraints["dependency_upgrade"], "none")
        self.assertFalse(constraints["fork_or_patch_of_dsh"])
        self.assertFalse(constraints["byq_child_resume_bridge"])


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
        self.assertEqual(verdict["exit_code"], 1)

    def test_every_negative_control_fails_and_required_defects_are_present(self):
        observer = _load_observer()
        result = observer.selfcheck(_contract())
        self.assertTrue(result["all_controls_pass"])
        self.assertTrue(result["known_good_unit_fixture_all_pass"])
        self.assertFalse([item for item in result["controls"] if item["fixed_all_pass"]])
        self.assertGreater(result["defect_targeting_pre_fix_passed_count"], 0)
        names = {item["name"] for item in result["controls"]}
        for required in REQUIRED_DEFECT_FAMILIES:
            self.assertIn(required, names, required)

    def test_observer_cli_exits_non_zero_on_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            inventory = Path(tmp) / "inventory.json"
            observer_module = _load_observer()
            inventory.write_text(json.dumps(observer_module.valid_fixture(_contract())),
                                 encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(OBSERVER), "--inventory", str(inventory),
                 "--out", str(Path(tmp) / "verdict.json")],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
            verdict = json.loads((Path(tmp) / "verdict.json").read_text(encoding="utf-8"))
        self.assertEqual(verdict["result"], "BLOCKED")
        self.assertTrue(verdict["external_blocked"])


class CommittedEvidenceTests(unittest.TestCase):
    def test_provenance_records_both_versions_and_no_coherent_python_pairing(self):
        for name, npm_version in (("provenance.rc2.v1.json", "0.1.5-rc.2"),
                                  ("provenance.alpha2.v1.json", "0.1.6-alpha.2")):
            provenance = _evidence(name)
            self.assertEqual(provenance["schema_version"],
                             "byq-v090-dsh-provider-qualification-provenance.v1")
            self.assertEqual(provenance["root"]["version"], npm_version)
            self.assertIsNotNone(provenance["root"]["integrity"])
            self.assertGreater(provenance["resolved_closure"]["count"], 0)
            self.assertTrue(provenance["resolved_closure"]["canonical_sha256"].startswith("sha256:"))
            providers = provenance["provider_closure"]
            self.assertEqual(len(providers), 6)
            self.assertTrue(all(item["published"] for item in providers))
            pairing = provenance["python_pairing"]
            self.assertFalse(pairing["coherent_pairing"])
            self.assertIsNone(pairing["sdk_match"])
        self.assertIn("not a coherent pairing",
                      _evidence("provenance.rc2.v1.json")["python_pairing"]["reason"])

    def test_capability_inventory_shows_no_out_of_process_continuable_provider(self):
        for name, npm_version in (("capability-inventory.rc2.v1.json", "0.1.5-rc.2"),
                                  ("capability-inventory.alpha2.v1.json", "0.1.6-alpha.2")):
            inventory = _evidence(name)
            self.assertEqual(
                inventory["schema_version"],
                "byq-v090-dsh-provider-qualification-capability-inventory.v1")
            self.assertEqual(inventory["examined_version"]["npm"], npm_version)
            self.assertEqual(inventory["evidence_class"], "native-runtime-isolated")
            self.assertIsNone(inventory["boot_error"])
            providers = {item["name"]: item for item in inventory["providers"]}
            for provider_name in ("spawn", "fork"):
                self.assertTrue(providers[provider_name]["prepare_continuable_present"])
                self.assertEqual(providers[provider_name]["boundary"], "in-process")
            for provider_name in ("acp", "codex", "claude-code", "dsh-sdk"):
                self.assertFalse(providers[provider_name]["prepare_continuable_present"])
                self.assertEqual(providers[provider_name]["boundary"], "out-of-process")
                self.assertEqual(providers[provider_name]["gate"]["errorCode"],
                                 "UNSUPPORTED_CAPABILITY")
            self.assertFalse(inventory["conclusions"]["out_of_process_continuable_provider_available"])
            self.assertEqual(inventory["conclusions"]["out_of_process_continuable_providers"], [])
            self.assertEqual(inventory["conclusions"]["in_process_continuable_providers"],
                             ["spawn", "fork"])
            self.assertIsNone(inventory["cross_process_continuation_qualification"])
            # Helper symbols are recorded but must not be treated as capability.
            self.assertTrue(inventory["out_of_process_helpers"])
            self.assertTrue(inventory["helper_symbols_are_not_capability"])
            limitations = inventory["declared_limitations"]
            self.assertTrue(limitations["process_local_residency"])
            self.assertTrue(limitations["durable_mailbox_absent"])
            self.assertTrue(limitations["cross_process_lease_absent"])
            self.assertTrue(limitations["acp_one_shot"])

    def test_committed_verdicts_are_separate_and_truthful_blocked(self):
        for name, version_id in (("verdict.rc2.v1.json", "rc2"),
                                 ("verdict.alpha2.v1.json", "alpha2")):
            verdict = _evidence(name)
            self.assertEqual(verdict["schema_version"],
                             "byq-v090-dsh-provider-qualification-verdict.v1")
            self.assertEqual(verdict["examined_version"]["id"], version_id)
            self.assertTrue(verdict["format_valid"])
            self.assertFalse(verdict["all_pass"])
            self.assertFalse(verdict["qualification_passed"])
            self.assertEqual(verdict["result"], "BLOCKED")
            self.assertTrue(verdict["external_blocked"])
            self.assertEqual(verdict["exit_code"], 1)
            self.assertIn("no registerable out-of-process provider", verdict["blocked_reasons"][0])

    def test_external_blocked_records_require_no_upgrade(self):
        for name in ("external-blocked.rc2.v1.json", "external-blocked.alpha2.v1.json"):
            blocked = _evidence(name)
            self.assertEqual(blocked["status"], "BLOCKED")
            self.assertTrue(blocked["is_external"])
            constraints = blocked["constraints"]
            self.assertEqual(constraints["r3_resume"], "NO")
            self.assertEqual(constraints["production_selector"], "dsh-0.1.2rc1")
            self.assertEqual(constraints["dependency_upgrade"], "none")
            self.assertFalse(constraints["fork_or_patch_of_dsh"])
            self.assertFalse(constraints["byq_child_resume_bridge"])

    def test_negative_controls_evidence_is_recorded(self):
        controls = _evidence("negative-controls.v1.json")
        self.assertTrue(controls["all_controls_pass"])
        self.assertGreater(controls["control_count"], 0)
        self.assertGreater(controls["defect_targeting_pre_fix_passed_count"], 0)
        names = {item["name"] for item in controls["controls"]}
        for required in REQUIRED_DEFECT_FAMILIES:
            self.assertIn(required, names)

    def test_upstream_requirement_package_exists_and_is_complete(self):
        text = (EVIDENCE / "upstream-requirement.md").read_text(encoding="utf-8")
        for required in ("Minimal interface contract", "Lifecycle & security invariants",
                         "Reproducible B1 / B2 scenarios", "Upstream acceptance checklist",
                         "prepareContinuable", "durable mailbox", "cross-process lease"):
            self.assertIn(required, text)

    def test_evidence_does_not_downgrade_the_blocker_or_change_production(self):
        capability = json.loads(
            (ROOT / "docs/evidence/d15/d15-g/capability-matrix.v1.json").read_text(encoding="utf-8"))
        self.assertIn("subagent-child-crash", capability["primary_named_blockers"])
        g_verdict = json.loads(
            (ROOT / "docs/evidence/d15/d15-g/verdict.v1.json").read_text(encoding="utf-8"))
        self.assertEqual(g_verdict["verdict"], "NO_GO")
        self.assertEqual(g_verdict["derived_capabilities"]["subagent-child-crash"], "BLOCKED")
        deployment = json.loads((ROOT / "config/dsh/deployment.json").read_text(encoding="utf-8"))
        self.assertEqual(deployment["default_release"], "dsh-0.1.5rc1")
        self.assertIn("dsh-0.1.2rc1", deployment["candidate_releases"])


class NoSubstitutionTests(unittest.TestCase):
    def test_no_byq_child_resume_bridge_or_fork(self):
        for path in QUALIFICATION.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".mjs", ".js", ".sh", ".json"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            self.assertNotIn("resume_delegated_child", text, str(path))
            self.assertNotIn("child-resume bridge implementation", text, str(path))

    def test_qualification_switch_is_required(self):
        runner = QUALIFICATION / "run_provider_qualification.sh"
        env = dict(os.environ)
        env.pop("BYQ_DSH_PROVIDER_QUALIFICATION", None)
        completed = subprocess.run(
            ["bash", str(runner), "0.1.5-rc.2", "rc2", "next"],
            capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(completed.returncode, 2)
        self.assertIn("qualification switch not set", completed.stderr)


@unittest.skipUnless(
    os.environ.get("BYQ_DSH_PROVIDER_QUALIFICATION") == "1"
    and os.environ.get("BYQ_DSH_PROVIDER_QUALIFICATION_MODULE_ROOT"),
    "set BYQ_DSH_PROVIDER_QUALIFICATION=1 and "
    "BYQ_DSH_PROVIDER_QUALIFICATION_MODULE_ROOT=<installed release> to run the native probe")
class NativeProbeIntegrationTests(unittest.TestCase):
    def test_real_probe_reproduces_blocked_for_the_examined_release(self):
        if shutil.which("node") is None:
            self.skipTest("node not available")
        module_root = Path(os.environ["BYQ_DSH_PROVIDER_QUALIFICATION_MODULE_ROOT"])
        npm_version = os.environ.get("BYQ_DSH_PROVIDER_QUALIFICATION_NPM_VERSION", "0.1.5-rc.2")
        version_id = "alpha2" if "alpha" in npm_version else "rc2"
        channel = "alpha" if version_id == "alpha2" else "next"
        with tempfile.TemporaryDirectory() as tmp:
            inventory = Path(tmp) / "capability-inventory.json"
            probe = subprocess.run(
                ["node", str(PROBE), "--module-root", str(module_root),
                 "--npm-version", npm_version, "--version-id", version_id,
                 "--channel", channel, "--out", str(inventory)],
                capture_output=True, text=True, timeout=300)
            self.assertEqual(probe.returncode, 0, probe.stderr[-2000:])
            verdict_path = Path(tmp) / "verdict.json"
            observed = subprocess.run(
                [sys.executable, str(OBSERVER), "--inventory", str(inventory),
                 "--out", str(verdict_path)],
                capture_output=True, text=True, timeout=120)
            self.assertEqual(observed.returncode, 1, observed.stdout + observed.stderr)
            verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
        self.assertEqual(verdict["result"], "BLOCKED")
        self.assertTrue(verdict["external_blocked"])
        self.assertFalse(verdict["conclusions"]["out_of_process_continuable_provider_available"])


if __name__ == "__main__":
    unittest.main()
