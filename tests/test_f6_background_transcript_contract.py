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

from packages.contracts.agent_execution_options import default_agent_execution_options
from packages.contracts.continuation_request import continuation_reservation_v3, validate_reservation_v3
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
                 "_validate_reservation_v3": validate_reservation_v3,
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
        self.receipt = {"status": "settled", "run_id": self.root}

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

    def execute_wait(self, sessions, settlement):
        outer = next(node for node in self.tree.body if isinstance(node, ast.Try) and node.finalbody)
        start = next(i for i, node in enumerate(outer.body) if isinstance(node, ast.Assign)
                     and ast.unparse(node.value) == "'background_one_exact_task_ready_read'")
        end = next(i + 1 for i, node in enumerate(outer.body[start:], start) if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == "request_settlement" for target in node.targets))
        calls = []
        def read_session(*args, timeout):
            calls.append(("session", timeout)); return sessions[min(sum(kind == "session" for kind, _ in calls)-1, len(sessions)-1)]
        def read_audit(*args, **kwargs):
            calls.append(("audit", kwargs.get("runtime_root_id")))
            if settlement is None:
                raise self.ns["EvidenceError"]("settlement_not_visible")
            self.ns["state"]["_settlement_receipt"] = settlement
            return {"runtime_root_id": self.root}
        self.ns.update(gateway_events=types.SimpleNamespace(assert_healthy=lambda: None),
            _session_call=read_session, _read_structured_agent_audit=read_audit, call=object(),
            session_id="conversation", trace_id="trace", task_id="task", backtest_task_id="backtest",
            signal_job_id="signal")
        self.ns["state"]["identities"].update(signal_snapshot_artifact_id="artifact",
            runtime_session_id="byq-session-" + "b" * 32,
            foreground_1_runtime_root_id="e" * 32, foreground_2_runtime_root_id="f" * 32)
        exec(compile(ast.Module(body=outer.body[start:end], type_ignores=[]), str(DRIVER), "exec"), self.ns)
        return calls

    def test_actual_wait_exits_immediately_on_answer_and_settlement(self):
        calls = self.execute_wait([self.view], self.receipt)
        self.assertEqual(len(calls), 2)
        self.assertEqual([kind for kind, _ in calls], ["session", "audit"])
        self.assertEqual(self.clock.sleeps, [])
        self.assertEqual(self.ns["request_settlement"], self.receipt)
        self.assertEqual(self.ns["assistant_answer"], self.answer)
        self.assertEqual(self.ns["state"]["background_wait_observation"]["last_poll"]["background_user_count"], 0)

    def test_actual_wait_answer_and_settlement_can_arrive_independently(self):
        absent = copy.deepcopy(self.view); absent["messages"][-1]["workflow_sequence"] = 2
        calls = self.execute_wait([absent, self.view], self.receipt)
        self.assertEqual([kind for kind, _ in calls], ["session", "session", "audit"])
        self.assertEqual(self.clock.sleeps, [2])
        self.assertTrue(self.ns["state"]["background_wait_observation"]["last_poll"]["exact_answer_ready"])
        with self.assertRaises(self.ns["EvidenceError"]) as missing_settlement:
            self.execute_wait([self.view], None)
        self.assertEqual(missing_settlement.exception.category, "settlement_not_visible")

    def test_actual_wait_does_not_accept_foreground_answer_and_is_bounded(self):
        absent = copy.deepcopy(self.view); absent["messages"][-1]["workflow_sequence"] = 2
        with self.assertRaises(self.ns["EvidenceError"]) as failure:
            self.execute_wait([absent], self.receipt)
        self.assertEqual(failure.exception.category, "background_answer_not_persisted_for_exact_ready_evidence")
        self.assertEqual(self.clock.now, 240)
        self.assertEqual(self.ns["state"]["background_wait_observation"]["last_poll"]["settlement_status"],
                         "not_read_in_public_session")
        self.assertFalse(self.ns["state"]["background_wait_observation"]["last_poll"]["assistant_answer_present"])


class ReadyEventBinding(unittest.TestCase):
    def setUp(self):
        self.ns, _, _ = observer()
        args = dict(owner_principal="f6-chain-user", workspace_id="workspace_" + "1" * 32,
            conversation_id="conversation_" + "2" * 32, task_id="task_" + "3" * 32,
            signal_job_id="signaljob_" + "a" * 32, result_artifact_id="artifact_" + "b" * 32,
            result_artifact_content_sha256="c" * 64,
            options=default_agent_execution_options(), options_revision=0)
        provisional = continuation_reservation_v3(**args, event_key="ready-v1:" + "0" * 64)
        digest = provisional["idempotency_key"].removeprefix("task-ready-event:")
        self.carrier = continuation_reservation_v3(**args, event_key="ready-v1:" + digest)
        self.receipt = {"reservation": self.carrier, "signal_job_id": args["signal_job_id"],
            "reservation_id": "continuation_" + digest[:32], "event_key": "ready-v1:" + digest}

    def test_authoritative_input_projects_only_closed_signal(self):
        self.assertEqual(validate_reservation_v3(self.carrier), self.carrier)
        self.assertNotIn("PRIVATE-", json.dumps(self.carrier))
        self.ns["_assert_background_ready_signal"](self.receipt,
            self.carrier["signal_job_id"], self.carrier["result_artifact_id"])

    def test_corrupt_input_event_and_ambiguous_signal_are_rejected(self):
        for field, value in (("source_fact_sha256", "f" * 64),
                             ("idempotency_key", "task-ready-event:" + "f" * 64),
                             ("event_key", "ready-v1:" + "f" * 64)):
            receipt = copy.deepcopy(self.receipt)
            receipt["reservation"][field] = value
            with self.subTest(field=field), self.assertRaises((ValueError, self.ns["EvidenceError"])):
                self.ns["_assert_background_ready_signal"](receipt,
                    self.carrier["signal_job_id"], self.carrier["result_artifact_id"])

    def test_signal_contract_rejects_foreign_job_artifact_and_private_extra(self):
        for field, value in (("signal_job_status", "running"),
                             ("result_artifact_status", "running"),
                             ("private", "PRIVATE-CANARY")):
            receipt = copy.deepcopy(self.receipt)
            receipt["reservation"][field] = value
            with self.subTest(field=field), self.assertRaises((ValueError, self.ns["EvidenceError"])):
                self.ns["_assert_background_ready_signal"](receipt,
                    self.carrier["signal_job_id"], self.carrier["result_artifact_id"])
        for job, artifact in (("signaljob_" + "f" * 32, self.carrier["result_artifact_id"]),
                              (self.carrier["signal_job_id"], "artifact_" + "f" * 32)):
            with self.assertRaises(self.ns["EvidenceError"]):
                self.ns["_assert_background_ready_signal"](self.receipt, job, artifact)


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
