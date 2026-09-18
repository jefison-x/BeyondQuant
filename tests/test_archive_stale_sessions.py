"""Pure classification/planning tests for the stale-session archive tool.

No live runtime, filesystem roots beyond ``tmp_path`` or database are touched.
"""
from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

PATH = str(Path(__file__).resolve().parents[1] / "scripts/ops")
sys.path.insert(0, PATH)
try:
    MODULE = importlib.import_module("archive_stale_sessions")
finally:
    sys.path.remove(PATH)


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


def _stale_entry(root: Path, session_id: str) -> dict:
    evidence = root / "byq-lifecycle-evidence"
    lock = _write_lock(evidence, session_id)
    stat = lock.stat()
    stored = MODULE.compute_lease_identity("old-boot", stat.st_dev, stat.st_ino, "a" * 32)
    _write_journal(evidence, session_id, lease_identity=stored)
    (root / session_id).mkdir()
    (root / session_id / "dsh-state.json").write_text("{}", encoding="utf-8")
    (root / "gateway").mkdir(exist_ok=True)
    (root / "gateway" / f"{session_id}.ndjson").write_text("{}\n", encoding="utf-8")
    return MODULE.inventory_session(
        session_id, evidence_root=evidence,
        session_root=root, trace_root=root / "gateway", boot_id="new-boot",
    )


