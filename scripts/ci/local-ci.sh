#!/usr/bin/env bash
#
# BeyondQuant local CI — replicates the GitHub Actions checks
# (.github/workflows/ci.yml) so the project can run its own CI locally
# without depending on GitHub-hosted runner billing.
#
# Usage:
#   scripts/ci/local-ci.sh [options]
#
# Options:
#   --base=<sha|ref>   Diff baseline (default: origin/main)
#   --only=<checks>    Comma list: docs,architecture,backend,gateway,runtime,mcp,frontend
#   --all              Run every check (ignore path filtering)
#   --build            Compatibility flag: selected images are always built with Docker cache
#   --with-e2e         Also run frontend Playwright e2e (needs browsers installed)
#   --with-smoke       Also run full compose smoke (./tests/smoke/run.sh)
#   --auto-smoke       Run full compose smoke only for integration-risk changes
#   --with-dsh-web     Also run DSH Web diagnostic profile checks
#   --retain-u6-artifacts  Local full CI only: retain exact U6 images/archive for rehearsal
#   --keep-postgres    Keep the local CI postgres container after the run
#   --no-cleanup       Leave compose/services running (debug)
#   --plan-only        Print the selected checks without executing them
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

BASE_SHA="origin/main"
DIFF_BASE=""
ONLY=""
ALL=0
DO_BUILD=0
WITH_E2E=0
WITH_SMOKE=0
AUTO_SMOKE=0
WITH_DSH_WEB=0
RETAIN_U6_ARTIFACTS=0
KEEP_POSTGRES=0
NO_CLEANUP=0
PLAN_ONLY=0

for arg in "$@"; do
  case "$arg" in
    --base=*) BASE_SHA="${arg#*=}" ;;
    --only=*) ONLY="${arg#*=}" ;;
    --all) ALL=1 ;;
    --build) DO_BUILD=1 ;;
    --with-e2e) WITH_E2E=1 ;;
    --with-smoke) WITH_SMOKE=1 ;;
    --auto-smoke) AUTO_SMOKE=1 ;;
    --with-dsh-web) WITH_DSH_WEB=1 ;;
    --retain-u6-artifacts|--retain-dsh-artifacts) RETAIN_U6_ARTIFACTS=1 ;;
    --keep-postgres) KEEP_POSTGRES=1 ;;
    --no-cleanup) NO_CLEANUP=1 ;;
    --plan-only) PLAN_ONLY=1 ;;
    --help|-h) sed -n '2,28p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

if [ "$RETAIN_U6_ARTIFACTS" -eq 1 ] && { [ "$ALL" -ne 1 ] || [ "$WITH_E2E" -ne 1 ] \
    || [ "$WITH_SMOKE" -ne 1 ] || [ "${GITHUB_ACTIONS:-false}" = true ]; }; then
  echo "U6 artifact handoff requires explicit local --all --with-e2e --with-smoke" >&2
  exit 2
fi

PASS=0
FAIL=0
step() { printf '\n==> %s\n' "$1"; }
ok()  { printf '    [PASS] %s\n' "$1"; PASS=$((PASS+1)); }
bad() { printf '    [FAIL] %s\n' "$1"; FAIL=$((FAIL+1)); }

# ---------------------------------------------------------------- changed paths
docs=no; docs_only=no; architecture=no; backend=no; gateway=no; runtime=no
mcp=no; frontend=no; integration=no; unknown=no; changed_count=0
compute_changed() {
  step "changes: diff baseline $BASE_SHA"
  git fetch --quiet origin 2>/dev/null || true
  if ! git rev-parse --verify --quiet "$BASE_SHA" >/dev/null; then
    echo "    [FAIL] baseline '$BASE_SHA' not found locally" >&2
    return 1
  fi
  DIFF_BASE="$(git merge-base "$BASE_SHA" HEAD 2>/dev/null || true)"
  if [ -z "$DIFF_BASE" ]; then
    echo "    [WARN] no merge base; comparing the exact baseline tree" >&2
    DIFF_BASE="$BASE_SHA"
  fi
  if ! CHANGED="$(git diff --name-only "$DIFF_BASE" HEAD)"; then
    echo "    [FAIL] unable to compute changed files from '$DIFF_BASE'" >&2
    return 1
  fi
  if [ "${GITHUB_ACTIONS:-false}" != true ]; then
    CHANGED="$({
      printf '%s\n' "$CHANGED"
      git diff --name-only HEAD
      git ls-files --others --exclude-standard
    } | sed '/^$/d' | sort -u)"
  fi
  if [ -z "$CHANGED" ]; then echo "    (no changed files)"; fi
  local classified
  if ! classified="$(printf '%s\n' "$CHANGED" | BYQ_CI_DIFF_BASE="$DIFF_BASE" scripts/ci/classify-changes.sh)"; then
    echo "    [FAIL] change-impact classifier failed; no empty-success fallback" >&2
    return 1
  fi
  while IFS='=' read -r key value; do
    case "$key" in
      changed_count|docs|docs_only|architecture|backend|gateway|runtime|mcp|frontend|integration|unknown)
        printf -v "$key" '%s' "$value"
        ;;
      *) echo "    [FAIL] unknown classifier output: $key" >&2; return 1 ;;
    esac
  done <<< "$classified"
  printf '    plan -> docs=%s architecture=%s backend=%s gateway=%s runtime=%s mcp=%s frontend=%s integration=%s unknown=%s\n' \
    "$docs" "$architecture" "$backend" "$gateway" "$runtime" "$mcp" "$frontend" "$integration" "$unknown"
}

