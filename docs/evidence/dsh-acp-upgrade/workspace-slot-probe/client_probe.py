from __future__ import annotations
import os, re, time, uuid
from pathlib import Path
from app.acp_product_slot_client import ProductSlotRegistry
from app.compat.acp_slot_transport import SlotAcpProcess

workspace = "workspace_probe"
base = Path("/var/lib/byq/dsh-sessions/dsh-v0.2.0-rc.2-acp") / workspace
leaf = "root-" + uuid.uuid4().hex
cwd = base / leaf
cwd.mkdir(mode=0o700)
(cwd / "tmp").mkdir(mode=0o700)
assert os.getuid() == 10002 and os.getgid() == 10002
for path in (cwd, cwd / "tmp"):
    info = os.stat(path, follow_symlinks=False)
    assert info.st_uid == 10002 and info.st_gid == 10002 and (info.st_mode & 0o777) == 0o700
print("ADAPTER_UID_HOME_TMP=PASS")

boot = uuid.uuid4().hex
root_run = uuid.uuid4().hex
generation = "generation-" + uuid.uuid4().hex
session = "probe-" + uuid.uuid4().hex[:24]
env = {
    "BYQ_MCP_URL": "http://127.0.0.1:18300/mcp/v1",
    "BYQ_MCP_ACP_DISCOVERY_TOKEN": "synthetic-discovery-token-for-no-network-probe",
    "BYQ_MCP_ACP_SIGNING_KEY": "synthetic-signing-key-for-no-network-probe",
    "BYQ_RUNTIME_BOOT_ID": boot,
    "BYQ_OWNER_PRINCIPAL": "user:acp-probe",
    "BYQ_WORKSPACE_ID": workspace,
    "BYQ_ACTOR_PRINCIPAL": "byq-product-agent-" + session,
    "BYQ_TRACE_ID": "trace-" + uuid.uuid4().hex[:20],
    "BYQ_SESSION_ID": session,
    "BYQ_PROVIDER_SESSION_ID": str(uuid.uuid4()),
    "BYQ_DSH_RUN_ID": generation,
    "BYQ_ROOT_RUN_ID": root_run,
    "DEEPSEEK_API_KEY": "synthetic-no-model-call-key",
}
registry = ProductSlotRegistry.from_environment()
command = ("/usr/local/bin/node", "/opt/dsh-runtime/apps/cli/lib/bin.js", "--profile", "acp", "--patch", "/opt/byq/profiles/byq-product.patch.yml")
process = SlotAcpProcess(command, cwd, env, registry=registry)
closed = False
try:
    process.start()
    print("OFFICIAL_ACP_INITIALIZE=PASS")
    result = process.request("session/new", {"cwd": str(cwd.resolve()), "mcpServers": []}, timeout=120.0)
    native_id = result.get("sessionId") if isinstance(result, dict) else None
    assert isinstance(native_id, str) and re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", native_id)
    print("OFFICIAL_ACP_SESSION_NEW=PASS")
    process.request("session/close", {"sessionId": native_id}, timeout=60.0)
    print("OFFICIAL_ACP_SESSION_CLOSE=PASS")
finally:
    process.close()
    closed = True
if not closed or process._cleanup_exit is None or process._cleanup_exit.cleanup != "proven":
    raise SystemExit("signed runner cleanup was not proven")
print("SIGNED_EXIT_CLEANUP=PROVEN")
