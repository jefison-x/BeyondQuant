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
  # BYQ currently embeds DDL in stores, not just migrations/. Check both trees so
  # removing the last DDL statement cannot make a schema change look low-risk.
  if [[ "$path" == services/backend/app/*.py ]]; then
    old_source=""
    if [ -n "${BYQ_CI_DIFF_BASE:-}" ]; then
      old_source="$(git show "$BYQ_CI_DIFF_BASE:$path" 2>/dev/null || true)"
    fi
    if [ ! -f "$path" ] || grep -Eqi '(CREATE|ALTER|DROP)[[:space:]]+(TABLE|INDEX|SCHEMA)' "$path" \
        || grep -Eqi '(CREATE|ALTER|DROP)[[:space:]]+(TABLE|INDEX|SCHEMA)' <<< "$old_source"; then
      docs_only=no
      mark_all_components
      integration=yes
      continue
    fi
  fi
  case "$path" in
    docs/contracts/*.json|docs/contracts/*.yaml|docs/contracts/*.yml|docs/contracts/*.ts|docs/contracts/*.py|apps/frontend/tests/e2e/real-*.ts|apps/frontend/playwright.real.config.ts|services/*/Dockerfile|services/*/pyproject.toml|services/*/requirements*.txt|services/*/package*.json|services/*/runtime/*|services/*/migrations/*|services/backend/app/db.py|services/backend/app/main.py|plugins/*|scripts/dsh/*)
      docs_only=no
      mark_all_components
      integration=yes
      ;;
    docs/*|README.md|LICENSE|CHANGELOG.md|CONTRIBUTING.md|CONTRIBUTOR_LICENSE_AGREEMENT.md|SECURITY.md|THIRD_PARTY_NOTICES.md)
      docs=yes
      case "$path" in
        docs/architecture/*|docs/contracts/*|docs/roadmap/*|docs/DEVELOPMENT_WORKFLOW.md|docs/operations/ci-policy.md|docs/legal/*|LICENSE|README.md|CONTRIBUTING.md|CONTRIBUTOR_LICENSE_AGREEMENT.md|SECURITY.md|THIRD_PARTY_NOTICES.md)
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
      ;;
    services/backend/*|services/feedback-hub/*|services/feedback-hub-cloudflare/*|deploy/feedback-hub/*|deploy/feedback-hub-cloudflare/*)
      docs_only=no
      backend=yes
      architecture=yes
      case "$path" in
        services/feedback-hub/*|services/feedback-hub-cloudflare/*|deploy/feedback-hub/*|deploy/feedback-hub-cloudflare/*) integration=yes ;;
      esac
      ;;
    services/gateway/*)
      docs_only=no
      gateway=yes
      architecture=yes
      ;;
    services/runtime-adapter/*|services/dsh/*)
      docs_only=no
      mark_all_components
      integration=yes
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
    scripts/evidence/*)
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
