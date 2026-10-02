"""Offline execution of current F6 restart control flow and Product projection."""
import ast
import copy
import contextlib
import hashlib
import io
import os
import json
import re
from pathlib import Path
import types
import tempfile
import unittest
import threading
import urllib.error
from urllib.request import Request
from email.message import Message

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "scripts/evidence/f6-chain-verification.py"
GATEWAY = ROOT / "services/gateway/app/main.py"


class Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def driver_namespace():
    source = ast.parse(DRIVER.read_text())
    functions = {"require", "_body_text", "_messages", "_answer_after", "_session_call",
                 "_remaining_timeout", "_wait_gateway_original_session", "_assert_original_session_connected",
                 "_closed_execution_observation", "_post_once",
                 "_write_evidence", "_failure_observation_summary"}
    classes = {"EvidenceError", "HttpFailure", "GatewayEventConnection"}
    constants = {"F6_OBSERVER_STAGES", "F6_OBSERVER_ACTIONS"}
    nodes = [node for node in source.body if
             (isinstance(node, ast.FunctionDef) and node.name in functions)
             or (isinstance(node, ast.ClassDef) and node.name in classes)
             or (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in constants
                                                      for t in node.targets))]
    assert {node.name for node in nodes if isinstance(node, ast.FunctionDef)} == functions
    clock = Clock()
    namespace = {"time": clock, "re": re, "Path": Path, "json": json,
                 "hashlib": hashlib, "os": os, "threading": threading, "Request": Request, "urllib": __import__("urllib"), "state": {"checks": {}, "mutation_attempts": [],
                                          "uncertain_actions": [], "stage": "preflight"}}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(DRIVER), "exec"), namespace)
    return namespace, clock, source




def gateway_public_status(session_id, trace_id, attached):
    source = ast.parse(GATEWAY.read_text())
    nodes = [copy.deepcopy(node) for node in source.body
             if isinstance(node, ast.FunctionDef) and node.name == "_public_conversation_status"]
    assert len(nodes) == 1
    private_id = "byq-session-" + "b" * 32
    boot_id = "boot-observer-fixture"
    live = types.SimpleNamespace(released=False, session_id=private_id, trace_id=trace_id, boot_id=boot_id)
    namespace = {"Principal": object,
                 "product_sessions": types.SimpleNamespace(find_owned=lambda *_: live if attached else None),
                 "_valid_runtime_boot_id": lambda value: value == boot_id}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(GATEWAY), "exec"), namespace)
    return namespace["_public_conversation_status"](
        {"status": "active", "conversation_id": session_id, "runtime_session_id": private_id,
         "trace_id": trace_id}, object(), boot_id)


