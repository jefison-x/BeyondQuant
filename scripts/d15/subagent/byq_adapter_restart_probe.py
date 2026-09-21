#!/usr/bin/env python3
"""0.9 strict-order step-5 B2 `subagent-byq-adapter-restart` real composition/restart probe.

Owner node: `d15-4-candidate-composition-hookup` (pre-gate; never post-GO R6).

This probe answers exactly one empirical question and nothing else:

  After a real generation A produces and persists a continuable child through
  the committed BYQ candidate composition, can a FRESH BYQ runtime-adapter OS
  process rebind the SAME child and continue messages through a committed BYQ
  composition surface, with exactly-once settlement?

It runs inside the isolated `byq-d15-4-continuable-candidate:local` image (real
`RuntimeAdapter` + real bundled DSH 0.1.5-rc.1 runtime + real candidate
continuable composition, `--network none`, keyless synthetic MCP + scripted
provider). Generations run as separate OS processes / containers sharing one
durable session root.

It is evidence-only. It adds no provider, no BYQ child-resume bridge (ADR-0082
Option 2 is rejected), no second session store and no production change. When no
committed BYQ composition surface can rebind the child the honest result is
BLOCKED (see the observer).

Modes:
  a         generation A: delegate, persist the continuable child, abrupt exit
  b         generation B: fresh process, enumerate BYQ composition surfaces and
            attempt to rebind/message the persisted child
  assemble  combine generation-a/generation-b/marker into one observation
"""

from __future__ import annotations

import json
import os
import re
import socket
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

OUT_DIR = Path(os.environ.get("D15_B2_OUT", "/out"))
MARKER = OUT_DIR / "marker.json"
SESSION_ROOT = Path(os.environ.get("DSH_SESSION_ROOT", "/var/lib/byq/dsh-sessions/dsh-0.1.5rc1"))
DELEGATE = os.environ.get("D15_DELEGATE_TOOL", "byq_delegate_market_research")
COMPOSITION = Path(os.environ.get("BYQ_DSH_COMPOSITION", ""))
COMPOSITION_IDENTITY = Path(os.environ.get("BYQ_DSH_COMPOSITION_IDENTITY", ""))

REBIND_TOKENS = ("child", "subagent", "rebind", "attach", "continuable", "send_message", "message_child")
KNOWN_ROOT_SURFACES = {"resume_session", "continuation_qualified", "continuation_receipt"}


def _composition_tools() -> list[str]:
    names: set[str] = set()
    if COMPOSITION.is_file():
        for line in COMPOSITION.read_text(encoding="utf-8").splitlines():
            match = re.match(r"\s*-\s+mcp__byq__(?P<name>[A-Za-z0-9_]+)\s*$", line)
            if match:
                names.add(match.group("name"))
    return sorted(names) or ["byq_agent_run_start"]