want() { # want <check>
  [ "$ALL" -eq 1 ] && return 0
  if [ -n "$ONLY" ]; then
    case ",$ONLY," in *",$1,"*) return 0 ;; *) return 1 ;; esac
  fi
  case "$1" in
    docs)         [ "$docs" = yes ] ;;
    architecture) [ "$architecture" = yes ] ;;
    backend)      [ "$backend" = yes ] ;;
    gateway)      [ "$gateway" = yes ] ;;
    runtime)      [ "$runtime" = yes ] ;;
    mcp)          [ "$mcp" = yes ] ;;
    frontend)     [ "$frontend" = yes ] ;;
    *) return 1 ;;
  esac
}

# ------------------------------------------------------------------- postgres
BYQ_CI_SCOPE="${BYQ_CI_SCOPE:-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-$$}}"
case "$BYQ_CI_SCOPE" in
  ''|*[!A-Za-z0-9_.-]*) echo "invalid CI scope" >&2; exit 2 ;;
esac
CI_PG="byq-ci-postgres-$BYQ_CI_SCOPE"
CI_BACKEND="byq-ci-backend-$BYQ_CI_SCOPE"
CI_PG_NET="byq-ci-network-$BYQ_CI_SCOPE"
CI_PG_VOL="byq-ci-postgres-data-$BYQ_CI_SCOPE"
CI_BACKEND_TEST="byq-ci-backend-test-$BYQ_CI_SCOPE"
CI_GATEWAY_TEST="byq-ci-gateway-test-$BYQ_CI_SCOPE"
CI_RUNTIME_TEST="byq-ci-runtime-test-$BYQ_CI_SCOPE"
CI_MCP_TEST="byq-ci-mcp-test-$BYQ_CI_SCOPE"
CI_MCP_SERVER="byq-ci-mcp-server-$BYQ_CI_SCOPE"
CI_CANDIDATE_TEST="byq-ci-runtime-candidate-test-$BYQ_CI_SCOPE"
CI_CANDIDATE_VOL="byq-ci-runtime-candidate-data-$BYQ_CI_SCOPE"
CI_BASELINE_BENCH_VOL="byq-ci-runtime-baseline-bench-$BYQ_CI_SCOPE"
CI_CANDIDATE_BENCH_VOL="byq-ci-runtime-candidate-bench-$BYQ_CI_SCOPE"
RESOURCES_TOUCHED=0
ACTIVE_CHILD_PID=""
HEAVY_LOCK_HELD=0

cleanup_on_exit() {
  exit_code=$?
  trap - EXIT INT TERM HUP
  if [ "$NO_CLEANUP" -eq 1 ]; then
    echo "CI debug resources retained for scope: $BYQ_CI_SCOPE" >&2
  elif [ "$RESOURCES_TOUCHED" -eq 1 ]; then
    cleanup_args=("--scope=$BYQ_CI_SCOPE" --quiet)
    [ "$KEEP_POSTGRES" -eq 0 ] || cleanup_args+=(--keep-postgres)
    scripts/ci/cleanup-resources.sh "${cleanup_args[@]}" || exit_code=1
  fi
  exit "$exit_code"
}
trap cleanup_on_exit EXIT

terminate_on_signal() {
  code="$1"
  if [ -n "$ACTIVE_CHILD_PID" ]; then
    kill -TERM "$ACTIVE_CHILD_PID" >/dev/null 2>&1 || true
  fi
  exit "$code"
}
trap 'terminate_on_signal 130' INT
trap 'terminate_on_signal 143' TERM HUP

run_interruptible() {
  "$@" &
  ACTIVE_CHILD_PID=$!
  if wait "$ACTIVE_CHILD_PID"; then
    child_status=0
  else
    child_status=$?
  fi
  ACTIVE_CHILD_PID=""
  return "$child_status"
}

acquire_heavy_capacity() {
  [ "$HEAVY_LOCK_HELD" -eq 0 ] || return 0
  available_kb="$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)"
  minimum_kb="${BYQ_CI_MIN_AVAILABLE_MEMORY_KB:-3145728}"
  if [ "$available_kb" -lt "$minimum_kb" ]; then
    echo "available memory ${available_kb}KiB is below ${minimum_kb}KiB" >&2
    return 1
  fi
  exec 9>/tmp/byq-ci-heavy.lock
  flock -w "${BYQ_CI_HEAVY_LOCK_TIMEOUT_SECONDS:-900}" 9 || return 1
  HEAVY_LOCK_HELD=1
}

if [ "${GITHUB_ACTIONS:-false}" = true ] && [ "$NO_CLEANUP" -eq 1 ]; then
  echo "--no-cleanup is forbidden in GitHub Actions" >&2
  exit 2
fi