class RestartObserver(unittest.TestCase):
    def setUp(self):
        self.ns, self.clock, self.tree = driver_namespace()
        self.sid = "conversation_" + "a" * 32
        self.trace = "byq-trace-" + "c" * 32
        self.prompt = "F6-CI:FG2\nexact current input"
        self.answer = "BacktestTask backtesttask_" + "d" * 32 + " SignalJob signaljob_" + "d" * 32
        self.session = {"conversation": {"session_id": self.sid, "trace_id": self.trace, "status": "active"},
                        "messages": [{"role": "user", "content": self.prompt},
                                     {"role": "assistant", "content": self.answer}]}

    def wait(self, api, seconds=2):
        return self.ns["_wait_gateway_original_session"](
            api, self.sid, self.trace, self.prompt, self.answer, seconds=seconds)

    def test_connected_session_requires_exact_identity_active_and_persisted_answer(self):
        check=self.ns["_assert_original_session_connected"]
        check(self.session, self.sid, self.trace, self.prompt, self.answer)
        for key,value in [("session_id","other"),("trace_id","other"),("status","unknown"),("status","interrupted")]:
            view=copy.deepcopy(self.session);view["conversation"][key]=value
            with self.subTest(key=key),self.assertRaises(self.ns["EvidenceError"]):
                check(view,self.sid,self.trace,self.prompt,self.answer)

    def test_current_gateway_restart_registry_is_unknown_until_live_attach(self):
        self.assertEqual(gateway_public_status(self.sid, self.trace, False), "unknown")
        self.assertEqual(gateway_public_status(self.sid, self.trace, True), "active")
        before_resume = copy.deepcopy(self.session)
        before_resume["conversation"]["status"] = gateway_public_status(self.sid, self.trace, False)
        self.wait(lambda method, path, **kw: {"status": "ready"} if path == "/agent-readyz" else before_resume)
        self.assertEqual(self.ns["state"]["mutation_attempts"], [])
        self.assertEqual(self.clock.sleeps, [])

    def test_transient_readiness_reads_then_exits_immediately_on_original_answer(self):
        calls = []
        def api(method, path, **kw):
            calls.append((method, path, kw["timeout"]))
            self.assertEqual(method, "GET")
            self.assertLessEqual(kw["timeout"], 2 - self.clock.now)
            if len(calls) == 1: raise self.ns["HttpFailure"](503)
            return {"status": "ready"} if path == "/agent-readyz" else self.session
        self.wait(api)
        self.assertEqual(len(calls), 3)
        self.assertEqual(self.clock.sleeps, [0.5])
        self.assertEqual(self.ns["state"]["checks"]["gateway_readiness"]["methods"], ["GET"])

    def test_transport_and_cold_gateway_http_errors_are_bounded_read_only(self):
        for category in ["transport", 502, 503, 504]:
            ns, clock, _ = driver_namespace()
            calls = []
            def api(method, path, **kw):
                calls.append(method)
                self.assertEqual(method, "GET")
                self.assertLessEqual(kw["timeout"], 1 - clock.now)
                raise (ns["EvidenceError"]("http_transport_or_read_outcome_unknown")
                       if category == "transport" else ns["HttpFailure"](category))
            with self.subTest(category=category), self.assertRaises(ns["EvidenceError"]):
                ns["_wait_gateway_original_session"](api, self.sid, self.trace, self.prompt, self.answer, seconds=1)
            self.assertEqual(clock.now, 1)
            self.assertEqual(calls, ["GET", "GET"])
            self.assertEqual(ns["state"]["mutation_attempts"], [])

    def test_http_denial_and_session_scope_change_stop_without_retry(self):
        for status in [401, 403, 404, 409]:
            calls = []
            def denied(*args, **kw):
                calls.append(args)
                raise self.ns["HttpFailure"](status)
            with self.subTest(status=status), self.assertRaises(self.ns["HttpFailure"]): self.wait(denied)
            self.assertEqual(len(calls), 1)
        for key, value in [("session_id", "other"), ("trace_id", "other"), ("status", "interrupted"),
                           ("status", "failed"), ("status", "archived"), ("status", None)]:
            calls = []
            wrong = copy.deepcopy(self.session); wrong["conversation"][key] = value
            def api(method, path, **kw):
                calls.append(method)
                return {"status": "ready"} if path == "/agent-readyz" else wrong
            with self.subTest(field=key), self.assertRaises(self.ns["EvidenceError"]): self.wait(api)
            self.assertEqual(calls, ["GET", "GET"])
            self.assertEqual(self.clock.sleeps, [])

    def test_missing_duplicate_or_changed_original_answer_stops(self):
        for messages in [[], self.session["messages"] * 2,
                         [{"role": "user", "content": self.prompt}, {"role": "assistant", "content": "other"}]]:
            def api(method, path, **kw):
                return {"status": "ready"} if path == "/agent-readyz" else {**self.session, "messages": messages}
            with self.subTest(messages=len(messages)), self.assertRaises(self.ns["EvidenceError"]): self.wait(api)
        self.assertEqual(self.clock.sleeps, [])

    def restart_block(self, api):
        statements = []
        for node in self.tree.body:
            if not isinstance(node, ast.Try): continue
            selected = False
            for statement in node.body:
                if (isinstance(statement, ast.Assign) and isinstance(statement.value, ast.Constant)
                        and statement.value.value == "gateway_restart_and_original_logical_session_connect"):
                    selected = True
                if (selected and isinstance(statement, ast.Assign) and isinstance(statement.value, ast.Constant)
                        and statement.value.value == "start_exact_signal_worker_once"):
                    break
                if selected: statements.append(statement)
        self.assertTrue(statements, "actual top-level restart block missing")
        ns = self.ns
        ns.update(call=api, session_id=self.sid, trace_id=self.trace, fg2=self.prompt, fg2_answer=self.answer,
                  signal_job_id="signaljob_" + "d" * 32, task_id="task_" + "e" * 32,
                  version_id="artifact_" + "f" * 32, snapshot_id="stock_pool_snapshot_" + "1" * 64,
                  _compose_once=lambda *_a, **_kw: "", _compose=lambda *_a, **_kw: "127.0.0.1:43123",
                  client=object())
        exec(compile(ast.Module(body=statements, type_ignores=[]), str(DRIVER), "exec"), ns)

    def test_actual_restart_flow_uses_public_events_without_resume_or_new_turn(self):
        calls=[]; connected=[]
        class Connection:
            def __init__(_,client,origin,sid,trace):
                self.assertEqual((sid,trace),(self.sid,self.trace));connected.append(True)
                self.assertEqual(calls[:2],[("GET","/agent-readyz"),("GET","/v1/agent/sessions/"+self.sid)])
            def assert_healthy(_): pass
        self.ns["GatewayEventConnection"]=Connection
        def api(method,path,payload=None,**kw):
            calls.append((method,path));self.assertEqual(method,"GET")
            if path=="/agent-readyz":return {"status":"ready"}
            if path=="/v1/agent/sessions/"+self.sid:
                view=copy.deepcopy(self.session)
                view["conversation"]["status"]=gateway_public_status(self.sid,self.trace,bool(connected))
                return view
            return {"job":{"job_id":"signaljob_"+"d"*32,"task_id":"task_"+"e"*32,
                "owner_principal":"f6-chain-user","strategy_version_artifact_id":"artifact_"+"f"*32,
                "stock_pool_snapshot_id":"stock_pool_snapshot_"+"1"*64,"status":"waiting_for_data"}}
        self.restart_block(api)
        self.assertEqual(len(connected),1)
        self.assertIn("gateway_restart",self.ns["state"]["checks"])

    def test_unknown_after_event_connect_does_not_claim_healthy_session(self):
        self.ns["GatewayEventConnection"]=lambda *_:types.SimpleNamespace(assert_healthy=lambda:None)
        view=copy.deepcopy(self.session);view["conversation"]["status"]="unknown"
        def api(method,path,payload=None,**kw):
            self.assertEqual(method,"GET")
            return {"status":"ready"} if path=="/agent-readyz" else view
        with self.assertRaises(self.ns["EvidenceError"]):self.restart_block(api)
        self.assertNotIn("gateway_restart",self.ns["state"]["checks"])

    def test_event_connect_failure_is_not_replayed_or_followed_by_job_reads(self):
        attempts=[];calls=[]
        def connect(*_):
            attempts.append(1);raise self.ns["EvidenceError"]("gateway_event_connection_unconfirmed")
        self.ns["GatewayEventConnection"]=connect
        def api(method,path,**kw):
            calls.append((method,path));return {"status":"ready"} if path=="/agent-readyz" else self.session
        with self.assertRaises(self.ns["EvidenceError"]):self.restart_block(api)
        self.assertEqual(attempts,[1]);self.assertEqual(len(calls),2)
        self.assertEqual(self.ns["state"]["uncertain_actions"],[])

    def test_actual_evidence_writer_exports_closed_stage_and_uncertain_actions(self):
        self.ns["state"].update(status="failed", stage="gateway_original_event_connection_once",
                                failure_category="http_transport_or_read_outcome_unknown",
                                identities={}, uncertain_actions=["foreground_agent_turn_2", "PRIVATE-ACTION-CANARY"])
        with tempfile.TemporaryDirectory(prefix="byq-f6-observer-") as directory:
            destination = Path(directory)/"evidence.json"
            self.ns.update(evidence_path=str(destination), project="byq-ci-stack-test")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.ns["_write_evidence"]()
            summary = json.loads(output.getvalue())
            private = json.loads(destination.read_text())
            self.assertEqual(private["uncertain_actions"], ["foreground_agent_turn_2", "PRIVATE-ACTION-CANARY"])
            self.assertNotIn("PRIVATE-", output.getvalue())
            self.assertEqual(summary["execution_observation"]["observer_stage"],
                             "gateway_original_event_connection_once")
            self.assertEqual(summary["execution_observation"]["uncertain_actions"], ["foreground_agent_turn_2"])
            self.assertTrue(summary["execution_observation"]["uncertain_actions_values_unknown"])
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            before = destination.read_bytes()
            with self.assertRaises(FileExistsError): self.ns["_write_evidence"]()
            self.assertEqual(destination.read_bytes(), before)

    def test_uploaded_execution_summary_filters_canaries_and_caps_actions(self):
        self.ns["state"].update(stage="PRIVATE-STAGE-CANARY", mutation_attempts=["gateway_restart"]*40,
                                uncertain_actions=["PRIVATE-ACTION-CANARY", {}, "foreground_agent_turn_2"])
        summary = self.ns["_closed_execution_observation"]()
        self.assertNotIn("PRIVATE-", json.dumps(summary))
        self.assertEqual(summary["observer_stage"], "unknown")
        self.assertEqual(len(summary["mutation_attempts"]), 32)
        self.assertTrue(summary["mutation_attempts_truncated"])
        self.assertTrue(summary["uncertain_actions_values_unknown"])
        self.assertEqual(summary["uncertain_actions"], ["foreground_agent_turn_2"])

    def test_connection_open_uses_only_exact_public_get_and_rejects_wrong_content_type(self):
        calls=[]
        headers=Message();headers['Content-Type']='application/json'
        closed=[]
        response=types.SimpleNamespace(status=200,headers=headers,close=lambda:closed.append(True))
        def open_(request,timeout):
            calls.append(request)
            self.assertEqual(request.get_method(),'GET')
            self.assertEqual(request.full_url,'http://127.0.0.1:43123/v1/workflows/'+self.sid+'/events')
            self.assertEqual(timeout,30)
            return response
        with self.assertRaises(self.ns['EvidenceError']):
            self.ns['GatewayEventConnection'](types.SimpleNamespace(open=open_),'http://127.0.0.1:43123',self.sid,self.trace)
        self.assertEqual(len(calls),1);self.assertEqual(closed,[True])

    def test_connection_close_stops_and_closes_before_bounded_join(self):
        conn=self.stream_fixture(iter([]));calls=[]
        conn.response.close=lambda:calls.append(('close',conn.stop.is_set()))
        conn.thread=types.SimpleNamespace(join=lambda timeout:calls.append(('join',timeout)))
        conn.close();self.assertEqual(calls,[('close',True),('join',1)])

    def stream_fixture(self, lines):
        klass=self.ns["GatewayEventConnection"]
        connection=klass.__new__(klass)
        connection.stop=threading.Event();connection.failure=None;connection.deadline=600
        connection.session_id=self.sid;connection.trace_id=self.trace
        connection.response=types.SimpleNamespace(readline=lambda _:next(lines,b""))
        return connection

    def test_public_event_identity_mismatch_stops_connection(self):
        for key in ["session_id","trace_id"]:
            event={"session_id":self.sid,"trace_id":self.trace};event[key]="other"
            conn=self.stream_fixture(iter([b"data: "+json.dumps(event).encode()+b"\n"]))
            conn._drain();self.assertEqual(conn.failure,"gateway_event_identity_changed")

    def test_stream_eof_invalid_json_and_size_are_bounded(self):
        for lines,category in [([],"gateway_event_connection_closed"),([b"data: bad\n"],"gateway_event_projection_invalid"),
                                ([b"x"*65537],"gateway_event_observation_limit")]:
            conn=self.stream_fixture(iter(lines));conn._drain();self.assertEqual(conn.failure,category)

    def test_closed_connection_never_claims_healthy(self):
        conn=self.stream_fixture(iter([]));conn.thread=types.SimpleNamespace(is_alive=lambda:False)
        with self.assertRaises(self.ns["EvidenceError"]):conn.assert_healthy()

    def test_drain_accepts_exact_public_event_and_stops_on_deadline(self):
        event={"session_id":self.sid,"trace_id":self.trace}
        conn=self.stream_fixture(iter([]))
        def read(_):
            self.clock.now=600
            return b"data: "+json.dumps(event).encode()+b"\n"
        conn.response.readline=read;conn._drain()
        self.assertEqual(conn.failure,"gateway_event_observation_deadline")

    def test_finally_keeps_connection_until_failure_reconciliation_and_evidence(self):
        outer=next(node for node in self.tree.body if isinstance(node,ast.Try) and node.finalbody)
        final=ast.unparse(ast.Module(body=outer.finalbody,type_ignores=[]))
        self.assertLess(final.index('_write_evidence'),final.index('gateway_events.close()'))
        failure=ast.unparse(ast.Module(body=[outer],type_ignores=[]))
        self.assertLess(failure.index('_failure_readonly_window'),failure.index('gateway_events.close()'))
        self.assertNotIn('/resume',DRIVER.read_text())


if __name__ == "__main__":
    unittest.main()
