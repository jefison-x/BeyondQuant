"""Opt-in keyless qualification on the exact pinned DSH runtime.

The probes use a local scripted provider and a local fake BYQ MCP server. They
exercise the real bundled process and public ``tools/pre-execute`` hook; they
do not use a real provider, database, or product user data.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import version
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("BYQ_BUDGET_SEMANTICS_TEST") != "1",
    reason="explicit isolated pinned DSH qualification",
)

_ALLOWED_ACTIONS = (
    "byq_research_get",
    "byq_backtest_task_get",
    "byq_agent_run_start",
    "byq_agent_authorize",
    "byq_agent_audit",
)
_ALLOWED_ALIASES = {"mcp__byq__" + name for name in _ALLOWED_ACTIONS}


def _sse(payloads: list[dict]) -> bytes:
    body = "".join(f"data: {json.dumps(item, separators=(',', ':'))}\n\n" for item in payloads)
    return (body + "data: [DONE]\n\n").encode()


def _tool_call(name: str, index: int) -> dict:
    return {
        "index": index,
        "id": f"continuation-call-{index + 1}",
        "type": "function",
        "function": {"name": name, "arguments": "{}"},
    }


def _root_tool_response() -> bytes:
    return _sse([
        {"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [_tool_call("mcp__byq__byq_research_get", 0)]}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
         "usage": {"prompt_tokens": 12, "completion_tokens": 4}},
    ])


def _many_tool_response(count: int) -> bytes:
    return _sse([
        {"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [
            _tool_call("mcp__byq__byq_research_get", index) for index in range(count)
        ]}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
         "usage": {"prompt_tokens": 12, "completion_tokens": 4}},
    ])


def _mcp_server():
    state = {"methods": [], "calls": [], "tools_list_count": 0}

    class Mcp(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers.get("content-length", "0"))))
            method = body.get("method")
            state["methods"].append(method)
            if "id" not in body:
                self.send_response(202)
                self.end_headers()
                return
            if method == "initialize":
                result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                          "serverInfo": {"name": "continuation-loopback", "version": "1"}}
            elif method == "tools/list":
                state["tools_list_count"] += 1
                result = {"tools": [{
                    "name": name,
                    "description": "Synthetic bounded continuation fixture.",
                    "inputSchema": {"type": "object", "properties": {
                        "task_id": {"type": "string"},
                    }},
                } for name in _ALLOWED_ACTIONS]}
            elif method == "tools/call":
                state["calls"].append(body.get("params", {}))
                result = {"content": [{"type": "text", "text": "synthetic read result"}]}
            else:
                result = {"tools": []}
            encoded = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Mcp)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, state


def _provider_server(responses: list[bytes]):
    state = {"requests": [], "tool_catalogs": []}

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers.get("content-length", "0"))))
            state["requests"].append(body)
            state["tool_catalogs"].append(sorted(
                item.get("function", {}).get("name")
                for item in body.get("tools", [])
                if isinstance(item, dict) and isinstance(item.get("function"), dict)
                and isinstance(item["function"].get("name"), str)
            ))
            payload = responses[min(len(state["requests"]) - 1, len(responses) - 1)]
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, state


def _configure_runtime(tmp_path, monkeypatch, mcp, provider):
    from packages.contracts.continuation_request import profile_binding, request_limits

    source = Path(os.environ["BYQ_DSH_COMPOSITION"]).read_text(encoding="utf-8")
    composition = tmp_path / "root-turn-composition.yml"
    composition.write_text(source, encoding="utf-8")
    identity = tmp_path / "root-turn-identity.json"
    identity.write_text(json.dumps({
        "root_identity_contract": "byq-root-process.v1",
        "composition_hash": "sha256:" + hashlib.sha256(source.encode()).hexdigest(),
    }), encoding="utf-8")
    monkeypatch.setenv("BYQ_DSH_PROCESS_OWNERSHIP", "root-turn")
    monkeypatch.setenv("BYQ_DSH_COMPOSITION", str(composition))
    monkeypatch.setenv("BYQ_DSH_COMPOSITION_IDENTITY", str(identity))
    monkeypatch.setenv("DSH_SESSION_ROOT", str(tmp_path / "sessions"))
    monkeypatch.setenv("BYQ_DSH_RUNTIME_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("BYQ_F6_EXECUTOR_ENABLED", "1")
    monkeypatch.setenv("BYQ_MCP_URL", f"http://127.0.0.1:{mcp.server_port}/mcp/v1")
    monkeypatch.setenv("BYQ_MCP_TOKEN", "synthetic-only")
    monkeypatch.setenv("BYQ_OWNER_PRINCIPAL", "synthetic-owner")
    monkeypatch.setenv("BYQ_WORKSPACE_ID", "synthetic-workspace")

    from app import runtime as runtime_module
    original_init = runtime_module.RequestGateProxy.__init__

    def loopback_upstream(self, gate, upstream):
        original_init(self, gate, upstream)
        # Test-only loopback seam after production's official-origin check.
        self._server.upstream = f"http://127.0.0.1:{provider.server_port}"

    monkeypatch.setattr(runtime_module.RequestGateProxy, "__init__", loopback_upstream)
    monkeypatch.setattr(runtime_module.RuntimeAdapter, "_resolve_model", lambda self, **kwargs: {
        "provider": "deepseek-official", "model": "deepseek-v4-flash", "api_key": "synthetic-only"})
    adapter = runtime_module.RuntimeAdapter()
    adapter._test_sdk_events = []
    adapter._test_sdk_exception = None
    original_run = adapter._compatibility.run_prepared_prompt
    original_prepare = adapter._compatibility.prepare_prompt

    def safe_error_value(value):
        if isinstance(value, str):
            return _safe_diagnostic_text(value, tmp_path)
        if value is None or isinstance(value, (int, bool)):
            return value
        if isinstance(value, dict):
            return {
                str(key)[:40]: safe_error_value(item)
                for key, item in list(value.items())[:8]
                if isinstance(key, str) and isinstance(item, (str, int, bool, dict, list, tuple))
            }
        if isinstance(value, (list, tuple)):
            return [safe_error_value(item) for item in value[:8]
                if isinstance(item, (str, int, bool, dict, list, tuple))]
        return {"type": type(value).__name__}

    def capture_sdk_exception(phase, error):
        attributes = {}
        for field in ("code", "message", "data", "error", "id"):
            try:
                value = getattr(error, field, None)
            except Exception:
                continue
            if value is not None:
                attributes[field] = safe_error_value(value)
        adapter._test_sdk_exception = {
            "phase": phase,
            "type": type(error).__name__,
            "message": _safe_diagnostic_text(str(error), tmp_path, max_chars=1000),
            "args": safe_error_value(getattr(error, "args", ())),
            "attributes": attributes,
        }

    def capture_prepare_prompt(harness, session_id):
        try:
            return original_prepare(harness, session_id)
        except Exception as error:
            capture_sdk_exception("prepare_prompt", error)
            raise

    def capture_sdk_events(prepared, content, callback):
        def capture(notification):
            method = getattr(notification, "method", None)
            payload = getattr(notification, "payload", None)
            event_row = {"method": method if isinstance(method, str) else type(method).__name__}
            if method == "session.status" and isinstance(payload, dict):
                status = payload.get("status")
                if isinstance(status, str):
                    event_row["status"] = status
            elif method == "session.event" and isinstance(payload, dict):
                event = payload.get("event")
                if isinstance(event, dict):
                    event_type = event.get("type")
                    if isinstance(event_type, str):
                        event_row["event_type"] = event_type
                    data = event.get("data")
                    reason = data.get("reason") if isinstance(data, dict) else None
                    if isinstance(reason, dict):
                        kind = reason.get("kind")
                        if isinstance(kind, str):
                            event_row["turn_reason"] = kind
                        error = reason.get("error")
                        if isinstance(error, dict):
                            for field in ("type", "code", "message"):
                                value = error.get(field)
                                if isinstance(value, str):
                                    event_row[f"error_{field}"] = _safe_diagnostic_text(value, tmp_path)
                        elif isinstance(error, str):
                            event_row["error_message"] = _safe_diagnostic_text(error, tmp_path)
            if len(adapter._test_sdk_events) < 256:
                adapter._test_sdk_events.append(event_row)
            callback(notification)
        try:
            return original_run(prepared, content, capture)
        except Exception as error:
            capture_sdk_exception("run_prepared_prompt", error)
            raise

    adapter._compatibility.prepare_prompt = capture_prepare_prompt
    adapter._compatibility.run_prepared_prompt = capture_sdk_events
    reservation = {
        "schema_version": "task-continuation-reservation.v2",
        "reservation_id": "continuation_" + "a" * 32,
        "task_id": "task_" + "b" * 32,
        "owner": "synthetic-owner",
        "workspace_id": "synthetic-workspace",
        "execution_profile": profile_binding(),
        "request_limits": request_limits(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
    }
    return adapter, reservation


def _safe_diagnostic_text(value: str, tmp_path: Path, *, max_chars: int = 200) -> str:
    value = value.replace(str(tmp_path), "<tmp>")
    value = re.sub(r"(?i)(api[_ -]?key|authorization)\s*[:=]\s*\S+", r"\1=[redacted]", value)
    value = re.sub(r"(?i)bearer\s+\S+", "Bearer [redacted]", value)
    value = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "[redacted]", value)
    return value[:max_chars]


def _continuation_failure_diagnostics(
    adapter, record, reservation, receipt, provider_state, mcp_state, tmp_path,
):
    from app.continuation_budget import read_request_guard
    from packages.contracts.continuation_request import exceeded_request_limits

    safe_payload_keys = ("code", "error", "retryable", "run_id", "finish_reason")
    terminal_events = []
    for event in record.history[-16:]:
        payload = event.get("payload") if isinstance(event, dict) else None
        selected = {
            key: (_safe_diagnostic_text(value, tmp_path) if isinstance(value, str) else value)
            for key, value in payload.items()
            if key in safe_payload_keys and isinstance(value, (str, int, bool))
        } if isinstance(payload, dict) else {}
        terminal_events.append({"kind": event.get("kind"), "payload": selected})

    generation = record.current_generation
    proxy = record.continuation_request_proxy
    gate = record.continuation_request_gate
    guard_rows = []
    journal_path = record.budget_journal
    if journal_path is not None and journal_path.is_file():
        try:
            for line in journal_path.read_text(encoding="utf-8").splitlines()[:20]:
                row = json.loads(line)
                guard_rows.append({
                    key: row[key] for key in ("phase", "ready", "call", "tool_name", "blocked_reason")
                    if key in row
                })
        except Exception as error:
            guard_rows.append({"read_error_type": type(error).__name__})

    gate_rows = []
    if gate is not None:
        for row in gate.receipts()[-32:]:
            gate_rows.append({
                key: row[key] for key in (
                    "phase", "reason", "status", "forwarded", "call", "attempt",
                    "input_bytes", "declared_max_output_tokens", "tool_payload_bytes",
                    "actual_input_tokens", "actual_cache_read_tokens", "actual_output_tokens",
                    "usage_source", "elapsed_ms",
                ) if key in row
            })

    settlement_probe = {}
    try:
        guard = read_request_guard(journal_path, reservation, terminal=True)
        settlement_probe["guard"] = guard
        usage = gate.request_usage(tool_calls=guard["tool_calls"])
        settlement_probe["usage_completeness"] = usage["actual_usage"]["completeness"]
        settlement_probe["violations"] = exceeded_request_limits(usage)
    except Exception as error:
        settlement_probe["error_type"] = type(error).__name__
        settlement_probe["error"] = _safe_diagnostic_text(str(error), tmp_path)

    session_root = Path(os.environ["DSH_SESSION_ROOT"])
    sdk_files = []
    if session_root.exists():
        relevant_names = {
            "continuation-tool-guard.jsonl",
            "continuation-provider-request.jsonl",
            "continuation.yml",
        }
        for directory in sorted(session_root.glob("root-*"))[:8]:
            for name in sorted(relevant_names):
                path = directory / name
                if path.is_file():
                    try:
                        sdk_files.append({"name": path.relative_to(session_root).as_posix(),
                            "size": path.stat().st_size})
                    except OSError:
                        sdk_files.append({"name": path.name, "size": "unavailable"})

    return {
        "receipt": receipt,
        "record_state": {
            "status": record.status,
            "process_closed": record.process_closed,
            "process_closing": record.process_closing,
            "active_run": record.active_run is not None,
            "generation": generation.describe() if generation is not None else None,
            "proxy_closed": record.continuation_proxy_closed,
            "proxy_internal_closed": getattr(proxy, "_closed", None),
            "terminal_events": terminal_events,
        },
        "sdk_events": list(getattr(adapter, "_test_sdk_events", [])),
        "sdk_exception": getattr(adapter, "_test_sdk_exception", None),
        "sdk_session_files": sdk_files,
        "proxy_receipts": gate_rows,
        "proxy_active_counts": {
            "clients": len(getattr(proxy, "_client_sockets", ())),
            "upstreams": len(getattr(proxy, "_upstream_responses", ())),
        },
        "guard_journal": guard_rows,
        "settlement_probe": settlement_probe,
        "provider": {
            "request_count": len(provider_state["requests"]),
            "tool_catalogs": provider_state["tool_catalogs"],
        },
        "mcp": {
            "call_count": len(mcp_state["calls"]),
            "method_counts": {
                method: mcp_state["methods"].count(method)
                for method in sorted(set(mcp_state["methods"]))
            },
        },
    }


def _wait_for_run(
    adapter, session_id: str, timeout: float = 30.0, *, require_continuation_cleanup: bool = False,
):
    record = adapter._get(session_id)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with record.lock:
            terminal = record.active_run is None
            if require_continuation_cleanup:
                terminal = (
                    terminal and record.process_closed and not record.process_closing
                    and record.continuation_proxy_closed
                )
            if terminal:
                return record
        time.sleep(0.02)
    raise AssertionError({
        "reason": "pinned DSH run did not reach a terminal state within its test bound",
        "last_status": adapter.describe_session(record).get("status"),
    })


def test_pinned_dsh_guard_restricts_prompt_tools_and_blocks_seventeenth_dispatch(tmp_path, monkeypatch):
    from deepseek_harness_runtime import bundled_runtime_path
    from app.runtime import SessionStatus

    assert version("deepseek-harness-sdk") == "0.1.5rc1"
    assert version("deepseek-harness-runtime-bin") == "0.1.5rc1"
    binary = Path(bundled_runtime_path())
    assert hashlib.sha256(binary.read_bytes()).hexdigest() == (
        "6f68ce88d98307533ee8fa58a8125de4dc019ab16fac8b512cec141a2d1961f8"
    )
    mcp, mcp_thread, mcp_state = _mcp_server()
    provider, provider_thread, provider_state = _provider_server([_many_tool_response(17)])
    adapter, reservation = _configure_runtime(tmp_path, monkeypatch, mcp, provider)
    try:
        adapter.create_session("continuation-guard", "continuation-guard-trace",
            "synthetic-owner", "synthetic-workspace")
        run_id = adapter.submit_prompt("continuation-guard", "Inspect the existing Job by its exact ID.",
            idempotency_key=reservation["reservation_id"], conversation_context=[],
            continuation_budget=reservation)
        record = _wait_for_run(
            adapter, "continuation-guard", require_continuation_cleanup=True)
        receipt = adapter.continuation_receipt("continuation-guard", reservation["reservation_id"])
        assert receipt["status"] == "settled", json.dumps(
            _continuation_failure_diagnostics(
                adapter, record, reservation, receipt, provider_state, mcp_state, tmp_path,
            ), sort_keys=True,
        )
        assert receipt["run_id"] == run_id
        assert receipt["outcome"] == "needs_attention"
        usage = receipt["request_usage"]
        assert usage["admission_usage"]["tool_calls"] == 16, usage
        assert usage["limit_violations"] == []
        assert provider_state["tool_catalogs"] == [sorted(_ALLOWED_ALIASES)]
        assert len(provider_state["requests"]) == 1
        assert len(mcp_state["calls"]) == 16
        assert all("mcp__byq__" + call["name"] in _ALLOWED_ALIASES for call in mcp_state["calls"])
        rows = [json.loads(line) for line in record.budget_journal.read_text().splitlines()]
        admitted = [row for row in rows if row.get("phase") == "tool"]
        blocked = [row for row in rows if row.get("phase") == "blocked"]
        assert len(admitted) == 16
        assert len(blocked) == 1
        assert blocked[0]["blocked_reason"] == "BYQ_CONTINUATION_TOOL_LIMIT"
        assert record.status == SessionStatus.FAILED
    finally:
        adapter.close()
        provider.shutdown()
        provider.server_close()
        provider_thread.join(timeout=2)
        mcp.shutdown()
        mcp.server_close()
        mcp_thread.join(timeout=2)


def test_actual_pinned_global_hook_counts_root_and_child_agents_in_one_process(tmp_path, monkeypatch):
    """Mechanics probe only: a test plugin creates a child Agent directly.

    ADR-0090's production profile blocks the delegate tool. This separate
    synthetic DSH probe deliberately exercises the SDK's public agents API to
    show that an untagged root-composition hook and the production guard closure
    remain global across root and child agents. It is not profile authorization.
    """
    from deepseek_harness_runtime import bundled_runtime_path
    from app import runtime as runtime_module

    assert version("deepseek-harness-sdk") == "0.1.5rc1"
    assert version("deepseek-harness-runtime-bin") == "0.1.5rc1"
    assert hashlib.sha256(Path(bundled_runtime_path()).read_bytes()).hexdigest() == (
        "6f68ce88d98307533ee8fa58a8125de4dc019ab16fac8b512cec141a2d1961f8"
    )
    mcp, mcp_thread, mcp_state = _mcp_server()
    provider, provider_thread, provider_state = _provider_server([
        _root_tool_response(), _many_tool_response(16),
    ])
    adapter, reservation = _configure_runtime(tmp_path, monkeypatch, mcp, provider)
    helper_source = """