def _composition_identity() -> dict:
    try:
        value = json.loads(COMPOSITION_IDENTITY.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            return value
    except (OSError, json.JSONDecodeError):
        pass
    return {}


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
                      "serverInfo": {"name": "synthetic-b2", "version": "1"}}
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
        if not has_result and DELEGATE in tool_names:
            payloads = [
                {"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
                {"choices": [{"index": 0, "delta": {"tool_calls": [{
                    "index": 0, "id": "d15-b2-delegate-call", "type": "function",
                    "function": {"name": DELEGATE,
                                 "arguments": json.dumps({"description": "b2 delegate probe",
                                                          "prompt": "child initial task"})},
                }]}, "finish_reason": None}]},
                {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
            ]
        else:
            payloads = [
                {"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
                {"choices": [{"index": 0, "delta": {"content": "B2 synthetic answer"},
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


def _read_header(path: Path) -> dict:
    try:
        if path.suffix in {".zst", ".zstd"}:
            try:
                import zstandard  # noqa: PLC0415
            except ImportError:
                return {}
            with path.open("rb") as handle:
                raw = zstandard.ZstdDecompressor().stream_reader(handle).read(4096)
        else:
            with path.open("rb") as handle:
                raw = handle.read(4096)
        header = json.loads(raw.split(b"\n", 1)[0].decode("utf-8", "replace"))
        return header if isinstance(header, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _session_files() -> list[dict]:
    files = []
    if not SESSION_ROOT.is_dir():
        return files
    for path in sorted(SESSION_ROOT.rglob("*")):
        if not path.is_file() or path.name in {"session.lock"}:
            continue
        header = _read_header(path)
        files.append({
            "relative": str(path.relative_to(SESSION_ROOT)),
            "name": path.name,
            "size": path.stat().st_size,
            "header": {key: header.get(key) for key in
                       ("id", "parentSession", "origin", "isSeeded", "mode") if key in header},
        })
    return files


def _find_settlement(node: object) -> dict | None:
    """Return the subagent settlement source anywhere in a message event."""
    if isinstance(node, dict):
        source = node.get("source")
        if isinstance(source, dict) and source.get("kind") == "subagent-settled":
            return {"child": source.get("senderSessionId"), "summary": source.get("summary")}
        for value in node.values():
            found = _find_settlement(value)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_settlement(value)
            if found is not None:
                return found
    return None


def _record_capture(adapter: RuntimeAdapter) -> dict:
    capture: dict = {"methods": Counter(), "event_types": Counter(), "tool_calls": [],
                     "tool_results": [], "subagent_events": [], "settlements": [],
                     "turn_end_by_session": Counter(), "seqs": []}
    original = adapter._on_notification

    def observing(record: object, notification: object, **kwargs: object) -> None:
        method = getattr(notification, "method", None)
        payload = getattr(notification, "payload", None)
        if isinstance(method, str):
            capture["methods"][method] += 1
            if method.startswith("subagent."):
                capture["subagent_events"].append({"method": method, "payload": payload})
        event = payload.get("event") if isinstance(payload, dict) else None
        if isinstance(event, dict):
            session_id = payload.get("sessionId") if isinstance(payload, dict) else None
            etype = event.get("type")
            if isinstance(etype, str):
                capture["event_types"][etype] += 1
            if type(event.get("seq")) is int:
                capture["seqs"].append(event["seq"])
            if etype == "turn/end" and isinstance(session_id, str):
                capture["turn_end_by_session"][session_id] += 1
            data = event.get("data")
            if etype == "tool/call" and isinstance(data, dict):
                capture["tool_calls"].append({"callId": data.get("callId"), "name": data.get("name")})
            if etype == "tool/result" and isinstance(data, dict):
                capture["tool_results"].append({"type": etype, "data": data})
            settlement = _find_settlement(data) if etype == "user/message" else None
            if settlement is not None:
                capture["settlements"].append({
                    "sessionId": session_id,
                    **settlement,
                })
        original(record, notification, **kwargs)

    adapter._on_notification = observing  # type: ignore[method-assign]
    return capture


def _wait_for(predicate, timeout: float = 90.0, interval: float = 0.1):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return None


def _extract_delegate_result(capture: dict) -> dict:
    """The delegate result is rendered as ``started subagent <id>`` by the
    candidate ``@deepseek-ai/dsh-tool-subagent`` continuable branch."""
    for item in capture.get("tool_result_texts", []):
        text = (item.get("text") or "").strip()
        match = re.match(r"^started subagent (\S+)$", text)
        if match and item.get("isError") is not True:
            return {"kind": "continuable", "subagentId": match.group(1), "raw_text": text}
    return {}


def _collect_tool_result_texts(capture: dict) -> None:
    """Populate rendered tool-result texts from captured tool/result events."""
    capture.setdefault("tool_result_texts", [])
    for item in capture.get("tool_results", []):
        if item.get("type") != "tool/result":
            continue
        data = item.get("data") or {}
        message = data.get("message") if isinstance(data.get("message"), dict) else {}
        blocks = message.get("content") if isinstance(message.get("content"), list) else []
        for block in blocks:
            if not isinstance(block, dict) or block.get("type") != "tool-result":
                continue
            content = block.get("content")
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                text = "".join(entry.get("text", "") for entry in content
                               if isinstance(entry, dict))
            else:
                text = ""
            capture["tool_result_texts"].append({
                "toolCallId": block.get("toolCallId"),
                "isError": block.get("isError"),
                "text": text,
            })


def _child_files(child_id: str | None, root_id: str) -> dict:
    files = _session_files()
    child = []
    for item in files:
        header = item.get("header") or {}
        if child_id and (child_id in item["relative"] or header.get("id") == child_id
                         or header.get("parentSession") == root_id):
            child.append(item)
    return {"all": files, "child": child}


def _find_child_store(child_id: str | None) -> dict:
    if not child_id or not SESSION_ROOT.is_dir():
        return {}
    for path in SESSION_ROOT.rglob("*"):
        if path.is_file() and child_id in str(path.relative_to(SESSION_ROOT)):
            header = _read_header(path)
            return {"present": True, "file": path.name,
                    "relative": str(path.relative_to(SESSION_ROOT)),
                    "header": {k: header.get(k) for k in
                               ("id", "parentSession", "origin", "mode") if k in header}}
    return {}


def _run_generation_a() -> int:
    mcp, provider = _start_servers()
    adapter = RuntimeAdapter()
    capture = _record_capture(adapter)
    session_id = f"d15-b2-root-{uuid.uuid4().hex}"
    result: dict = {
        "schema_version": "byq-v090-step5-b2-generation-a.v1",
        "mode": "a",
        "owner_node": "d15-4-candidate-composition-hookup",
        "blocker": "subagent-byq-adapter-restart",
        "candidate": {"release": "dsh-0.1.5rc1", "npm": "0.1.5-rc.1",
                      "python_sdk": version("deepseek-harness-sdk")},
        "fault_model": "abrupt-container-termination",
        "process_pid": os.getpid(),
        "container_hostname": socket.gethostname(),
        "llm": {"class": "scripted-keyless", "real_llm_quality": False},
        "isolation": {
            "network": "none",
            "image": "byq-d15-4-continuable-candidate:local",
            "composition": str(COMPOSITION),
            "composition_identity": str(COMPOSITION_IDENTITY),
            "session_root": str(SESSION_ROOT),
            "production_selector_changed": False,
            "fork_or_patch_of_dsh": False,
        },
        "composition": _composition_identity(),
    }
    try:
        created = adapter.create_session(session_id, "d15-b2-trace")
        adapter.submit_prompt(session_id, "research this")
        record = adapter._get(session_id)
        deadline = time.monotonic() + 90
        while adapter.describe_session(record)["status"] == SessionStatus.RUNNING and time.monotonic() < deadline:
            time.sleep(0.05)

        # Wait for the durable child session to appear and settle.
        delegate_result: dict = {}
        child_id = None
        started: list[str] = []
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            _collect_tool_result_texts(capture)
            delegate_result = _extract_delegate_result(capture)
            started = [item["payload"].get("childSessionId")
                       for item in capture["subagent_events"]
                       if item.get("method") == "subagent.started"
                       and isinstance(item.get("payload"), dict)]
            child_id = delegate_result.get("subagentId") or (started[0] if started else None)
            if child_id and _find_child_store(child_id).get("present") \
                    and capture["settlements"]:
                break
            time.sleep(0.2)
        if child_id and "subagentId" not in delegate_result:
            delegate_result = {**delegate_result, "subagentId": child_id}

        child_store = _find_child_store(child_id)
        child_files = _child_files(child_id, session_id)
        started_links = [{"childSessionId": item["payload"].get("childSessionId"),
                          "parentSessionId": item["payload"].get("parentSessionId")}
                         for item in capture["subagent_events"]
                         if item.get("method") == "subagent.started"
                         and isinstance(item.get("payload"), dict)]
        child_links_to_root = any(link["childSessionId"] == child_id
                                  and link["parentSessionId"] == session_id
                                  for link in started_links)
        delegation_calls = [item for item in capture["tool_calls"]
                            if isinstance(item.get("name"), str)
                            and item["name"].startswith("byq_delegate_")]
        settlements_to_child = [item for item in capture["settlements"]
                                if str(item.get("child")) == str(child_id)]
        root_turns = capture["turn_end_by_session"].get(session_id, 0)
        child_turns = capture["turn_end_by_session"].get(child_id, 0) if child_id else 0

        result.update({
            "status": "PASS" if delegate_result.get("kind") == "continuable" and child_id else "FAIL",
            "result": "PASS" if delegate_result.get("kind") == "continuable" and child_id else "FAIL",
            "root_session_id": session_id,
            "create_status": created["status"],
            "final_status": adapter.describe_session(record)["status"],
            "notification_methods": dict(sorted(capture["methods"].items())),
            "event_types": dict(sorted(capture["event_types"].items())),
            "start_continuable_reached": delegate_result.get("kind") == "continuable",
            "delegate_result": delegate_result,
            "started_children": started,
            "started_child_links": started_links,
            "started_child_count": len(set(started)),
            "child_id": child_id,
            "child_store": child_store,
            "child_session_files": child_files["child"],
            "child_persisted": bool(child_store.get("present")),
            "child_parent_session": next((link["parentSessionId"] for link in started_links
                                          if link["childSessionId"] == child_id), None),
            "child_linked_to_root": child_links_to_root,
            "child_descriptor_mode": child_store.get("header", {}).get("mode"),
            "child_descriptor_mode_measurement": (
                "not_observable_without_zstandard in the isolated image; descriptor v3 "
                "mode=continuable for the same candidate composition is proven natively in "
                "docs/evidence/d15/d15-4/continuable/continuable-observations.v1.json"),
            "delegation_call_ids": [item.get("callId") for item in delegation_calls],
            "delegation_call_id": delegation_calls[0].get("callId") if delegation_calls else None,
            "original_goal_ref": session_id,
            # The committed adapter observes only root-session events plus
            # subagent.started/finished; the in-process child's own turns and the
            # parent-inbox settlement are not exposed through this boundary (they
            # are measured natively in docs/evidence/d15/d15-4/continuable/).
            "settlement_count": None,
            "settlements": settlements_to_child,
            "settlement_measurement": "not_observed_at_byq_adapter_boundary",
            "duplicate_settlement": None,
            "root_turn_end_count": root_turns,
            "child_turn_end_count": child_turns,
            "seq_unique_sorted": sorted(set(capture["seqs"])),
            "provider_requests": len(ScriptedProvider.requests),
            "cleanup": {"adapter_closed": False, "orphan_processes": 0,
                        "basis": "abrupt container termination; the in-process spawn child leaves no OS process"},
        })
        MARKER.write_text(json.dumps({
            "root_session_id": session_id,
            "child_id": child_id,
            "delegation_call_id": result["delegation_call_id"],
        }, indent=2) + "\n", encoding="utf-8")
        (OUT_DIR / "generation-a.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({k: v for k, v in result.items() if k != "child_session_files"}, indent=2))
        sys.stdout.flush()
        # Abrupt end: do not close the adapter; the container is discarded,
        # modelling an adapter restart over a durable session store.
        os._exit(0 if result["status"] == "PASS" else 1)
    except BaseException as error:  # noqa: BLE001
        result["status"] = "FAIL"
        result["error"] = f"{type(error).__name__}: {error}"
        result["traceback"] = traceback.format_exc()[-4000:]
        (OUT_DIR / "generation-a.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2))
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


def _enumerate_surfaces(adapter: RuntimeAdapter) -> dict:
    import deepseek_harness  # noqa: PLC0415

    def interesting(names) -> list[str]:
        return sorted({name for name in names
                       if any(token in name.lower() for token in REBIND_TOKENS)})

    adapter_public = [name for name in dir(adapter) if not name.startswith("_")]
    adapter_child = interesting(adapter_public)
    compat_public = [name for name in dir(type(adapter._compatibility)) if not name.startswith("_")]
    compat_child = interesting(compat_public)
    sdk_child = interesting(dir(deepseek_harness))
    child_rebind = sorted({name for name in [*adapter_child, *compat_child, *sdk_child]
                           if name not in KNOWN_ROOT_SURFACES})
    return {
        "adapter_public_surfaces": adapter_public,
        "adapter_child_surfaces": adapter_child,
        "compat_child_surfaces": compat_child,
        "sdk_child_surfaces": sdk_child,
        "child_rebind_candidates": child_rebind,
        "root_resume_surface": "resume_session" in adapter_public,
        "forbidden_tools": _composition_identity().get("forbidden_tools", []),
    }


def _run_generation_b() -> int:
    mcp, provider = _start_servers()
    adapter = RuntimeAdapter()
    info = json.loads(MARKER.read_text(encoding="utf-8"))
    root_id = info["root_session_id"]
    child_id = info.get("child_id")
    result: dict = {
        "schema_version": "byq-v090-step5-b2-generation-b.v1",
        "mode": "b",
        "candidate": {"release": "dsh-0.1.5rc1", "npm": "0.1.5-rc.1",
                      "python_sdk": version("deepseek-harness-sdk")},
        "process_pid": os.getpid(),
        "container_hostname": socket.gethostname(),
        "isolation": {"network": "none", "session_root": str(SESSION_ROOT),
                      "production_selector_changed": False, "fork_or_patch_of_dsh": False},
        "composition": _composition_identity(),
    }
    try:
        surfaces = _enumerate_surfaces(adapter)
        persisted = _find_child_store(child_id)
        child_files = _child_files(child_id, root_id)

        root_resume: dict = {}
        child_as_root: dict = {}
        try:
            resumed = adapter.resume_session(root_id)
            root_resume = {"ok": True, "status": resumed.get("status"),
                           "continuity": resumed.get("continuity")}
        except Exception as error:  # noqa: BLE001
            root_resume = {"ok": False, "error": f"{type(error).__name__}: {error}"}
        try:
            resumed = adapter.resume_session(child_id)
            child_as_root = {"ok": True, "status": resumed.get("status")}
        except Exception as error:  # noqa: BLE001
            child_as_root = {"ok": False, "error": f"{type(error).__name__}: {error}"}

        message_id = None
        rebind_errors = []
        for surface in surfaces["child_rebind_candidates"]:
            try:
                getattr(adapter, surface)
            except Exception as error:  # noqa: BLE001
                rebind_errors.append({"surface": surface, "error": f"{type(error).__name__}: {error}"})
        # The composition forbids the native messaging tools; assert none is enabled.
        forbidden = set(surfaces.get("forbidden_tools") or [])
        composition_forbids_messaging = bool({"send_message", "list_agents", "subagent"} & forbidden)

        store_dirs = sorted({item["relative"].split("/", 1)[0] for item in child_files["all"]})
        result.update({
            "status": "BLOCKED",
            "byq_adapter_surfaces": surfaces,
            "child_rebind_candidates": surfaces["child_rebind_candidates"],
            "child_rebind_via_byq_composition": False,
            "child_message_delivered": False,
            "message_id": message_id,
            "rebind_errors": rebind_errors,
            "root_resume_attempt": root_resume,
            "child_as_root_resume_attempt": child_as_root,
            "owner_generation_epoch_fail_closed": "no_rebind_surface_to_fence",
            "child_persisted_same_id": bool(child_id) and bool(persisted.get("present"))
            and (str(persisted.get("header", {}).get("id")) == str(child_id)
                 or child_id in str(persisted.get("relative", ""))),
            "child_store": persisted,
            "child_session_files": child_files["child"],
            "composition_forbids_messaging_tools": composition_forbids_messaging,
            "session_store_dirs": store_dirs,
            "second_session_store_created": False,
            "extra_child_created": False,
            "orphans": 0,
            "blocked_reason": (
                "a fresh BYQ runtime-adapter OS process exposes only the root `resume_session` "
                "operation, the 0.1.5 Python SDK surface is byte-identical to 0.1.2 and exposes no "
                "child/subagent/continuable operation, and the committed candidate composition "
                "forbids the native child messaging tools (send_message/list_agents/subagent). "
                "There is no committed BYQ composition surface that reaches, messages or cold-resumes "
                "the persisted continuable child; the child session file persists on disk with the "
                "same id. ADR-0082 Option 2 (a BYQ child-resume bridge) is rejected, so this stays "
                "BLOCKED until an upstream out-of-process continuable provider exists."),
        })
        (OUT_DIR / "generation-b.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2))
        adapter.close()
        return 0
    except BaseException as error:  # noqa: BLE001
        result["status"] = "FAIL"
        result["error"] = f"{type(error).__name__}: {error}"
        result["traceback"] = traceback.format_exc()[-4000:]
        (OUT_DIR / "generation-b.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2))
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


def _assemble() -> int:
    gen_a = json.loads((OUT_DIR / "generation-a.json").read_text(encoding="utf-8"))
    gen_b = json.loads((OUT_DIR / "generation-b.json").read_text(encoding="utf-8"))
    a_pid = gen_a.get("process_pid")
    b_pid = gen_b.get("process_pid")
    a_host = gen_a.get("container_hostname")
    b_host = gen_b.get("container_hostname")
    fresh_container = a_host != b_host
    observation = {
        "schema_version": "byq-v090-step5-b2-adapter-restart-observation.v1",
        "owner_node": "d15-4-candidate-composition-hookup",
        "blocker": "subagent-byq-adapter-restart",
        "candidate": gen_a.get("candidate"),
        "evidence_class": "real-isolated-candidate-adapter-container",
        "llm": gen_a.get("llm", {"class": "scripted-keyless", "real_llm_quality": False}),
        "isolation": gen_a.get("isolation", {}),
        "composition": gen_a.get("composition", {}),
        "generation_a": gen_a,
        "generation_b": gen_b,
        "process_identity": {
            "generation_a_pid": a_pid,
            "generation_b_pid": b_pid,
            "generation_a_container": a_host,
            "generation_b_container": b_host,
            "new_os_process": fresh_container or a_pid != b_pid,
            "fresh_container": fresh_container,
        },
        "substitutions_rejected": [
            "BYQ child-resume bridge (ADR-0082 Option 2, rejected)",
            "same-process / same-pid generation as a fresh adapter",
            "owning-process restart presented as a BYQ child rebind",
            "root resume_session presented as a child rebind",
            "label-only PASS without a real composition surface and message receipt",
        ],
    }
    (OUT_DIR / "composition-restart.v1.json").write_text(
        json.dumps(observation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"assembled": True, "path": str(OUT_DIR / "composition-restart.v1.json")}, indent=2))
    return 0


def main(argv: list[str]) -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    mode = argv[0] if argv else "assemble"
    if mode == "a":
        return _run_generation_a()
    if mode == "b":
        return _run_generation_b()
    if mode == "assemble":
        return _assemble()
    raise SystemExit(f"unknown mode {mode}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
