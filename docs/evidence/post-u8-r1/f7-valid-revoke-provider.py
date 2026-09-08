"""Pause a valid synthetic tool response until its test owner is disabled."""
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from helpers import fields, stream
from tests.test_strategy_artifact import strategy_payload
from tests.test_ml_strategy import valid_strategy

state = {"calls": 0, "total_calls": 0, "paused": False}
release = threading.Event()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        body = json.dumps({key: state[key] for key in ("calls", "total_calls", "paused")}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("content-length", "0"))
        if not 0 < length <= 2 * 1024 * 1024:
            self.send_error(413)
            return
        body = json.loads(self.rfile.read(length))
        if self.path == "/control":
            assert set(body) == {"owner", "action"}
            assert re.fullmatch(r"ci-f7-revoke-[a-z]+", body["owner"])
            assert body["action"] in {"byq_strategy_validate", "byq_ml_strategy_create"}
            state.update(calls=0, paused=False, **body)
            release.clear()
            self.send_response(204)
            self.end_headers()
            return
        if self.path == "/release":
            assert body == {"owner_disabled": True} and state["paused"]
            release.set()
            self.send_response(204)
            self.end_headers()
            return
        state["calls"] += 1
        state["total_calls"] += 1
        count = state["calls"]
        if count > 4:
            self.send_error(429, "synthetic cap")
            return
        action = state["action"]
        results = [message.get("content") for message in body.get("messages", []) if message.get("role") == "tool"]
        if count == 1:
            name = "byq_agent_run_start"
            args = {"role_id": "strategy_researcher" if action == "byq_strategy_validate" else "ml_researcher",
                    "idempotency_key": "revoke-run"}
        elif count == 2:
            state["run"] = fields(results, "run_id")[-1]
            name = "byq_research_task_create"
            args = {"owner_principal": state["owner"], "title": "Synthetic revocation probe",
                    "objective": "Reject a tool after identity revocation", "trace_id": "not-authority",
                    "idempotency_key": "revoke-task"}
        elif count == 3:
            name = action
            args = {"agent_run_id": state["run"], "task_id": fields(results, "task_id")[-1],
                    "idempotency_key": "revoke-valid-input",
                    **({"trace_id": "model-not-authority"} if action == "byq_strategy_validate" else {}),
                    "strategy": strategy_payload() if action == "byq_strategy_validate" else valid_strategy()}
            state["paused"] = True
            if not release.wait(timeout=20):
                self.send_error(504, "revocation test release expired")
                return
            state["paused"] = False
        else:
            name, args = None, {}
        wire_name = "mcp__byq__" + name if name else None
        if wire_name and wire_name not in {item["function"]["name"] for item in body.get("tools", [])}:
            self.send_error(422, "tool ceiling")
            return
        response = stream(wire_name, args, count,
            text="Synthetic identity revoked. No research or artifact completion is claimed." if name is None else None)
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("content-length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)


ThreadingHTTPServer(("0.0.0.0", 8801), Handler).serve_forever()
