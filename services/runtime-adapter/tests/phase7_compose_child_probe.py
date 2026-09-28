"""Opt-in PID-1 fixture for the isolated Phase 7 Compose child-death check.

Only the scripted model/MCP endpoints are synthetic. The runtime adapter and
pinned DSH foreground delegate are real. This file is mounted read-only into a
disposable Adapter container; it is never a product command.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from test_dsh015_foreground_child_process import DELEGATE_TOOL, _servers, _sse


if os.environ.get("BYQ_PHASE7_CHILD_PROBE") != "1":
    raise SystemExit("isolated Phase 7 fixture flag required")

composition = Path("/opt/byq/profiles/byq-product.patch.yml")
observer_url = os.environ.get("BYQ_PHASE7_PRODUCT_MCP_OBSERVER_URL")
if observer_url:
    state = {"child_request_started": threading.Event(), "provider_requests": []}

    class ProductObserverProvider(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            messages = body.get("messages", [])
            offered = {item["function"]["name"] for item in body.get("tools", [])
                       if isinstance(item, dict) and isinstance(item.get("function"), dict)
                       and isinstance(item["function"].get("name"), str)}
            used = {call["function"]["name"] for message in messages
                    for call in message.get("tool_calls", [])
                    if isinstance(call, dict) and isinstance(call.get("function"), dict)
                    and isinstance(call["function"].get("name"), str)}
            role_tool = "mcp__byq__byq_agent_roles"
            if DELEGATE_TOOL in offered and role_tool not in used:
                name, arguments = role_tool, "{}"
            elif DELEGATE_TOOL in offered and DELEGATE_TOOL not in used:
                name, arguments = DELEGATE_TOOL, json.dumps({
                    "description": "Phase 7 foreground child", "prompt": "Return the fixed synthetic child answer."})
            elif DELEGATE_TOOL not in offered:
                state["child_request_started"].set()
                threading.Event().wait()  # host kills PID 1 while child waits
                return
            else:
                payloads = [
                    {"choices": [{"index": 0, "delta": {"content": "Synthetic root answer."},
                                  "finish_reason": None}]},
                    {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                     "usage": {"prompt_tokens": 5, "completion_tokens": 6}},
                ]
                encoded = _sse(payloads)
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.send_header("content-length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
                return
            payloads = [
                {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0,
                    "id": "phase7-" + name, "type": "function",
                    "function": {"name": name, "arguments": arguments}}]}, "finish_reason": None}]},
                {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
            ]
            encoded = _sse(payloads)
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    provider = ThreadingHTTPServer(("127.0.0.1", 0), ProductObserverProvider)
    provider.daemon_threads = True
    threading.Thread(target=provider.serve_forever, daemon=True).start()
    os.environ["BYQ_MCP_URL"] = observer_url
else:
    state, mcp, provider, _threads = _servers(composition, block_child=True)
class _HoldUntilProcessDeath:
    def wait(self, timeout=None):
        threading.Event().wait()


# The shared qualification fixture normally releases the synthetic response
# after 25 seconds. This PID-1 probe must keep the child live until host kill.
if not observer_url:
    state["child_response_release"] = _HoldUntilProcessDeath()
    os.environ["BYQ_MCP_URL"] = f"http://127.0.0.1:{mcp.server_port}/mcp/v1"
    os.environ["BYQ_MCP_TOKEN"] = "phase7-loopback-only"
os.environ["DEEPSEEK_API_KEY"] = "phase7-loopback-only"
os.environ["DEEPSEEK_BASE_URL"] = f"http://127.0.0.1:{provider.server_port}"
sys.path.insert(0, "/app")

from app import main as runtime_main  # noqa: E402 - fixture environment first
import uvicorn  # noqa: E402


def scenario() -> None:
    adapter = runtime_main.adapter
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        try:
            adapter.require_current_backend_authority()
            break
        except Exception:
            time.sleep(0.1)
    else:
        raise RuntimeError("Gateway never established this Adapter boot")

    seen = []
    original = adapter._on_notification

    def observe(record, notification, **kwargs):
        if getattr(notification, "method", None) == "subagent.started":
            seen.append(getattr(notification, "payload", None))
        return original(record, notification, **kwargs)

    adapter._on_notification = observe
    suffix = uuid.uuid4().hex
    session_id = "phase7-child-" + suffix
    adapter.create_session(session_id, "trace-" + suffix, "phase7-owner", "phase7-workspace")
    adapter.submit_prompt(session_id, "Run the synthetic delegated market research turn.")
    if not state["child_request_started"].wait(timeout=20):
        raise RuntimeError("pinned DSH foreground child did not start")
    if not seen:
        raise RuntimeError("real subagent.started notification was not observed")
    if not observer_url and (state["mcp_methods"].count("initialize") < 1
                             or state["mcp_methods"].count("tools/list") < 1):
        raise RuntimeError("real DSH MCP initialization/list traffic was not observed")
    print(json.dumps({"phase7_child_probe": "BLOCKED_CHILD_LIVE",
                      "subagent_started": True, "mcp_initialized": not bool(observer_url),
                      "product_mcp_observer": bool(observer_url),
                      "pid1": os.getpid(), "boot_id": adapter.boot_id}), flush=True)
    # The host kills PID 1 while the provider response is blocked. No test
    # code here may release the child or fabricate its terminal result.
    while True:
        time.sleep(1)


threading.Thread(target=scenario, name="phase7-child-probe", daemon=True).start()
uvicorn.run(runtime_main.app, host="0.0.0.0", port=8400)