ensure_clean_postgres() {
  RESOURCES_TOUCHED=1
  docker network inspect "$CI_PG_NET" >/dev/null 2>&1 || \
    docker network create --label "byq.ci.scope=$BYQ_CI_SCOPE" "$CI_PG_NET" >/dev/null
  if ! docker inspect "$CI_PG" >/dev/null 2>&1; then
    step "postgres: creating clean CI instance ($CI_PG)"
    docker volume create --label "byq.ci.scope=$BYQ_CI_SCOPE" "$CI_PG_VOL" >/dev/null
    docker run -d --name "$CI_PG" --label "byq.ci.scope=$BYQ_CI_SCOPE" --network "$CI_PG_NET" \
      -e POSTGRES_DB=byq_domain -e POSTGRES_USER=byq_app -e POSTGRES_PASSWORD=byq-app-dev \
      -v "$CI_PG_VOL":/var/lib/postgresql/data \
      -v "$REPO_ROOT/infra/postgres/init:/docker-entrypoint-initdb.d:ro" \
      postgres:16-alpine >/dev/null
  fi
  for _ in $(seq 1 30); do
    docker exec "$CI_PG" pg_isready -U byq_app -d byq_domain >/dev/null 2>&1 && return 0
    sleep 1
  done
  return 1
}
ensure_ci_backend() {
  RESOURCES_TOUCHED=1
  if ! docker inspect "$CI_BACKEND" >/dev/null 2>&1; then
    step "backend: starting live MCP contract dependency ($CI_BACKEND)"
    docker run -d --name "$CI_BACKEND" --label "byq.ci.scope=$BYQ_CI_SCOPE" --network "$CI_PG_NET" --network-alias backend \
      -e BYQ_DATABASE_URL="postgresql+psycopg://byq_test:byq-test-dev@$CI_PG:5432/byq_domain_test" \
      -e PYTHONDONTWRITEBYTECODE=1 \
      -v "$REPO_ROOT/services/backend:/app" -w /app \
      -v "$REPO_ROOT/plugins/dsh-byq/registry:/app/plugin-registry:ro" \
      -e BYQ_WEB_EVIDENCE_PROVENANCE_POLICY=/opt/byq-evidence/web-evidence-provenance.json \
      -v "$REPO_ROOT/config/dsh/generated/web-evidence-provenance.json:/opt/byq-evidence/web-evidence-provenance.json:ro" \
      "$(ci_image backend)" >/dev/null
  fi
  for _ in $(seq 1 30); do
    docker exec "$CI_BACKEND" python -c \
      "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=1)" \
      >/dev/null 2>&1 && return 0
    sleep 1
  done
  docker logs "$CI_BACKEND" >&2 || true
  return 1
}
ensure_ci_mcp() {
  ensure_clean_postgres || return 1
  ensure_ci_backend || return 1
  RESOURCES_TOUCHED=1
  if ! docker inspect "$CI_MCP_SERVER" >/dev/null 2>&1; then
    docker run -d --name "$CI_MCP_SERVER" --label "byq.ci.scope=$BYQ_CI_SCOPE" \
      --network "$CI_PG_NET" --network-alias mcp \
      -e BYQ_MCP_TOKEN=ci-mcp-test-only -e BYQ_BACKEND_URL=http://backend:8000 \
      -e BYQ_WEB_EVIDENCE_PROVENANCE_POLICY=/app/dsh-0.1.2rc1.web-evidence-provenance.json \
      "$(ci_image mcp)" >/dev/null
  fi
  for _ in $(seq 1 30); do
    docker exec "$CI_MCP_SERVER" node -e \
      "fetch('http://127.0.0.1:8300/healthz').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))" \
      >/dev/null 2>&1 && return 0
    sleep 1
  done
  docker logs "$CI_MCP_SERVER" >&2 || true
  return 1
}
prepare_ci_compose_env() {
  # Never load the operator's .env/override or inherit production credentials.
  export COMPOSE_FILE="$REPO_ROOT/compose.yml"
  export COMPOSE_DISABLE_ENV_FILE=1 COMPOSE_ENV_FILES=/dev/null COMPOSE_PROFILES=""
  export COMPOSE_PROJECT_NAME="byq-ci-stack-$BYQ_CI_SCOPE"
  export BYQ_PRODUCT_NETWORK_NAME="byq-ci-product-$BYQ_CI_SCOPE"
  export BYQ_SIGNAL_SANDBOX_NETWORK_NAME="byq-ci-signal-sandbox-$BYQ_CI_SCOPE"
  export BYQ_POSTGRES_VOLUME_NAME="byq-ci-postgres-$BYQ_CI_SCOPE"
  export BYQ_DOMAIN_VOLUME_NAME="byq-ci-domain-$BYQ_CI_SCOPE"
  export BYQ_ML_MODEL_VOLUME_NAME="byq-ci-ml-model-$BYQ_CI_SCOPE"
  export BYQ_DSH_SESSIONS_VOLUME_NAME="byq-ci-dsh-sessions-$BYQ_CI_SCOPE"
  export BYQ_WORKFLOW_TRACES_VOLUME_NAME="byq-ci-workflow-traces-$BYQ_CI_SCOPE"
  # An empty host-port asks Docker to allocate an available loopback port.
  # Explicit bindings remain available for local debugging.
  export BYQ_FRONTEND_BIND="${BYQ_CI_FRONTEND_BIND:-127.0.0.1:0}"
  export BYQ_GATEWAY_BIND="${BYQ_CI_GATEWAY_BIND:-127.0.0.1:0}"
  export BYQ_POSTGRES_VOLUME_EXTERNAL=false
  export POSTGRES_DB=byq_domain POSTGRES_USER=byq_app POSTGRES_PASSWORD=byq-app-dev
  export BYQ_DATABASE_URL=postgresql+psycopg://byq_app:byq-app-dev@postgres:5432/byq_domain
  export BYQ_MCP_TOKEN=ci-mcp-test-only BYQ_PRODUCT_TOKEN=ci-product-test-only
  export BYQ_CREDENTIAL_KEYRING='{"ci-v1":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"}'
  export BYQ_CREDENTIAL_ACTIVE_KEY_ID=ci-v1
  export BYQ_CREDENTIAL_RESOLVER_TOKEN=ci-credential-resolver-test-only
  export BYQ_PLUGIN_DEPLOYMENT_TOKEN=ci-plugin-test-only
  export BYQ_FEEDBACK_PUBLISHER_TOKEN=ci-publisher-test-only BYQ_FEEDBACK_HUB_RELAY_TOKEN=ci-relay-test-only
  export DEEPSEEK_API_KEY="" TUSHARE_TOKEN=""
  export BYQ_FEEDBACK_GITHUB_TOKEN="" BYQ_FEEDBACK_GITHUB_APP_ID="" BYQ_FEEDBACK_GITHUB_REPOSITORY=""
  export BYQ_FEEDBACK_GITHUB_INSTALLATION_ID="" BYQ_FEEDBACK_GITHUB_APP_PRIVATE_KEY_FILE=""
  export BYQ_FEEDBACK_HUB_URL=""
  export BYQ_DSH_COMPOSITION_SOURCE=plugins/dsh-byq/compositions/byq-product-sdk.cordis.yml
  export BYQ_DSH_IDENTITY_SOURCE=plugins/dsh-byq/compositions/byq-product-sdk.identity.json
  # Explicit rollback baseline for the legacy full suite. The exact promoted
  # bundled artifact is separately built and exercised by check_dsh_candidate
  # and U7's closed Product/model/browser qualification; never silently retag it.
  export BYQ_DSH_RUNTIME_DOCKERFILE=services/runtime-adapter/Dockerfile.u7
  export BYQ_DSH_COMPATIBILITY_RELEASE=dsh-0.1.1rc1
  export BYQ_DSH_COMPOSITION=/opt/byq/compositions/byq-product-sdk.cordis.yml
  export BYQ_DSH_SESSION_ROOT=/var/lib/byq/dsh-sessions/dsh-0.1.1rc1
  export BYQ_WEB_EVIDENCE_PROVENANCE_POLICY=/app/web-evidence-provenance.json
  export BYQ_PLUGIN_REGISTRY_PATH=/app/plugin-registry/plugins.json
  export BYQ_BOOTSTRAP_ADMIN_USERNAME="${BYQ_CI_BOOTSTRAP_ADMIN_USERNAME:-ci-admin}"
  export BYQ_BOOTSTRAP_ADMIN_PASSWORD="${BYQ_CI_BOOTSTRAP_ADMIN_PASSWORD:-ci-bootstrap-test-only}"
  export BYQ_E2E_ADMIN_USERNAME="$BYQ_BOOTSTRAP_ADMIN_USERNAME"
  export BYQ_E2E_ADMIN_PASSWORD="$BYQ_BOOTSTRAP_ADMIN_PASSWORD"
  export BYQ_GOLDEN_OWNER_USERNAME="$BYQ_BOOTSTRAP_ADMIN_USERNAME"
  export BYQ_GOLDEN_OWNER_PASSWORD="$BYQ_BOOTSTRAP_ADMIN_PASSWORD"
  export BYQ_GOLDEN_OTHER_USERNAME="${BYQ_CI_GOLDEN_OTHER_USERNAME:-ci-user}"
  export BYQ_GOLDEN_OTHER_PASSWORD="${BYQ_CI_GOLDEN_OTHER_PASSWORD:-ci-user-test-only}"
}

