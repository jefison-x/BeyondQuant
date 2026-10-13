"""Offline contract tests for the task-specific ACP observer (synthetic only)."""
from __future__ import annotations

import importlib.util
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("acp-ordinary-continuous-observer.py")
SPEC = importlib.util.spec_from_file_location("ordinary_observer", SCRIPT)
observer = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(observer)


class OrdinaryObserverContractTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self._capture()

    def tearDown(self):
        self.temp.cleanup()

    def put(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def get(self, name):
        return json.loads((self.root / name).read_text(encoding="utf-8"))

    def _capture(self):
        self.put("batch-clock.json", {"schema_version": "byq-ordinary-capture-clock.v1",
            "boot_id": "00000000-0000-0000-0000-000000000001", "started_monotonic_ns": 100,
            "deadline_monotonic_ns": 240000000100, "started_utc": "2026-10-13T00:00:00+00:00",
            "budget_seconds": 240})
        self.put("authorized-login-writes.json", {
            "schema_version": "byq-ordinary-capture-authorized-login-writes.v1",
            "durable_login_may_write_auth_sessions": True, "business_jobs_created_by_capture": False})
        for action in ("preflight", "turn-1", "turn-2", "finish"):
            self.put(f"checkpoint-{action}-pass.json", {"action": action, "status": "PASS"})
        jobs = {name: 0 for name in ("backtest_jobs", "data_sync_jobs", "factor_jobs",
            "market_session_sync_jobs", "ml_prediction_runs", "ml_training_runs",
            "optimization_jobs", "security_master_sync_jobs", "signal_producer_jobs",
            "research_tasks", "artifacts")}
        self.put("jobs-before.json", jobs)
        self.put("jobs-after.json", jobs)
        containers = {"project": "byq-dev-e8b02b5475",
            "requested_ids": {"gateway": "1" * 12, "adapter": "2" * 12,
                "runner": "3" * 12, "postgres": "4" * 12},
            "containers": {"gateway": {"id": "1" * 64}, "adapter": {"id": "2" * 64},
                "runner": {"id": "3" * 64}, "postgres": {"id": "4" * 64}}}
        self.put("container-facts-preflight.json", containers)
        self.put("container-facts-finish-final.json", containers)
        scope = {"conversation_id": "conv-1", "runtime_session_id": "sess-1", "trace_id": "trace-1",
                 "workspace_id": "ws-1", "owner_principal": "user-1", "actor_principal": "user-1"}
        self.put("scope.json", scope)
        r1, r2 = "1" * 32, "2" * 32
        u1, u2 = "first request", "second request"
        trace = []
        for seq, root, answer in ((1, r1, "first answer"), (4, r2, "second answer")):
            trace.extend([
                self.event(seq, "session.started", {"run_id": root}),
                self.event(seq + 1, "agent.output.delta", {"schema_version": "workflow-answer.v1",
                    "channel": "answer", "delta": answer, "truncated": False}),
                self.event(seq + 2, "session.result", {"run_id": root}),
            ])
        self.put("trace.json", trace)
        messages = [
            {"message_id": "u1", "sequence": 1, "role": "user", "content": u1, "workflow_sequence": None},
            {"message_id": "a1", "sequence": 2, "role": "assistant", "content": "first answer", "workflow_sequence": 2},
            {"message_id": "u2", "sequence": 3, "role": "user", "content": u2, "workflow_sequence": None},
            {"message_id": "a2", "sequence": 4, "role": "assistant", "content": "second answer", "workflow_sequence": 5},
        ]
        self.put("conversation.json", {"conversation": {"session_id": "conv-1", "trace_id": "trace-1"},
                                        "messages": messages})
        self.put("native-projection.json", {
            "schema_version": "byq-native-session-input-projection.v1",
            "producer_source_sha256": observer._NATIVE_PROJECTION_SOURCE_SHA256,
            "native_session_id": "native-1", "compressed_sha256": "c" * 64,
            "compressed_bytes": 1024, "header_id": "native-1", "header_version": 4,
            "human_input_sha256_order": [observer._sha(u1.encode()), observer._sha(u2.encode())],
        })
        for root, generation in ((r1, "gen-1"), (r2, "gen-2")):
            self.put(f"binding-snapshots/{root}.json", {
                "schema_version": "byq-acp-root-binding.v1", "session_id": "sess-1", "trace_id": "trace-1",
                "owner_principal": "user-1", "workspace_id": "ws-1", "root_run_id": root,
                "native_session_id": "native-1", "runtime_generation": generation,
                "previous_boot_id": "boot-1",
                "settlement_receipt": {"schema_version": "agent-run-lifecycle-receipt.v1", "root_run_id": root,
                                        "sequence": 3 if root == r1 else 6,
                                        "event_sha256": "a" * 64 if root == r1 else "b" * 64},
            })
        generation_by_root = {r1: "gen-1", r2: "gen-2"}
        terminals, acks = [], []
        for root, seq, digest in ((r1, 3, "a" * 64), (r2, 6, "b" * 64)):
            terminals.append({"root_run_id": root, "status": "completed", "authority_status": "closed",
                              "terminal_sequence": seq, "terminal_event_sha256": digest,
                              "terminal_unknown_claim_count": 0, "terminal_unknown_claims_sha256": "f" * 64})
            acks.append({"schema_version": "agent-run-lifecycle-receipt.v1", "root_run_id": root,
                         "sequence": seq, "event_sha256": digest})
            path = self.root / f"journals/product-turn-provider-request-{root}.jsonl"
            generation = generation_by_root[root]
            admitted = {
                "schema_version": "continuation-request-gate.v1", "request_id": "product-turn-" + generation,
                "phase": "admitted", "role": "root", "call": 1, "attempt": 1,
                "input_bytes": 10, "declared_max_output_tokens": 128, "tool_payload_bytes": 0,
                "admitted": True, "reason": "within_request_budget", "at_ms": 1000,
            }
            completed = {
                **admitted, "phase": "completed", "status": 200, "forwarded": True,
                "elapsed_ms": 25, "completed_at_ms": 1025, "actual_input_tokens": 10,
                "actual_cache_read_tokens": 0, "actual_output_tokens": 4,
                "usage_source": "provider_response",
            }
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(json.dumps(row) for row in (
                admitted, completed,
            )) + "\n", encoding="utf-8")
        self.put("terminal.json", {"schema_version": "byq-business-root-status.v1", "roots": terminals})
        ack_events = [{
                "schema_version": "byq-gateway-terminal-ack-observed.v1",
                "event": "terminal_ack_observed", "root_run_id": root, "session_id": "sess-1",
                "boot_id": "boot-1", "trace_id": "trace-1", "sequence": seq,
                "event_sha256": digest, "outcome": "completed",
            } for root, seq, digest in ((r1, 3, "a" * 64), (r2, 6, "b" * 64))]
        self.put("gateway-ack-observed.json", {
            "schema_version": "byq-gateway-terminal-ack-observed-set.v1", "events": ack_events,
        })
        lines = []
        for row in ack_events:
            marker = "terminal_ack_observed " + json.dumps(row, separators=(",", ":"))
            lines.append({"line_bytes": len(marker.encode()), "line_sha256": hashlib.sha256(marker.encode()).hexdigest(),
                          "matched_line": marker})
        self.put("gateway-ack-original-matches.json", {
            "schema_version": "byq-gateway-terminal-ack-lines.v1", "lines": lines,
        })
        for turn in (1, 2):
            self.put(f"delivery-turn-{turn}.json", {
                "schema_version": "public-answer-delivery-status.v1", "state": "up_to_date",
                "pending_events": 0, "exhausted_events": 0, "rejected_events": 0,
            })

    @staticmethod
    def event(sequence, kind, payload):
        return {"trace_id": "trace-1", "session_id": "conv-1", "sequence": sequence,
                "timestamp": "2026-10-11T00:00:00Z", "kind": kind,
                "source": "runtime-adapter", "payload": payload}

    def assert_rejected(self, expected_failure):
        result = observer.inspect(self.root)
        self.assertEqual("FAIL", result["status"], result)
        self.assertTrue(any(expected_failure in failure for failure in result["failures"]), result)

    def test_contract_shaped_capture_passes_offline_only(self):
        self.assertEqual("PASS", observer.inspect(self.root)["status"])

    def test_duplicate_native_input_is_rejected(self):
        value = self.get("native-projection.json")
        value["human_input_sha256_order"] = [value["human_input_sha256_order"][0]] * 2
        self.put("native-projection.json", value)
        self.assert_rejected("native human input hashes/order differ")

    def test_wrong_native_header_id_is_rejected(self):
        path = self.root / "native-projection.json"
        projection = self.get("native-projection.json")
        projection["header_id"] = "foreign-native"
        self.put("native-projection.json", projection)
        self.assert_rejected("native header.id does not match the binding identity")

    def test_missing_ack_and_none_none_cannot_pass(self):
        self.put("terminal.json", {"schema_version": "byq-business-root-status.v1", "roots": [
            {"root_run_id": "1" * 32, "status": "completed", "authority_status": "closed",
             "terminal_sequence": None, "terminal_event_sha256": None}]})
        binding = self.get(f"binding-snapshots/{'1' * 32}.json")
        binding["settlement_receipt"] = {"schema_version": "agent-run-lifecycle-receipt.v1",
                                          "root_run_id": "1" * 32, "sequence": None, "event_sha256": None}
        self.put(f"binding-snapshots/{'1' * 32}.json", binding)
        self.assert_rejected("persisted settlement receipt does not match Backend terminal")

    def test_persisted_receipt_without_gateway_log_is_not_ack(self):
        self.put("gateway-ack-observed.json", {
            "schema_version": "byq-gateway-terminal-ack-observed-set.v1", "events": [],
        })
        self.assert_rejected("Gateway observed ACK log roots must match one-to-one")

    def test_gateway_ack_wrong_boot_is_rejected(self):
        receipt = self.get("gateway-ack-observed.json")
        receipt["events"][0]["boot_id"] = "foreign-boot"
        self.put("gateway-ack-observed.json", receipt)
        self.assert_rejected("lacks a matching observed Gateway terminal ACK tuple")

    def test_wrong_persisted_answer_is_rejected(self):
        conv = self.get("conversation.json")
        conv["messages"][1]["content"] = "wrong answer"
        self.put("conversation.json", conv)
        self.assert_rejected("persisted assistant content differs")

    def test_product_messages_must_follow_two_root_turn_order(self):
        conv = self.get("conversation.json")
        conv["messages"][1]["sequence"] = 3
        conv["messages"][2]["sequence"] = 2
        self.put("conversation.json", conv)
        self.assert_rejected("Product message sequence must be user1, all root1 answers, user2, all root2 answers")

    def test_foreign_native_source_is_rejected(self):
        projection = self.get("native-projection.json")
        projection["producer_source_sha256"] = "0" * 64
        self.put("native-projection.json", projection)
        self.assert_rejected("native session input projection does not match")

    def test_missing_journal_completion_is_rejected(self):
        root = "1" * 32
        path = self.root / f"journals/product-turn-provider-request-{root}.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        path.write_text(json.dumps(rows[0]) + "\n")
        self.assert_rejected("has admitted requests without completion")

    def test_foreign_binding_owner_is_rejected(self):
        path = f"binding-snapshots/{'1' * 32}.json"
        binding = self.get(path)
        binding["owner_principal"] = "other-user"
        self.put(path, binding)
        self.assert_rejected("binding identity does not match request scope: owner_principal")

    def test_http_500_is_rejected(self):
        root = "1" * 32
        path = self.root / f"journals/product-turn-provider-request-{root}.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[1]["status"] = 500
        path.write_text("\n".join(json.dumps(x) for x in rows) + "\n")
        self.assert_rejected("not completed HTTP 200/forwarded")

    def test_unknown_journal_outcome_is_rejected(self):
        root = "1" * 32
        path = self.root / f"journals/product-turn-provider-request-{root}.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[1]["phase"] = "unknown"
        path.write_text("\n".join(json.dumps(x) for x in rows) + "\n")
        self.assert_rejected("rejected/aborted/unknown phase unknown")

    def test_concurrent_journal_admissions_are_rejected(self):
        root = "1" * 32
        path = self.root / f"journals/product-turn-provider-request-{root}.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        concurrent = dict(rows[0])
        concurrent.update({"attempt": 2, "call": 2, "at_ms": 1001})
        rows.insert(1, concurrent)
        path.write_text("\n".join(json.dumps(x) for x in rows) + "\n")
        self.assert_rejected("exceeded attempts=16 or concurrency=1")

    def test_wrapped_trace_and_deleted_journals_cannot_bypass_checks(self):
        self.put("trace.json", {"events": []})
        for path in (self.root / "journals").glob("*.jsonl"):
            path.write_text("")
        self.assert_rejected("trace.json must be the actual SSE extracted WorkflowTrace event array, not a wrapper")

    def test_empty_per_root_journals_cannot_pass(self):
        for path in (self.root / "journals").glob("*.jsonl"):
            path.write_text("")
        self.assert_rejected("must contain at least one admitted/completed request pair")

    def test_fake_journal_schema_is_rejected(self):
        path = self.root / f"journals/product-turn-provider-request-{'1' * 32}.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[0]["schema_version"] = "byq-provider-request-journal.v1"
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        self.assert_rejected("contains invalid row schema")


if __name__ == "__main__":
    unittest.main()
