#!/usr/bin/env bash
set -euo pipefail

compose=(docker compose)

echo "== base compose status =="
"${compose[@]}" ps

echo "== base services running and healthchecked services healthy =="
while IFS= read -r service; do
  container_id=$("${compose[@]}" ps -q "$service")
  test -n "$container_id"
  test "$(docker inspect "$container_id" --format '{{.State.Status}}')" = "running"
  health=$(docker inspect "$container_id" --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}')
  test -z "$health" || test "$health" = "healthy"
done < <("${compose[@]}" config --services)

echo "== non-root runtime users =="
for service in gateway backend mcp runtime-adapter signal-worker signal-sandbox feedback-hub-relay; do
  uid=$("${compose[@]}" exec -T "$service" id -u | tr -d '\r')
  test "$uid" != "0"
done

echo "== Signal producer privilege and network boundary =="
worker_id=$("${compose[@]}" ps -q signal-worker)
sandbox_id=$("${compose[@]}" ps -q signal-sandbox)
product_network=${BYQ_PRODUCT_NETWORK_NAME:-byq_product}
sandbox_network=${BYQ_SIGNAL_SANDBOX_NETWORK_NAME:-byq_signal_sandbox}
sandbox_networks=$(docker inspect "$sandbox_id" --format '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}')
worker_networks=$(docker inspect "$worker_id" --format '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}')
test "$(printf '%s\n' "$sandbox_networks" | sed '/^$/d')" = "$sandbox_network"
printf '%s\n' "$worker_networks" | grep -Fx "$product_network" >/dev/null
printf '%s\n' "$worker_networks" | grep -Fx "$sandbox_network" >/dev/null
backend_id=$("${compose[@]}" ps -q backend)
if docker inspect "$backend_id" --format '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}' | grep -Fx "$sandbox_network"; then
  echo "Backend unexpectedly joined the signal sandbox network" >&2
  exit 1
fi
if docker inspect "$sandbox_id" --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -Ei '(BYQ_DATABASE_URL|TOKEN|PASSWORD|CREDENTIAL|TUSHARE|DSH|MCP)'; then
  echo "Signal sandbox unexpectedly received a credential-bearing environment variable" >&2
  exit 1
fi

echo "== Runtime Adapter has only the session persistence mount =="
runtime_id=$("${compose[@]}" ps -q runtime-adapter)
mounts=$(docker inspect "$runtime_id" --format '{{range .Mounts}}{{println .Destination}}{{end}}')
test "$mounts" = "/var/lib/byq/dsh-sessions"

echo "== Runtime Adapter filesystem permissions =="
"${compose[@]}" exec -T runtime-adapter sh -c \
  'test -w /var/lib/byq/dsh-sessions && test ! -w /app && test ! -w /opt/byq'

"${compose[@]}" exec -T runtime-adapter python3 - <<'PYCODE'
import os
from deepseek_harness_runtime import bundled_runtime_path
runtime = bundled_runtime_path()
assert runtime.is_file() and os.access(runtime, os.X_OK)
assert not os.access(runtime, os.W_OK)
PYCODE

echo "== MCP contract and auth wall =="
contract_workspace="$("${compose[@]}" exec -T backend python -c 'from tests.workspace_helpers import trusted_agent_context; print(trusted_agent_context("mcp-contract")["x-byq-workspace-id"])')"
"${compose[@]}" exec -T \
  -e BYQ_MCP_CONTRACT_OWNER=mcp-contract \
  -e BYQ_MCP_CONTRACT_WORKSPACE="$contract_workspace" \
  -e BYQ_MCP_CONTRACT_WEB_PLUGIN_VERSION=0.1.2-rc.1 \
  -e BYQ_EXPECTED_WEB_EVIDENCE_PRODUCER=0.1.2-rc.1 mcp npm test
"${compose[@]}" exec -T mcp node --input-type=module -e \
  "const r=await fetch('http://127.0.0.1:8300/mcp/v1',{method:'POST',headers:{'content-type':'application/json'},body:'{}'}); if(r.status!==401) process.exit(1);"

