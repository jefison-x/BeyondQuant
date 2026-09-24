"""0.9 formal repo default dependency/selector upgrade to DSH 0.1.5-rc.1."""

from __future__ import annotations

import hashlib
import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/evidence/v090-dsh-015rc1-default-upgrade"
VERIFY = ROOT / "scripts/v090/dsh_default_upgrade/verify.py"
CANDIDATE = "dsh-0.1.5rc1"
ROLLBACK = "dsh-0.1.2rc1"

SNAPSHOT_FILES = {
    "config/dsh/releases/dsh-0.1.5rc1.json": "promotion-snapshot.release.json",
    "config/dsh/generated/deployment.identity.json": "promotion-snapshot.identity.json",
    "services/runtime-adapter/Dockerfile.post-u8-candidate": "promotion-snapshot.Dockerfile",
    "scripts/dsh/build_revision.py": "promotion-snapshot.build_revision.py",
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


class DefaultUpgradeVerifierTests(unittest.TestCase):
    def test_verifier_passes_and_is_fail_closed(self) -> None:
        result = subprocess.run(["python3", str(VERIFY), "--snapshot-dir", str(EVIDENCE)], cwd=ROOT,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "PASS")
        selfcheck = subprocess.run(["python3", str(VERIFY), "--snapshot-dir", str(EVIDENCE),
                                    "--selfcheck"], cwd=ROOT,
                                   capture_output=True, text=True)
        self.assertEqual(selfcheck.returncode, 0, selfcheck.stdout + selfcheck.stderr)
        payload = json.loads(selfcheck.stdout)
        self.assertGreaterEqual(payload["negative_controls"], 10)
        self.assertEqual(payload["negative_controls"], payload["defect_targeting"])

    def test_committed_verification_matches_the_promotion_snapshot(self) -> None:
        committed = _load(EVIDENCE / "verification.v1.json")
        result = subprocess.run(["python3", str(VERIFY), "--snapshot-dir",
                                 str(EVIDENCE)], cwd=ROOT,
                                capture_output=True, text=True)
        live = json.loads(result.stdout)
        for key in ("status", "default_release", "rollback_release",
                    "promoted_build", "rollback_build", "promoted_descriptor_hash"):
            self.assertEqual(committed[key], live[key], key)


class DefaultUpgradeEvidenceTests(unittest.TestCase):
    def test_inventory_reuses_candidate_assets_and_preserves_the_baseline(self) -> None:
        inventory = _load(EVIDENCE / "inventory.v1.json")
        self.assertEqual(inventory["base"],
                         "4671c3e948b77c75a87c84a514888974f683a54b")
        assets = inventory["reused_candidate_qualification_assets"]
        self.assertTrue((ROOT / assets["candidate_registry"]).is_file())
        self.assertTrue((ROOT / assets["candidate_python_lock"]).is_file())
        self.assertTrue((ROOT / assets["compat_shim"]).is_file())
        for path in assets["d15_evidence"]:
            self.assertTrue((ROOT / path).is_file(), path)
        baseline = inventory["prior_baseline_rollback"]
        for key in ("release_descriptor", "python_lock", "build_manifest"):
            item = baseline[key]
            self.assertEqual(item["sha256"], _sha256(ROOT / item["path"]), key)

    def test_default_upgrade_evidence_matches_the_promotion_snapshot(self) -> None:
        evidence = _load(EVIDENCE / "default-upgrade.v1.json")
        self.assertEqual(evidence["release"], CANDIDATE)
        self.assertEqual(evidence["pairing"]["python_sdk"], "0.1.5rc1")
        self.assertEqual(evidence["pairing"]["bundled_npm"], "0.1.5-rc.1")
        for relative, digest in evidence["changes"].items():
            source = (EVIDENCE / SNAPSHOT_FILES[relative]
                      if relative in SNAPSHOT_FILES else ROOT / relative)
            self.assertEqual(digest, _sha256(source), relative)
        self.assertEqual(evidence["default_selector"]["identity"],
                         "config/dsh/generated/deployment.identity.json")

    def test_rollback_evidence_binds_the_frozen_baseline(self) -> None:
        rollback = _load(EVIDENCE / "rollback.v1.json")
        self.assertEqual(rollback["prior_baseline"], ROLLBACK)
        for relative, item in rollback["intact_artifacts"].items():
            if not relative.endswith(".json") and not relative.endswith(".lock"):
                continue
            self.assertEqual(item["sha256"], _sha256(ROOT / relative), relative)
        self.assertGreaterEqual(len(rollback["procedure"]), 4)

    def test_business_verification_is_real_and_bound(self) -> None:
        business = _load(EVIDENCE / "business-verification.v1.json")
        self.assertEqual(business["default_under_test"], CANDIDATE)
        self.assertEqual(business["provider"],
                         "keyless scripted loopback (no real model credential, no external network)")
        results = {item["id"]: item["result"] for item in business["results"]}
        for required in ("image-build", "adapter-readiness",
                         "runtime-unit-and-domain-wire",
                         "continuation-budget-executor",
                         "keyless-start-and-tool-turn"):
            self.assertEqual(results.get(required), "PASS", required)
        self.assertGreaterEqual(business["fail_closed"]["defect_targeting"], 10)
        self.assertEqual(business["fail_closed"]["verifier"],
                         "scripts/v090/dsh_default_upgrade/verify.py")

    def test_boundaries_are_unchanged(self) -> None:
        verdict = _load(ROOT / "docs/evidence/d15/d15-g/verdict.v1.json")
        self.assertEqual(verdict["verdict"], "NO_GO")
        deployment = _load(ROOT / "config/dsh/deployment.json")
        self.assertEqual(deployment["default_release"], CANDIDATE)
        self.assertEqual(deployment["candidate_releases"], [ROLLBACK])
        status = (ROOT / "docs/roadmap/STATUS.md").read_text(encoding="utf-8")
        for marker in ("<!-- byq:v090-step5-b1-subagent-child-crash=blocked-external -->",
                       "<!-- byq:v090-step5-b2-adapter-restart=blocked-external -->",
                       "<!-- byq:v090-dsh-default-upgrade=promoted -->"):
            self.assertIn(marker, status)
        for forbidden in ("superseding_assessment_passed", "production_deploy_verified",
                          "release_tag_created", "phase_100_resumed", "zero-ten-started"):
            self.assertNotIn(forbidden, json.dumps(_load(EVIDENCE / "default-upgrade.v1.json")))


if __name__ == "__main__":
    unittest.main()
