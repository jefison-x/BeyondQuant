"""Regression tests for the fail-closed interface reliability auditor.

These tests prove the auditor is fail-closed: the current ledger is genuinely
``complete`` (discovered == reviewed, missing == 0, stale == 0, fake_pass == 0),
and a missing row, a stale source hash, or a fake PASS each make it exit
non-zero instead of reporting success.
"""

from __future__ import annotations

import importlib.util
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


class AuditorFailClosedTests(unittest.TestCase):
    def test_current_ledger_is_complete(self):
        result = MODULE.audit()
        self.assertTrue(result["complete"], result["errors"][:5])
        self.assertEqual(result["discovered"], result["reviewed"])
        self.assertEqual(result["missing"], 0)
        self.assertEqual(result["stale"], 0)
        self.assertEqual(result["fake_pass"], 0)
        self.assertEqual(result["errors"], [])

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
        value = json.loads(LEDGER.read_text(encoding="utf-8"))
        scenarios = {}
        missing = json.loads(json.dumps(value))
        missing["entries"] = missing["entries"][:-1]
        scenarios["missing"] = missing
        stale = json.loads(json.dumps(value))
        stale["entries"][0]["source_sha256"] = "0" * 64
        scenarios["stale"] = stale
        fake = json.loads(json.dumps(value))
        fake["entries"][0]["evidence"] = []
        fake["entries"][0]["authorization"] = ""
        scenarios["fake_pass"] = fake
        with tempfile.TemporaryDirectory() as directory:
            for name, payload in scenarios.items():
                ledger_path = Path(directory) / f"{name}.json"
                ledger_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                completed = subprocess.run(
                    [sys.executable, str(SCRIPT), "--root", str(ROOT), "--ledger", str(ledger_path)],
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

    def test_cli_is_zero_for_the_real_ledger(self):
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(ROOT), "--ledger", str(LEDGER)],
            capture_output=True, text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout[-500:])
        self.assertTrue(json.loads(completed.stdout)["complete"])


if __name__ == "__main__":
    unittest.main()
