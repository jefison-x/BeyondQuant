"""PID-1 scripted provider and private boolean observer for Phase 10's joined flow."""
from __future__ import annotations

import hmac
import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


if os.environ.get("BYQ_PHASE10_TWO_TURN_PROBE") != "1":
    raise SystemExit("isolated Phase 10 probe opt-in required")

_NONCE = os.environ["BYQ_PHASE10_NONCE"]
if re.fullmatch(r"[0-9a-f]{24}", _NONCE) is None:
    raise SystemExit("Phase 10 fixture nonce is invalid")
_OBSERVER_TOKEN = os.environ["BYQ_PHASE10_OBSERVER_TOKEN"]
_FIRST_PROMPT = "P10_FIRST_PUBLIC_PROMPT_" + _NONCE
_ANSWER = "P10_COMPLETED_PUBLIC_ANSWER_" + _NONCE
_SECOND_PROMPT = "P10_SECOND_CURRENT_PROMPT_" + _NONCE
_REGISTRATION_TOOL = "mcp__byq__byq_agent_run_start"
_REGISTRATION_KEYS = {
    "first": "p10-" + _NONCE + "-root-one",
    "second": "p10-" + _NONCE + "-root-two",
}
_PRIVATE_SENTINEL = _REGISTRATION_KEYS["first"]
_LOCK = threading.RLock()
_PROVIDER_REQUESTS: list[dict[str, object]] = []
_TERMINAL_ACKS: list[dict[str, object]] = []
_PREPARED_ROOTS: list[dict[str, object]] = []
_HARNESSES: dict[int, dict[str, str]] = {}
_PROVIDER_KEY = "p10-provider-" + os.urandom(24).hex()


def _tool_calls(messages: list[object]) -> list[dict[str, object]]:
    return [call for message in messages if isinstance(message, dict)
            for call in message.get("tool_calls", [])
            if isinstance(call, dict)]


def _registered_keys(messages: list[object]) -> set[str]:
    found: set[str] = set()
    for call in _tool_calls(messages):
        function = call.get("function")
        if not isinstance(function, dict) or function.get("name") != _REGISTRATION_TOOL:
            continue
        try:
            arguments = json.loads(str(function.get("arguments", "{}")))
        except (TypeError, json.JSONDecodeError):
            continue
        key = arguments.get("idempotency_key") if isinstance(arguments, dict) else None
        if isinstance(key, str):
            found.add(key)
    return found


def _pid_for_provider_peer(handler: BaseHTTPRequestHandler) -> int | None:
    """Resolve the loopback client socket to its owning DSH process via /proc."""
    try:
        peer_port = int(handler.client_address[1])
        local_port = int(handler.server.server_port)
        inodes: set[str] = set()
        for table in ("/proc/net/tcp", "/proc/net/tcp6"):
            try:
                lines = Path(table).read_text().splitlines()[1:]
            except OSError:
                continue
            for line in lines:
                fields = line.split()
                if len(fields) < 10 or fields[3] != "01":
                    continue
                local = fields[1].rsplit(":", 1)[-1]
                remote = fields[2].rsplit(":", 1)[-1]
                if local.upper() == f"{peer_port:04X}" and remote.upper() == f"{local_port:04X}":
                    inodes.add(fields[9])
        for proc in Path("/proc").glob("[0-9]*"):
            try:
                for fd in (proc / "fd").iterdir():
                    try:
                        target = os.readlink(fd)
                    except OSError:
                        continue
                    if any(target == f"socket:[{inode}]" for inode in inodes):
                        pid = int(proc.name)
                        return None if pid == os.getpid() else pid
            except OSError:
                continue
    except (OSError, ValueError, AttributeError):
        return None
    return None


