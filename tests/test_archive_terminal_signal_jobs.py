"""Pure logic and non-destructive behavior tests for the terminal-job audit.

No live database is touched. Database access is proven to be read-only by
inspecting the emitted SQL and by the module's connection contract.
"""
from __future__ import annotations

import importlib
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest import mock

PATH = str(Path(__file__).resolve().parents[1] / "scripts/ops")
sys.path.insert(0, PATH)
try:
    MODULE = importlib.import_module("archive_terminal_signal_jobs")
finally:
    sys.path.remove(PATH)

FORBIDDEN_SQL = ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "GRANT", "CREATE")


def _row(**overrides) -> dict:
    row = {
        "job_id": "signaljob_abc123",
        "owner_principal": "admin",
        "status": "failed",
        "task_id": "task_xyz",
        "task_title": "沪深300 momentum study",
        "conversation_id": "conversation_1",
        "strategy_version_artifact_id": "artifact_strategy",
        "stock_pool_snapshot_id": "stock_pool_snapshot_1",
        "result_artifact_id": None,
        "error_code": "signal_execution_failed",
        "attempt_count": 2,
        "created_at": "2026-09-19T00:00:00+00:00",
        "started_at": "2026-09-19T00:01:00+00:00",
        "finished_at": "2026-09-19T00:02:00+00:00",
        "updated_at": "2026-09-19T00:02:00+00:00",
        "conversation_title": "研究会话",
        "conversation_status": "active",
        "conversation_message_count": 5,
    }
    row.update(overrides)
    return row


class StatusTests(unittest.TestCase):
    def test_only_known_terminal_statuses_are_accepted(self):
        self.assertEqual(MODULE.TERMINAL_STATUSES, ("failed", "completed", "cancelled"))
        self.assertEqual(MODULE.validate_statuses(None), MODULE.TERMINAL_STATUSES)
        self.assertEqual(MODULE.validate_statuses(["failed"]), ("failed",))
        for invalid in ("running", "queued", "waiting_for_data", "archived"):
            with self.assertRaises(MODULE.AuditError):
                MODULE.validate_statuses([invalid])


class QueryTests(unittest.TestCase):
    def test_query_is_read_only_and_parameterised(self):
        query = MODULE.build_query()
        upper = query.upper()
        for keyword in FORBIDDEN_SQL:
            self.assertIsNone(re.search(rf"\b{keyword}\b", upper), keyword)
        self.assertTrue(upper.lstrip().startswith("SELECT"))
        self.assertIn("WHERE J.STATUS = ANY(%S)", upper)
        self.assertIn("LEFT JOIN PRODUCT_CONVERSATIONS", upper)

    def test_owner_filter_is_bound_not_interpolated(self):
        owner = "admin'; DROP TABLE signal_producer_jobs; --"
        query = MODULE.build_query(owner=owner)
        self.assertNotIn(owner, query)
        self.assertIn("AND j.owner_principal = %s", query)
        self.assertIn("ANY(%s)", query)

    def test_connection_is_opened_read_only(self):
        source = Path(MODULE.__file__).read_text(encoding="utf-8")
        self.assertIn("connection.read_only = True", source)
        self.assertNotIn("connection.commit()", source)


class EntryTests(unittest.TestCase):
    def test_entry_links_task_owner_error_and_conversation(self):
        entry = MODULE.build_entry(_row())
        self.assertEqual(entry["job_id"], "signaljob_abc123")
        self.assertEqual(entry["owner_principal"], "admin")
        self.assertEqual(entry["error_code"], "signal_execution_failed")
        self.assertEqual(entry["task"]["task_id"], "task_xyz")
        self.assertEqual(entry["conversation"]["conversation_id"], "conversation_1")
        self.assertEqual(entry["conversation"]["message_count"], 5)
        self.assertEqual(entry["result_artifact_id"], None)
        self.assertEqual(entry["finished_at"], "2026-09-19T00:02:00+00:00")

    def test_entry_without_conversation_is_explicit(self):
        entry = MODULE.build_entry(_row(conversation_id=None))
        self.assertIsNone(entry["conversation"])

    def test_manifest_is_explicitly_non_destructive(self):
        entries = [MODULE.build_entry(_row()),
                   MODULE.build_entry(_row(job_id="signaljob_done", status="completed",
                                           conversation_id=None,
                                           result_artifact_id="artifact_result"))]
        document = MODULE.build_manifest(entries, generated_at="2026-09-19T00:00:00+00:00",
                                         database="<redacted>", owner=None)
        self.assertEqual(document["schema_version"], MODULE.SCHEMA_VERSION)
        self.assertEqual(document["counts"]["total"], 2)
        self.assertEqual(document["counts"]["by_status"]["failed"], 1)
        self.assertEqual(document["counts"]["by_status"]["completed"], 1)
        self.assertEqual(document["counts"]["with_conversation"], 1)
        self.assertFalse(document["database_rows_modified"])
        self.assertFalse(document["production_data_deleted"])
        self.assertTrue(document["archive_requires_domain_action"])
        self.assertEqual(document["domain_archive_mechanism"], "unsupported_signal_jobs")


