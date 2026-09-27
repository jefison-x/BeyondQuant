"""Opt-in PID-1 fixture for the isolated Phase 7 Compose child-death check.

Only the scripted model/MCP endpoints are synthetic. The runtime adapter and
pinned DSH foreground delegate are real. This file is mounted read-only into a
disposable Adapter container; it is never a product command.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path

from test_dsh015_foreground_child_process import _servers


if os.environ.get("BYQ_PHASE7_CHILD_PROBE") != "1":
    raise SystemExit("isolated Phase 7 fixture flag required")

composition = Path("/opt/byq/profiles/byq-product.patch.yml")
state, mcp, provider, _threads = _servers(composition, block_child=True)
class _HoldUntilProcessDeath:
    def wait(self, timeout=None):
        threading.Event().wait()


# The shared qualification fixture normally releases the synthetic response
# after 25 seconds. This PID-1 probe must keep the child live until host kill.
state["child_response_release"] = _HoldUntilProcessDeath()
os.environ["BYQ_MCP_URL"] = f"http://127.0.0.1:{mcp.server_port}/mcp/v1"
os.environ["BYQ_MCP_TOKEN"] = "phase7-loopback-only"
os.environ["DEEPSEEK_API_KEY"] = "phase7-loopback-only"
os.environ["DEEPSEEK_BASE_URL"] = f"http://127.0.0.1:{provider.server_port}"
sys.path.insert(0, "/app")

from app import main as runtime_main  # noqa: E402 - fixture environment first
import uvicorn  # noqa: E402


def scenario() -> None:
    adapter = runtime_main.adapter
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        try:
            adapter.require_current_backend_authority()
            break
        except Exception:
            time.sleep(0.1)
    else:
        raise RuntimeError("Gateway never established this Adapter boot")

    seen = []
    original = adapter._on_notification

    def observe(record, notification, **kwargs):
        if getattr(notification, "method", None) == "subagent.started":
            seen.append(getattr(notification, "payload", None))
        return original(record, notification, **kwargs)

    adapter._on_notification = observe
    suffix = uuid.uuid4().hex
    session_id = "phase7-child-" + suffix
    adapter.create_session(session_id, "trace-" + suffix, "phase7-owner", "phase7-workspace")
    adapter.submit_prompt(session_id, "Run the synthetic delegated market research turn.")
    if not state["child_request_started"].wait(timeout=20):
        raise RuntimeError("pinned DSH foreground child did not start")
    if not seen:
        raise RuntimeError("real subagent.started notification was not observed")
    if state["mcp_methods"].count("initialize") < 1 or state["mcp_methods"].count("tools/list") < 1:
        raise RuntimeError("real DSH MCP initialization/list traffic was not observed")
    print(json.dumps({"phase7_child_probe": "BLOCKED_CHILD_LIVE",
                      "subagent_started": True, "mcp_initialized": True,
                      "pid1": os.getpid(), "boot_id": adapter.boot_id}), flush=True)
    # The host kills PID 1 while the provider response is blocked. No test
    # code here may release the child or fabricate its terminal result.
    while True:
        time.sleep(1)


threading.Thread(target=scenario, name="phase7-child-probe", daemon=True).start()
uvicorn.run(runtime_main.app, host="0.0.0.0", port=8400)
