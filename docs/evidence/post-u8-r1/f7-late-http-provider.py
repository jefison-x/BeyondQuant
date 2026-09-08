"""Local synthetic Provider: hold root two while old HTTP is replayed."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from native_provider import fields, stream

state = {"phase": 1, "calls": 0, "total": 0, "waiting": False}
release = threading.Event()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        raw = json.dumps(state).encode()
        self.send_response(200)
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        length = int(self.headers.get("content-length", "0"))
        if not 0 < length <= 2 * 1024 * 1024:
            self.send_error(413)
            return
        body = json.loads(self.rfile.read(length))
        if self.path == "/control":
            if body == {"phase": 2} and state["phase"] == 1:
                state.update(phase=2, calls=0)
            elif body == {"release": True}:
                release.set()
            else:
                self.send_error(409)
                return
            self.send_response(204)
            self.end_headers()
            return
        state["calls"] += 1
        state["total"] += 1
        count, phase = state["calls"], state["phase"]
        if count > 4 or state["total"] > 8:
            self.send_error(429)
            return
        results = [m.get("content") for m in body.get("messages", []) if m.get("role") == "tool"]
        if count == 1:
            name, args = "byq_agent_run_start", {"role_id": "strategy_researcher", "idempotency_key": f"late-agent-{phase}"}
        elif count == 2 and phase == 1:
            name, args = "byq_research_task_create", {"owner_principal": "ci-late-http",
                "title": "合成迟到请求研究", "objective": "仅验证请求隔离，不训练或回测。",
                "trace_id": "model-not-authority", "idempotency_key": "late-task"}
        elif count == 2:
            name, args = "byq_agent_context", {}
        elif count == 4 and phase == 2:
            state["waiting"] = True
            release.wait(90)
            try:
                raw = stream(None, {}, state["total"], text="合成测试结束，未执行研究。")
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.send_header("content-length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        else:
            name, args = "byq_strategy_validate", {"task_id": fields(results, "task_id")[-1],
                "agent_run_id": fields(results, "run_id")[-1], "idempotency_key": f"late-invalid-{count}",
                "strategy": {} if count == 3 else {"name": "invalid-repair"}}
        raw = stream("mcp__byq__" + name, args, state["total"])
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


ThreadingHTTPServer(("0.0.0.0", 8801), Handler).serve_forever()
