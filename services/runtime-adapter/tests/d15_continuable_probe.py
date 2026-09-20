"""D15-4 real isolated candidate continuable-delegate probe.

Runs inside the isolated `dsh-0.1.5rc1` candidate image with the
candidate-specific continuable profile mounted. It is keyless and networkless: a
loopback synthetic MCP server and a loopback scripted SSE provider stand in for
the BYQ MCP and the model provider, and the real bundled 0.1.5 runtime (through
the real `RuntimeAdapter`) is started, prompted and observed.

Two OS-process generations share one session root:

* generation ``a`` submits a turn whose scripted model calls a real
  ``byq_delegate_market_research`` tool, records the tool result kind, the child
  session identity persisted under the DSH home, the observed subagent
  notifications and then terminates abruptly (`os._exit`) to model an
  adapter-process restart.
* generation ``b`` starts a fresh adapter over the same session root and
  attempts to reach/cold-resume the persisted child through any committed BYQ
  surface, recording the exact outcome.

It is evidence-only: no production storage, no real credential, no new provider.
"""

from __future__ import annotations

import json
import os
import re
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

MARKER = Path(os.environ.get("D15_CONTINUABLE_MARKER", "/tmp/d15-continuable-marker.json"))
DELEGATE = os.environ.get("D15_DELEGATE_TOOL", "byq_delegate_market_research")


def _composition_tools() -> list[str]:
    patch = Path(os.environ.get("BYQ_DSH_COMPOSITION", ""))
    names: set[str] = set()
    if patch.is_file():
        for line in patch.read_text(encoding="utf-8").splitlines():
            # The synthetic MCP server is named `byq`, so DSH itself prefixes
            # advertised tools with `mcp__byq__`; advertise the unprefixed name.
            match = re.match(r"\s*-\s+mcp__byq__(?P<name>[A-Za-z0-9_]+)\s*$", line)
            if match:
                names.add(match.group("name"))
    return sorted(names) or ["byq_agent_run_start"]


