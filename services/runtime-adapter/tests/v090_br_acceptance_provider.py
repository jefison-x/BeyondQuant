"""Controlled keyless model provider for the v090 business-recovery acceptance.

This is an explicit, isolated acceptance fixture (never a production runtime
mode). It runs the REAL Runtime Adapter app with a scripted OpenAI-compatible
provider so a real lost run and a real recovery run can be produced
deterministically without any model credential.

Mode is read from ``BYQ_V090_BR_MODE_FILE`` at every model call:

* ``block``      -> never answer, so the real executor run stays open until the
                    adapter OS process is terminated (a real executor loss).
* ``read_only``  -> one read-only MCP call, then stop (an eligible read-only
                    recovery run).
* ``new_key``    -> one side-effecting MCP call with a brand-new idempotency key
                    (must be refused by the Backend recovery-mode envelope).
* ``exact_reuse``-> replay the original five-tuple recorded in the reservation
                    (an eligible exact-reuse recovery run).

Nothing here is business logic: it is the model. The Adapter, Gateway, Backend,
MCP, PostgreSQL and DSH runtime remain the real committed components.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _task_id(body: dict) -> str:
    text = "\n".join(str(m.get("content", "")) for m in body["messages"] if m["role"] == "user")
    match = re.search(r"BYQ trusted task continuation.*?task (task_[0-9a-f]{32})", text, re.DOTALL)
    return match.group(1) if match else "task_" + "0" * 32


def _read_mode() -> str:
    path = os.environ.get("BYQ_V090_BR_MODE_FILE", "/var/lib/byq/dsh-sessions/__acceptance_mode")
    try:
        with open(path, "r", encoding="utf-8") as stream:
            return stream.read().strip() or "block"
    except OSError:
        return "block"


def _has_tool_result(body: dict) -> bool:
    return any(message.get("role") == "tool" for message in body["messages"])


def _arguments(task_id: str, mode: str) -> dict | None:
    if mode == "read_only":
        return {"tool": "mcp__byq__byq_research_get",
                "args": {"entity_type": "research_task", "entity_id": task_id}}
    if mode == "new_key":
        return {"tool": "mcp__byq__byq_strategy_validate",
                "args": {"task_id": task_id, "agent_run_id": "f" * 32,
                         "idempotency_key": "acceptance-brand-new-key-0001",
                         "strategy": {"code": "synthetic-recovery-write"}}}
    if mode == "exact_reuse":
        try:
            key = json.loads(os.environ.get("BYQ_V090_BR_EXACT_KEY", "{}"))
        except ValueError:
            key = {}
        return {"tool": "mcp__byq__byq_strategy_validate",
                "args": {"task_id": task_id, "agent_run_id": key.get("agent_run_id", "f" * 32),
                         "idempotency_key": key.get("idempotency_key", "acceptance-exact-key-0001"),
                         "strategy": {"code": "synthetic-recovery-exact"}}}
    return None


def next_action(body: dict) -> dict | None:
    mode = _read_mode()
    if mode == "block":
        time.sleep(600)
        return None
    if _has_tool_result(body):
        return None
    return _arguments(_task_id(body), mode)


def main() -> None:
    if os.environ.get("BYQ_V090_BR_ACCEPTANCE") != "1":
        raise SystemExit("explicit isolated acceptance provider invocation required")

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            try:
                body = json.loads(self.rfile.read(int(self.headers["content-length"])))
                action = next_action(body)
                if action:
                    name, args = action["tool"], action["args"]
                    delta = {"tool_calls": [{"index": 0,
                        "id": hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:24],
                        "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}
                    reason = "tool_calls"
                else:
                    delta, reason = {"content": "已核对本任务的真实领域结果并保存进度。"}, "stop"
                data = ("data: " + json.dumps({"choices": [{"index": 0, "delta": delta, "finish_reason": None}]})
                    + "\n\ndata: " + json.dumps({"choices": [{"index": 0, "delta": {}, "finish_reason": reason}],
                        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}})
                    + "\n\ndata: [DONE]\n\n").encode()
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except Exception as exc:  # noqa: BLE001
                print("acceptance provider failed: " + type(exc).__name__, flush=True)
                self.send_error(400, "acceptance provider rejected the request")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    from app import main as runtime_main
    import uvicorn
    original = runtime_main.adapter._compatibility.build_harness

    def loopback_build(**kwargs):
        kwargs["environment"]["DEEPSEEK_BASE_URL"] = f"http://127.0.0.1:{server.server_port}"
        return original(**kwargs)

    runtime_main.adapter._compatibility.build_harness = loopback_build
    try:
        uvicorn.run(runtime_main.app, host="0.0.0.0", port=8400)
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