echo "== Gateway health and readyz =="
python3 - <<'PY'
import json
import os
from urllib.request import urlopen

gateway = os.environ.get("BYQ_SMOKE_GATEWAY_URL", "http://127.0.0.1:8100")

with urlopen(gateway + "/healthz", timeout=5) as response:
    health = json.load(response)
assert response.status == 200
assert health["service"] == "byq-gateway"
assert health["status"] == "ok"

with urlopen(gateway + "/readyz", timeout=5) as response:
    payload = json.load(response)
assert response.status == 200
assert payload["service"] == "byq-gateway"
assert payload["status"] == "ok"
assert payload["dsh_runtime_integration"] == "runtime-adapter"
print(json.dumps(payload, sort_keys=True))
PY

echo "== Authenticated Product Agent session and BYQ trace replay =="
python3 - <<'PY'
import json
import os
import http.cookiejar
import urllib.request
from urllib.error import HTTPError
from urllib.request import Request, urlopen

gateway = os.environ.get("BYQ_SMOKE_GATEWAY_URL", "http://127.0.0.1:8100")
username = os.environ["BYQ_E2E_ADMIN_USERNAME"]
password = os.environ["BYQ_E2E_ADMIN_PASSWORD"]
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

def request(path, *, method="GET", payload=None, auth=True):
    body = None if payload is None else json.dumps(payload).encode()
    headers = {"content-type": "application/json"} if body else {}
    target = gateway + path
    outgoing = Request(target, data=body, headers=headers, method=method)
    return opener.open(outgoing, timeout=20) if auth else urlopen(outgoing, timeout=20)

try:
    request("/v1/agent/sessions", method="POST", payload={}, auth=False)
except HTTPError as exc:
    assert exc.code == 401
else:
    raise AssertionError("Product Agent accepted an unauthenticated request")

with request(
    "/api/product/auth/login", method="POST",
    payload={"username": username, "password": password}, auth=True,
) as response:
    assert response.status == 200

with request("/v1/agent/sessions", method="POST", payload={}) as response:
    assert response.status == 201
    created = json.load(response)
session_id = created["session_id"]
assert session_id.startswith("conversation_")

with request(f"/v1/workflows/{session_id}/events") as response:
    assert response.status == 200
    first_event = None
    for line in response:
        if line.startswith(b"data: "):
            first_event = json.loads(line[6:])
            break
assert first_event and first_event["kind"] == "session.ready"
assert first_event["source"] == "runtime-adapter"
assert "session.event" not in json.dumps(first_event)

if not os.environ.get("DEEPSEEK_API_KEY"):
    try:
        request(
            f"/v1/agent/sessions/{session_id}/turns",
            method="POST",
            payload={"content": "keyless phase 7 smoke"},
        )
    except HTTPError as exc:
        assert exc.code == 503
    else:
        raise AssertionError("keyless Product Agent turn was not rejected")

with request(f"/v1/agent/sessions/{session_id}", method="DELETE") as response:
    assert response.status == 200
    assert json.load(response)["status"] == "deleted"
try:
    request(f"/v1/agent/sessions/{session_id}")
except HTTPError as exc:
    assert exc.code == 404
else:
    raise AssertionError("deleted Product conversation remained readable")
print(json.dumps({"session_id": session_id, "first_event": first_event}, sort_keys=True))
PY

echo "== Legacy Gateway runtime proxy routes are absent =="
python3 - <<'PY'
import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen

gateway_root = os.environ.get("BYQ_SMOKE_GATEWAY_URL", "http://127.0.0.1:8100")
routes = (
    ("GET", "/internal/runtime/health", None),
    ("POST", "/internal/runtime/sessions", {"session_id": "smoke", "trace_id": "smoke"}),
    ("POST", "/internal/runtime/sessions/smoke/prompt", {"content": "smoke"}),
    ("POST", "/internal/runtime/sessions/smoke/cancel", None),
    ("POST", "/internal/runtime/sessions/smoke/release", None),
    ("GET", "/internal/workflows/smoke/events", None),
)
for method, path, payload in routes:
    body = None if payload is None else json.dumps(payload).encode()
    request = Request(
        gateway_root + path,
        data=body,
        headers={"content-type": "application/json"} if body else {},
        method=method,
    )
    try:
        with urlopen(request, timeout=10) as response:
            raise AssertionError(f"legacy Gateway route remains: {method} {path} ({response.status})")
    except HTTPError as exc:
        assert exc.code == 404, (method, path, exc.code)