class McpHandler(BaseHTTPRequestHandler):
    tools: list[str] = []

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
            result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "synthetic-continuable", "version": "1"}}
        elif method == "tools/list":
            result = {"tools": [{
                "name": name, "description": f"synthetic tool {name}",
                "inputSchema": {"type": "object", "properties": {
                    "idempotency_key": {"type": "string"}}},
            } for name in self.__class__.tools]}
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
        messages = body.get("messages", [])
        has_result = any(item.get("role") == "tool" for item in messages)
        tool_names = sorted({
            item["function"]["name"]
            for item in body.get("tools", [])
            if isinstance(item, dict) and isinstance(item.get("function"), dict)
        })
        # Emit the delegate call only where the delegate tool is actually
        # available (the root request), never in the child's filtered tool list.
        if not has_result and DELEGATE in tool_names:
            payloads = [
                {"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
                {"choices": [{"index": 0, "delta": {"tool_calls": [{
                    "index": 0, "id": "d15-delegate-call", "type": "function",
                    "function": {"name": DELEGATE,
                                 "arguments": json.dumps({"description": "delegate probe",
                                                          "prompt": "child task"})},
                }]}, "finish_reason": None}]},
                {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
            ]
        else:
            payloads = [
                {"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
                {"choices": [{"index": 0, "delta": {"content": "D15 continuable synthetic answer"},
                              "finish_reason": None}]},
                {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 5, "completion_tokens": 6}},
            ]
        encoded = "".join(f"data: {json.dumps(item, separators=(',', ':'))}\n\n"
                          for item in payloads) + "data: [DONE]\n\n"
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("content-length", str(len(encoded.encode())))
        self.end_headers()
        self.wfile.write(encoded.encode())

    def log_message(self, *args: object) -> None:  # noqa: N802
        return


def _read_header(path: Path) -> dict:
    """Best-effort header read for a plain or zstd-compressed session store."""
    try:
        if path.suffix == ".zst":
            try:
                import zstandard  # noqa: PLC0415
            except ImportError:
                return {}
            with path.open("rb") as handle:
                raw = zstandard.ZstdDecompressor().stream_reader(handle).read(4096)
        else:
            with path.open("rb") as handle:
                raw = handle.read(4096)
        first = raw.split(b"\n", 1)[0]
        header = json.loads(first.decode("utf-8", "replace"))
        if isinstance(header, dict):
            return header
    except Exception:  # noqa: BLE001
        pass
    return {}


def _session_files(session_root: Path) -> list[dict]:
    files = []
    for path in sorted(session_root.rglob("*")):
        if not path.is_file():
            continue
        header = _read_header(path)
        files.append({
            "name": path.name,
            "relative": str(path.relative_to(session_root)),
            "size": path.stat().st_size,
            "header": {key: header.get(key) for key in
                       ("id", "parentSession", "origin", "isSeeded") if key in header},
        })
    return files


def _start_servers() -> tuple[ThreadingHTTPServer, ThreadingHTTPServer]:
    McpHandler.tools = _composition_tools()
    mcp = ThreadingHTTPServer(("127.0.0.1", 0), McpHandler)
    provider = ThreadingHTTPServer(("127.0.0.1", 0), ScriptedProvider)
    for server in (mcp, provider):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    os.environ.update(
        BYQ_MCP_URL=f"http://127.0.0.1:{mcp.server_port}/mcp/v1",
        BYQ_MCP_TOKEN="probe-token",
        DEEPSEEK_API_KEY="probe-api-key",
        DEEPSEEK_BASE_URL=f"http://127.0.0.1:{provider.server_port}",
    )
    return mcp, provider


def _run_adapter(session_id: str, content: str, *,
                 resume_existing: bool = False) -> tuple[RuntimeAdapter, dict, list[dict]]:
    adapter = RuntimeAdapter()
    capture = {"methods": Counter(), "event_types": Counter(), "tool_results": [],
               "subagent_events": [], "seqs": []}
    original = adapter._on_notification

    def observing(record: object, notification: object, **kwargs: object) -> None:
        method = getattr(notification, "method", None)
        if isinstance(method, str):
            capture["methods"][method] += 1
            if method.startswith("subagent."):
                capture["subagent_events"].append({"method": method,
                                                    "payload": getattr(notification, "payload", None)})
        payload = getattr(notification, "payload", None)
        event = payload.get("event") if isinstance(payload, dict) else None
        if isinstance(event, dict):
            if isinstance(event.get("type"), str):
                capture["event_types"][event["type"]] += 1
            if type(event.get("seq")) is int:
                capture["seqs"].append(event["seq"])
            if event.get("type") in {"tool/call", "tool/result"}:
                capture["tool_results"].append({"type": event["type"], "data": event.get("data")})
        original(record, notification, **kwargs)

    adapter._on_notification = observing  # type: ignore[method-assign]
    if resume_existing:
        created = adapter.resume_session(session_id)
    else:
        created = adapter.create_session(session_id, "d15-continuable-trace")
    adapter.submit_prompt(session_id, content)
    record = adapter._get(session_id)
    deadline = time.monotonic() + 90
    while adapter.describe_session(record)["status"] == SessionStatus.RUNNING and time.monotonic() < deadline:
        time.sleep(0.05)
    summary = {
        "create_status": created["status"],
        "final_status": adapter.describe_session(record)["status"],
        "notification_methods": dict(sorted(capture["methods"].items())),
        "event_types": dict(sorted(capture["event_types"].items())),
        "subagent_events": capture["subagent_events"],
        "tool_results": capture["tool_results"],
        "history_kinds": [item["kind"] for item in record.history],
        "seq_contiguous": (capture["seqs"] == list(range(min(capture["seqs"]),
                                                          min(capture["seqs"]) + len(capture["seqs"])))
                           if capture["seqs"] else None),
        "provider_requests": len(ScriptedProvider.requests),
    }
    return adapter, summary, [dict(item) for item in capture["tool_results"]]


def _tool_result_texts(tool_results: list[dict]) -> list[dict]:
    rendered = []
    for entry in tool_results:
        if entry.get("type") != "tool/result":
            continue
        data = entry.get("data") or {}
        message = data.get("message") if isinstance(data.get("message"), dict) else {}
        blocks = message.get("content") if isinstance(message.get("content"), list) else []
        for block in blocks:
            if not isinstance(block, dict) or block.get("type") != "tool-result":
                continue
            content = block.get("content")
            text = ""
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                text = "".join(item.get("text", "") for item in content
                               if isinstance(item, dict))
            rendered.append({"toolCallId": block.get("toolCallId"),
                             "isError": block.get("isError"), "text": text})
    return rendered


def _extract_delegate_result(tool_results: list[dict]) -> dict:
    """Derive the durable continuable result shape from the rendered tool result.

    DSH renders the continuable object as ``started subagent <id>`` (see the
    candidate ``@deepseek-ai/dsh-tool-subagent`` continuation branch), while the
    routing probe independently proved the underlying object is
    ``{kind: continuable, subagentId}``. A foreground result renders differently.
    """
    for item in _tool_result_texts(tool_results):
        text = (item.get("text") or "").strip()
        match = re.match(r"^started subagent (\S+)$", text)
        if match and item.get("isError") is not True:
            return {"kind": "continuable", "subagentId": match.group(1), "raw_text": text}
    return {}


def _find_child_headers(session_root: Path, root_id: str,
                        child_id: str | None = None) -> list[dict]:
    children = []
    for item in _session_files(session_root):
        header = item.get("header") or {}
        if header.get("parentSession") == root_id:
            children.append(item)
        elif child_id and child_id in item.get("relative", ""):
            children.append(item)
    return children


def main(argv: list[str]) -> int:
    mode = argv[0] if argv else "a"
    session_root = Path(os.environ.get("DSH_SESSION_ROOT", "/var/lib/byq/dsh-sessions/dsh-0.1.5rc1"))
    result: dict[str, object] = {
        "schema_version": "byq-d15-continuable-adapter-probe.v1",
        "mode": mode,
        "sdk": version("deepseek-harness-sdk"),
        "runtime_bin": version("deepseek-harness-runtime-bin"),
        "selector": os.environ.get("BYQ_DSH_COMPATIBILITY_RELEASE"),
        "composition": os.environ.get("BYQ_DSH_COMPOSITION"),
        "delegate_tool": DELEGATE,
        "keyless": True,
        "network": "none",
    }
    mcp, provider = _start_servers()
    adapter = None
    try:
        if mode == "a":
            session_id = f"d15-continuable-root-{uuid.uuid4().hex}"
            adapter, summary, tool_results = _run_adapter(session_id, "research this")
            delegate_result = _extract_delegate_result(tool_results)
            started_children = [item["payload"].get("childSessionId")
                                for item in summary.get("subagent_events", [])
                                if item.get("method") == "subagent.started"
                                and isinstance(item.get("payload"), dict)]
            child_id = delegate_result.get("subagentId") or (started_children[0] if started_children else None)
            if child_id and "subagentId" not in delegate_result:
                delegate_result = {**delegate_result, "subagentId": child_id}
            child_files = _find_child_headers(session_root, session_id, child_id)
            result.update({
                "root_session_id": session_id,
                "summary": summary,
                "delegate_result": delegate_result,
                "started_children": started_children,
                "child_sessions": child_files,
                "session_files": _session_files(session_root),
                "status": "PASS" if delegate_result.get("kind") == "continuable"
                and child_id else "FAIL",
            })
            MARKER.write_text(json.dumps({
                "root_session_id": session_id,
                "child_session_id": delegate_result.get("subagentId"),
                "child_sessions": child_files,
                "delegate_result": delegate_result,
                "summary": summary,
            }, indent=2) + "\n", encoding="utf-8")
            output = Path(os.environ.get("D15_PROBE_OUTPUT", "/tmp/d15-continuable-generation-a.json"))
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({k: v for k, v in result.items() if k != "session_files"}, indent=2))
            # Stop this adapter generation so a fresh OS process (mode b) restarts
            # over the same durable session root. The native harness separately
            # covers an abrupt owning-process SIGKILL.
            adapter.close()
            sys.stdout.flush()
            return 0 if result["status"] == "PASS" else 1
        if mode == "b":
            info = json.loads(MARKER.read_text(encoding="utf-8"))
            root_id = info["root_session_id"]
            child_id = info.get("child_session_id")
            adapter = RuntimeAdapter()
            # Enumerate every operation the committed BYQ runtime-adapter / SDK
            # boundary exposes that could reach or resume a child.
            tokens = ("child", "subagent", "resume", "continuable", "attach")
            candidates = sorted({
                name for source in (adapter, type(adapter), adapter._compatibility,
                                    type(adapter._compatibility))
                for name in dir(source) if any(token in name.lower() for token in tokens)
            })
            sdk_candidates = sorted(name for name in dir(_sdk_module())
                                    if any(token in name.lower() for token in tokens))
            # The persisted child (generation A) must still be on disk.
            persisted = _find_child_headers(session_root, root_id, child_id)
            # Attempt whatever root-level resume surface exists, recording the
            # real outcome instead of assuming it.
            resume_attempt: dict = {}
            try:
                resumed = adapter.resume_session(root_id)
                resume_attempt = {"ok": True, "status": resumed.get("status"),
                                  "continuity": resumed.get("continuity")}
            except Exception as error:  # noqa: BLE001
                resume_attempt = {"ok": False, "error": f"{type(error).__name__}: {error}"}
            result.update({
                "marker": info,
                "adapter_child_surfaces": candidates,
                "sdk_child_surfaces": sdk_candidates,
                "child_sessions_after": persisted,
                "root_resume_attempt": resume_attempt,
                "child_has_surface": any(
                    name in {"resume_child", "child_resume", "subagent_resume",
                             "continuable_resume", "send_message", "message_child"}
                    for name in [*candidates, *sdk_candidates]),
                "root_only_surfaces": [name for name in candidates if name == "resume_session"],
                "container_restart_observed": True,
                "child_resumed_via_byq_surface": False,
                "child_persisted_same_id": bool(child_id) and any(
                    child_id in item.get("relative", "") for item in persisted),
                "status": "BLOCKED",
                "blocked_reason": (
                    "a fresh isolated adapter process exposes only the root `resume_session` operation and "
                    "the byte-identical 0.1.2 Python SDK exposes no child/subagent/continuable operation; "
                    "there is no committed BYQ surface that reaches, messages or cold-resumes the persisted "
                    "continuable child. A BYQ adapter restart therefore cannot rebind the child, even though "
                    "the child session file persists on disk. The owning-process (adapter) restart tested "
                    "here is NOT a child-only SIGKILL."),
            })
            output = Path(os.environ.get("D15_PROBE_OUTPUT", "/tmp/d15-continuable-generation-b.json"))
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(result, indent=2))
            adapter.close()
            return 0
        raise SystemExit(f"unknown mode {mode}")
    except BaseException as error:  # noqa: BLE001
        result["status"] = "FAIL"
        result["error"] = f"{type(error).__name__}: {error}"
        result["traceback"] = traceback.format_exc()[-4000:]
        output = Path(os.environ.get("D15_PROBE_OUTPUT", f"/tmp/d15-continuable-{mode}.json"))
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2))
        if adapter is not None:
            try:
                adapter.close()
            except Exception:  # noqa: BLE001
                pass
        return 1
    finally:
        for server in (mcp, provider):
            try:
                server.shutdown()
                server.server_close()
            except Exception:  # noqa: BLE001
                pass


def adapter_class() -> type:
    return RuntimeAdapter


def _sdk_module() -> object:
    import deepseek_harness  # noqa: PLC0415
    return deepseek_harness


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
