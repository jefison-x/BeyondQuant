"""Opt-in PID-1 fixture for Phase 7 terminal-close/lost-response evidence.

The ordinary Runtime Adapter app remains the server. This test-only process adds
an in-memory OpenAI-compatible provider on loopback. The host creates every
Product session and turn through Gateway; this fixture never creates one.
"""
from __future__ import annotations

import hmac
import json
import os
import secrets
import signal
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


if os.environ.get("BYQ_PHASE7_TERMINAL_FIXTURE") != "1":
    raise SystemExit("isolated Phase 7 terminal fixture opt-in required")

_PROVIDER_KEY = "phase7-" + secrets.token_urlsafe(32)
_REGISTRATION_TOOL = "mcp__byq__byq_agent_run_start"
_REGISTRATION_KEY = "phase7-terminal-registration"
_FINAL_ANSWER = "Phase 7 synthetic terminal answer."
_RELEASE = threading.Event()
_STATE_LOCK = threading.Lock()
_PROVIDER_REQUESTS = 0


def _log(event: str, **metadata: object) -> None:
    # Intentionally accepts only fixture metadata. Never pass model request
    # bodies, headers, credentials, prompts, or tool arguments here.
    print(json.dumps({"phase7_terminal_fixture": event, **metadata},
                     separators=(",", ":"), sort_keys=True), flush=True)


def _on_release_signal(_signum: int, _frame: object) -> None:
    # Keep signal handling minimal; the provider thread emits the release marker
    # after observing the Event.
    _RELEASE.set()


signal.signal(signal.SIGUSR1, _on_release_signal)


def _send_sse(handler: BaseHTTPRequestHandler, chunks: list[dict[str, object]]) -> None:
    encoded = ("".join(
        "data: " + json.dumps(chunk, separators=(",", ":")) + "\n\n"
        for chunk in chunks
    ) + "data: [DONE]\n\n").encode()
    handler.send_response(200)
    handler.send_header("content-type", "text/event-stream")
    handler.send_header("cache-control", "no-cache")
    handler.send_header("content-length", str(len(encoded)))
    handler.end_headers()
    handler.wfile.write(encoded)


def _offered_tool(request: dict[str, object], name: str) -> bool:
    tools = request.get("tools")
    if not isinstance(tools, list):
        return False
    return any(
        isinstance(item, dict)
        and isinstance(item.get("function"), dict)
        and item["function"].get("name") == name
        for item in tools
    )


def _used_tool(request: dict[str, object], name: str) -> bool:
    messages = request.get("messages")
    if not isinstance(messages, list):
        return False
    for message in messages:
        if not isinstance(message, dict):
            continue
        calls = message.get("tool_calls")
        if not isinstance(calls, list):
            continue
        for call in calls:
            if (isinstance(call, dict)
                    and isinstance(call.get("function"), dict)
                    and call["function"].get("name") == name):
                return True
    return False


class _ScriptedOpenAIProvider(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args: object) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802
        global _PROVIDER_REQUESTS
        with _STATE_LOCK:
            _PROVIDER_REQUESTS += 1
            number = _PROVIDER_REQUESTS
        _log("PROVIDER_REQUEST", request_number=number, pid1=os.getpid())

        if not self.path.rstrip("/").endswith("/chat/completions"):
            self.send_error(404, "unsupported fixture endpoint")
            return
        supplied = self.headers.get("Authorization", "")
        if not hmac.compare_digest(supplied, "Bearer " + _PROVIDER_KEY):
            self.send_error(401, "fixture provider key required")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 8 * 1024 * 1024:
                raise ValueError("invalid content length")
            request = json.loads(self.rfile.read(length))
        except (ValueError, json.JSONDecodeError):
            self.send_error(400, "OpenAI-compatible JSON request required")
            return
        if (not isinstance(request, dict)
                or not isinstance(request.get("model"), str)
                or not isinstance(request.get("messages"), list)):
            self.send_error(400, "OpenAI-compatible chat completion required")
            return
        if not _offered_tool(request, _REGISTRATION_TOOL):
            self.send_error(400, "Product Agent registration tool is required")
            return

        if not _used_tool(request, _REGISTRATION_TOOL):
            arguments = json.dumps(
                {"role_id": "quant_orchestrator",
                 "idempotency_key": _REGISTRATION_KEY},
                separators=(",", ":"),
            )
            _send_sse(self, [
                {"choices": [{"index": 0, "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "id": "phase7-terminal-registration",
                        "type": "function",
                        "function": {
                            "name": _REGISTRATION_TOOL,
                            "arguments": arguments,
                        },
                    }],
                }, "finish_reason": None}]},
                {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
            ])
            return

        _log("PROVIDER_WAITING", request_number=number, pid1=os.getpid())
        _RELEASE.wait()
        _log("PROVIDER_RELEASED", request_number=number, pid1=os.getpid())
        _log("FINAL_ANSWER", request_number=number, pid1=os.getpid())
        _send_sse(self, [
            {"choices": [{"index": 0, "delta": {"role": "assistant"},
                          "finish_reason": None}]},
            {"choices": [{"index": 0, "delta": {"content": _FINAL_ANSWER},
                          "finish_reason": None}]},
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
             "usage": {"prompt_tokens": 5, "completion_tokens": 6, "total_tokens": 11}},
        ])


provider = ThreadingHTTPServer(("127.0.0.1", 0), _ScriptedOpenAIProvider)
provider.daemon_threads = True
threading.Thread(
    target=provider.serve_forever,
    name="phase7-terminal-provider",
    daemon=True,
).start()

# Only the disposable local DSH runtime receives this generated key. Disable
# resolver credentials so a persisted provider binding cannot replace it.
os.environ["BYQ_CREDENTIAL_RESOLVER_TOKEN"] = ""
os.environ["DEEPSEEK_API_KEY"] = _PROVIDER_KEY
os.environ["DEEPSEEK_BASE_URL"] = "http://127.0.0.1:" + str(provider.server_port)

import sys  # noqa: E402

sys.path.insert(0, "/app")

from app import main as runtime_main  # noqa: E402
import uvicorn  # noqa: E402


uvicorn.run(runtime_main.app, host="0.0.0.0", port=8400)