print("legacy Gateway runtime proxies return 404")
PY

echo "== Runtime Adapter keyless initialize, lifecycle and release =="
docker compose exec -T runtime-adapter python3 - <<'PY'
import json
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen

session_id = f"phase6-smoke-{uuid.uuid4().hex}"
base = "http://127.0.0.1:8400/internal/runtime"

with urlopen("http://127.0.0.1:8400/readyz", timeout=20) as response:
    readiness = json.load(response)
assert readiness["sdk"] == "deepseek-harness-sdk==0.1.5rc1"
assert readiness["runtime_bin"] == "deepseek-harness-runtime-bin==0.1.5rc1"
assert readiness["plugin_profile"] == "byq-product-candidate"
assert readiness["enabled_plugin_ids"] == ["compaction", "guard", "web-search"]
assert readiness["composition_hash"].startswith("sha256:")
serialized_readiness = json.dumps(readiness).lower()
assert "deepseek_api_key" not in serialized_readiness
assert "authorization" not in serialized_readiness

def post(path, payload=None, expected=(200, 201, 202)):
    body = None if payload is None else json.dumps(payload).encode()
    request = Request(
        base + path,
        data=body,
        headers={"content-type": "application/json"} if body else {},
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            assert response.status in expected
            return response.status, json.load(response)
    except HTTPError as exc:
        return exc.code, json.loads(exc.read())

status, created = post("/sessions", {"session_id": session_id, "trace_id": "phase6-smoke-trace",
                                     "owner_principal": "phase6-smoke-user", "workspace_id": "phase6-smoke-workspace"})
assert status == 201, (status, created)
assert created["status"] == "ready"
assert created["process_ownership"] == "dedicated"
assert created["persistence"] == "dsh-owned"

duplicate_status, _ = post("/sessions", {"session_id": session_id, "trace_id": "duplicate",
                                         "owner_principal": "phase6-smoke-user", "workspace_id": "phase6-smoke-workspace"})
assert duplicate_status == 409

# The enqueue is keyless. If the provider fails immediately, the lifecycle
# settles to failed/idle and hard cancel correctly returns 409; otherwise the
# active run is hard-cancelled and the owned process is closed.
prompt_status, _ = post(f"/sessions/{session_id}/prompt", {"content": "keyless smoke"})
assert prompt_status == 202
cancel_status, cancelled = post(f"/sessions/{session_id}/cancel?mode=hard")
assert cancel_status in (200, 409)
if cancel_status == 200:
    assert cancelled["status"] == "interrupted"
    resume_status, _ = post(f"/sessions/{session_id}/resume")
    assert resume_status == 409  # Lost process cannot be reconstructed under the old session.

release_status, released = post(f"/sessions/{session_id}/release")
assert release_status == 200
assert released["status"] == "closed"
print(json.dumps({"created": created, "prompt_status": prompt_status, "cancelled": cancelled, "released": released}, sort_keys=True))
PY

echo "== owned DSH child cleanup =="
if docker top "$runtime_id" -eo pid,args | grep -E 'deepseek-harness-sdk-runtime-linux-x64|dsh-jsonrpc-agent|packaged-bin.js|/lib/bin.js'; then
  echo "Released session left an owned DSH runtime process behind" >&2
  exit 1
fi

echo "== named session volume survives adapter restart =="
marker="/var/lib/byq/dsh-sessions/phase6-volume-marker"
"${compose[@]}" exec -T runtime-adapter sh -c "printf phase6 > '$marker'"
"${compose[@]}" restart runtime-adapter
"${compose[@]}" exec -T runtime-adapter sh -c "test \"\$(cat '$marker')\" = phase6"

echo "Product API + direct Runtime Adapter keyless smoke PASS"
