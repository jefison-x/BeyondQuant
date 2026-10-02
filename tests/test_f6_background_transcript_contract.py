"""Offline execution of exact F6 output/readiness and completed public context."""
import ast
import copy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import types
import unittest

from tests.test_f6_gateway_restart_observer import Clock

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "scripts/evidence/f6-chain-verification.py"
FIXTURE = ROOT / "scripts/evidence/f6-chain-fixture.py"
GATEWAY = ROOT / "services/gateway/app/main.py"


def load(path, names, namespace):
    tree = ast.parse(path.read_text())
    nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))
             and node.name in names or isinstance(node, ast.Assign)
             and any(isinstance(target, ast.Name) and target.id in names for target in node.targets)]
    found = {node.name for node in nodes if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    found.update(target.id for node in nodes if isinstance(node, ast.Assign) for target in node.targets
                 if isinstance(target, ast.Name))
    assert found == names, (found, names)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    return tree


def observer():
    clock = Clock()
    namespace = {"time": clock, "json": json, "hashlib": hashlib, "re": re,
                 "state": {"checks": {}, "identities": {}}}
    tree = load(DRIVER, {"require", "EvidenceError", "_messages", "_body_text",
        "_background_answer_for_root", "_assert_background_ready_signal", "_validate_settlement_identity",
        "_background_wait_observation", "_remaining_timeout", "RUNTIME_ROOT_PATTERN",
        "RESERVATION_PATTERN", "SHA256_PATTERN"}, namespace)
    return namespace, clock, tree


def event(sequence, kind, root, timestamp=None):
    item = {"session_id": "conversation", "trace_id": "trace", "source": "runtime-adapter",
            "sequence": sequence, "kind": kind, "payload": {"run_id": root}}
    if timestamp is not None:
        item["timestamp"] = timestamp
    return item


class BackgroundTranscript(unittest.TestCase):
    def setUp(self):
        self.ns, self.clock, self.tree = observer()
        self.root = "a" * 32
        self.answer = "task backtest signal artifact No domain writes were made."
        self.view = {"conversation": {"session_id": "conversation", "trace_id": "trace", "status": "active"},
                     "messages": [{"role": "user", "content": "FG2"},
                         {"role": "assistant", "workflow_sequence": 2, "content": "old foreground"},
                         {"role": "assistant", "workflow_sequence": 12, "content": self.answer}],
                     "events": [event(10, "session.started", self.root), event(13, "session.result", self.root)]}
        self.receipt = {"status": "settled", "dispatch_attempts": 1, "grant_version": 1,
            "run_id": self.root, "reservation_id": "continuation_" + "b" * 32,
            "event_key": "ready-v1:" + "c" * 64, "input_sha256": "d" * 64,
            "settlement_sha256": "e" * 64, "outcome": "completed"}
        self.permission = {"schema_version": "task-continuation-permission.v2",
            "permission": {"grant_version": 1}, "request_state": {"requests_reserved": 1,
            "requests_remaining": 0, "unconfirmed_requests": 0, "request_identity": self.receipt}}

    def select(self):
        return self.ns["_background_answer_for_root"](self.view, self.root)

    def test_exact_durable_answer_without_synthetic_user_or_delta(self):
        self.assertEqual(self.select(), self.answer)
        self.assertFalse(any("task-ready" in row["content"] for row in self.view["messages"]))

    def test_missing_or_other_root_answer_is_not_persistence(self):
        for change in ({"workflow_sequence": 2}, {"workflow_sequence": 10},
                       {"workflow_sequence": 13}, {"workflow_sequence": True}, {"role": "user"}):
            with self.subTest(change=change):
                view = copy.deepcopy(self.view); view["messages"][-1].update(change)
                self.assertIsNone(self.ns["_background_answer_for_root"](view, self.root))

    def test_foreign_scope_and_incomplete_terminal_do_not_match(self):
        for change in ({"session_id": "other"}, {"trace_id": "other"},
                       {"source": "other"}, {"payload": {"run_id": "f" * 32}}):
            with self.subTest(change=change):
                view = copy.deepcopy(self.view); view["events"][-1].update(change)
                self.assertIsNone(self.ns["_background_answer_for_root"](view, self.root))

    def test_duplicate_overlap_and_failed_root_are_rejected(self):
        for additional in (event(10, "session.started", self.root),
                           event(13, "session.result", self.root),
                           event(11, "session.started", "f" * 32)):
            with self.subTest(additional=additional):
                view = copy.deepcopy(self.view); view["events"].append(additional)
                with self.assertRaises(self.ns["EvidenceError"]):
                    self.ns["_background_answer_for_root"](view, self.root)
        self.view["events"][-1]["kind"] = "session.failed"
        with self.assertRaises(self.ns["EvidenceError"]): self.select()

    def test_ordered_fragments_and_duplicate_workflow_sequence(self):
        self.view["messages"].append({"role": "assistant", "workflow_sequence": 11, "content": "first"})
        self.assertEqual(self.select(), "first\n" + self.answer)
        self.view["messages"].append(copy.deepcopy(self.view["messages"][-1]))
        with self.assertRaises(self.ns["EvidenceError"]): self.select()

    def execute_wait(self, permissions, sessions):
        outer = next(node for node in self.tree.body if isinstance(node, ast.Try) and node.finalbody)
        start = next(i for i, node in enumerate(outer.body) if isinstance(node, ast.Assign)
                     and ast.unparse(node.value) == "'background_one_exact_task_ready_read'")
        end = next(i for i, node in enumerate(outer.body[start:], start) if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == "permission_state" for target in node.targets))
        calls = []
        def read_session(*args, timeout):
            calls.append(("session", timeout)); return sessions[min(len(calls)//2, len(sessions)-1)]
        def read_permission(*args, timeout):
            calls.append(("permission", timeout)); return permissions[min((len(calls)-1)//2, len(permissions)-1)]
        self.ns.update(gateway_events=types.SimpleNamespace(assert_healthy=lambda: None),
            _session_call=read_session, _permission_view=read_permission, call=object(),
            session_id="conversation", trace_id="trace", task_id="task", backtest_task_id="backtest",
            signal_job_id="signal", grant_version=1)
        self.ns["state"]["identities"]["signal_snapshot_artifact_id"] = "artifact"
        exec(compile(ast.Module(body=outer.body[start:end], type_ignores=[]), str(DRIVER), "exec"), self.ns)
        return calls

    def test_actual_wait_exits_immediately_on_answer_and_settlement(self):
        calls = self.execute_wait([self.permission], [self.view])
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.clock.sleeps, [])
        self.assertEqual(self.ns["request_settlement"], self.receipt)
        self.assertEqual(self.ns["assistant_answer"], self.answer)
        self.assertEqual(self.ns["state"]["background_wait_observation"]["last_poll"]["background_user_count"], 0)

    def test_actual_wait_answer_and_settlement_can_arrive_independently(self):
        unsettled = copy.deepcopy(self.permission)
        unsettled["request_state"].update(unconfirmed_requests=1)
        unsettled["request_state"]["request_identity"]["status"] = "accepted"
        calls = self.execute_wait([unsettled, self.permission], [self.view])
        self.assertEqual(len(calls), 4)
        self.assertEqual(self.clock.sleeps, [2])
        self.assertTrue(self.ns["state"]["background_wait_observation"]["last_poll"]["exact_answer_ready"])

    def test_actual_wait_does_not_accept_foreground_answer_and_is_bounded(self):
        absent = copy.deepcopy(self.view); absent["messages"][-1]["workflow_sequence"] = 2
        with self.assertRaises(self.ns["EvidenceError"]) as failure:
            self.execute_wait([self.permission], [absent])
        self.assertEqual(failure.exception.category, "background_answer_not_persisted_for_exact_ready_evidence")
        self.assertEqual(self.clock.now, 240)
        self.assertEqual(self.ns["state"]["background_wait_observation"]["last_poll"]["request_status"], "settled")
        self.assertFalse(self.ns["state"]["background_wait_observation"]["last_poll"]["assistant_answer_present"])


class ReadyEventBinding(unittest.TestCase):
    def setUp(self):
        self.ns, _, _ = observer()
        load(FIXTURE, {"_ready_signal_from_receipt", "SIGNAL_JOB_PATTERN", "ARTIFACT_PATTERN", "SHA256_PATTERN"}, self.ns)
        self.signal = {"kind": "signal_producer_jobs", "data_ready": True, "status": "completed",
            "identity": "signaljob_" + "a" * 32, "result_artifact_id": "artifact_" + "b" * 32,
            "updated_at": "2026-10-02T16:00:00+00:00"}
        self.instruction = "PRIVATE-INSTRUCTION-CANARY\nReady signal: " + json.dumps(self.signal) + "\nRead exact task only."
        self.digest = hashlib.sha256(self.instruction.encode()).hexdigest()
        self.event_key = "ready-v1:" + hashlib.sha256(json.dumps(self.signal, sort_keys=True).encode()).hexdigest()

    def test_authoritative_input_projects_only_closed_signal(self):
        signal = self.ns["_ready_signal_from_receipt"](self.instruction, self.digest, self.event_key)
        self.assertEqual(signal, self.signal)
        self.assertNotIn("PRIVATE-", json.dumps(signal))
        self.ns["_assert_background_ready_signal"]({"ready_signal": signal,
            "event_key": self.event_key, "input_sha256": self.digest},
            self.signal["identity"], self.signal["result_artifact_id"])

    def test_corrupt_input_event_and_ambiguous_signal_are_rejected(self):
        for instruction, digest, key in ((self.instruction, "f" * 64, self.event_key),
            (self.instruction, self.digest, "ready-v1:" + "f" * 64),
            (self.instruction + "\nReady signal: " + json.dumps(self.signal), None, self.event_key)):
            with self.subTest(key=key), self.assertRaises(SystemExit):
                self.ns["_ready_signal_from_receipt"](instruction,
                    digest or hashlib.sha256(instruction.encode()).hexdigest(), key)

    def test_signal_contract_rejects_foreign_job_artifact_and_private_extra(self):
        for change in ({"identity": "other"}, {"data_ready": 1}, {"status": "running"},
                       {"result_artifact_id": "other"}, {"private": "PRIVATE-CANARY"}):
            signal = {**self.signal, **change}; instruction = "Ready signal: " + json.dumps(signal)
            with self.subTest(change=change), self.assertRaises(SystemExit):
                self.ns["_ready_signal_from_receipt"](instruction, hashlib.sha256(instruction.encode()).hexdigest(),
                    "ready-v1:" + hashlib.sha256(json.dumps(signal, sort_keys=True).encode()).hexdigest())
        for job, artifact in (("signaljob_" + "f" * 32, self.signal["result_artifact_id"]),
                              (self.signal["identity"], "artifact_" + "f" * 32)):
            with self.assertRaises(self.ns["EvidenceError"]):
                self.ns["_assert_background_ready_signal"]({"ready_signal": self.signal,
                    "event_key": self.event_key, "input_sha256": self.digest}, job, artifact)


class CompletedPublicContext(unittest.TestCase):
    def setUp(self):
        self.ns = {"datetime": datetime}
        delivery = ROOT / "services/gateway/app/agent_lifecycle_delivery.py"
        cls = next(node for node in ast.parse(delivery.read_text()).body if isinstance(node, ast.ClassDef)
                   and node.name == "LifecycleDelivery")
        project = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "_project")
        exec(compile(ast.Module(body=[project], type_ignores=[]), str(delivery), "exec"), self.ns)
        project_method = self.ns["_project"]
        self.ns["answer_delivery"] = types.SimpleNamespace(_project=lambda event, ctx:
            project_method(types.SimpleNamespace(private_source=None), event, ctx))
        load(GATEWAY, {"_event_time", "_runtime_events", "_successful_public_answers", "_completed_public_messages"}, self.ns)
        self.events = []
        self.messages = []

    def root(self, name, offset, start, end, answer):
        started = event(offset, "session.started", name, start)
        output = event(offset+1, "agent.output.delta", name, start)
        output["payload"] = {"schema_version": "workflow-answer.v1", "channel": "answer", "delta": answer}
        self.events.extend([started, output, event(offset+2, "session.result", name, end)])
        self.messages.append({"sequence": len(self.messages)+1, "role": "assistant", "content": answer,
                              "workflow_sequence": offset+1, "created_at": end})

    def user(self, content, created):
        self.messages.append({"sequence": len(self.messages)+1, "role": "user", "content": content, "created_at": created})

    def selected(self):
        return self.ns["_completed_public_messages"](self.messages, self.events, "conversation", "trace")

    def test_completed_automatic_answer_with_no_user_is_public_context(self):
        self.root("bg", 1, "2026-10-02T16:00:01Z", "2026-10-02T16:00:02Z", "public update")
        self.assertEqual(self.selected(), self.messages)

    def test_two_foreground_pairs_and_background_actual_roles_are_preserved(self):
        self.user("FG1", "2026-10-02T16:00:00Z")
        self.root("fg1", 1, "2026-10-02T16:00:01Z", "2026-10-02T16:00:02Z", "first answer")
        self.user("FG2", "2026-10-02T16:00:03Z")
        self.root("fg2", 4, "2026-10-02T16:00:04Z", "2026-10-02T16:00:05Z", "second answer")
        self.root("bg", 7, "2026-10-02T16:00:06Z", "2026-10-02T16:00:07Z", "background answer")
        self.assertEqual(self.selected(), self.messages)
        self.assertEqual([row["role"] for row in self.selected()], ["user", "assistant", "user", "assistant", "assistant"])

    def test_failed_old_user_is_not_borrowed_by_completed_automatic_root(self):
        self.user("failed private task", "2026-10-02T16:00:00Z")
        self.events.extend([event(1, "session.started", "failed", "2026-10-02T16:00:01Z"),
                            event(2, "session.failed", "failed", "2026-10-02T16:00:02Z")])
        self.root("bg", 3, "2026-10-02T16:00:03Z", "2026-10-02T16:00:04Z", "public update")
        self.assertEqual(self.selected(), self.messages[1:])

    def test_invalid_root_interval_fails_closed(self):
        self.user("old", "2026-10-02T16:00:00Z")
        self.events.append(event(1, "session.result", "old", "invalid"))
        self.root("bg", 2, "2026-10-02T16:00:02Z", "2026-10-02T16:00:03Z", "public update")
        self.assertEqual(self.selected(), [])

    def test_failed_current_root_and_mismatched_answer_do_not_enter_context(self):
        self.user("question", "2026-10-02T16:00:00Z")
        self.root("root", 1, "2026-10-02T16:00:01Z", "2026-10-02T16:00:02Z", "partial")
        self.events[-1]["kind"] = "session.failed"
        self.assertEqual(self.selected(), [])
        self.events[-1]["kind"] = "session.result"
        self.messages[-1]["content"] = "different persisted value"
        self.assertEqual(self.selected(), [])


if __name__ == "__main__":
    unittest.main()
