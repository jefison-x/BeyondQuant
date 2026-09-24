#!/usr/bin/env python3
"""ADR-0085 P4: real Runtime Adapter turn_runner end-to-end through the carrier.

Runs INSIDE the runtime-adapter candidate image with a LIVE isolated read-only MCP
endpoint. It imports the real ``app.research_judgment_turn.DshBoundedTurnRunner``,
which builds the real DSH harness over the dedicated bounded composition, forces
the root to invoke the bounded persona, and extracts the closed result from the
real ``subagent.finished`` notification. A keyless scripted provider returns the
closed JSON as the child result.

Exits non-zero unless the real carrier run produced the expected closed result and
neither root nor child saw a write/approval/execute/routing tool.

    docker run --rm --network host --entrypoint python -v "$PWD:/repo:ro" \
        -e BYQ_MCP_READ_ONLY_URL=http://127.0.0.1:<port>/mcp/v1 \
        -e BYQ_MCP_READ_ONLY_TOKEN=<read-only-token> \
        byq-d15-runtime-candidate:local \
        /repo/scripts/v091/continuation_p4/carrier_turn_runner_probe.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, "/repo")
sys.path.insert(0, "/repo/services/runtime-adapter")

from app import research_judgment_turn as turn  # noqa: E402
from app.research_judgment import resolve_read_only_mcp_endpoint  # noqa: E402

PERSONA_TOOL = turn.RESEARCH_JUDGMENT_PERSONA_TOOL
FORBIDDEN_TOOLS = {
    "byq_strategy_version_create", "byq_strategy_approve", "byq_backtest_task_create",
    "byq_backtest_task_execute", "byq_research_transition", "byq_research_task_create",
    "byq_agent_approval_decide", "byq_ml_training_create", "byq_web_evidence_create",
}
STATE: dict = {"requests": [], "root_tool_call_sent": False}

CHILD_RESULT = json.dumps({
    "proposal": {
        "schema_version": "research-proposal.v1", "task_id": "task_" + "a" * 32,
        "plan_version": 1, "task_version": 1, "stage": "backtest_analysis",
        "iteration": 1, "proposal_kind": "backtest_analysis",
        "evidence_sufficient": True, "escalate": False, "summary": "bounded judgment",
    },
    "durable_evidence": {"kind": "none"},
})


def _tool_names(body: dict) -> list[str]:
    names = []
    for tool in body.get("tools") or []:
        fn = tool.get("function") if isinstance(tool.get("function"), dict) else tool
        name = fn.get("name") if isinstance(fn, dict) else None
        if isinstance(name, str):
            names.append(name)
    return sorted(set(names))


def _sse(payloads: list[dict]) -> bytes:
    body = "".join("data: " + json.dumps(p) + "\n\n" for p in payloads)
    return (body + "data: [DONE]\n\n").encode()


class Recorder(BaseHTTPRequestHandler):
    def log_message(self, *args):  # noqa: D401
        return

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("content-length", "0"))))
        names = _tool_names(body)
        is_child = PERSONA_TOOL not in names
        STATE["requests"].append({"role": "child" if is_child else "root", "tool_names": names})
        if not is_child and not STATE["root_tool_call_sent"]:
            STATE["root_tool_call_sent"] = True
            arguments = {"description": "bounded judgment", "prompt": "Return the closed JSON result."}
            payloads = [
                {"choices": [{"index": 0, "delta": {"tool_calls": [{
                    "index": 0, "id": "call_judgment_1", "type": "function",
                    "function": {"name": PERSONA_TOOL, "arguments": json.dumps(arguments)}}]},
                    "finish_reason": None}]},
                {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
                 "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}},
            ]
        else:
            text = CHILD_RESULT if is_child else "DONE"
            payloads = [
                {"choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]},
                {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}},
            ]
        data = _sse(payloads)
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> int:
    result: dict = {"runner_ok": False}
    try:
        endpoint = resolve_read_only_mcp_endpoint(dict(os.environ))
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 2
    server = ThreadingHTTPServer(("127.0.0.1", 0), Recorder)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    os.environ["DEEPSEEK_API_KEY"] = "probe-keyless-only"
    os.environ["DEEPSEEK_BASE_URL"] = f"http://127.0.0.1:{server.server_port}"
    os.environ["BYQ_MCP_READ_ONLY_URL"] = endpoint["url"]
    os.environ["BYQ_MCP_READ_ONLY_TOKEN"] = endpoint["token"]
    identity = {
        "owner_principal": "probe", "workspace_id": "probe", "actor_principal": "probe",
        "trace_id": "probe", "session_id": "probe", "dsh_run_id": "probe",
    }
    from app.compat import compatibility_for_release

    home = tempfile.mkdtemp(prefix="byq-p4-turn-")
    runner = turn.DshBoundedTurnRunner(
        compatibility=compatibility_for_release("dsh-0.1.5rc1"),
        composition_path=os.environ.get(
            "PROBE_PATCH",
            "/repo/plugins/dsh-byq/profiles/dsh-0.1.5rc1-continuable/byq-research-judgment.patch.yml"),
        identity=identity, provider="deepseek-official", model="deepseek-v4-flash",
        session_root=home, session_id="p4-turn-runner",
        environment={**os.environ})
    try:
        closed = runner({"stage_input": {
            "schema_version": "research-stage-input.v1", "task_id": "task_" + "a" * 32,
            "stage": "backtest_analysis", "proposal_kinds": ["backtest_analysis", "escalate"]}},
            PERSONA_TOOL)
        result["closed_result"] = closed
        result["runner_ok"] = closed.get("proposal", {}).get("proposal_kind") == "backtest_analysis"
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {str(exc)[:400]}"
    finally:
        server.shutdown()
        server.server_close()
    requests = STATE["requests"]
    result["requests"] = requests
    result["child_invoked"] = any(r["role"] == "child" for r in requests)
    result["forbidden_exposed"] = sorted({
        name for r in requests for name in r["tool_names"] if name in FORBIDDEN_TOOLS})
    violations = []
    if not result["runner_ok"]:
        violations.append("turn_runner did not return the expected closed result")
    if not result["child_invoked"]:
        violations.append("bounded child persona was not invoked")
    if result["forbidden_exposed"]:
        violations.append(f"forbidden tool exposed: {result['forbidden_exposed']}")
    result["violations"] = violations
    result["all_observed"] = not violations
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not violations else 1


if __name__ == "__main__":
    raise SystemExit(main())
