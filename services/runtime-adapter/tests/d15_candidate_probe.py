"""D15-1 isolated candidate probe for the coherent DSH 0.1.5-rc.1 pairing.

Runs inside the isolated candidate image only. It is a keyless probe: no real
model credential and no external network are used. A loopback synthetic MCP
server and a loopback scripted SSE provider stand in for the BYQ MCP and the
model provider so the official bundled 0.1.5 runtime can be started, prompted
and observed. The probe records raw notification methods, session event types
and event sequence numbers so the D15 ledger's ``tool_event_schema`` and
``profile_schema`` unknowns can be resolved with evidence.

It never writes to production storage: ``DSH_SESSION_ROOT`` is the candidate
session root baked into the image.
"""

from __future__ import annotations

import json
import os
import platform
import sys
import threading
import time
import traceback
import uuid
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import version
from pathlib import Path

sys.path.insert(0, "/app")

from app.runtime import RuntimeAdapter, SessionStatus  # noqa: E402


OUTPUT = Path(os.environ.get("D15_PROBE_OUTPUT", "/tmp/d15-candidate-probe.json"))


class McpHandler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:  # noqa: N802
        return

    def do_POST(self) -> None:  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        if "id" not in body:
            self.send_response(202)
            self.end_headers()
            return
        method = body.get("method")
        if method == "initialize":
            result = {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "synthetic", "version": "1"},
            }
        elif method == "tools/list":
            result = {"tools": [{
                "name": "byq_agent_run_start",
                "description": "synthetic D15 event-schema probe",
                "inputSchema": {"type": "object", "properties": {
                    "role_id": {"type": "string"},
                    "idempotency_key": {"type": "string"},
                }},
            }]}
        elif method == "tools/call":
            result = {"content": [{"type": "text", "text": json.dumps({"status": "ok"})}]}
        else:
            result = {"tools": []}
        encoded = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