ci_image() {
  # Compose's default build image name, scoped to this run/attempt.
  printf '%s-%s' "$COMPOSE_PROJECT_NAME" "$1"
}

build_test_images() {
  local services=() service
  python3 scripts/dsh/release.py check || return 1
  python3 scripts/dsh/promotion.py check || return 1
  python3 -c 'from scripts.dsh import build_revision as b; [b.check(b.selected_build_id(r)) for r in sorted(b.RELEASES)]' || return 1
  prepare_ci_compose_env
  if [ "$WITH_SMOKE" -eq 1 ] || [ "$WITH_DSH_WEB" -eq 1 ]; then
    services=(backend gateway runtime-adapter mcp frontend data-worker signal-worker ml-worker signal-sandbox feedback-publisher feedback-hub-relay)
  else
    if want backend || want mcp; then services+=(backend); fi
    if want gateway; then services+=(gateway); fi
    if want runtime; then services+=(runtime-adapter); fi
    if want mcp; then services+=(mcp); fi
  fi
  [ "${#services[@]}" -gt 0 ] || return 0
  step "build: selected run-scoped images (cache allowed, stale fallback forbidden)"
  RESOURCES_TOUCHED=1
  acquire_heavy_capacity || return 1
  run_interruptible docker compose --profile feedback-publisher build "${services[@]}" || return 1
  for service in "${services[@]}"; do
    printf '    image identity -> service=%s tag=%s id=' "$service" "$(ci_image "$service")"
    docker image inspect "$(ci_image "$service")" --format '{{.Id}}' || return 1
  done
}
resolve_ci_compose_urls() {
  local frontend_address gateway_address
  frontend_address="$(docker compose port frontend 80)"
  gateway_address="$(docker compose port gateway 8100)"
  test -n "$frontend_address"
  test -n "$gateway_address"
  export BYQ_REAL_BASE_URL="http://$frontend_address"
  export BYQ_SMOKE_GATEWAY_URL="http://$gateway_address"
  printf '    isolated endpoints -> frontend=%s gateway=%s\n' \
    "$BYQ_REAL_BASE_URL" "$BYQ_SMOKE_GATEWAY_URL"
}
wait_for_product_ready() {
  local attempt
  for attempt in $(seq 1 30); do
    if curl --fail --silent --show-error --max-time 2 \
        "$BYQ_SMOKE_GATEWAY_URL/readyz" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "    [FAIL] Product API was not externally ready after backend restart" >&2
  return 1
}

