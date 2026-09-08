"""Deterministic, non-forwarding local test provider; never contacts a model."""
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

state = {"calls": 0, "action": "byq_strategy_validate", "owner": "ci-f7-joined", "steps": []}
lock = threading.Lock()


def tool(name, args, count):
    chunks = [{"choices": [{"index": 0, "delta": {"role": "assistant", "tool_calls": [{
        "index": 0, "id": f"synthetic-call-{count}", "type": "function",
        "function": {"name": "mcp__byq__" + name, "arguments": json.dumps(args)}}]}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
         "usage": {"prompt_tokens": 4, "completion_tokens": 2}}]
    return ("".join("data: " + json.dumps(item) + "\n\n" for item in chunks) + "data: [DONE]\n\n").encode()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        with lock:
            body = json.dumps(state).encode()
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
            assert set(body) == {"action", "owner"}
            assert body["action"] in {"byq_strategy_validate", "byq_ml_strategy_create"}
            assert re.fullmatch(r"ci-f7-[a-z-]+", body["owner"])
            with lock:
                state.update(calls=0, action=body["action"], owner=body["owner"], steps=[])
            self.send_response(204)
            self.end_headers()
            return
        with lock:
            state["calls"] += 1
            count, action, owner = state["calls"], state["action"], state["owner"]
        if count > 8:
            self.send_error(429, "synthetic cap")
            return
        if count == 1:
            name = "byq_agent_run_start"
            args = {"role_id": "strategy_researcher" if action == "byq_strategy_validate" else "ml_researcher",
                    "idempotency_key": "synthetic-joined-run"}
        elif count == 2:
            name = "byq_research_task_create"
            args = {"owner_principal": owner, "title": "Synthetic F7 schema stop", "objective": "Bounded local schema failures only",
                    "trace_id": "model-trace-is-not-authority", "idempotency_key": "synthetic-joined-task"}
        else:
            results = json.dumps([item.get("content") for item in body.get("messages", []) if item.get("role") == "tool"])
            runs = re.findall(r"agent_run_[a-f0-9]{32}", results)
            tasks = re.findall(r"(?<![a-z_])task_[a-f0-9]{32}", results)
            if not runs or not tasks:
                with lock:
                    state["steps"].append({"error": "missing durable references", "has_run": bool(runs), "has_task": bool(tasks)})
                self.send_error(422, "synthetic prerequisite failed")
                return
            name = action
            args = {"task_id": tasks[-1], "agent_run_id": runs[-1], "idempotency_key": f"synthetic-invalid-{count}",
                    "strategy": {} if count == 3 else {"name": f"synthetic-repair-{count}"}}
        tools = {item["function"]["name"] for item in body.get("tools", [])}
        if "mcp__byq__" + name not in tools:
            with lock:
                state["steps"].append({"error": "tool not available", "tool": name})
            self.send_error(422, "synthetic tool ceiling")
            return
        with lock:
            state["steps"].append({"tool": name, "call": count})
        response = tool(name, args, count)
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("content-length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)


ThreadingHTTPServer(("0.0.0.0", 8801), Handler).serve_forever()
