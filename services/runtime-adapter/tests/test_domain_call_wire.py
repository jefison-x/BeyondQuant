"""Official-process identity probe, loopback only; no domain or paid Provider."""
import json
import os
import threading
import time
import uuid
import statistics
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import version

import pytest

from app.runtime import RuntimeAdapter, SessionStatus


pytestmark = pytest.mark.skipif(
    os.environ.get("BYQ_DOMAIN_CALL_WIRE_TEST") != "1" or version("deepseek-harness-sdk") != "0.1.2rc1",
    reason="explicit loopback official-process identity qualification",
)


@pytest.mark.parametrize("action", ["byq_strategy_validate", "byq_ml_strategy_create"])
@pytest.mark.parametrize("root_scoped,stop_on_error,cycles", [(False, False, 0), (True, False, 0), (True, True, 0),
    (False, False, 20), (True, False, 20)])
def test_wire_identity_across_roots(monkeypatch, action, root_scoped, stop_on_error, cycles):
    if cycles and os.environ.get("BYQ_ROOT_CYCLE_QUALIFICATION") != "1":
        pytest.skip("explicit 20-cycle process/RSS qualification")
    turns = cycles or (1 if stop_on_error else 3 if root_scoped else 2)
    if root_scoped:
        profile_root = os.environ.get("BYQ_ROOT_PROFILE_ROOT")
        if not profile_root:
            pytest.skip("root-scoped independent profile must be explicitly mounted")
        profile = Path(profile_root) / "dsh-0.1.2rc1"
        monkeypatch.setenv("BYQ_DSH_PROCESS_OWNERSHIP", "root-turn")
        monkeypatch.setenv("BYQ_DSH_COMPOSITION", str(profile / "byq-product.yml"))
        monkeypatch.setenv("BYQ_DSH_COMPOSITION_IDENTITY", str(profile / "byq-product.identity.json"))
    calls, observations, requests, wire_results, measurements = [], [], [], [], []
    def process_family():
        rows = {}
        for path in Path("/proc").glob("[0-9]*/status"):
            try:
                fields = dict(line.split(":", 1) for line in path.read_text().splitlines() if ":" in line)
                rows[int(path.parent.name)] = (int(fields["PPid"].strip()), int(fields.get("VmRSS", "0 kB").split()[0]))
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                continue
        family = {os.getpid()}
        while True:
            expanded = family | {pid for pid, (parent, _) in rows.items() if parent in family}
            if expanded == family:
                break
            family = expanded
        return {"children": len(family) - 1, "rss_kib": sum(rows.get(pid, (0, 0))[1] for pid in family)}
    arguments = {"task_id": "task_synthetic", "agent_run_id": "agent_synthetic",
                 "idempotency_key": "synthetic-same-key", "strategy": {"label": "合成"}}

    class Mcp(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            method = body.get("method")
            if "id" not in body:
                self.send_response(202)
                self.end_headers()
                return
            if method == "initialize":
                result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                          "serverInfo": {"name": "synthetic-identity-probe", "version": "1"}}
            elif method == "tools/list":
                result = {"tools": [{"name": action, "description": "Synthetic identity observation only",
                                     "inputSchema": {"type": "object", "additionalProperties": True}}]}
            elif method == "tools/call":
                if cycles:
                    measurements.append(process_family())
                calls.append({"body": body, "headers": {key: value for key, value in self.headers.items()
                              if key.lower().startswith("x-byq-")}})
                result = {"content": [{"type": "text", "text": "Synthetic rejection; no domain write"}], "isError": True}
                if stop_on_error:
                    result["content"][0]["text"] = json.dumps({"service": "beyondquant-mcp", "status": "error",
                        "backend": {"admission": {"schema_version": "domain-call-admission.v1", "state": "blocked",
                            "reason": "correction_budget_exhausted", "stop": True}}})
            else:
                result = {}
            encoded = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            requests.append(body)
            if len(requests) > (4 if stop_on_error else 2 * turns):
                self.send_error(429, "synthetic request cap")
                return
            calling = stop_on_error or len(requests) % 2 == 1
            delta = {"tool_calls": [{"index": 0, "id": "model-call-reused", "type": "function", "function": {
                "name": "mcp__byq__" + action, "arguments": json.dumps(arguments)}}]} if calling else {"content": "合成结束"}
            chunks = [{"choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                      {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls" if calling else "stop"}]}]
            encoded = ("".join(f"data: {json.dumps(item)}\n\n" for item in chunks) + "data: [DONE]\n\n").encode()
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    mcp = ThreadingHTTPServer(("127.0.0.1", 0), Mcp)
    provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in (mcp, provider)]
    for thread in threads:
        thread.start()
    monkeypatch.setenv("BYQ_MCP_URL", f"http://127.0.0.1:{mcp.server_port}/mcp/v1")
    monkeypatch.setenv("BYQ_MCP_TOKEN", "synthetic-only")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-only")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", f"http://127.0.0.1:{provider.server_port}")
    monkeypatch.setenv("BYQ_CREDENTIAL_RESOLVER_TOKEN", "")
    adapter = RuntimeAdapter()
    original = adapter._on_notification

    def observe(record, notification, **kwargs):
        payload = getattr(notification, "payload", {})
        event = payload.get("event", {})
        if event.get("type") == "tool/call":
            observations.append({"root": kwargs["source_run"].run_id, "data": event.get("data"),
                                 "session": payload.get("sessionId")})
        if stop_on_error and event.get("type") == "tool/result":
            wire_results.append(event.get("data"))
        original(record, notification, **kwargs)

    adapter._on_notification = observe
    session = "identity-" + uuid.uuid4().hex
    try:
        initialized_at = time.monotonic()
        adapter.create_session(session, "synthetic-trace", "synthetic-owner", "synthetic-workspace")
        initialization_seconds = time.monotonic() - initialized_at
        cycle_seconds, retained = [], []
        record = adapter._get(session)
        generation = record.runtime_generation
        for index in range(turns):
            cycle_started = time.monotonic()
            root = adapter.submit_prompt(session, f"Synthetic observation {index}", conversation_context=[])
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                with record.lock:
                    if record.active_run is None and (not stop_on_error or record.process_closed):
                        break
                time.sleep(0.02)
            if stop_on_error:
                assert record.status == SessionStatus.FAILED
                assert record.process_closed and not record.process_closing
                if not any(event["payload"].get("code") == "domain-correction-stopped" for event in record.history):
                    print("synthetic-tool-result-shape", json.dumps(wire_results[:1], ensure_ascii=False)[:5000])
                assert any(event["kind"] == "session.failed" and event["payload"].get("code") == "domain-correction-stopped"
                           for event in record.history), (list(record.history)[-3:], wire_results[:1])
                assert len(calls) <= 2 and len(requests) <= 3
                assert time.monotonic() < deadline
                return
            assert record.status == SessionStatus.IDLE
            cycle_seconds.append(time.monotonic() - cycle_started)
            if cycles:
                snapshot = process_family()
                retained.append(snapshot)
                if root_scoped:
                    assert snapshot["children"] == 0
            adapter.acknowledge_terminal(session, record.terminal_receipts[root])
        assert len(calls) == len(observations) == turns
        assert observations[0]["root"] != observations[1]["root"]
        assert (record.runtime_generation == generation) is not root_scoped
        assert all(call["body"]["params"]["arguments"] == arguments for call in calls)
        if root_scoped:
            for call, observation in zip(calls, observations):
                headers = {key.lower(): value for key, value in call["headers"].items()}
                assert headers["x-byq-root-run-id"] == observation["root"]
            assert calls[0]["headers"] != calls[1]["headers"]
        else:
            assert calls[0]["headers"] == calls[1]["headers"]
        assert all(set(call["body"]["params"]) == {"name", "arguments"} for call in calls)
        if not root_scoped:
            assert calls[0]["body"]["id"] != calls[1]["body"]["id"]
        assert all(item["data"]["callId"] == "model-call-reused" for item in observations)
        assert [item["data"]["turn"] for item in observations] == ([1] * turns if root_scoped else list(range(1, turns + 1)))
        # The MCP request counter is not present in the official tool/call
        # observation. Neither counter arithmetic nor model callId is proof.
        assert all("id" not in item["data"] for item in observations)
        if cycles:
            print("root-cycle-qualification", json.dumps({"root_scoped": root_scoped, "action": action,
                "cycles": cycles, "initialization_seconds": round(initialization_seconds, 3),
                "median_cycle_seconds": round(statistics.median(cycle_seconds), 3),
                "maximum_cycle_seconds": round(max(cycle_seconds), 3),
                "maximum_sampled_family_rss_kib": max(item["rss_kib"] for item in measurements),
                "post_cycle_family_rss_kib": [item["rss_kib"] for item in retained],
                "post_cycle_children": [item["children"] for item in retained]}, sort_keys=True))
    finally:
        adapter.close()
        for server in (mcp, provider):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=2)