# ------------------------------------------------------------------- checks
check_hygiene() {
  step "hygiene: git diff --check"
  if [ "${GITHUB_ACTIONS:-false}" = true ]; then
    hygiene_command=(git diff --check "$DIFF_BASE" HEAD)
  else
    hygiene_command=(git diff --check "$DIFF_BASE")
  fi
  if "${hygiene_command[@]}"; then ok "git diff --check"; else bad "git diff --check"; fi
}

check_docs() {
  step "docs: changed Markdown links and structure"
  if scripts/ci/check-docs.py --base="$DIFF_BASE"; then ok "docs checks"; else bad "docs checks"; fi
}

check_architecture() {
  step "architecture: unittest"
  if python3 -m unittest discover -s tests -p 'test_*.py'; then
    ok "architecture tests"; else bad "architecture tests"; fi
}

check_backend() {
  step "backend: pytest against clean postgres"
  ensure_clean_postgres || { bad "clean postgres"; return; }
  RESOURCES_TOUCHED=1
  if run_interruptible docker run --rm --name "$CI_BACKEND_TEST" --label "byq.ci.scope=$BYQ_CI_SCOPE" --network "$CI_PG_NET" \
      -e BYQ_DATABASE_URL="postgresql+psycopg://byq_test:byq-test-dev@$CI_PG:5432/byq_domain_test" \
      -e PYTHONDONTWRITEBYTECODE=1 \
      -v "$REPO_ROOT/services/backend:/app" -w /app \
      -v "$REPO_ROOT/plugins/dsh-byq/registry:/app/plugin-registry:ro" \
      -e BYQ_WEB_EVIDENCE_PROVENANCE_POLICY=/opt/byq-evidence/web-evidence-provenance.json \
      -v "$REPO_ROOT/config/dsh/generated/web-evidence-provenance.json:/opt/byq-evidence/web-evidence-provenance.json:ro" \
      -v "$REPO_ROOT/config/dsh/generated/dsh-0.1.2rc1.web-evidence-provenance.json:/opt/byq-evidence/dsh-0.1.2rc1.web-evidence-provenance.json:ro" \
      "$(ci_image backend)" python -m pytest -q -p no:cacheprovider; then
    ok "backend tests"; else bad "backend tests"; fi
  if [ -d "$REPO_ROOT/workers/feedback-publisher/tests" ]; then
    if run_interruptible docker run --rm --name "$CI_BACKEND_TEST" --label "byq.ci.scope=$BYQ_CI_SCOPE" \
        -e PYTHONDONTWRITEBYTECODE=1 \
        -v "$REPO_ROOT/workers/feedback-publisher:/publisher:ro" -w /publisher \
        "$(ci_image backend)" python -m pytest -q -p no:cacheprovider tests; then
      ok "feedback publisher fake-GitHub tests"; else bad "feedback publisher fake-GitHub tests"; fi
  fi
  if [ -d "$REPO_ROOT/workers/feedback-hub-relay/tests" ]; then
    if run_interruptible docker run --rm --name "$CI_BACKEND_TEST" --label "byq.ci.scope=$BYQ_CI_SCOPE" \
        -e PYTHONDONTWRITEBYTECODE=1 -v "$REPO_ROOT/workers/feedback-hub-relay:/relay:ro" -w /relay \
        "$(ci_image backend)" python -m pytest -q -p no:cacheprovider tests; then
      ok "feedback hub relay tests"; else bad "feedback hub relay tests"; fi
  fi
}

check_cloudflare_feedback_hub() {
  step "central feedback hub: Cloudflare workerd tests and deploy dry-run"
  if (
    # Wrangler imports matching process.env keys as bindings. Product's empty
    # publisher configuration must not override the Hub's fixed repository/test secrets.
    for name in ${!BYQ_FEEDBACK_@}; do unset "$name"; done
    cd "$REPO_ROOT/deploy/feedback-hub-cloudflare"
    npm ci --ignore-scripts --no-audit --no-fund --legacy-peer-deps \
      && npm run check \
      && npm run dry-run
  ); then
    ok "Cloudflare feedback hub tests and bundles"
  else
    bad "Cloudflare feedback hub tests and bundles"
  fi
}

check_gateway() {
  step "gateway: pytest (mocked backend)"
  RESOURCES_TOUCHED=1
  if run_interruptible docker run --rm --name "$CI_GATEWAY_TEST" --label "byq.ci.scope=$BYQ_CI_SCOPE" -e PYTHONDONTWRITEBYTECODE=1 \
      -v "$REPO_ROOT/services/gateway:/app" \
      -v "$REPO_ROOT/packages:/app/packages" -w /app \
      "$(ci_image gateway)" python -m pytest -q -p no:cacheprovider; then
    ok "gateway tests"; else bad "gateway tests"; fi
}

