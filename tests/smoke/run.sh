#!/usr/bin/env bash
set -euo pipefail

compose=(docker compose)

echo "== compose status =="
"${compose[@]}" ps

echo "== all services healthy =="
while IFS= read -r health; do
  test "$health" = "healthy"
done < <("${compose[@]}" ps --format '{{.Health}}')

echo "== DSH has no runtime mounts =="
dsh_id=$("${compose[@]}" ps -q dsh)
test -n "$dsh_id"
mounts=$(docker inspect "$dsh_id" --format '{{json .Mounts}}')
test "$mounts" = "[]"

echo "== MCP contract =="
"${compose[@]}" exec -T mcp npm test

echo "== MCP auth wall =="
"${compose[@]}" exec -T mcp node --input-type=module -e \
  "const r=await fetch('http://127.0.0.1:8300/mcp/v1',{method:'POST',headers:{'content-type':'application/json'},body:'{}'}); if(r.status!==401) process.exit(1);"

echo "== DSH composed config =="
config=$("${compose[@]}" run --rm --no-deps dsh dsh --profile byq --dump-config)
grep -q '@deepseek-ai/dsh-mcp-client' <<<"$config"
grep -q 'serverName: byq' <<<"$config"
grep -q 'transport: streamable-http' <<<"$config"
grep -q 'failOnStartupError: true' <<<"$config"

echo "== DSH logs =="
logs=$("${compose[@]}" logs dsh 2>&1)
if grep -Eiq '(mcp.*startup.*fail|startup.*mcp.*fail|failed.*mcp)' <<<"$logs"; then
  echo "DSH MCP startup failure detected" >&2
  exit 1
fi
if grep -Eiq '(--host[ =]0\.0\.0\.0|socat|nginx|iptables|network_mode: host|RCE.*workaround)' <<<"$logs"; then
  echo "DSH Web exposure workaround detected" >&2
  exit 1
fi

# With failOnStartupError=true, a healthy DSH process proves that the initial
# MCP connection and tool synchronization did not fail. rc.6 does not expose
# a stable non-LLM tool-registry endpoint, so the accepted evidence is config
# composition + the MCP contract + clean DSH startup logs.
echo "DSH MCP discovery evidence: config + MCP contract + clean startup logs"
if ! grep -Eiq '(mcp__byq__byq_health|byq_health|registered.*tool|tools?.*(sync|discover|register)|connected.*byq)' <<<"$logs"; then
  echo "DSH logs do not expose the tool name; retaining the permitted combined evidence." >&2
  echo "$logs" >&2
fi

echo "== Gateway health and readyz =="
python3 - <<'PY'
import json
from urllib.request import urlopen

with urlopen("http://127.0.0.1:8100/healthz", timeout=5) as response:
    health = json.load(response)
assert response.status == 200
assert health["service"] == "byq-gateway"
assert health["status"] == "ok"

with urlopen("http://127.0.0.1:8100/readyz", timeout=5) as response:
    payload = json.load(response)

assert response.status == 200
assert payload["service"] == "byq-gateway"
assert payload["status"] == "ok"
assert payload["dsh_runtime_integration"] == "not-configured"
print(json.dumps(payload, sort_keys=True))
PY

echo "Phase 5 smoke PASS"
