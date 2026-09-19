"""Tests for the explicit, reversible session-lease re-anchor operator tool.

Everything runs against ``tmp_path``; no live runtime, database or production
root is touched.
"""
from __future__ import annotations

import hashlib
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
    MODULE = importlib.import_module("reanchor_session_lease")
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


def _write_journal(evidence_root: Path, session_id: str, *, lease_identity: str,
                   owner: str = "alice", workspace_id: str = "workspace_alice",
                   trace_id: str | None = None, sequence: int = 3) -> Path:
    state = {
        "context": {
            "session_id": session_id,
            "trace_id": trace_id or f"{session_id}-trace",
            "owner": owner,
            "workspace_id": workspace_id,
        },
        "sequence": sequence,
        "open_root": None,
        "events": [],
        "prompts": {},
        "terminal_acks": {},
        "calls": [],
        "lease_identity": lease_identity,
    }
    encoded = json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
    envelope = {
        "schema_version": "byq-lifecycle-journal.v3",
        "state": state,
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }
    evidence_root.mkdir(parents=True, exist_ok=True)
    path = evidence_root / f"{session_id}.json"
    path.write_text(json.dumps(envelope, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    return path


def _write_lock(evidence_root: Path, session_id: str, token: str = "a" * 32) -> Path:
    evidence_root.mkdir(parents=True, exist_ok=True)
    path = evidence_root / f"{session_id}.lock"
    path.write_text(token, encoding="ascii")
    return path


def _stale_root(directory: str, session_id: str) -> tuple[Path, Path, str]:
    root = Path(directory)
    evidence = root / "byq-lifecycle-evidence"
    lock = _write_lock(evidence, session_id)
    stat = lock.stat()
    stored = MODULE.archive.compute_lease_identity(
        "old-boot", stat.st_dev, stat.st_ino, "a" * 32)
    _write_journal(evidence, session_id, lease_identity=stored)
    (root / "gateway").mkdir(exist_ok=True)
    (root / "gateway" / f"{session_id}.ndjson").write_text("{}\n", encoding="utf-8")
    return root, evidence, stored


def _inventory(root: Path, session_id: str) -> dict:
    return MODULE.archive.inventory_session(
        session_id,
        evidence_root=root / "byq-lifecycle-evidence",
        session_root=root,
        trace_root=root / "gateway",
        boot_id=MODULE.archive.read_boot_id(),
    )


class ReanchorToolTests(unittest.TestCase):
    def test_apply_reanchors_stale_and_is_idempotent_with_reversible_manifest(self):
        root, evidence, stored = _stale_root(tempfile.mkdtemp(), "stale-one")
        argv = [
            "--apply", "--session-root", str(root), "--trace-root", str(root / "gateway"),
            "--session-id", "stale-one", "--timestamp", "20260919T000000Z",
        ]
        self.assertEqual(MODULE.main(argv), 0)

        after = _inventory(root, "stale-one")
        self.assertEqual(after["classification"], "stable")
        self.assertNotEqual(after["stored_lease_identity"], stored)

        output = root / MODULE.DEFAULT_ARCHIVE_NAME / "20260919T000000Z"
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        audit = json.loads((output / "audit.json").read_text(encoding="utf-8"))
        self.assertTrue(manifest["reversible"])
        self.assertFalse(manifest["database_rows_modified"])
        self.assertFalse(manifest["production_data_deleted"])
        self.assertEqual(manifest["sessions"][0]["previous_lease_identity"], stored)
        self.assertEqual(manifest["sessions"][0]["status"], "reanchored")
        self.assertEqual(audit["gateway_lease_binding"], "none")
        self.assertIn("no Gateway cursor", audit["gateway_note"])
        # The adapter also keeps a per-session audit beside the journal.
        audits = list((evidence / "reanchor-audit").glob("stale-one.*.json"))
        self.assertEqual(len(audits), 1)
        detail = json.loads(audits[0].read_text(encoding="utf-8"))
        self.assertEqual(detail["previous_lease_identity"], stored)
        self.assertEqual(detail["lease_identity"], after["stored_lease_identity"])
        self.assertEqual(detail["previous_journal_sha256"],
                         manifest["sessions"][0]["previous_journal_sha256"])

        # Re-running the exact same apply is a no-op.
        self.assertEqual(MODULE.main(argv), 0)

    def test_apply_requires_explicit_selection(self):
        root, _evidence, _stored = _stale_root(tempfile.mkdtemp(), "select-me")
        with self.assertRaises(SystemExit):
            MODULE.main([
                "--apply", "--session-root", str(root), "--trace-root", str(root / "gateway"),
                "--timestamp", "20260919T000001Z",
            ])

    def test_apply_refuses_unknown_session_without_mutation(self):
        root, evidence, stored = _stale_root(tempfile.mkdtemp(), "known")
        before = (evidence / "known.json").read_bytes()
        self.assertEqual(MODULE.main([
            "--apply", "--session-root", str(root), "--trace-root", str(root / "gateway"),
            "--session-id", "never-existed", "--timestamp", "20260919T000002Z",
        ]), 2)
        self.assertEqual((evidence / "known.json").read_bytes(), before)
        self.assertFalse((root / MODULE.DEFAULT_ARCHIVE_NAME).exists())

    def test_current_stable_session_is_a_noop_and_archive_tool_is_unaffected(self):
        root = Path(tempfile.mkdtemp())
        evidence = root / "byq-lifecycle-evidence"
        ctx = {"session_id": "current-one", "trace_id": "current-one-trace",
               "owner": "alice", "workspace_id": "workspace_alice"}
        journal = MODULE.LifecycleJournal.claim(evidence, ctx, create=True)
        journal.close()
        before = (evidence / "current-one.json").read_bytes()
        self.assertEqual(MODULE.main([
            "--apply", "--session-root", str(root), "--trace-root", str(root / "gateway"),
            "--session-id", "current-one", "--timestamp", "20260919T000003Z",
        ]), 0)
        self.assertEqual((evidence / "current-one.json").read_bytes(), before)
        # An already-current selection never creates a reanchor audit record.
        self.assertFalse((evidence / "reanchor-audit").exists())

        entries = MODULE.archive.enumerate_sessions(
            session_root=root, trace_root=root / "gateway",
            boot_id=MODULE.archive.read_boot_id(),
            archive_name="byq-stale-session-archive",
        )
        self.assertEqual([entry["session_id"] for entry in entries], ["current-one"])
        self.assertEqual(entries[0]["classification"], "stable")

    def test_plan_refuses_active_or_unprovable_sessions(self):
        for classification in ("active", "unprovable", "archived"):
            with self.subTest(classification=classification):
                with self.assertRaises(MODULE.ReanchorError):
                    MODULE.plan([{
                        "session_id": "x", "classification": classification, "reason": "r",
                    }])

    def test_session_file_selection_is_supported(self):
        root, _evidence, stored = _stale_root(tempfile.mkdtemp(), "file-one")
        listing = root / "ids.txt"
        listing.write_text("# one per line\n\nfile-one\n", encoding="utf-8")
        self.assertEqual(MODULE.main([
            "--apply", "--session-root", str(root), "--trace-root", str(root / "gateway"),
            "--session-file", str(listing), "--timestamp", "20260919T000004Z",
        ]), 0)
        after = _inventory(root, "file-one")
        self.assertEqual(after["classification"], "stable")
        self.assertNotEqual(after["stored_lease_identity"], stored)

    def test_gateway_stores_no_lease_bound_state(self):
        gateway = Path(__file__).resolve().parents[1] / "services/gateway/app"
        for name in ("trace_store.py", "agent_lifecycle_delivery.py"):
            self.assertNotIn("lease_identity",
                             (gateway / name).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
