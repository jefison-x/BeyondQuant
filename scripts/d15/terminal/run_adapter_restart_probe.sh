#!/usr/bin/env bash
#
# Reproduce the 0.9 step-5 B3 `terminal-adapter-restart` native probe.
#
# It uses the real isolated DSH 0.1.5-rc.1 candidate closure installed in
# `scripts/d15/terminal/node_modules` (npm ci, packages only) and runs separate
# OS processes for each native runtime generation, each BYQ adapter generation
# and each client action. It touches no production stack and creates no
# release/tag.
#
# Usage: scripts/d15/terminal/run_adapter_restart_probe.sh [out-dir]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="${1:-$(mktemp -d /tmp/byq-b3-out.XXXXXX)}"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"

cd "$HERE"
node adapter_restart_harness.mjs run --out "$OUT/native-observations.v1.json"
python3 adapter_restart_observer.py --selfcheck --out "$OUT/negative-controls.v1.json"
python3 adapter_restart_observer.py \
  --observations "$OUT/native-observations.v1.json" \
  --out "$OUT/verdict.v1.json"
python3 adapter_restart_scope_probe.py --out "$OUT/scope-probe.v1.json"
python3 adapter_restart_provenance.py --out "$OUT/provenance.v1.json"

echo "evidence written to $OUT"
