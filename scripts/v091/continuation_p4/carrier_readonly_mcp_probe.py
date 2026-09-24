#!/usr/bin/env python3
"""ADR-0085 P4 real-carrier read-only MCP + bounded-persona probe.

Runs INSIDE the runtime-adapter candidate image with a LIVE isolated read-only
MCP endpoint. A keyless scripted provider records the real ROOT and CHILD
provider requests, forces the root to invoke the bounded
``byq_research_judgment_turn`` persona, and returns a closed child result. It also
queries the MCP endpoint's real ``tools/list`` so the five-tool surface is proven
from the same endpoint the carrier loaded -- not inferred from the static YAML.

The dedicated composition reads ONLY ``BYQ_MCP_READ_ONLY_URL`` /
``BYQ_MCP_READ_ONLY_TOKEN``. This probe fails closed (non-zero exit) if they are
missing, if they collide with the Product ``BYQ_MCP_URL``/``BYQ_MCP_TOKEN``, or if
the observed root/child tool arrays, child invocation or ``tools/list`` are not
exactly the bounded read-only surface. It is not a PASS label: it returns 0 only
on the real observed facts.

    docker run --rm --network host --entrypoint python -v "$PWD:/repo:ro" \
        -e PROBE_PATCH=/repo/<composition.patch.yml> \
        -e BYQ_MCP_READ_ONLY_URL=http://127.0.0.1:<port>/mcp/v1 \
        -e BYQ_MCP_READ_ONLY_TOKEN=<read-only-token> \
        byq-d15-runtime-candidate:local \
        /repo/scripts/v091/continuation_p4/carrier_readonly_mcp_probe.py
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PERSONA_TOOL = "byq_research_judgment_turn"
READ_ONLY_TOOLS = [
    "mcp__byq__byq_agent_context",
    "mcp__byq__byq_backtest_analysis_get",
    "mcp__byq__byq_backtest_task_get",
    "mcp__byq__byq_research_get",
    "mcp__byq__byq_research_stage_input_get",
]
FORBIDDEN_TOOLS = [
    "byq_strategy_version_create", "byq_strategy_approve", "byq_backtest_task_create",
    "byq_backtest_task_execute", "byq_research_transition", "byq_research_task_create",
    "byq_agent_approval_decide", "byq_ml_training_create", "byq_web_evidence_create",
]
READ_ONLY_URL_ENV = "BYQ_MCP_READ_ONLY_URL"
READ_ONLY_TOKEN_ENV = "BYQ_MCP_READ_ONLY_TOKEN"
PRODUCT_URL_ENV = "BYQ_MCP_URL"
PRODUCT_TOKEN_ENV = "BYQ_MCP_TOKEN"

STATE: dict = {"requests": [], "root_tool_call_sent": False}


def resolve_probe_env(env: dict) -> dict:
    """Return the dedicated read-only endpoint or raise on a missing/colliding one."""

    url = (env.get(READ_ONLY_URL_ENV) or "").strip()
    token = (env.get(READ_ONLY_TOKEN_ENV) or "").strip()
    if not url or not token:
        raise ValueError("read-only MCP endpoint is not configured for the probe")
    if url == (env.get(PRODUCT_URL_ENV) or "").strip() or token == (
            env.get(PRODUCT_TOKEN_ENV) or "").strip():
        raise ValueError("read-only MCP endpoint or credential collides with the Product MCP")
    return {"url": url, "token": token}


def evaluate_observations(result: dict) -> list[str]:
    """Return the list of real-fact violations; empty means the bounded surface held."""

    violations: list[str] = []
    if result.get("started") is not True:
        violations.append("carrier did not start")
    if result.get("run_ok") is not True:
        violations.append("run did not complete")
    if result.get("child_invoked") is not True:
        violations.append("bounded child persona was not invoked")
    if result.get("mcp_tools_list") != sorted(
            name.replace("mcp__byq__", "") for name in READ_ONLY_TOOLS):
        violations.append(f"read-only MCP tools/list mismatch: {result.get('mcp_tools_list')}")
    expected_root = sorted([PERSONA_TOOL, *READ_ONLY_TOOLS])
    for tool_array in result.get("root_tool_arrays", []):
        if tool_array != expected_root:
            violations.append(f"root tool array is not the bounded surface: {tool_array}")
    for tool_array in result.get("child_tool_arrays", []):
        if tool_array != sorted(READ_ONLY_TOOLS):
            violations.append(f"child tool array is not the read-only surface: {tool_array}")
    for request in result.get("requests", []):
        leaked = [name for name in request.get("tool_names", []) if name in FORBIDDEN_TOOLS]
        if leaked:
            violations.append(f"forbidden tool exposed: {leaked}")
    if result.get("child_tool_arrays") and result.get("root_tool_arrays") and not violations:
        roles = [request.get("role") for request in result.get("requests", [])]
        if roles[:3] != ["root", "child", "root"]:
            violations.append(f"unexpected provider call roles: {roles}")
    return violations


def _tool_names(body: dict) -> list[str]:
    names: list[str] = []
    for tool in body.get("tools") or []:
        fn = tool.get("function") if isinstance(tool.get("function"), dict) else tool
        name = fn.get("name") if isinstance(fn, dict) else None
        if isinstance(name, str):
            names.append(name)
    return sorted(set(names))


def _sse(payloads: list[dict]) -> bytes:
    body = "".join("data: " + json.dumps(payload) + "\n\n" for payload in payloads)
    return (body + "data: [DONE]\n\n").encode()


class Recorder(BaseHTTPRequestHandler):
    def log_message(self, *args):  # noqa: D401
        return

    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("content-length", "0"))))
            names = _tool_names(body)
            is_child = PERSONA_TOOL not in names
            messages = body.get("messages") or []
            tool_excerpt = ""
            for message in messages:
                if isinstance(message, dict) and message.get("role") == "tool":
                    tool_excerpt = json.dumps(message.get("content"))[:600]
            entry = {
                "index": len(STATE["requests"]),
                "role": "child" if is_child else "root",
                "tool_names": names,
                "tool_count": len(names),
                "message_count": len(messages),
                "message_roles": [m.get("role") for m in messages if isinstance(m, dict)],
                "last_tool_excerpt": tool_excerpt,
                "action": None,
            }
            if not is_child and not STATE["root_tool_call_sent"]:
                STATE["root_tool_call_sent"] = True
                entry["action"] = "tool_call"
                arguments = {
                    "description": "bounded judgment",
                    "prompt": ("Return exactly one closed bounded research judgment for the "
                               "stage input. Do not request or attempt any write, approval, "
                               "execution, routing, identity or idempotency capability."),
                }
                payloads = [
                    {"choices": [{"index": 0, "delta": {"tool_calls": [{
                        "index": 0, "id": "call_judgment_1", "type": "function",
                        "function": {"name": PERSONA_TOOL,
                                     "arguments": json.dumps(arguments)}}]},
                        "finish_reason": None}]},
                    {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
                     "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}},
                ]
            else:
                entry["action"] = "text"
                text = ("closed bounded judgment: evidence sufficient; no write, approval, "
                        "execution or routing capability is needed."
                        if is_child else "bounded judgment turn completed.")
                payloads = [
                    {"choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]},
                    {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                     "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}},
                ]
            STATE["requests"].append(entry)
            data = _sse(payloads)
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as exc:  # noqa: BLE001
            print("probe provider failed: " + type(exc).__name__, flush=True)
            self.send_error(400, "probe rejected")


def _mcp_post(url: str, token: str, body: dict, session_id: str | None = None,
              timeout: float = 10.0) -> tuple[str | None, str]:
    headers = {
        "content-type": "application/json",
        "accept": "application/json, text/event-stream",
        "authorization": f"Bearer {token}",
    }
    if session_id:
        headers["mcp-session-id"] = session_id
    request = urllib.request.Request(url, data=json.dumps(body).encode(),
                                     headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.headers.get("mcp-session-id"), response.read().decode()


def _mcp_payload(text: str) -> dict:
    for line in text.splitlines():
        if line.startswith("data: "):
            return json.loads(line[len("data: "):])
    return json.loads(text)


def mcp_tools_list(url: str, token: str) -> list[str]:
    session_id, _ = _mcp_post(url, token, {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "byq-p4-probe", "version": "1"}}})
    _mcp_post(url, token, {"jsonrpc": "2.0", "method": "notifications/initialized"},
              session_id)
    _, body = _mcp_post(url, token, {"jsonrpc": "2.0", "id": 2, "method": "tools/list",
                                     "params": {}}, session_id)
    tools = _mcp_payload(body).get("result", {}).get("tools", [])
    return sorted(tool.get("name") for tool in tools if isinstance(tool, dict))


def main() -> int:
    result: dict = {"started": False, "run_ok": False}
    try:
        endpoint = resolve_probe_env(dict(os.environ))
    except ValueError as exc:
        result["error"] = str(exc)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 2

    # Heavy runtime imports stay inside main so the observation evaluator is
    # importable and unit-testable without the DSH runtime.
    from deepseek_harness import DeepSeekHarness, DeepSeekHarnessConfig
    from deepseek_harness_runtime import bundled_runtime_path

    patch = Path(os.environ["PROBE_PATCH"])
    result.update({"patch": str(patch), "mcp_url": endpoint["url"]})
    server = ThreadingHTTPServer(("127.0.0.1", 0), Recorder)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    home = Path(tempfile.mkdtemp(prefix="byq-p4-ro-"))
    try:
        config = DeepSeekHarnessConfig(
            provider=os.environ.get("PROBE_PROVIDER", "deepseek-official"),
            model=os.environ.get("PROBE_MODEL", "deepseek-v4-flash"),
            dsh_bin=str(bundled_runtime_path().resolve()),
            profile="sdk", patches=(str(patch),),
            dsh_home=str(home), cwd=str(home), runtime_cwd=str(home),
            env={
                "DSH_RUNTIME_MODE": "exe", "DSH_TELEMETRY_DISABLED": "1",
                "DSH_PERMISSION_MODE": "read-only", "DSH_MAX_TOKENS_AS_SUCCESS": "false",
                "DEEPSEEK_API_KEY": "probe-keyless-only",
                "DEEPSEEK_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                READ_ONLY_URL_ENV: endpoint["url"], READ_ONLY_TOKEN_ENV: endpoint["token"],
                "BYQ_OWNER_PRINCIPAL": "probe", "BYQ_WORKSPACE_ID": "probe",
                "BYQ_ACTOR_PRINCIPAL": "probe", "BYQ_TRACE_ID": "probe",
                "BYQ_SESSION_ID": "probe", "BYQ_DSH_RUN_ID": "probe",
            },
            initialize_timeout_seconds=120.0, request_timeout_seconds=180.0,
            shutdown_timeout_seconds=5.0,
        )
        harness = DeepSeekHarness(config=config)
        try:
            harness.start()
            result["started"] = True
            session = harness.start_session("p4-ro-probe")
            session.run("Return one bounded judgment for the stage input.")
            result["run_ok"] = True
        finally:
            try:
                harness.close()
            except Exception:  # noqa: BLE001
                pass
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {str(exc)[:400]}"
    finally:
        server.shutdown()
        server.server_close()
    requests = STATE["requests"]
    result["requests"] = requests
    result["root_tool_arrays"] = [r["tool_names"] for r in requests if r["role"] == "root"]
    result["child_tool_arrays"] = [r["tool_names"] for r in requests if r["role"] == "child"]
    result["child_invoked"] = any(r["role"] == "child" for r in requests)
    result["call_count"] = len(requests)
    try:
        result["mcp_tools_list"] = mcp_tools_list(endpoint["url"], endpoint["token"])
        result["mcp_tool_count"] = len(result["mcp_tools_list"])
    except Exception as exc:  # noqa: BLE001
        result["mcp_tools_list_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    violations = evaluate_observations(result)
    result["violations"] = violations
    result["all_observed"] = not violations
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not violations else 1


if __name__ == "__main__":
    raise SystemExit(main())
