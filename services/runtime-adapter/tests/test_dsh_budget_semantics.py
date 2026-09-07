"""Qualify official SDK max_tokens with a loopback-only synthetic Provider."""
import json
import os
import re
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("BYQ_BUDGET_SEMANTICS_TEST") != "1", reason="explicit loopback qualification")


def test_locked_product_composition_has_meter_but_no_agent_budget(tmp_path):
    """Inventory evidence only: this is not proof that every extension lacks a guard."""
    from importlib.metadata import version
    from deepseek_harness_runtime import bundled_runtime_path

    assert version("deepseek-harness-sdk") == "0.1.2rc1"
    assert version("deepseek-harness-runtime-bin") == "0.1.2rc1"
    result = subprocess.run(
        [str(bundled_runtime_path()), "--profile", "sdk", "--patch",
         "/opt/byq/profiles/byq-product.patch.yml", "--dump-config"],
        cwd=tmp_path, env={"PATH": os.defpath, "DSH_HOME": str(tmp_path),
                          "DSH_TELEMETRY_DISABLED": "1"},
        capture_output=True, text=True, timeout=15, check=True,
    )
    names = set(re.findall(r"^  name: '([^']+)'$", result.stdout, re.MULTILINE))
    assert {"@deepseek-ai/dsh-token-meter", "@deepseek-ai/dsh-llm-retry",
            "@deepseek-ai/dsh-compaction-basic", "@deepseek-ai/dsh-web-search-deepseek",
            "@deepseek-ai/dsh-tool-subagent"} <= names
    assert "@deepseek-ai/dsh-agent-budget" not in names


def test_sdk_max_tokens_does_not_bound_whole_multistep_turn(tmp_path):
    from deepseek_harness import DeepSeekHarness, DeepSeekHarnessConfig
    from deepseek_harness_runtime import bundled_runtime_path

    requests = []
    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["content-length"])))
            requests.append({"max_tokens": payload.get("max_tokens")})
            if len(requests) > 2:
                self.send_error(429, "synthetic request budget exhausted")
                return
            if len(requests) == 1:
                delta = {"tool_calls": [{"index": 0, "id": "probe", "type": "function", "function": {
                    "name": "synthetic_nonexistent_tool", "arguments": "{}"}}]}
                reason = "tool_calls"
            else:
                delta, reason = {"content": "Synthetic done"}, "stop"
            chunks = [{"choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                      {"choices": [{"index": 0, "delta": {}, "finish_reason": reason}],
                       "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}}]
            body = ("".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n").encode()
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        config = DeepSeekHarnessConfig(max_tokens=8, dsh_bin=str(bundled_runtime_path()),
            cwd=str(tmp_path), runtime_cwd=str(tmp_path), dsh_home=str(tmp_path),
            request_timeout_seconds=20, initialize_timeout_seconds=20,
            env={"DEEPSEEK_API_KEY": "synthetic-loopback-only", "DEEPSEEK_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                 "DSH_PERMISSION_MODE": "read-only", "DSH_TELEMETRY_DISABLED": "1"})
        with DeepSeekHarness(config=config) as harness:
            result = harness.run("Synthetic SDK budget test only.")
        assert result.finish_reason == "completed"
        assert requests == [{"max_tokens": 8}, {"max_tokens": 8}]
    finally:
        server.shutdown()
        server.server_close()