class ManifestWriteTests(unittest.TestCase):
    def _document(self) -> dict:
        entries = [MODULE.build_entry(_row())]
        return MODULE.build_manifest(entries, generated_at="2026-09-19T00:00:00+00:00",
                                     database="<redacted>", owner=None)

    def test_apply_writes_reversible_manifest_then_is_idempotent(self):
        root = Path(tempfile.mkdtemp())
        archive_root = root / "archive"
        document = self._document()
        manifest, status = MODULE.write_manifest(archive_root, document,
                                                 timestamp="20260919T000000Z")
        self.assertEqual(status, "manifest_written")
        self.assertFalse(manifest["database_rows_modified"])
        path = archive_root / "20260919T000000Z" / "manifest.json"
        self.assertTrue(path.is_file())
        stored = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(stored["schema_version"], MODULE.SCHEMA_VERSION)
        self.assertTrue(stored["reversal"])
        again, status = MODULE.write_manifest(archive_root, document,
                                              timestamp="20260919T000000Z")
        self.assertEqual(status, "already_archived")
        self.assertEqual(again["schema_version"], MODULE.SCHEMA_VERSION)

    def test_apply_refuses_existing_directory_without_manifest(self):
        root = Path(tempfile.mkdtemp())
        archive_root = root / "archive"
        (archive_root / "20260919T000000Z").mkdir(parents=True)
        with self.assertRaises(MODULE.AuditError):
            MODULE.write_manifest(archive_root, self._document(), timestamp="20260919T000000Z")

    def test_apply_rejects_bad_timestamp(self):
        root = Path(tempfile.mkdtemp())
        with self.assertRaises(MODULE.AuditError):
            MODULE.write_manifest(root, self._document(), timestamp="not-a-timestamp")


class CliTests(unittest.TestCase):
    def test_audit_mode_prints_manifest_without_writing_or_db(self):
        entries = [MODULE.build_entry(_row())]
        with mock.patch.object(MODULE, "fetch_terminal_jobs", return_value=entries) as loader:
            buffer = io.StringIO()
            with mock.patch("sys.stdout", buffer):
                code = MODULE.main(["--database-url", "postgresql://byq_app:secret@db/byq_domain"])
        self.assertEqual(code, 0)
        self.assertEqual(loader.call_count, 1)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["mode"], "audit")
        self.assertFalse(payload["database_rows_modified"])
        self.assertEqual(payload["counts"]["total"], 1)

    def test_apply_mode_persists_manifest_and_reports_no_db_change(self):
        entries = [MODULE.build_entry(_row())]
        root = Path(tempfile.mkdtemp())
        with mock.patch.object(MODULE, "fetch_terminal_jobs", return_value=entries):
            buffer = io.StringIO()
            with mock.patch("sys.stdout", buffer):
                code = MODULE.main([
                    "--database-url", "postgresql://byq_app:secret@db/byq_domain",
                    "--apply", "--archive-root", str(root),
                    "--timestamp", "20260919T000000Z",
                ])
        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["mode"], "manifest_written")
        self.assertFalse(payload["database_rows_modified"])
        self.assertTrue((root / "20260919T000000Z" / "manifest.json").is_file())

    def test_fetch_failure_fails_closed(self):
        with mock.patch.object(MODULE, "fetch_terminal_jobs",
                               side_effect=MODULE.AuditError("boom")):
            buffer = io.StringIO()
            with mock.patch("sys.stdout", buffer):
                code = MODULE.main(["--database-url", "postgresql://x@db/byq_domain"])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(buffer.getvalue())["database_rows_modified"], False)


if __name__ == "__main__":
    unittest.main()
