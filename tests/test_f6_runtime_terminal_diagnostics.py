"""Offline proof that F6 diagnostic wrappers cannot change SDK execution."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("f6_runtime_diagnostics", ROOT / "services/runtime-adapter/tests/f6_runtime_diagnostics.py")
diagnostics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostics)


class JsonRpcError(Exception):
    pass


class RuntimeHook(unittest.TestCase):
    def run_hook(self, *, failure=False, bad_storage=False):
        calls, callbacks, observed = [], [], []
        class Compatibility:
            @staticmethod
            def run_prepared_prompt(prepared, content, callback):
                calls.append((prepared, content))
                callback("PRIVATE-NOTIFICATION-CANARY")
                if failure:
                    raise JsonRpcError("PRIVATE-SDK-ERROR-CANARY")
                return "completed"
        class Adapter:
            def _run_prompt(self, record, active_run, *args, **kwargs):
                try:
                    value = Compatibility.run_prepared_prompt("prepared", "PRIVATE-PROMPT-CANARY", callbacks.append)
                except JsonRpcError:
                    record.status = "failed"
                    record.history = [{"kind": "session.failed", "payload": {"run_id": active_run.run_id, "error": "JsonRpcError"}}]
                    raise
                record.status = "idle"
                record.history = [{"kind": "session.result", "payload": {"run_id": active_run.run_id}}]
                record.budget_receipts[record.continuation_budget["reservation_id"]] = {"status": "settled", "outcome": "completed"}
                record.process_closed = record.continuation_proxy_closed = True
                record.active_run = None
                return value
        fake_runtime = types.SimpleNamespace(RuntimeAdapter=Adapter, compatibility_for_release=lambda *_: Compatibility())
        fake_app = types.ModuleType("app");fake_app.__path__ = [];fake_app.runtime = fake_runtime
        fake_budget = types.ModuleType("app.continuation_budget")
        fake_budget.read_request_guard = lambda *_a, **_k: {"tool_calls": 7, "blocked_reason": None}
        reservation = "continuation_" + "b" * 32
        record = types.SimpleNamespace(lock=threading.RLock(), continuation_budget={"reservation_id": reservation},
            budget_run_id="a" * 32, session_id="byq-session-" + "c" * 32, budget_receipts={},
            history=[], status="running", active_run=object(), process_closed=False, process_closing=False,
            continuation_proxy_closed=False, budget_journal=Path("/tmp/synthetic-guard"),
            continuation_request_gate=types.SimpleNamespace(receipts=lambda: [], request_usage=lambda **_: {
                "admission_usage": {"provider_attempts": 8}, "actual_usage": {"completeness": "unknown"}, "limit_violations": []}))
        def store(row):
            if bad_storage: raise OSError("PRIVATE-STORAGE-CANARY")
            observed.append(row)
        sink = types.SimpleNamespace(record=store)
        output = io.StringIO()
        with patch.dict("sys.modules", {"app": fake_app, "app.runtime": fake_runtime, "app.continuation_budget": fake_budget}):
            diagnostics.install(sink)
            with contextlib.redirect_stdout(output):
                if failure:
                    with self.assertRaises(JsonRpcError): Adapter()._run_prompt(record, types.SimpleNamespace(run_id="a" * 32))
                    result = "original_exception_retained"
                else:
                    result = Adapter()._run_prompt(record, types.SimpleNamespace(run_id="a" * 32))
        return result, calls, callbacks, observed, output.getvalue()

    def test_success_records_three_phases_and_calls_original_sdk_once(self):
        result, calls, callbacks, rows, output = self.run_hook()
        self.assertEqual(result, "completed")
        self.assertEqual(len(calls), 1);self.assertEqual(len(callbacks), 1)
        self.assertEqual([row["record_type"] for row in rows], ["background_started", "native_finished", "background_terminal"])
        self.assertEqual(rows[0]["native_finish"], "not_returned")
        self.assertEqual(rows[1]["native_finish"], "completed")
        self.assertFalse(rows[1]["process_closed"])
        self.assertEqual(rows[1]["receipt_cache_status"], "not_cached")
        self.assertEqual(rows[2]["receipt_cache_status"], "settled")
        self.assertTrue(rows[2]["process_closed"])
        self.assertTrue(rows[2]["usage_observed"])
        self.assertEqual(rows[2]["usage_completeness"], "unknown")
        self.assertNotIn("PRIVATE-", json.dumps(rows) + output)

    def test_sdk_exception_and_terminal_class_are_retained_without_error_text(self):
        result, calls, callbacks, rows, output = self.run_hook(failure=True)
        self.assertEqual(result, "original_exception_retained")
        self.assertEqual(len(calls), 1);self.assertEqual(len(callbacks), 1)
        self.assertEqual(rows[1]["native_finish"], "exception")
        self.assertEqual(rows[2]["terminal_kind"], "session.failed")
        self.assertEqual(rows[2]["terminal_exception_kind"], "JsonRpcError")
        self.assertNotIn("PRIVATE-", json.dumps(rows) + output)

    def test_diagnostic_storage_failure_does_not_modify_return_or_retry_sdk(self):
        result, calls, callbacks, rows, output = self.run_hook(bad_storage=True)
        self.assertEqual(result, "completed")
        self.assertEqual(len(calls), 1);self.assertEqual(len(callbacks), 1)
        self.assertEqual(rows, [])
        self.assertNotIn("PRIVATE-", output)
        self.assertEqual(output.count("diagnostic unavailable"), 3)

    def test_journal_is_exclusive_private_and_bounded_without_acceptance_claim(self):
        with tempfile.TemporaryDirectory(prefix="byq-runtime-diagnostics-") as directory:
            destination = Path(directory) / "journal.jsonl"
            recorder = diagnostics.RuntimeDiagnostics(destination)
            try:
                for _ in range(20): recorder.record({"schema_version": diagnostics.SCHEMA})
            finally: recorder.close()
            self.assertEqual(len(destination.read_bytes().splitlines()), 8)
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            before = destination.read_bytes()
            with self.assertRaises(FileExistsError): diagnostics.RuntimeDiagnostics(destination)
            self.assertEqual(destination.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
