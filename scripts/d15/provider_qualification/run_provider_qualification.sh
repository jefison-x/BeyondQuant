#!/usr/bin/env bash
#
# Independent DSH provider-qualification slice orchestrator.
#
# Examines one published DSH release for an out-of-process continuable provider
# (the ADR-0082 Option 1 capability). This is an OPT-IN qualification probe: it is
# NOT part of the daily CI profile and only runs when the explicit qualification
# switch is set:
#
#     BYQ_DSH_PROVIDER_QUALIFICATION=1 \
#       scripts/d15/provider_qualification/run_provider_qualification.sh 0.1.5-rc.2 rc2 next
#
# The probe installs the examined release into an isolated scratch directory
# (never the repository, never a production file), boots the real
# SubagentRuntime, runs the real capability gate and writes the inventory plus a
# fail-able verdict. It exits non-zero when the capability is absent (BLOCKED),
# which is the honest result for an unqualified release.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
SUBAGENT_MANIFEST="${REPO_ROOT}/scripts/d15/subagent/package.json"
TEMPLATE_VERSION="0.1.5-rc.1"

NPM_VERSION="${1:-}"
VERSION_ID="${2:-}"
CHANNEL="${3:-unknown}"

if [[ "${BYQ_DSH_PROVIDER_QUALIFICATION:-}" != "1" ]]; then
  echo "BLOCKED: qualification switch not set; export BYQ_DSH_PROVIDER_QUALIFICATION=1" >&2
  exit 2
fi
if [[ -z "${NPM_VERSION}" || -z "${VERSION_ID}" ]]; then
  echo "usage: BYQ_DSH_PROVIDER_QUALIFICATION=1 $0 <npm-version> <version-id> [channel]" >&2
  exit 2
fi

for tool in node npm python3; do
  command -v "${tool}" >/dev/null 2>&1 || { echo "missing required tool: ${tool}" >&2; exit 2; }
done

SCRATCH="${BYQ_DSH_PROVIDER_QUALIFICATION_DIR:-$(mktemp -d /tmp/byq-dsh-provider-qualification-XXXXXX)}"
mkdir -p "${SCRATCH}"

python3 - "${SUBAGENT_MANIFEST}" "${NPM_VERSION}" "${TEMPLATE_VERSION}" "${SCRATCH}/package.json" <<'PY'
import json, sys
manifest, npm_version, template_version, out = sys.argv[1:]
data = json.load(open(manifest, encoding="utf-8"))
data["name"] = "byq-dsh-provider-qualification"
data["dependencies"] = {
    name: (npm_version if pinned == template_version else pinned)
    for name, pinned in data["dependencies"].items()
}
json.dump(data, open(out, "w", encoding="utf-8"), indent=2)
PY

echo "== installing ${NPM_VERSION} into ${SCRATCH}" >&2
( cd "${SCRATCH}" && npm install --no-audit --no-fund --legacy-peer-deps >/dev/null )

INVENTORY="${SCRATCH}/capability-inventory.${VERSION_ID}.v1.json"
node "${SCRIPT_DIR}/capability_inventory.mjs" \
  --module-root "${SCRATCH}" \
  --npm-version "${NPM_VERSION}" \
  --version-id "${VERSION_ID}" \
  --channel "${CHANNEL}" \
  --out "${INVENTORY}" >/dev/null

set +e
python3 "${SCRIPT_DIR}/provider_qualification_observer.py" \
  --inventory "${INVENTORY}" \
  --out "${SCRATCH}/verdict.${VERSION_ID}.v1.json" \
  --blocked-out "${SCRATCH}/external-blocked.${VERSION_ID}.v1.json"
CODE=$?
set -e
echo "qualification scratch: ${SCRATCH}" >&2
echo "qualification exit: ${CODE} (1 = BLOCKED, 0 = PASS)" >&2
exit "${CODE}"