class LeaseClassificationTests(unittest.TestCase):
    def test_identity_uses_the_adapter_formula(self):
        boot = "11111111-2222-3333-4444-555555555555"
        token = "a" * 32
        expected = hashlib.sha256(f"{boot}:7:9:{token}".encode()).hexdigest()
        self.assertEqual(MODULE.compute_lease_identity(boot, 7, 9, token), expected)

    def test_classify_lease_states(self):
        identity = "b" * 64
        self.assertEqual(MODULE.classify_lease(identity, identity), "current")
        self.assertEqual(MODULE.classify_lease(identity, "c" * 64), "stale")
        self.assertEqual(MODULE.classify_lease(identity, identity, lock_held=True), "active")
        self.assertEqual(MODULE.classify_lease(None, identity), "unprovable")
        self.assertEqual(MODULE.classify_lease(identity, "not-hex"), "unprovable")
        self.assertEqual(MODULE.classify_lease("short", identity), "unprovable")

    def test_read_journal_state_rejects_tampering_and_missing_fields(self):
        directory = Path(tempfile.mkdtemp())
        journal = _write_journal(directory, "tamper-me", lease_identity="d" * 64)
        envelope = json.loads(journal.read_text(encoding="utf-8"))
        envelope["sha256"] = "0" * 64
        journal.write_text(json.dumps(envelope, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        with self.assertRaises(MODULE.ArchiveError):
            MODULE.read_journal_state(journal)

        journal.write_text(json.dumps({"schema_version": "byq-lifecycle-journal.v3"}),
                           encoding="utf-8")
        with self.assertRaises(MODULE.ArchiveError):
            MODULE.read_journal_state(journal)


class InventoryTests(unittest.TestCase):
    def test_stale_lease_is_detected_with_mismatch_evidence(self):
        root = Path(tempfile.mkdtemp())
        evidence = root / "byq-lifecycle-evidence"
        lock = _write_lock(evidence, "stale-one")
        stat = lock.stat()
        stored = MODULE.compute_lease_identity("old-boot-id", stat.st_dev, stat.st_ino, "a" * 32)
        journal = _write_journal(evidence, "stale-one", lease_identity=stored)
        entry = MODULE.inventory_session(
            "stale-one", evidence_root=evidence,
            session_root=root, trace_root=root, boot_id="new-boot-id",
        )
        self.assertEqual(entry["classification"], "stale")
        self.assertEqual(entry["stored_lease_identity"], stored)
        self.assertNotEqual(entry["stored_lease_identity"], entry["current_lease_identity"])
        self.assertEqual(entry["journal_path"], str(journal))
        self.assertEqual(entry["owner"], "alice")
        self.assertIn("boot", entry["reason"])

    def test_current_lease_is_unaffected(self):
        root = Path(tempfile.mkdtemp())
        evidence = root / "byq-lifecycle-evidence"
        lock = _write_lock(evidence, "current-one")
        stat = lock.stat()
        stored = MODULE.compute_lease_identity("same-boot-id", stat.st_dev, stat.st_ino, "a" * 32)
        _write_journal(evidence, "current-one", lease_identity=stored)
        entry = MODULE.inventory_session(
            "current-one", evidence_root=evidence,
            session_root=root, trace_root=root, boot_id="same-boot-id",
        )
        self.assertEqual(entry["classification"], "current")

    def test_missing_lock_and_unknown_session_are_unprovable(self):
        root = Path(tempfile.mkdtemp())
        evidence = root / "byq-lifecycle-evidence"
        _write_journal(evidence, "no-lock", lease_identity="e" * 64)
        entry = MODULE.inventory_session(
            "no-lock", evidence_root=evidence,
            session_root=root, trace_root=root, boot_id="boot",
        )
        self.assertEqual(entry["classification"], "unprovable")
        missing = MODULE.inventory_session(
            "never-existed", evidence_root=evidence,
            session_root=root, trace_root=root, boot_id="boot",
        )
        self.assertEqual(missing["classification"], "unprovable")


class PlanTests(unittest.TestCase):
    def test_plan_only_contains_stale_sessions_and_is_pure(self):
        root = Path(tempfile.mkdtemp())
        stale = _stale_entry(root, "stale-plan")
        current = dict(stale, session_id="current-plan", classification="current")
        archive_root = root / "archive" / "ts"
        gateway_root = root / "gateway-archive" / "ts"
        moves = MODULE.plan_archive([stale, current], archive_root=archive_root,
                                    gateway_archive_root=gateway_root)
        kinds = {move["kind"] for move in moves}
        self.assertEqual(kinds, {"journal", "lock", "session_dir", "trace"})
        self.assertTrue(all(move["session_id"] == "stale-plan" for move in moves))
        self.assertTrue(all(
            str(archive_root) in move["destination"] or str(gateway_root) in move["destination"]
            for move in moves
        ))
        # Pure planning created nothing on disk.
        self.assertFalse(archive_root.exists())
        self.assertFalse(gateway_root.exists())

    def test_apply_moves_and_is_reversible_then_idempotent(self):
        root = Path(tempfile.mkdtemp())
        stale = _stale_entry(root, "stale-apply")
        archive_root = root / "archive" / "ts"
        gateway_root = root / "gateway-archive" / "ts"
        moves = MODULE.plan_archive([stale], archive_root=archive_root,
                                    gateway_archive_root=gateway_root)
        manifest, status = MODULE.apply_archive(
            [stale], moves, archive_root=archive_root, boot_id="new-boot",
            timestamp="20260919T000000Z", session_root=root, trace_root=root / "gateway",
        )
        self.assertEqual(status, "archived")
        self.assertFalse((root / "byq-lifecycle-evidence" / "stale-apply.json").exists())
        self.assertFalse((root / "byq-lifecycle-evidence" / "stale-apply.lock").exists())
        self.assertFalse((root / "stale-apply").exists())
        self.assertFalse((root / "gateway" / "stale-apply.ndjson").exists())
        self.assertTrue((archive_root / "stale-apply" / "dsh-session" / "dsh-state.json").is_file())
        self.assertTrue((gateway_root / "stale-apply.ndjson").is_file())
        self.assertTrue((archive_root / "manifest.json").is_file())
        self.assertFalse(manifest["database_rows_modified"])
        self.assertFalse(manifest["production_data_deleted"])
        self.assertTrue(manifest["reversible"])
        for record in manifest["files"]:
            self.assertEqual(record["sha256"], MODULE.sha256_file(Path(record["archived_path"])))
            self.assertTrue(record["original_path"])
            self.assertIn("session_id", record)
        # Re-applying the same plan is an idempotent no-op.
        again, status = MODULE.apply_archive(
            [stale], moves, archive_root=archive_root, boot_id="new-boot",
            timestamp="20260919T000000Z", session_root=root, trace_root=root / "gateway",
        )
        self.assertEqual(status, "already_archived")
        self.assertEqual(again["schema_version"], MODULE.SCHEMA_VERSION)

    def test_enumerate_marks_already_archived_sessions(self):
        root = Path(tempfile.mkdtemp())
        stale = _stale_entry(root, "stale-enum")
        archive_root = root / "byq-stale-session-archive" / "20260919T000000Z"
        gateway_root = root / "gateway" / "byq-stale-session-archive" / "20260919T000000Z"
        moves = MODULE.plan_archive([stale], archive_root=archive_root,
                                    gateway_archive_root=gateway_root)
        MODULE.apply_archive(
            [stale], moves, archive_root=archive_root, boot_id="new-boot",
            timestamp="20260919T000000Z", session_root=root, trace_root=root / "gateway",
        )
        # Re-create only the journal to prove the enumeration reports it archived.
        stored = stale["stored_lease_identity"]
        _write_journal(root / "byq-lifecycle-evidence", "stale-enum", lease_identity=stored)
        entries = MODULE.enumerate_sessions(
            session_root=root, trace_root=root / "gateway", boot_id="new-boot",
            archive_name="byq-stale-session-archive",
        )
        by_id = {entry["session_id"]: entry for entry in entries}
        self.assertEqual(by_id["stale-enum"]["classification"], "archived")

    def test_apply_refuses_existing_directory_without_manifest(self):
        root = Path(tempfile.mkdtemp())
        stale = _stale_entry(root, "stale-refuse")
        archive_root = root / "archive" / "ts"
        archive_root.mkdir(parents=True)
        with self.assertRaises(MODULE.ArchiveError):
            MODULE.apply_archive(
                [stale], MODULE.plan_archive(
                    [stale], archive_root=archive_root,
                    gateway_archive_root=root / "gateway-archive" / "ts"),
                archive_root=archive_root, boot_id="new-boot", timestamp="20260919T000000Z",
                session_root=root, trace_root=root / "gateway",
            )

    def test_apply_refuses_a_source_that_escapes_its_root(self):
        root = Path(tempfile.mkdtemp())
        outside = root / "outside.ndjson"
        outside.write_text("{}\n", encoding="utf-8")
        entry = {
            "session_id": "escape", "classification": "stale", "reason": "x",
            "stored_lease_identity": "a" * 64, "current_lease_identity": "b" * 64,
            "owner": None, "workspace_id": None, "conversation": None,
            "conversation_lookup": "not_configured", "journal_path": None,
            "lock_path": None, "session_dir": None, "trace_path": str(outside),
        }
        archive_root = root / "archive" / "ts"
        moves = MODULE.plan_archive(
            [entry], archive_root=archive_root,
            gateway_archive_root=root / "gateway-archive" / "ts")
        with self.assertRaises(MODULE.ArchiveError):
            MODULE.apply_archive(
                [entry], moves, archive_root=archive_root, boot_id="new-boot",
                timestamp="20260919T000000Z", session_root=root, trace_root=root / "gateway",
            )


if __name__ == "__main__":
    unittest.main()
