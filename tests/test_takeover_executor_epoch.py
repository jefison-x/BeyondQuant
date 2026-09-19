"""Tests for the explicit, audited runtime executor takeover operator tool.

No live runtime, database or production root is touched; everything runs under
``tmp_path``.
"""
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest


PATH = str(Path(__file__).resolve().parents[1] / "scripts/ops")
sys.path.insert(0, PATH)
try:
    MODULE = importlib.import_module("takeover_executor_epoch")
finally:
    sys.path.remove(PATH)


_IDENTITY_DIR: str | None = None
_PREVIOUS_IDENTITY: str | None = None


def setUpModule():
    global _IDENTITY_DIR, _PREVIOUS_IDENTITY
    _IDENTITY_DIR = tempfile.mkdtemp()
    path = Path(_IDENTITY_DIR) / "deployment.identity.json"
    path.write_text(json.dumps({
        "schema_version": "dsh-deployment-identity.v1",
        "default_release": "dsh-0.1.2rc1",
        "python": {"sdk": "0.1.2rc1", "runtime_bin": "0.1.2rc1"},
        "runtime_executor": {
            "schema_version": "runtime-executor.v1",
            "deployment_id": "byq-test-runtime",
            "runtime_release": "dsh-0.1.2rc1",
            "volume_identity": "byq-test-sessions",
            "executor_epoch": 1,
        },
    }), encoding="utf-8")
    _PREVIOUS_IDENTITY = os.environ.get("BYQ_DSH_RELEASE_IDENTITY")
    os.environ["BYQ_DSH_RELEASE_IDENTITY"] = str(path)


def tearDownModule():
    if _PREVIOUS_IDENTITY is None:
        os.environ.pop("BYQ_DSH_RELEASE_IDENTITY", None)
    else:
        os.environ["BYQ_DSH_RELEASE_IDENTITY"] = _PREVIOUS_IDENTITY


def session_root() -> Path:
    root = Path(tempfile.mkdtemp())
    (root / "byq-lifecycle-evidence").mkdir(parents=True)
    return root


class TakeoverToolTests(unittest.TestCase):
    def test_audit_mode_is_read_only(self):
        root = session_root()
        self.assertEqual(MODULE.main(["--session-root", str(root)]), 0)
        self.assertFalse((root / "byq-lifecycle-evidence" / "executor-state").exists())

    def test_apply_increments_epoch_and_writes_audit(self):
        root = session_root()
        self.assertEqual(MODULE.main([
            "--apply", "--session-root", str(root),
            "--reason", "operator executor replacement", "--operator", "operator-a",
        ]), 0)
        state = MODULE.executor_identity.read_epoch_state(root / "byq-lifecycle-evidence")
        self.assertEqual(state["executor_epoch"], 1)
        # A first takeover on an empty volume establishes the deployment floor.
        self.assertEqual(MODULE.main([
            "--apply", "--session-root", str(root),
            "--reason", "second explicit takeover", "--operator", "operator-b",
        ]), 0)
        state = MODULE.executor_identity.read_epoch_state(root / "byq-lifecycle-evidence")
        self.assertEqual(state["executor_epoch"], 2)
        audits = sorted(
            (root / "byq-lifecycle-evidence" / "executor-state" / "takeover-audit").glob("*.json"))
        self.assertEqual(len(audits), 2)
        audit = json.loads(audits[-1].read_text(encoding="utf-8"))
        self.assertEqual(audit["previous_epoch"], 1)
        self.assertEqual(audit["executor_epoch"], 2)
        self.assertFalse(audit["database_rows_modified"])
        self.assertFalse(audit["reversible"])

    def test_apply_requires_a_specific_reason(self):
        root = session_root()
        with self.assertRaises(SystemExit):
            MODULE.main(["--apply", "--session-root", str(root), "--reason", "short"])

    def test_corrupt_epoch_fails_closed(self):
        root = session_root()
        state_dir = root / "byq-lifecycle-evidence" / "executor-state"
        state_dir.mkdir(parents=True)
        (state_dir / "executor-epoch.v1.json").write_text("{broken", encoding="utf-8")
        self.assertEqual(MODULE.main([
            "--apply", "--session-root", str(root), "--reason", "must not overwrite corruption",
        ]), 2)


if __name__ == "__main__":
    unittest.main()
