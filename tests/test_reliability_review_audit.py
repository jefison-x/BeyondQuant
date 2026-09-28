"""Regression tests for the fail-closed interface reliability auditor.

These tests prove the auditor is fail-closed against a complete isolated
fixture. The H4 ledger is historical evidence for the pre-Clean Break tree;
it cannot be audited against the current architecture's changed interfaces.
"""

from __future__ import annotations

import importlib.util
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ci/check-reliability-review.py"
LEDGER = ROOT / "docs/evidence/research-handoff-h4/INTERFACE-REVIEW.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("byq_check_reliability_review", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = _load_module()


def _reviewed_entry(identity: str, digest: str) -> dict:
    return {
        "kind": "route",
        "file": "svc.py",
        "line": 1,
        "method": "GET",
        "path": identity,
        "handler": identity.strip("/") or "root",
        "audit_status": "VERIFIED_OK",
        "owner": "owner",
        "mode": "read",
        "authorization": "authorization",
        "idempotency": "idempotency",
        "timeout": "timeout",
        "errors": "errors",
        "retry": "retry",
        "authority": "authority",
        "recovery": "recovery",
        "consumers": ["consumer"],
        "evidence": ["docs/evidence/v090-full-interface-rebaseline/README.md"],
        "source_sha256": digest,
    }


def _fixture(root: Path) -> Path:
    (root / "svc.py").write_text("x = 1\n", encoding="utf-8")
    evidence = root / "docs/evidence/v090-full-interface-rebaseline/README.md"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("Isolated review evidence.\n", encoding="utf-8")
    digest = MODULE.hashlib.sha256((root / "svc.py").read_bytes()).hexdigest()
    entry = _reviewed_entry("/a", digest)
    inventory = root / "scripts/ci/inventory-reliability.py"
    inventory.parent.mkdir(parents=True)
    inventory.write_text(f"def inventory():\n    return {[entry]!r}\n", encoding="utf-8")
    manual = []
    for name in sorted(MODULE.MANUAL):
        reviewed = _reviewed_entry(f"/{name}", digest)
        reviewed["name"] = name
        manual.append(reviewed)
    ledger = root / "ledger.json"
    ledger.write_text(json.dumps({"entries": [entry], "manual_surfaces": manual}), encoding="utf-8")
    return ledger


class AuditorFailClosedTests(unittest.TestCase):
    def test_complete_fixture_is_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = _fixture(root)
            result = MODULE.audit(root, ledger)
            self.assertTrue(result["complete"], result["errors"][:5])
            self.assertEqual(result["discovered"], result["reviewed"])
            self.assertEqual(result["missing"], 0)
            self.assertEqual(result["stale"], 0)
            self.assertEqual(result["fake_pass"], 0)

    def test_historical_ledger_remains_preserved(self):
        value = json.loads(LEDGER.read_text(encoding="utf-8"))
        self.assertGreater(len(value["entries"]), 500)
        self.assertEqual(value["schema_version"], "h4-interface-review.v1")
        historical = subprocess.check_output(
            ["git", "show", "2f8aca4a:docs/evidence/research-handoff-h4/INTERFACE-REVIEW.json"],
            cwd=ROOT,
        )
        self.assertEqual(hashlib.sha256(LEDGER.read_bytes()).digest(), hashlib.sha256(historical).digest())

    def test_missing_row_is_reported_and_not_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "svc.py").write_text("x = 1\n", encoding="utf-8")
            digest = MODULE.hashlib.sha256((root / "svc.py").read_bytes()).hexdigest()
            source = [_reviewed_entry("/a", digest), _reviewed_entry("/b", digest)]
            ledger = {"entries": [_reviewed_entry("/a", digest)], "manual_surfaces": []}
            result = MODULE.evaluate(source, ledger, root)
            self.assertFalse(result["complete"])
            self.assertEqual(result["missing"], 1)
            self.assertEqual(result["unreviewed"], 1)

    def test_stale_hash_is_reported_and_not_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "svc.py").write_text("x = 1\n", encoding="utf-8")
            entry = _reviewed_entry("/a", "0" * 64)
            result = MODULE.evaluate([_reviewed_entry("/a", "0" * 64)], {"entries": [entry]}, root)
            self.assertFalse(result["complete"])
            self.assertEqual(result["stale"], 1)
            self.assertTrue(any(item["error"].startswith("source drift") for item in result["errors"]))

    def test_fake_pass_is_reported_and_not_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "svc.py").write_text("x = 1\n", encoding="utf-8")
            digest = MODULE.hashlib.sha256((root / "svc.py").read_bytes()).hexdigest()
            entry = _reviewed_entry("/a", digest)
            entry["evidence"] = []
            entry["owner"] = "   "
            result = MODULE.evaluate([_reviewed_entry("/a", digest)], {"entries": [entry]}, root)
            self.assertFalse(result["complete"])
            self.assertGreaterEqual(result["fake_pass"], 1)

    def test_cli_is_nonzero_for_missing_stale_and_fake_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = json.loads(_fixture(root).read_text(encoding="utf-8"))
            scenarios = {}
            missing = json.loads(json.dumps(value))
            missing["entries"] = []
            scenarios["missing"] = missing
            stale = json.loads(json.dumps(value))
            stale["entries"][0]["source_sha256"] = "0" * 64
            scenarios["stale"] = stale
            fake = json.loads(json.dumps(value))
            fake["entries"][0]["evidence"] = []
            fake["entries"][0]["authorization"] = ""
            scenarios["fake_pass"] = fake
            for name, payload in scenarios.items():
                ledger_path = Path(directory) / f"{name}.json"
                ledger_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                completed = subprocess.run(
                    [sys.executable, str(SCRIPT), "--root", str(root), "--ledger", str(ledger_path)],
                    capture_output=True, text=True,
                )
                self.assertEqual(completed.returncode, 1, f"{name}: {completed.stdout[-500:]}")
                result = json.loads(completed.stdout)
                self.assertFalse(result["complete"], name)
                if name == "missing":
                    self.assertEqual(result["missing"], 1)
                elif name == "stale":
                    self.assertGreaterEqual(result["stale"], 1)
                else:
                    self.assertGreaterEqual(result["fake_pass"], 1)

    def test_cli_is_zero_for_complete_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = _fixture(root)
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--root", str(root), "--ledger", str(ledger)],
                capture_output=True, text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout[-500:])
            self.assertTrue(json.loads(completed.stdout)["complete"])


if __name__ == "__main__":
    unittest.main()
