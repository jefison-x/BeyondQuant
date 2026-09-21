#!/usr/bin/env bash
#
# Reproduce the 0.9 step-5 B2 `subagent-byq-adapter-restart` real composition /
# restart probe inside the isolated candidate image.
#
# It strictly avoids production: the image is `byq-d15-4-continuable-candidate:local`,
# started with `--network none`, a keyless synthetic MCP + scripted provider and a
# throwaway session volume. Generation A and generation B run as separate OS
# processes in separate containers sharing only the durable session root.
#
# Usage: scripts/d15/subagent/run_byq_adapter_restart_probe.sh [out-dir]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
PROBE="$REPO_ROOT/scripts/d15/subagent/byq_adapter_restart_probe.py"
IMG="${BYQ_D15_B2_IMAGE:-byq-d15-4-continuable-candidate:local}"
OUT="${1:-$(mktemp -d /tmp/byq-b2-out.XXXXXX)}"
SESSIONS="$(mktemp -d /tmp/byq-b2-sessions.XXXXXX)"
mkdir -p "$OUT"
chmod 777 "$SESSIONS" "$OUT"

run_generation() {
  local mode="$1"
  docker run --rm --network none --user root \
    -v "$SESSIONS":/sessions -v "$OUT":/out \
    -v "$PROBE":/tmp/byq_adapter_restart_probe.py:ro \
    -e DSH_SESSION_ROOT=/sessions -e D15_B2_OUT=/out \
    --entrypoint python3 "$IMG" /tmp/byq_adapter_restart_probe.py "$mode"
}

run_generation a || true   # generation A exits abruptly by design
run_generation b
docker run --rm --network none --user root -v "$OUT":/out \
  -v "$PROBE":/tmp/byq_adapter_restart_probe.py:ro -e D15_B2_OUT=/out \
  --entrypoint python3 "$IMG" /tmp/byq_adapter_restart_probe.py assemble

python3 "$REPO_ROOT/scripts/d15/subagent/byq_adapter_restart_observer.py" \
  --observation "$OUT/composition-restart.v1.json" \
  --out "$OUT/verdict.v1.json" \
  --blocked-out "$OUT/external-blocked.v1.json" || true

echo "evidence written to $OUT"
