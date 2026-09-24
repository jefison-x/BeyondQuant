#!/usr/bin/env python3
"""ADR-0085 P4 carrier feasibility probe (real DSH 0.1.5rc1).

Decisive question: with a dedicated static composition, can the real carrier
start, and what tools does the ROOT session actually expose? The provider
request body carries the authoritative tool array, so a keyless recording
provider records exactly what the model would see (agent-spine built-ins and
MCP tools included) -- not a YAML guess.

Runs inside the runtime-adapter candidate image:

    docker run --rm --entrypoint python -v "$PWD:/repo:ro" \
        -e PROBE_PATCH=/repo/<composition.patch.yml> \
        byq-d15-runtime-candidate:local \
        /repo/scripts/v091/continuation_p4/carrier_feasibility_probe.py
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from deepseek_harness import DeepSeekHarness, DeepSeekHarnessConfig
from deepseek_harness_runtime import bundled_runtime_path

RECORDED: dict = {"tool_names": [], "requests": 0, "messages": 0}


class Recorder(BaseHTTPRequestHandler):
    def log_message(self, *args):  # noqa: D401
        return

    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("content-length", "0"))))
            RECORDED["requests"] += 1
            tools = body.get("tools") or []
            names = []
            for tool in tools:
                if isinstance(tool, dict):
                    fn = tool.get("function") if isinstance(tool.get("function"), dict) else tool
                    name = fn.get("name")
                    if isinstance(name, str):
                        names.append(name)
            if names and not RECORDED["tool_names"]:
                RECORDED["tool_names"] = sorted(set(names))
            RECORDED["messages"] = len(body.get("messages") or [])
            data = (
                'data: ' + json.dumps({"choices": [{"index": 0, "delta": {
                    "content": "bounded judgment: evidence insufficient"}, "finish_reason": None}]})
                + '\n\ndata: ' + json.dumps({"choices": [{"index": 0, "delta": {},
                    "finish_reason": "stop"}], "usage": {"prompt_tokens": 10,
                    "completion_tokens": 5, "total_tokens": 15}})
                + '\n\ndata: [DONE]\n\n').encode()
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as exc:  # noqa: BLE001
            print("probe provider failed: " + type(exc).__name__, flush=True)
            self.send_error(400, "probe rejected")


def main() -> int:
    patch = Path(os.environ["PROBE_PATCH"])
    server = ThreadingHTTPServer(("127.0.0.1", 0), Recorder)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    home = Path(tempfile.mkdtemp(prefix="byq-p4-probe-"))
    result: dict = {"patch": str(patch), "started": False, "run_ok": False}
    try:
        config = DeepSeekHarnessConfig(
            provider=os.environ.get("PROBE_PROVIDER", "deepseek-official"),
            model=os.environ.get("PROBE_MODEL", "deepseek-v4-flash"),
            dsh_bin=str(bundled_runtime_path().resolve()),
            profile="sdk",
            patches=(str(patch),),
            dsh_home=str(home), cwd=str(home), runtime_cwd=str(home),
            env={
                "DSH_RUNTIME_MODE": "exe", "DSH_TELEMETRY_DISABLED": "1",
                "DSH_PERMISSION_MODE": "read-only", "DSH_MAX_TOKENS_AS_SUCCESS": "false",
                "DEEPSEEK_API_KEY": "probe-keyless-only",
                "DEEPSEEK_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                "BYQ_MCP_URL": os.environ.get("BYQ_MCP_URL", "http://127.0.0.1:1/mcp/v1"),
                "BYQ_MCP_TOKEN": "probe", "BYQ_OWNER_PRINCIPAL": "probe",
                "BYQ_WORKSPACE_ID": "probe", "BYQ_ACTOR_PRINCIPAL": "probe",
                "BYQ_TRACE_ID": "probe", "BYQ_SESSION_ID": "probe", "BYQ_DSH_RUN_ID": "probe",
            },
            initialize_timeout_seconds=90.0, request_timeout_seconds=120.0,
            shutdown_timeout_seconds=5.0,
        )
        harness = DeepSeekHarness(config=config)
        try:
            harness.start()
            result["started"] = True
            session = harness.start_session("p4-probe")
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
    result.update(RECORDED)
    result["tool_count"] = len(RECORDED["tool_names"])
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