check_runtime() {
  step "runtime-adapter: pytest"
  RESOURCES_TOUCHED=1
  if run_interruptible docker run --rm --name "$CI_RUNTIME_TEST" --label "byq.ci.scope=$BYQ_CI_SCOPE" -e PYTHONDONTWRITEBYTECODE=1 \
      -v "$REPO_ROOT/services/runtime-adapter:/app" \
      -v "$REPO_ROOT/packages:/app/packages" -w /app \
      -v "$REPO_ROOT/plugins/dsh-byq/compositions/byq-product-sdk.cordis.yml:/opt/byq/compositions/byq-product-sdk.cordis.yml:ro" \
      -v "$REPO_ROOT/plugins/dsh-byq/runtime:/opt/byq/runtime:ro" \
      -v "$REPO_ROOT/plugins/dsh-byq/skills:/opt/dsh/bundles/dsh-byq/skills:ro" \
      "$(ci_image runtime-adapter)" sh -ec 'node --test /opt/byq/runtime/*.test.js && python3 -m pytest -q -p no:cacheprovider'; then
    ok "runtime-adapter tests"; else bad "runtime-adapter tests"; fi
}

check_dsh_candidate() {
  step "runtime-adapter: real 0.1.2rc1 candidate qualification"
  local benchmark_dir="$REPO_ROOT/.ci-artifacts/$BYQ_CI_SCOPE"
  mkdir -p "$benchmark_dir"
  ensure_ci_mcp || { bad "candidate live MCP dependency"; return; }
  RESOURCES_TOUCHED=1
  candidate_image="$(ci_image runtime-candidate)"
  if ! run_interruptible docker build -f services/runtime-adapter/Dockerfile.u7-candidate \
      -t "$candidate_image" .; then
    bad "candidate image build"; return
  fi
  printf '    candidate image identity -> tag=%s id=' "$candidate_image"
  docker image inspect "$candidate_image" --format '{{.Id}}' || { bad "candidate image identity"; return; }
  for volume in "$CI_CANDIDATE_VOL" "$CI_BASELINE_BENCH_VOL" "$CI_CANDIDATE_BENCH_VOL"; do
    docker volume create --label "byq.ci.scope=$BYQ_CI_SCOPE" "$volume" >/dev/null
  done
  common=(--rm --label "byq.ci.scope=$BYQ_CI_SCOPE" --network "$CI_PG_NET"
    -e BYQ_MCP_TOKEN=ci-mcp-test-only -e BYQ_MCP_URL="http://$CI_MCP_SERVER:8300/mcp/v1"
    -e BYQ_OWNER_PRINCIPAL=ci-candidate -e BYQ_ACTOR_PRINCIPAL=ci-candidate
    -e BYQ_WORKSPACE_ID=ci-candidate -e PYTHONDONTWRITEBYTECODE=1)
  if ! run_interruptible docker run --name "$CI_CANDIDATE_TEST" "${common[@]}" \
      -e BYQ_DSH_REAL_PROCESS_TEST=1 -v "$CI_CANDIDATE_VOL:/var/lib/byq/dsh-sessions" \
      -v "$REPO_ROOT/tests/dsh_upgrade:/qualification:ro" "$candidate_image" \
      python3 -m pytest -q -p no:cacheprovider \
      /app/tests/test_dsh_012_real_process.py /qualification/test_candidate_journeys.py; then
    bad "candidate real-process/delegate journeys"; return
  fi
  if ! run_interruptible docker run --name "$CI_RUNTIME_TEST" "${common[@]}" \
      -v "$CI_BASELINE_BENCH_VOL:/var/lib/byq/dsh-sessions" \
      -v "$REPO_ROOT/tests/dsh_upgrade:/qualification:ro" "$(ci_image runtime-adapter)" \
      python3 /qualification/runtime_benchmark.py > "$benchmark_dir/baseline-benchmark.json"; then
    cat "$benchmark_dir/baseline-benchmark.json" >&2
    bad "baseline lifecycle benchmark"; return
  fi
  cat "$benchmark_dir/baseline-benchmark.json"
  if ! run_interruptible docker run --name "$CI_CANDIDATE_TEST" "${common[@]}" \
      -e BYQ_DSH_REAL_PROCESS_TEST=1 -v "$CI_CANDIDATE_BENCH_VOL:/var/lib/byq/dsh-sessions" \
      -v "$REPO_ROOT/tests/dsh_upgrade:/qualification:ro" "$candidate_image" \
      python3 /qualification/runtime_benchmark.py > "$benchmark_dir/candidate-benchmark.json"; then
    cat "$benchmark_dir/candidate-benchmark.json" >&2
    bad "candidate lifecycle benchmark"; return
  fi
  cat "$benchmark_dir/candidate-benchmark.json"
  ok "candidate real-process, five delegates and old/new lifecycle benchmarks"
}