class ScriptedProvider(BaseHTTPRequestHandler):
    requests: list[dict] = []

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length", "0"))
        body = json.loads(self.rfile.read(length))
        self.__class__.requests.append(body)
        has_result = any(item.get("role") == "tool" for item in body.get("messages", []))
        if has_result:
            payloads = [
                {"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
                {"choices": [{"index": 0, "delta": {"content": "D15候选运行正常"}, "finish_reason": None}]},
                {
                    "choices": [{"index": 0, "delta": {"content": ""}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 6},
                },
            ]
        else:
            payloads = [
                {"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
                {"choices": [{"index": 0, "delta": {"tool_calls": [{
                    "index": 0, "id": "d15-synthetic-call", "type": "function",
                    "function": {
                        "name": "mcp__byq__byq_agent_run_start",
                        "arguments": json.dumps({
                            "role_id": "quant_orchestrator",
                            "idempotency_key": "d15-synthetic-key",
                        }),
                    },
                }]}, "finish_reason": None}]},
                {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
            ]
        encoded = "".join(
            f"data: {json.dumps(item, separators=(',', ':'))}\n\n" for item in payloads
        ) + "data: [DONE]\n\n"
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("content-length", str(len(encoded.encode())))
        self.end_headers()
        self.wfile.write(encoded.encode())

    def log_message(self, *args: object) -> None:  # noqa: N802
        return


def main() -> int:
    result: dict[str, object] = {
        "schema_version": "byq-d15-candidate-start-probe.v1",
        "sdk": version("deepseek-harness-sdk"),
        "runtime_bin": version("deepseek-harness-runtime-bin"),
        "selector": os.environ.get("BYQ_DSH_COMPATIBILITY_RELEASE"),
        "platform": {"os": platform.system().lower(), "arch": platform.machine().lower()},
        "isolated": os.environ.get("DSH_SESSION_ROOT"),
        "keyless": True,
        "status": "FAIL",
    }
    mcp = ThreadingHTTPServer(("127.0.0.1", 0), McpHandler)
    provider = ThreadingHTTPServer(("127.0.0.1", 0), ScriptedProvider)
    for server in (mcp, provider):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    os.environ.update(
        BYQ_MCP_URL=f"http://127.0.0.1:{mcp.server_port}/mcp/v1",
        BYQ_MCP_TOKEN="synthetic-only",
        DEEPSEEK_API_KEY="scripted-test-only",
        DEEPSEEK_BASE_URL=f"http://127.0.0.1:{provider.server_port}",
    )
    adapter = None
    notification_methods: Counter[str] = Counter()
    event_types: Counter[str] = Counter()
    event_seqs: list[int] = []
    tool_events: dict[str, object] = {}
    try:
        adapter = RuntimeAdapter()
        result["compatibility_family"] = adapter._compatibility.family
        result["runtime_command"] = list(adapter.runtime_command)
        capture = {"methods": notification_methods, "types": event_types, "seqs": event_seqs}

        original = adapter._on_notification

        def observing(record: object, notification: object, **kwargs: object) -> None:
            method = getattr(notification, "method", None)
            if isinstance(method, str):
                capture["methods"][method] += 1
            payload = getattr(notification, "payload", None)
            event = payload.get("event") if isinstance(payload, dict) else None
            if isinstance(event, dict):
                if isinstance(event.get("type"), str):
                    capture["types"][event["type"]] += 1
                seq = event.get("seq")
                if type(seq) is int:
                    capture["seqs"].append(seq)
                if event.get("type") == "tool/call" and isinstance(event.get("data"), dict):
                    tool_events["tool_call_keys"] = sorted(event["data"].keys())
                    tool_events["tool_call_name"] = event["data"].get("name")
                if event.get("type") == "tool/result" and isinstance(event.get("data"), dict):
                    tool_events.setdefault("tool_result_keys", sorted(event["data"].keys()))
            original(record, notification, **kwargs)

        adapter._on_notification = observing  # type: ignore[method-assign]
        session_id = f"d15-probe-{uuid.uuid4().hex}"
        created = adapter.create_session(session_id, "d15-probe-trace")
        result["start_status"] = created["status"]
        result["start_reached_ready"] = created["status"] == SessionStatus.READY
        adapter.submit_prompt(session_id, "只回复D15候选运行正常")
        record = adapter._get(session_id)
        deadline = time.monotonic() + 60
        while adapter.describe_session(record)["status"] == SessionStatus.RUNNING and time.monotonic() < deadline:
            time.sleep(0.05)
        result["final_status"] = adapter.describe_session(record)["status"]
        if ScriptedProvider.requests:
            request = ScriptedProvider.requests[0]
            tools = request.get("tools", [])
            names = sorted({
                item["function"]["name"]
                for item in tools
                if isinstance(item, dict) and isinstance(item.get("function"), dict)
            })
            result["provider_request_seen"] = True
            result["tool_count"] = len(names)
            result["tool_names"] = names
            result["message_tool_blocked"] = not any(
                name in {
                    "bash", "pwsh", "jobs", "fs", "fs_search", "str_replace_editor",
                    "subagent", "subagent_fork", "workflow", "todo_write", "goal",
                    "ralph", "web_fetch", "list_agents", "send_message",
                }
                for name in names
            )
        else:
            result["provider_request_seen"] = False
        result["notification_methods"] = dict(sorted(capture["methods"].items()))
        result["event_types"] = dict(sorted(capture["types"].items()))
        result["event_seqs"] = capture["seqs"]
        result["event_seq_contiguous"] = (
            capture["seqs"] == list(range(min(capture["seqs"]), min(capture["seqs"]) + len(capture["seqs"])))
            if capture["seqs"] else None
        )
        result["history_kinds"] = [item["kind"] for item in record.history]
        result["tool_events"] = tool_events
        if result["final_status"] == SessionStatus.IDLE and result["start_reached_ready"]:
            result["status"] = "PASS"
    except BaseException as error:  # noqa: BLE001 - probe must always emit evidence
        result["status"] = "FAIL"
        result["error"] = f"{type(error).__name__}: {error}"
        result["traceback"] = traceback.format_exc()[-4000:]
        if adapter is not None:
            for session in list(adapter._sessions.values()):
                try:
                    result.setdefault("stderr_tail", list(session.harness.client._stderr_lines)[-80:])
                except Exception:  # noqa: BLE001
                    pass
    finally:
        if adapter is not None:
            try:
                adapter.close()
            except Exception:  # noqa: BLE001
                pass
        for server in (mcp, provider):
            server.shutdown()
            server.server_close()
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
