"""Opt-in PID-1 fixture for the isolated Phase 7 Gateway restart check.

The normal Runtime Adapter app and its pinned DSH runtime remain in use. This
fixture supplies a loopback OpenAI-compatible endpoint. Its first response
requests a real Product MCP AgentRun registration, then it holds DSH's next
root provider request open. The host creates the Product session and turn
through Gateway; this file never creates a session or submits a prompt.
"""
from __future__ import annotations

import hmac
import json
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


if os.environ.get("BYQ_PHASE7_GATEWAY_ROOT_PROBE") != "1":
    raise SystemExit("isolated Phase 7 Gateway root probe flag required")


_provider_key = "phase7-" + secrets.token_urlsafe(32)
_request_lock = threading.Lock()
_provider_request_count = 0
_hold_requests = threading.Event()
_registration_tool = "mcp__byq__byq_agent_run_start"


class _BlockingOpenAIProvider(BaseHTTPRequestHandler):
    """Accept the generated test key and leave DSH's model call pending."""

    def log_message(self, *_args):
        return

    def do_POST(self):  # noqa: N802
        authorization = self.headers.get("Authorization", "")
        if not hmac.compare_digest(authorization, f"Bearer {_provider_key}"):
            print(json.dumps({
                "phase7_gateway_root_probe": "ROOT_PROVIDER_AUTH_REJECTED",
                "pid1": os.getpid(),
                "path": self.path,
            }), flush=True)
            self.send_error(401, "test provider key required")
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 8 * 1024 * 1024:
                raise ValueError("invalid Content-Length")
            request = json.loads(self.rfile.read(length))
        except (ValueError, json.JSONDecodeError):
            self.send_error(400, "OpenAI-compatible JSON request required")
            return

        if (not self.path.rstrip("/").endswith("/chat/completions")
                or not isinstance(request, dict)
                or not isinstance(request.get("model"), str)
                or not isinstance(request.get("messages"), list)):
            self.send_error(404, "unsupported test provider endpoint")
            return

        global _provider_request_count
        with _request_lock:
            _provider_request_count += 1
            request_number = _provider_request_count
        print(json.dumps({"phase7_gateway_root_probe": "ROOT_PROVIDER_REQUEST",
                          "provider_request_number": request_number}), flush=True)

        offered = {tool["function"]["name"] for tool in request.get("tools", [])
                   if isinstance(tool, dict) and isinstance(tool.get("function"), dict)
                   and isinstance(tool["function"].get("name"), str)}
        used = {call["function"]["name"] for message in request["messages"]
                if isinstance(message, dict) for call in message.get("tool_calls", [])
                if isinstance(call, dict) and isinstance(call.get("function"), dict)
                and isinstance(call["function"].get("name"), str)}
        if _registration_tool not in offered:
            self.send_error(400, "required Product Agent registration tool is not offered")
            return
        if _registration_tool not in used:
            arguments = json.dumps({"role_id": "quant_orchestrator",
                                    "idempotency_key": "phase7-gateway-root-registration"})
            payloads = [
                {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0,
                    "id": "phase7-root-registration", "type": "function",
                    "function": {"name": _registration_tool, "arguments": arguments}}]},
                    "finish_reason": None}]},
                {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
            ]
            encoded = ("".join(f"data: {json.dumps(item, separators=(',', ':'))}\n\n"
                               for item in payloads) + "data: [DONE]\n\n").encode()
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            return

        # The host waits for this exact JSON marker before restarting only
        # Gateway. Do not log the key, request messages, or any credentials.
        print(json.dumps({
            "phase7_gateway_root_probe": "ROOT_PROVIDER_BLOCKED",
            "provider_request_number": request_number,
            "pid1": os.getpid(),
            "path": self.path,
            "model": request["model"],
            "message_count": len(request["messages"]),
        }), flush=True)

        # Hold every authenticated completion request. In particular, never
        # let a retry turn the active root into a fabricated terminal result.
        _hold_requests.wait()


provider = ThreadingHTTPServer(("127.0.0.1", 0), _BlockingOpenAIProvider)
provider.daemon_threads = True
threading.Thread(target=provider.serve_forever, name="phase7-root-provider", daemon=True).start()

# The disposable DSH process gets only a key generated for this local endpoint.
# Disable credential lookup so a stored real provider binding cannot replace it.
os.environ["BYQ_CREDENTIAL_RESOLVER_TOKEN"] = ""
os.environ["DEEPSEEK_API_KEY"] = _provider_key
os.environ["DEEPSEEK_BASE_URL"] = f"http://127.0.0.1:{provider.server_port}"

import sys  # noqa: E402

sys.path.insert(0, "/app")

from app import main as runtime_main  # noqa: E402
import uvicorn  # noqa: E402


uvicorn.run(runtime_main.app, host="0.0.0.0", port=8400)