check_mcp() {
  step "mcp: npm test (tsc build + in-container server + contract tests)"
  ensure_clean_postgres || { bad "clean postgres for MCP"; return; }
  ensure_ci_backend || { bad "live backend for MCP"; return; }
  # A successful domain write needs a real isolated user/workspace, not the
  # deliberately invalid identities used by the original read/error-only tests.
  local contract_workspace
  if ! contract_workspace="$(docker exec "$CI_BACKEND" python -c 'from tests.workspace_helpers import trusted_agent_context; print(trusted_agent_context("mcp-contract")["x-byq-workspace-id"])')"; then
    bad "MCP workspace fixture"; return
  fi
  # Mount only sources so the image's complete node_modules/dist stay intact;
  # run as root so tsc can rewrite /app/dist; start the MCP server in-container
  # because the contract test connects to a live 127.0.0.1:8300 endpoint.
  RESOURCES_TOUCHED=1
  if run_interruptible docker run --rm --name "$CI_MCP_TEST" --label "byq.ci.scope=$BYQ_CI_SCOPE" --network "$CI_PG_NET" -u 0 \
      -e BYQ_MCP_TOKEN=ci-phase5-test-only \
      -e BYQ_BACKEND_URL=http://backend:8000 \
      -e MCP_URL=http://127.0.0.1:8300/mcp/v1 \
      -e BYQ_MCP_CONTRACT_OWNER=mcp-contract \
      -e BYQ_MCP_CONTRACT_WORKSPACE="$contract_workspace" \
      -v "$REPO_ROOT/services/mcp/src:/app/src" \
      -v "$REPO_ROOT/services/mcp/tests:/app/tests" \
      -v "$REPO_ROOT/services/mcp/package.json:/app/package.json" \
      -v "$REPO_ROOT/services/mcp/tsconfig.json:/app/tsconfig.json" \
      -w /app "$(ci_image mcp)" \
      sh -ec 'npm run build; node dist/src/server.js >/tmp/byq-mcp-server.log 2>&1 & server_pid=$!; trap "kill $server_pid >/dev/null 2>&1 || true" EXIT; sleep 3; npm test'; then
    ok "mcp tests"; else bad "mcp tests"; fi
}

check_frontend() {
  step "frontend: npm ci + build + vitest (locked local node toolchain)"
  if ( cd apps/frontend && npm ci --no-audit --no-fund ); then
    ok "frontend locked install"; else bad "frontend locked install"; return; fi
  if ( cd apps/frontend && npm run build ); then
    ok "frontend build"; else bad "frontend build"; fi
  if ( cd apps/frontend && npm run test ); then
    ok "frontend unit tests"; else bad "frontend unit tests"; fi
  if ( cd apps/frontend && npm audit --audit-level=high ); then
    ok "frontend dependency audit"; else bad "frontend dependency audit"; fi
  if [ "$WITH_E2E" -eq 1 ]; then
    if ( cd apps/frontend && npx playwright install chromium && npm run test:e2e:mocked -- \
        --output "$REPO_ROOT/.ci-artifacts/$BYQ_CI_SCOPE/mocked-e2e" ); then
      ok "frontend mocked UI e2e"; else bad "frontend mocked UI e2e"; fi
  fi
}