import { randomUUID } from 'node:crypto';
import { brandString } from '@deepseek-ai/dsh-brand';
import { createUserMessage } from '@deepseek-ai/dsh-llm';
import { installModelSelection } from '@deepseek-ai/dsh-agent';
export const name = 'byq-child-scope-probe';
export const inject = ['agents', 'tools'];
export function apply(ctx) {
  let childStarted = false;
  const selection = ctx.get('agentDefaultModel').currentSelection();
  ctx.on('tools/pre-execute', async (exec, next) => {
    if (!childStarted && exec.name === 'mcp__byq__byq_research_get') {
      childStarted = true;
      const handle = await ctx.get('agents').create({
        sessionId: brandString('session-' + randomUUID()),
        parentAgent: exec.agent,
        meta: { cwd: process.cwd() },
        agentOptions: { provider: selection.provider, model: selection.model },
        setup: (agentCtx) => installModelSelection(agentCtx, { current: selection, assembled: void 0 }),
      });
      await handle.agent.whenIdle();
      handle.agent.followup(createUserMessage({
        content: [{ type: 'text', text: 'CHILD_SCOPE_PROBE' }],
        source: { kind: 'user' },
      }));
      await handle.agent.whenIdle();
      await handle.dispose();
    }
    return next();
  });
}
"""
    original_create_patch = runtime_module.create_guard_patch

    def install_helper_after_guard(source, root, carrier, **kwargs):
        patch, journal = original_create_patch(source, root, carrier, **kwargs)
        helper = Path(root) / "profiles" / "child-scope-probe.mjs"
        helper.parent.mkdir(parents=True, exist_ok=True)
        helper.write_text(helper_source, encoding="utf-8")
        with patch.open("a", encoding="utf-8") as stream:
            stream.write("\n- insert:\n    - id: child-scope-probe\n")
            stream.write("      name: " + json.dumps(helper.as_uri()) + "\n")
        return patch, journal

    monkeypatch.setattr(runtime_module, "create_guard_patch", install_helper_after_guard)
    try:
        adapter.create_session("continuation-hook-scope", "continuation-hook-scope-trace",
            "synthetic-owner", "synthetic-workspace")
        run_id = adapter.submit_prompt("continuation-hook-scope", "ROOT_SCOPE_PROBE",
            idempotency_key=reservation["reservation_id"], conversation_context=[],
            continuation_budget=reservation)
        record = _wait_for_run(
            adapter, "continuation-hook-scope", require_continuation_cleanup=True)
        receipt = adapter.continuation_receipt("continuation-hook-scope", reservation["reservation_id"])
        assert receipt["status"] == "settled", json.dumps(
            _continuation_failure_diagnostics(
                adapter, record, reservation, receipt, provider_state, mcp_state, tmp_path,
            ), sort_keys=True,
        )
        assert receipt["run_id"] == run_id
        assert receipt["outcome"] == "needs_attention"
        assert provider_state["tool_catalogs"][:2] == [sorted(_ALLOWED_ALIASES)] * 2, json.dumps(
            _continuation_failure_diagnostics(
                adapter, record, reservation, receipt, provider_state, mcp_state, tmp_path,
            ), sort_keys=True,
        )
        assert len(provider_state["requests"]) == 2
        assert len(mcp_state["calls"]) == 15, mcp_state
        rows = [json.loads(line) for line in record.budget_journal.read_text().splitlines()]
        admitted = [row for row in rows if row.get("phase") == "tool"]
        blocked = [row for row in rows if row.get("phase") == "blocked"]
        assert len(admitted) == 16, admitted
        assert len(blocked) == 1
        assert blocked[0]["blocked_reason"] == "BYQ_CONTINUATION_TOOL_LIMIT"
        assert receipt["request_usage"]["admission_usage"]["tool_calls"] == 16
    finally:
        adapter.close()
        provider.shutdown()
        provider.server_close()
        provider_thread.join(timeout=2)
        mcp.shutdown()
        mcp.server_close()
        mcp_thread.join(timeout=2)


@pytest.mark.parametrize('disable_search,expected', [(False, 1), (True, 0)])
def test_direct_search_bypasses_llm_guard_unless_provider_is_disabled(tmp_path, disable_search, expected):
    from deepseek_harness import DeepSeekHarness, DeepSeekHarnessConfig
    from deepseek_harness_runtime import bundled_runtime_path

    requests = []

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['content-length'])))
            requests.append((self.path, body.get('tools', [{}])[0].get('name')))
            self.send_error(400, 'synthetic search refusal')

    server = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    plugin = tmp_path / 'search-probe.mjs'
    plugin.write_text("""
