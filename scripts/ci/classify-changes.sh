#!/usr/bin/env bash
set -euo pipefail

# Read one repository-relative changed path per line and emit a stable CI plan.
# Unknown executable/source paths fail closed into the full integration tier.

changed_count=0
docs=no
docs_only=yes
architecture=no
backend=no
gateway=no
runtime=no
mcp=no
frontend=no
integration=no
unknown=no

mark_all_components() {
  architecture=yes
  backend=yes
  gateway=yes
  runtime=yes
  mcp=yes
  frontend=yes
}

while IFS= read -r path; do
  [ -n "$path" ] || continue
  changed_count=$((changed_count + 1))
  case "$path" in
    docs/*|README.md|LICENSE|CHANGELOG.md)
      docs=yes
      case "$path" in
        docs/architecture/*|docs/contracts/*|docs/roadmap/STATUS.md|docs/roadmap/IMPLEMENTATION_PLAN.md)
          architecture=yes
          ;;
      esac
      ;;
    AGENTS.md|ARCHITECTURE.md)
      docs=yes
      architecture=yes
      ;;
    apps/frontend/*)
      docs_only=no
      frontend=yes
      architecture=yes
      case "$path" in
        apps/frontend/tests/e2e/real-product.spec.ts|apps/frontend/playwright.real.config.ts)
          integration=yes
          ;;
      esac
      ;;
    services/backend/*)
      docs_only=no
      backend=yes
      architecture=yes
      ;;
    services/gateway/*)
      docs_only=no
      gateway=yes
      architecture=yes
      ;;
    services/runtime-adapter/*|services/dsh/*|plugins/*)
      docs_only=no
      runtime=yes
      architecture=yes
      ;;
    services/mcp/*)
      docs_only=no
      mcp=yes
      architecture=yes
      ;;
    packages/*)
      docs_only=no
      mark_all_components
      integration=yes
      ;;
    workers/*)
      docs_only=no
      backend=yes
      architecture=yes
      integration=yes
      ;;
    infra/*|compose.yml|compose.*.yml|.github/workflows/*|scripts/ci/*|tests/smoke/*)
      docs_only=no
      mark_all_components
      integration=yes
      ;;
    scripts/evidence/*|apps/frontend/tests/e2e/real-*.ts)
      docs_only=no
      mark_all_components
      integration=yes
      ;;
    tests/architecture/*)
      docs_only=no
      architecture=yes
      ;;
    .gitignore|.dockerignore|Makefile)
      docs_only=no
      architecture=yes
      ;;
    *)
      docs_only=no
      unknown=yes
      mark_all_components
      integration=yes
      ;;
  esac
done

if [ "$changed_count" -eq 0 ]; then
  docs_only=no
  architecture=yes
fi

cat <<EOF
changed_count=$changed_count
docs=$docs
docs_only=$docs_only
architecture=$architecture
backend=$backend
gateway=$gateway
runtime=$runtime
mcp=$mcp
frontend=$frontend
integration=$integration
unknown=$unknown
EOF
