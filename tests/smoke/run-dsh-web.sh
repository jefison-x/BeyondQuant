#!/usr/bin/env bash
set -euo pipefail

compose=(docker compose -f compose.yml -f compose.dsh-web.yml --profile dsh-web)

echo "== diagnostic DSH Web status =="
"${compose[@]}" ps
test -n $("${compose[@]}" ps -q dsh)
health=$("${compose[@]}" ps --format '{{.Service}} {{.Health}}' | awk '$1 == "dsh" {print $2}')
test "$health" = healthy

echo "== diagnostic DSH Web has no mounts or host publication =="
dsh_id=$("${compose[@]}" ps -q dsh)
test "$(docker inspect "$dsh_id" --format '{{json .Mounts}}')" = "[]"
if "${compose[@]}" config | grep -qE '3080:3080|network_mode: host|docker.sock'; then
  echo "Diagnostic DSH Web profile exposes an unsafe host boundary" >&2
  exit 1
fi

echo "== diagnostic DSH Web composition =="
config=$("${compose[@]}" run --rm --no-deps dsh dsh --profile byq --dump-config)
grep -q '@deepseek-ai/dsh-mcp-client' <<<"$config"
grep -q 'serverName: byq' <<<"$config"
grep -q 'transport: streamable-http' <<<"$config"
grep -q 'failOnStartupError: true' <<<"$config"
preset_block=$(awk '/^- id: agent-presets$/{capture=1} /^- id: mcp-byq$/{capture=0} capture' <<<"$config")
grep -q 'default: byq-product' <<<"$preset_block"
grep -q 'includeUserRoot: false' <<<"$preset_block"
if grep -Eiq 'default: (standard|minimal|code|cordis)' <<<"$preset_block"; then
  echo "Diagnostic DSH selected a coding preset" >&2
  exit 1
fi

echo "== diagnostic DSH Web logs =="
logs=$("${compose[@]}" logs dsh 2>&1)
if grep -Eiq '(mcp.*startup.*fail|startup.*mcp.*fail|failed.*mcp|socat|nginx|iptables|network_mode: host)' <<<"$logs"; then
  echo "Diagnostic DSH Web startup or exposure failure detected" >&2
  exit 1
fi

echo "DSH Web diagnostic profile smoke PASS"
