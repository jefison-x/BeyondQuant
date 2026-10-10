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

echo "== ACP Runtime Adapter has only its bounded runner and workspace mounts =="
runtime_id=$("${compose[@]}" ps -q runtime-adapter)
workspace_root="$DSH_SESSION_ROOT/$BYQ_ACP_PRODUCT_WORKSPACE_ID"
actual_mounts=$(docker inspect "$runtime_id" --format '{{range .Mounts}}{{println .Destination}}{{end}}' | sort)
expected_mounts=$(printf '%s\n' \
  /run/byq-acp-product-runner \
  /run/byq-acp-runner \
  "$workspace_root" | sort)
test "$actual_mounts" = "$expected_mounts"
test -n "$BYQ_ACP_PRODUCT_WORKSPACE_ID"

echo "== Runtime Adapter filesystem permissions =="
"${compose[@]}" exec -T runtime-adapter sh -c \
  "test -w '$workspace_root' && test ! -w /app && test ! -w /opt/byq"

"${compose[@]}" exec -T runtime-adapter sh -c \
  'test -f /opt/dsh-runtime/apps/cli/lib/bin.js && test ! -w /opt/dsh-runtime/apps/cli/lib/bin.js'

echo "== MCP contract and auth wall =="
contract_workspace="$("${compose[@]}" exec -T backend python - <<'PYCODE'
from app.conversation_catalog import ConversationCatalogStore
from tests.workspace_helpers import trusted_product_agent_context

# The contract client uses a Product Agent identity. Research writes must bind
# its original owner/workspace/session/trace conversation, just as production.
headers = trusted_product_agent_context(
    "mcp-contract", actor="byq-product-agent-session_mcp_contract",
    session_id="session_mcp_contract", trace_id="trace_mcp_contract",
)
catalog = ConversationCatalogStore()
try:
    conversation = catalog.create("mcp-contract", headers["x-byq-session-id"], headers["x-byq-trace-id"])
    assert conversation["workspace_id"] == headers["x-byq-workspace-id"]
finally:
    catalog.close()
print(headers["x-byq-workspace-id"])
PYCODE
)"
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

echo "== ACP Runtime Adapter release readiness =="
"${compose[@]}" exec -T runtime-adapter python3 - <<'PYCODE'
import json
from urllib.request import urlopen

with urlopen("http://127.0.0.1:8400/readyz", timeout=20) as response:
    readiness = json.load(response)
assert readiness["runtime_adapter"] == "ready"
assert readiness["release_id"] == "dsh-v0.2.0-rc.2"
assert readiness["release_identity"] == "matched"
assert readiness["sdk"] == "deepseek-harness-sdk==not-applicable"
assert readiness["runtime_bin"] == "deepseek-harness-runtime-bin==not-applicable"
assert readiness["composition_hash"].startswith("sha256:")
serialized_readiness = json.dumps(readiness).lower()
assert "deepseek_api_key" not in serialized_readiness
assert "authorization" not in serialized_readiness
print(json.dumps({key: readiness[key] for key in ("runtime_adapter", "release_id", "release_identity", "sdk", "runtime_bin", "plugin_profile", "composition_hash")}, sort_keys=True))
PYCODE

echo "== Product runner uses the workspace-scoped session volume =="
product_runner_id=$("${compose[@]}" ps -q acp-product-runner)
product_mounts=$(docker inspect "$product_runner_id" --format '{{range .Mounts}}{{if ne .Type "tmpfs"}}{{println .Destination}}{{end}}{{end}}' | sort)
expected_product_mounts=$(printf '%s\n' \
  /run/byq-acp-product-runner \
  /var/lib/byq/acp-product-runner-state \
  "$workspace_root" | sort)
test "$product_mounts" = "$expected_product_mounts"
# Cycle only the idle Product runner before any Product session or user turn. This
# checks that the current workspace-scoped volume survives a normal runner restart;
# it does not claim crash recovery or DSH process continuation.
marker="$workspace_root/.byq-ci-volume-marker-$BYQ_CI_SCOPE"
marker_value="workspace-volume-$BYQ_CI_SCOPE"
docker exec "$product_runner_id" sh -c "printf '%s' '$marker_value' > '$marker'"
"${compose[@]}" restart acp-product-runner >/dev/null
"${compose[@]}" up -d --pull never --no-build --wait acp-product-runner >/dev/null
product_runner_id=$("${compose[@]}" ps -q acp-product-runner)
test "$(docker exec "$product_runner_id" sh -c "cat '$marker'")" = "$marker_value"
docker exec "$product_runner_id" rm -f "$marker"

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

echo "ACP Product API, authenticated workspace, and current release smoke PASS"