def _sse(handler: BaseHTTPRequestHandler, chunks: list[dict[str, object]]) -> None:
    body = ("".join("data: " + json.dumps(chunk, separators=(",", ":")) + "\n\n"
                    for chunk in chunks) + "data: [DONE]\n\n").encode()
    handler.send_response(200)
    handler.send_header("content-type", "text/event-stream")
    handler.send_header("cache-control", "no-cache")
    handler.send_header("content-length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class _Provider(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args: object) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self.send_error(404)
            return
        if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + _PROVIDER_KEY):
            self.send_error(401)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 8 * 1024 * 1024:
                raise ValueError
            request = json.loads(self.rfile.read(size))
        except (ValueError, json.JSONDecodeError):
            self.send_error(400)
            return
        if (not isinstance(request, dict) or not isinstance(request.get("model"), str)
                or not isinstance(request.get("messages"), list)):
            self.send_error(400)
            return
        messages = request["messages"]
        rendered = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
        turn = "second" if _SECOND_PROMPT in rendered else "first"
        own_key = _REGISTRATION_KEYS[turn]
        current_keys = _registered_keys(messages)
        calls = _tool_calls(messages)
        is_initial = own_key not in current_keys
        user_messages = [item.get("content") for item in messages
                         if isinstance(item, dict) and item.get("role") == "user"]
        if turn == "first":
            expected_input = _FIRST_PROMPT
        else:
            from packages.contracts.conversation_rehydration import rehydrated_prompt
            expected_input = rehydrated_prompt([
                {"role": "user", "content": _FIRST_PROMPT},
                {"role": "assistant", "content": _ANSWER},
            ], _SECOND_PROMPT)
        # DSH may add its own instruction messages. Require the exact BYQ
        # Product input as one user message, once, without constraining those
        # DSH-owned instructions.
        exact_input = sum(content == expected_input for content in user_messages) == 1
        user_text = json.dumps(user_messages, ensure_ascii=False, separators=(",", ":"))
        with _LOCK:
            _PROVIDER_REQUESTS.append({
                "turn": turn,
                "initial": is_initial,
                "caller_pid": _pid_for_provider_peer(self),
                "exact_public_input": exact_input,
                "user_message_count": len(user_messages),
                "current_prompt_present": (_FIRST_PROMPT if turn == "first" else _SECOND_PROMPT) in user_text,
                "first_answer_present": _ANSWER in user_text,
                "user_text_length": len(user_text),
                "prior_private_tool_absent": (_PRIVATE_SENTINEL not in rendered and
                    not any(isinstance(item, dict) and item.get("role") == "tool" for item in messages)),
                "no_recovery_or_failed_envelope": (
                    "conversation_recovery" not in user_text and "failed_turn" not in user_text),
                "registration_call_count": sum(
                    1 for call in calls
                    if isinstance(call.get("function"), dict)
                    and call["function"].get("name") == _REGISTRATION_TOOL
                ),
                "own_registration_present": own_key in current_keys,
                "other_registration_present": any(
                    key in current_keys for key in _REGISTRATION_KEYS.values() if key != own_key
                ),
            })
        if is_initial:
            tools = request.get("tools", [])
            if not any(isinstance(item, dict) and isinstance(item.get("function"), dict)
                       and item["function"].get("name") == _REGISTRATION_TOOL for item in tools):
                self.send_error(400)
                return
            args = json.dumps({"role_id": "quant_orchestrator", "idempotency_key": own_key},
                              separators=(",", ":"))
            _sse(self, [
                {"choices": [{"index": 0, "delta": {"tool_calls": [{
                    "index": 0, "id": "p10-call-" + turn, "type": "function",
                    "function": {"name": _REGISTRATION_TOOL, "arguments": args},
                }]}, "finish_reason": None}]},
                {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
            ])
            return
        answer = _ANSWER if turn == "first" else "P10_SECOND_COMPLETED_" + _NONCE
        _sse(self, [
            {"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
            {"choices": [{"index": 0, "delta": {"content": answer}, "finish_reason": None}]},
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
             "usage": {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12}},
        ])

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/__phase10/evidence":
            self.send_error(404)
            return
        if not hmac.compare_digest(self.headers.get("Authorization", ""),
                                   "Bearer " + _OBSERVER_TOKEN):
            self.send_error(401)
            return
        with _LOCK:
            body = json.dumps({"provider_requests": list(_PROVIDER_REQUESTS),
                               "terminal_acks": list(_TERMINAL_ACKS),
                               "prepared_roots": list(_PREPARED_ROOTS)},
                              separators=(",", ":")).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _instrument_adapter(runtime_main: object) -> None:
    adapter = runtime_main.adapter
    original_build = adapter._build_harness

    def observed_build(*args: object, **kwargs: object) -> object:
        harness = original_build(*args, **kwargs)
        with _LOCK:
            _HARNESSES[id(harness)] = {
                "root_run_id": str(kwargs.get("root_run_id", "")),
                "generation_id": str(kwargs.get("runtime_generation", "")),
            }
        return harness

    adapter._build_harness = observed_build
    compatibility = adapter._compatibility
    original_prepare = compatibility.prepare_prompt

    def observed_prepare(harness: object, native_session_id: str) -> object:
        prepared = original_prepare(harness, native_session_id)
        with _LOCK:
            _PREPARED_ROOTS.append({**_HARNESSES.get(id(harness), {}),
                                    "native_session_id": native_session_id})
        return prepared

    compatibility.prepare_prompt = observed_prepare
    original_ack = adapter.acknowledge_terminal

    def observed_ack(session_id: str, receipt: object) -> dict:
        result = original_ack(session_id, receipt)
        with _LOCK:
            _TERMINAL_ACKS.append({"session_id": session_id, "receipt": receipt,
                                   "exact_ack": result == {"receipt": receipt}})
        return result

    adapter.acknowledge_terminal = observed_ack


provider = ThreadingHTTPServer(("127.0.0.1", 0), _Provider)
provider.daemon_threads = True
threading.Thread(target=provider.serve_forever, name="p10-scripted-provider", daemon=True).start()
observer = ThreadingHTTPServer(("127.0.0.1", 8401), _Provider)
observer.daemon_threads = True
threading.Thread(target=observer.serve_forever, name="p10-private-observer", daemon=True).start()
os.environ["BYQ_CREDENTIAL_RESOLVER_TOKEN"] = ""
os.environ["DEEPSEEK_API_KEY"] = _PROVIDER_KEY
os.environ["DEEPSEEK_BASE_URL"] = f"http://127.0.0.1:{provider.server_port}"

import sys  # noqa: E402

sys.path.insert(0, "/app")
from app import main as runtime_main  # noqa: E402
import uvicorn  # noqa: E402

_instrument_adapter(runtime_main)
uvicorn.run(runtime_main.app, host="0.0.0.0", port=8400)