export const name = 'byq-search-budget-probe';
export const inject = ['llm', 'web'];
export function apply(ctx) {
  ctx.on('llm/stream', async function* () {
    try { await ctx.web.search({query: 'synthetic budget qualification', maxResults: 1}); }
    catch { /* the local provider or missing provider is expected to refuse */ }
    throw new Error('BYQ_SEARCH_PROBE_ROOT_DENIED');
  });
}
""")
    patch = tmp_path / 'search.yml'
    patch.write_text(('- id: web-search-deepseek\n  disabled: true\n' if disable_search else '')
        + '- insert:\n    - id: search-probe\n      name: ' + json.dumps(plugin.as_uri()) + '\n')
    config = DeepSeekHarnessConfig(dsh_bin=str(bundled_runtime_path()), patches=(str(patch),),
        cwd=str(tmp_path), runtime_cwd=str(tmp_path), dsh_home=str(tmp_path),
        request_timeout_seconds=20, initialize_timeout_seconds=20,
        env={'DEEPSEEK_API_KEY': 'synthetic-only',
             'DEEPSEEK_BASE_URL': f'http://127.0.0.1:{server.server_port}',
             'DEEPSEEK_SEARCH_BASE_URL': f'http://127.0.0.1:{server.server_port}',
             'DSH_TELEMETRY_DISABLED': '1'})
    try:
        with DeepSeekHarness(config=config) as harness:
            result = harness.run('Synthetic guard bypass qualification only.')
        assert result.finish_reason == 'error'
        assert 'BYQ_SEARCH_PROBE_ROOT_DENIED' in str(result.events)
        assert requests == [('/messages', 'web_search')] * expected
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("tool_count", [0, 7])
def test_pinned_completion_settles_without_fabricating_missing_provider_usage(
    tmp_path, monkeypatch, tool_count,
):
    """Native SDK/guard/proxy receipt probe, not Product continuation acceptance.

    Match the CI Provider's two-chunk SSE shape and deliberately omit usage.
    The seven-read case exercises the tool loop without Job or domain writes.
    """
    from deepseek_harness_runtime import bundled_runtime_path
    from app.runtime import SessionStatus
    from tests.f6_synthetic_runtime import _sse_completion
    from tests.f6_runtime_diagnostics import RuntimeDiagnostics, install
    from app import runtime as runtime_module

    compatibility_type = type(runtime_module.compatibility_for_release(
        os.environ.get("BYQ_DSH_COMPATIBILITY_RELEASE", "dsh-0.1.2rc1")))
    # Register restoration before test-only install changes these class hooks.
    monkeypatch.setattr(runtime_module.RuntimeAdapter, "_run_prompt", runtime_module.RuntimeAdapter._run_prompt)
    monkeypatch.setattr(compatibility_type, "run_prepared_prompt", staticmethod(compatibility_type.run_prepared_prompt))
    diagnostic_path = tmp_path / "native-terminal-diagnostics.jsonl"
    terminal_diagnostics = RuntimeDiagnostics(diagnostic_path)
    install(terminal_diagnostics)

    assert version("deepseek-harness-sdk") == "0.1.5rc1"
    assert version("deepseek-harness-runtime-bin") == "0.1.5rc1"
    assert hashlib.sha256(Path(bundled_runtime_path()).read_bytes()).hexdigest() == (
        "6f68ce88d98307533ee8fa58a8125de4dc019ab16fac8b512cec141a2d1961f8"
    )
    responses = [_sse_completion({"probe_step": step}, (
        "mcp__byq__byq_research_get", {"task_id": "task_" + "b" * 32},
    )) for step in range(tool_count)]
    responses.append(_sse([
        {"id": "chatcmpl-native-probe", "object": "chat.completion.chunk",
         "model": "deepseek-v4-flash", "choices": [{"index": 0,
          "delta": {"content": "Synthetic bounded read completed."}, "finish_reason": None}]},
        {"id": "chatcmpl-native-probe", "object": "chat.completion.chunk",
         "model": "deepseek-v4-flash", "choices": [{"index": 0,
          "delta": {}, "finish_reason": "stop"}]},
    ]))
    mcp, mcp_thread, mcp_state = _mcp_server()
    provider, provider_thread, provider_state = _provider_server(responses)
    adapter = None
    try:
        adapter, reservation = _configure_runtime(tmp_path, monkeypatch, mcp, provider)
        sid = "byq-session-" + "d" * 32
        adapter.create_session(sid, "continuation-completion-trace",
            "synthetic-owner", "synthetic-workspace")
        run_id = adapter.submit_prompt(sid, "Bounded synthetic read only.",
            idempotency_key=reservation["reservation_id"], conversation_context=[],
            continuation_budget=reservation)
        record = _wait_for_run(adapter, sid, require_continuation_cleanup=True)
        receipt = adapter.continuation_receipt(sid, reservation["reservation_id"])
        diagnostic = json.dumps(_continuation_failure_diagnostics(
            adapter, record, reservation, receipt, provider_state, mcp_state, tmp_path,
        ), sort_keys=True)
        assert receipt["status"] == "settled", diagnostic
        assert receipt["run_id"] == run_id, diagnostic
        assert receipt["outcome"] == "completed", diagnostic
        assert record.status == SessionStatus.IDLE, diagnostic
        assert record.process_closed and record.continuation_proxy_closed, diagnostic
        assert any(event["kind"] == "session.result"
            and event["payload"].get("run_id") == run_id for event in record.history), diagnostic
        usage = receipt["request_usage"]
        assert usage["limit_violations"] == [], diagnostic
        assert usage["admission_usage"]["provider_attempts"] == tool_count + 1, diagnostic
        assert usage["admission_usage"]["tool_calls"] == tool_count, diagnostic
        assert usage["actual_usage"] == {
            "input_tokens": "unknown", "cache_read_tokens": "unknown", "output_tokens": "unknown",
            "provider_attempts": "unknown", "usage_source": "unknown", "completeness": "unknown",
        }, diagnostic
        assert len(provider_state["requests"]) == tool_count + 1, diagnostic
        assert len(mcp_state["calls"]) == tool_count, diagnostic
        journal_deadline = time.monotonic() + 2
        while True:
            content = diagnostic_path.read_bytes()
            rows = [json.loads(line) for line in content.splitlines()] if content.endswith(b"\n") else []
            if len(rows) == 3:
                break
            assert time.monotonic() < journal_deadline, diagnostic
            time.sleep(0.01)
        assert [row["record_type"] for row in rows] == [
            "background_started", "native_finished", "background_terminal"], diagnostic
        assert rows[1]["native_finish"] == "completed", diagnostic
        terminal = rows[2]
        assert terminal["terminal_kind"] == "session.result", diagnostic
        assert terminal["receipt_cache_status"] == "settled", diagnostic
        assert terminal["request_outcome"] == "completed", diagnostic
        assert terminal["process_closed"] and terminal["proxy_closed"], diagnostic
        assert terminal["guard_observed"] and terminal["usage_observed"], diagnostic
        assert terminal["provider_attempts"] == tool_count + 1, diagnostic
        assert terminal["tool_calls"] == tool_count, diagnostic
        assert terminal["usage_completeness"] == "unknown", diagnostic
        assert terminal["session_sha256"] == hashlib.sha256(sid.encode()).hexdigest(), diagnostic
        assert terminal["root_sha256"] == hashlib.sha256(run_id.encode()).hexdigest(), diagnostic
    finally:
        try:
            if adapter is not None:
                adapter.close()
        finally:
            try:
                provider.shutdown()
                provider.server_close()
                provider_thread.join(timeout=2)
                mcp.shutdown()
                mcp.server_close()
                mcp_thread.join(timeout=2)
            finally:
                terminal_diagnostics.close()