check_smoke() {
  step "smoke: isolated full compose stack"
  RESOURCES_TOUCHED=1
  if ! acquire_heavy_capacity; then
    bad "heavy-CI resource preflight/lock"
    return
  fi
  prepare_ci_compose_env
  if ! run_interruptible docker compose up -d --no-build --wait; then
    docker compose logs --no-color || true
    bad "isolated compose startup"
    return
  fi
  if ! resolve_ci_compose_urls; then
    bad "isolated compose endpoint discovery"
    return
  fi
  if run_interruptible ./tests/smoke/run.sh; then ok "full smoke"; else bad "full smoke"; fi
  if [ -f "$REPO_ROOT/workers/feedback-publisher/Dockerfile" ]; then
    if run_interruptible docker compose --profile feedback-publisher up -d --no-build --wait feedback-publisher \
      && [ "$(docker compose --profile feedback-publisher exec -T feedback-publisher id -u)" = "10006" ] \
      && docker compose --profile feedback-publisher exec -T feedback-publisher python -c \
        "import json,urllib.request; data=json.load(urllib.request.urlopen('http://127.0.0.1:8700/healthz')); assert data['status']=='ok'" \
      && docker compose exec -T postgres sh -ec \
        'test "$(psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT configured FROM product_feedback_publisher_state WHERE destination_key='"'"'github_primary'"'"'")" = f'; then
      ok "unconfigured non-root feedback publisher"; else bad "unconfigured non-root feedback publisher"; fi
    # The profile is optional and the rest of the smoke validates the default
    # Product stack. Do not let its heartbeat alter that test workload.
    run_interruptible docker compose --profile feedback-publisher stop feedback-publisher >/dev/null 2>&1 || true
  fi
  if docker compose cp scripts/evidence/phase67-seed.py backend:/tmp/phase67-seed.py >/dev/null \
    && docker compose exec -T backend python /tmp/phase67-seed.py; then
    ok "Phase 67 validated index fixture"; else bad "Phase 67 validated index fixture"; fi
  if docker compose cp scripts/evidence/phase70-seed.py backend:/tmp/phase70-seed.py >/dev/null \
    && docker compose exec -T backend python /tmp/phase70-seed.py; then
    ok "Phase 70 multi-index catalogue fixture"; else bad "Phase 70 multi-index catalogue fixture"; fi
  if docker compose cp scripts/evidence/phase68-seed.py backend:/tmp/phase68-seed.py >/dev/null \
    && docker compose exec -T backend python /tmp/phase68-seed.py; then
    ok "Phase 68 dynamic inputs fixture"; else bad "Phase 68 dynamic inputs fixture"; fi
  if docker compose cp scripts/evidence/phase74-seed.py backend:/tmp/phase74-seed.py >/dev/null \
    && docker compose exec -T backend python /tmp/phase74-seed.py; then
    ok "Phase 74 LightGBM fixture"; else bad "Phase 74 LightGBM fixture"; fi
  if (
    cd apps/frontend
    [ -x node_modules/.bin/playwright ] || npm ci --no-audit --no-fund
    npx playwright install chromium
    npm run test:e2e:real -- --output "$REPO_ROOT/.ci-artifacts/$BYQ_CI_SCOPE/real-e2e"
  ); then
    ok "real Product API browser smoke"; else bad "real Product API browser smoke"; fi
  local evidence_dir="$REPO_ROOT/.ci-artifacts/$BYQ_CI_SCOPE"
  mkdir -p "$evidence_dir"
  if BYQ_GOLDEN_ORIGIN="$BYQ_SMOKE_GATEWAY_URL" \
      scripts/evidence/phase74-product-verification.py "$evidence_dir/phase74-identities.json" \
    && docker compose restart ml-worker >/dev/null \
    && docker compose up -d --no-build --wait ml-worker >/dev/null \
    && BYQ_GOLDEN_ORIGIN="$BYQ_SMOKE_GATEWAY_URL" \
      scripts/evidence/phase74-product-verification.py --verify "$evidence_dir/phase74-identities.json"; then
    ok "Phase 74 restart persistence and two-user isolation"; else bad "Phase 74 restart persistence and two-user isolation"; fi
  if BYQ_GOLDEN_ORIGIN="$BYQ_SMOKE_GATEWAY_URL" \
      scripts/evidence/phase90-feedback-verification.py "$evidence_dir/phase90-feedback.json" \
    && docker compose restart backend >/dev/null \
    && docker compose up -d --no-build --wait backend >/dev/null \
    && wait_for_product_ready \
    && BYQ_GOLDEN_ORIGIN="$BYQ_SMOKE_GATEWAY_URL" \
      scripts/evidence/phase90-feedback-verification.py --verify "$evidence_dir/phase90-feedback.json"; then
    ok "Phase 90 feedback restart persistence and two-user isolation"; else bad "Phase 90 feedback restart persistence and two-user isolation"; fi
  if docker compose cp scripts/evidence/phase48-seed.py backend:/tmp/phase48-seed.py >/dev/null \
    && docker compose exec -T \
      -e BYQ_GOLDEN_OTHER_USERNAME="$BYQ_GOLDEN_OTHER_USERNAME" \
      -e BYQ_GOLDEN_OTHER_PASSWORD="$BYQ_GOLDEN_OTHER_PASSWORD" \
      backend python /tmp/phase48-seed.py \
    && BYQ_GOLDEN_ORIGIN="$BYQ_SMOKE_GATEWAY_URL" scripts/evidence/phase48-product-golden.py; then
    ok "Phase 48 no-mock two-user Product coherence"; else bad "Phase 48 no-mock two-user Product coherence"; fi
}

check_dsh_web() {
  step "dsh-web: diagnostic profile"
  RESOURCES_TOUCHED=1
  prepare_ci_compose_env
  if ! acquire_heavy_capacity; then
    bad "heavy-CI resource preflight/lock"
    return
  fi
  if ! run_interruptible docker compose -f compose.yml -f compose.dsh-web.yml --profile dsh-web build dsh; then
    bad "dsh-web build; stale fallback forbidden"
    return
  fi
  if ! run_interruptible docker compose -f compose.yml -f compose.dsh-web.yml --profile dsh-web up -d --no-build --wait; then
    bad "dsh-web startup"
    return
  fi
  if run_interruptible ./tests/smoke/run-dsh-web.sh; then ok "dsh-web smoke"; else bad "dsh-web smoke"; fi
}

# ------------------------------------------------------------------- main
# Allow contract tests to exercise functions with fake Docker, without running CI.
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then return 0; fi
compute_changed

if [ "$AUTO_SMOKE" -eq 1 ] && [ "$integration" = yes ]; then
  WITH_SMOKE=1
fi

printf '    execution -> all=%s e2e=%s smoke=%s dsh_web=%s\n' \
  "$ALL" "$WITH_E2E" "$WITH_SMOKE" "$WITH_DSH_WEB"
if [ "$PLAN_ONLY" -eq 1 ]; then
  exit 0
fi

if ! build_test_images; then
  bad "image build/identity gate; tests must not reuse old images"
  exit 1
fi

check_hygiene
want docs && check_docs
want architecture && check_architecture
if want backend; then
  check_backend
  check_cloudflare_feedback_hub
fi
want gateway && check_gateway
want runtime && check_runtime
[ "$integration" = yes ] && want runtime && check_dsh_candidate
want mcp && check_mcp
want frontend && check_frontend
[ "$WITH_SMOKE" -eq 1 ] && check_smoke
[ "$WITH_DSH_WEB" -eq 1 ] && check_dsh_web

printf '\n=============================\n'
if [ "$FAIL" -gt 0 ]; then
  printf 'Local CI: %d passed, %d FAILED\n' "$PASS" "$FAIL"
  exit 1
fi
if [ "$RETAIN_U6_ARTIFACTS" -eq 1 ]; then
  python3 scripts/dsh/retain_u6_ci_images.py --scope "$BYQ_CI_SCOPE" || exit 1
fi
printf 'Local CI: all %d checks passed\n' "$PASS"
