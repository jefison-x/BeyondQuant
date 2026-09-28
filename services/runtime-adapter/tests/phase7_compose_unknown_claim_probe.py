"""Real DSH/Product MCP sequence for Phase 7 unknown-claim evidence.

The host creates the Product session and turn through Gateway. This Adapter
PID-1 fixture provides only a local scripted model endpoint; it calls the real
Product MCP tools through the configured MCP URL and blocks after observing the
actual non-retryable ``outcome_unknown`` result.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


if os.environ.get("BYQ_PHASE7_UNKNOWN_CLAIM_PROBE") != "1":
    raise SystemExit("isolated Phase 7 unknown-claim Adapter opt-in required")

_PROVIDER_KEY = "phase7-" + secrets.token_urlsafe(32)
_HOLD_AFTER_UNKNOWN = threading.Event()
_CONTEXT = "mcp__byq__byq_agent_context"
_REGISTRATION = "mcp__byq__byq_agent_run_start"
_TASK_CREATE = "mcp__byq__byq_research_task_create"
_STRATEGY_VALIDATE = "mcp__byq__byq_strategy_validate"
_AGENT_RUN_ID = re.compile(r"agent_run_[0-9a-f]{32}")
_TASK_ID = re.compile(r"task_[0-9a-f]{32}")


def _log(event: str, **metadata: object) -> None:
    # Never pass provider request bodies, tool arguments, credentials, or
    # business identifiers to this intentionally metadata-only logger.
    print(json.dumps({"phase7_unknown_claim_probe": event, **metadata},
                     separators=(",", ":"), sort_keys=True), flush=True)


def _texts(value: object):
    if isinstance(value, str):
        yield value
        try:
            decoded = json.loads(value)
        except (ValueError, TypeError):
            return
        if decoded != value:
            yield from _texts(decoded)
    elif isinstance(value, dict):
        for child in value.values():
            yield from _texts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _texts(child)


def _called_tools(messages: list[object]) -> set[str]:
    called: set[str] = set()
    for message in messages:
        if not isinstance(message, dict):
            continue
        for call in message.get("tool_calls", []):
            if not isinstance(call, dict):
                continue
            function = call.get("function")
            if isinstance(function, dict) and isinstance(function.get("name"), str):
                called.add(function["name"])
    return called


def _history_ids(messages: list[object]) -> tuple[str | None, str | None]:
    history = "\n".join(text for text in _texts(messages))
    agent_run = _AGENT_RUN_ID.search(history)
    task = _TASK_ID.search(history)
    return (agent_run.group(0) if agent_run else None,
            task.group(0) if task else None)


def _json_values(value: object):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _json_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _json_values(child)
    elif isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (ValueError, TypeError):
            return
        if decoded != value:
            yield from _json_values(decoded)


def _trusted_owner_trace(messages: list[object]) -> tuple[str | None, str | None]:
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "tool":
            continue
        for value in _json_values(message.get("content")):
            context = value.get("context")
            if (isinstance(context, dict)
                    and isinstance(context.get("owner_principal"), str)
                    and isinstance(context.get("trace_id"), str)):
                return context["owner_principal"], context["trace_id"]
    return None, None


def _unknown_result(messages: list[object]) -> tuple[bool, bool]:
    # MCP tool output is represented as text in the DSH conversation. Decode
    # nested JSON strings without logging or retaining the raw content.
    text = "\n".join(item for item in _texts(messages))
    status_unknown = re.search(r'"status"\s*:\s*"outcome_unknown"', text) is not None
    retryable_false = re.search(r'"retryable"\s*:\s*false', text) is not None
    return status_unknown, retryable_false


def _sse(handler: BaseHTTPRequestHandler, tool: str, arguments: dict[str, object], call_id: str) -> None:
    chunks = [
        {"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0,
            "id": call_id, "type": "function", "function": {
                "name": tool, "arguments": json.dumps(arguments, separators=(",", ":")),
            }}]}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
    ]
    body = ("".join("data: " + json.dumps(item, separators=(",", ":")) + "\n\n"
                     for item in chunks) + "data: [DONE]\n\n").encode()
    handler.send_response(200)
    handler.send_header("content-type", "text/event-stream")
    handler.send_header("cache-control", "no-cache")
    handler.send_header("content-length", str(len(body)))
    handler.end_headers()
    try:
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError):
        return


class _ScriptedProvider(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args: object) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802
        if not hmac.compare_digest(self.headers.get("Authorization", ""),
                                   "Bearer " + _PROVIDER_KEY):
            self.send_error(401)
            return
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self.send_error(404)
            return
        try:
            size = int(self.headers.get("content-length", "0"))
            if size <= 0 or size > 8 * 1024 * 1024:
                raise ValueError("invalid request size")
            request = json.loads(self.rfile.read(size))
        except (ValueError, TypeError, json.JSONDecodeError):
            self.send_error(400)
            return
        if (not isinstance(request, dict) or not isinstance(request.get("model"), str)
                or not isinstance(request.get("messages"), list)):
            self.send_error(400)
            return
        messages = request["messages"]
        offered = {item.get("function", {}).get("name") for item in request.get("tools", [])
                   if isinstance(item, dict) and isinstance(item.get("function"), dict)}
        if not {_CONTEXT, _REGISTRATION, _TASK_CREATE, _STRATEGY_VALIDATE}.issubset(offered):
            self.send_error(400)
            return

        called = _called_tools(messages)
        if _CONTEXT not in called:
            _sse(self, _CONTEXT, {}, "phase7-unknown-claim-context")
            return
        if _REGISTRATION not in called:
            _sse(self, _REGISTRATION,
                 {"role_id": "quant_orchestrator",
                  "idempotency_key": "phase7-unknown-claim-agent-run"},
                 "phase7-unknown-claim-agent-run")
            return
        if _TASK_CREATE not in called:
            owner_principal, trace_id = _trusted_owner_trace(messages)
            if owner_principal is None or trace_id is None:
                _log("TRUSTED_CONTEXT_MISSING", owner_present=owner_principal is not None,
                     trace_present=trace_id is not None)
                self.send_error(502)
                return
            _sse(self, _TASK_CREATE,
                 {"owner_principal": owner_principal,
                  "title": "Phase 7 unknown claim fixture",
                  "objective": "Disposable synthetic task for an unknown strategy validation outcome.",
                  "trace_id": trace_id,
                  "idempotency_key": "phase7-unknown-claim-task"},
                 "phase7-unknown-claim-task")
            return
        if _STRATEGY_VALIDATE not in called:
            agent_run_id, task_id = _history_ids(messages)
            _owner_principal, trace_id = _trusted_owner_trace(messages)
            if agent_run_id is None or task_id is None:
                _log("REQUIRED_TOOL_RESULT_ID_MISSING", agent_run_id_present=agent_run_id is not None,
                     task_id_present=task_id is not None)
                self.send_error(502)
                return
            if trace_id is None:
                _log("TRUSTED_CONTEXT_MISSING", owner_present=False, trace_present=False)
                self.send_error(502)
                return
            _sse(self, _STRATEGY_VALIDATE,
                 {"task_id": task_id, "agent_run_id": agent_run_id,
                  "idempotency_key": "phase7-unknown-claim-strategy",
                  "trace_id": trace_id,
                  "strategy": {"strategy_id": "Phase7UnknownClaim",
                               "name": "Phase 7 unknown claim fixture",
                               "category": "custom", "source_type": "python_script",
                               "script": "class CustomStrategy:\n"
                                         "    def generate_signals(self, data, parameters):\n"
                                         "        return {}"}},
                 "phase7-unknown-claim-strategy")
            return

        status_unknown, retryable_false = _unknown_result(messages)
        if not status_unknown or not retryable_false:
            _log("MCP_OUTCOME_UNKNOWN_MISMATCH", status_is_outcome_unknown=status_unknown,
                 retryable_is_false=retryable_false)
            self.send_error(502)
            return
        _log("MCP_OUTCOME_UNKNOWN", status_is_outcome_unknown=True,
             retryable_is_false=True)
        _HOLD_AFTER_UNKNOWN.wait()


provider = ThreadingHTTPServer(("127.0.0.1", 0), _ScriptedProvider)
provider.daemon_threads = True
threading.Thread(target=provider.serve_forever, name="phase7-unknown-claim-provider",
                 daemon=True).start()

# Only the isolated DSH runtime receives this generated local key.
os.environ["BYQ_CREDENTIAL_RESOLVER_TOKEN"] = ""
os.environ["DEEPSEEK_API_KEY"] = _PROVIDER_KEY
os.environ["DEEPSEEK_BASE_URL"] = f"http://127.0.0.1:{provider.server_port}"

import sys  # noqa: E402

sys.path.insert(0, "/app")

from app import main as runtime_main  # noqa: E402
import uvicorn  # noqa: E402


uvicorn.run(runtime_main.app, host="0.0.0.0", port=8400)
