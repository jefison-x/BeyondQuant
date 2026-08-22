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
#   --only=<checks>    Comma list: architecture,backend,gateway,runtime,mcp,frontend
#   --all              Run every check (ignore path filtering)
#   --build            docker compose build before service tests (reuse images by default)
#   --with-e2e         Also run frontend Playwright e2e (needs browsers installed)
#   --with-smoke       Also run full compose smoke (./tests/smoke/run.sh)
#   --with-dsh-web     Also run DSH Web diagnostic profile checks
#   --keep-postgres    Keep the local CI postgres container after the run
#   --no-cleanup       Leave compose/services running (debug)
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
WITH_DSH_WEB=0
KEEP_POSTGRES=0
NO_CLEANUP=0

for arg in "$@"; do
  case "$arg" in
    --base=*) BASE_SHA="${arg#*=}" ;;
    --only=*) ONLY="${arg#*=}" ;;
    --all) ALL=1 ;;
    --build) DO_BUILD=1 ;;
    --with-e2e) WITH_E2E=1 ;;
    --with-smoke) WITH_SMOKE=1 ;;
    --with-dsh-web) WITH_DSH_WEB=1 ;;
    --keep-postgres) KEEP_POSTGRES=1 ;;
    --no-cleanup) NO_CLEANUP=1 ;;
    --help|-h) sed -n '2,28p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

PASS=0
FAIL=0
step() { printf '\n==> %s\n' "$1"; }
ok()  { printf '    [PASS] %s\n' "$1"; PASS=$((PASS+1)); }
bad() { printf '    [FAIL] %s\n' "$1"; FAIL=$((FAIL+1)); }

# ---------------------------------------------------------------- changed paths
backend=no; gateway=no; runtime=no; mcp=no; frontend=no; infra=no
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
  if [ -z "$CHANGED" ]; then echo "    (no changed files)"; fi
  echo "$CHANGED" | grep -qE '^services/backend/' && backend=yes
  echo "$CHANGED" | grep -qE '^services/gateway/|^packages/' && gateway=yes
  echo "$CHANGED" | grep -qE '^services/runtime-adapter/|^services/dsh/|^plugins/|^packages/' && runtime=yes
  echo "$CHANGED" | grep -qE '^services/mcp/' && mcp=yes
  echo "$CHANGED" | grep -qE '^apps/frontend/' && frontend=yes
  echo "$CHANGED" | grep -qE '^\.github/workflows/|^compose.*\.yml$|^infra/|^tests/smoke/' && infra=yes
  printf '    changed -> backend=%s gateway=%s runtime=%s mcp=%s frontend=%s infra=%s\n' \
    "$backend" "$gateway" "$runtime" "$mcp" "$frontend" "$infra"
}

want() { # want <check>
  [ "$ALL" -eq 1 ] && return 0
  if [ -n "$ONLY" ]; then
    case ",$ONLY," in *",$1,"*) return 0 ;; *) return 1 ;; esac
  fi
  case "$1" in
    architecture) return 0 ;; # always run
    backend)  [ "$backend" = yes ] || [ "$infra" = yes ] ;;
    gateway)  [ "$gateway" = yes ] || [ "$infra" = yes ] ;;
    runtime)  [ "$runtime" = yes ] || [ "$infra" = yes ] ;;
    mcp)      [ "$mcp" = yes ] || [ "$infra" = yes ] ;;
    frontend) [ "$frontend" = yes ] || [ "$infra" = yes ] ;;
    *) return 1 ;;
  esac
}

# ------------------------------------------------------------------- postgres
BYQ_CI_SCOPE="${GITHUB_RUN_ID:-local-$$}"
CI_PG="byq-ci-postgres-$BYQ_CI_SCOPE"
CI_BACKEND="byq-ci-backend-$BYQ_CI_SCOPE"
CI_PG_NET="byq-ci-network-$BYQ_CI_SCOPE"
CI_PG_VOL="byq-ci-postgres-data-$BYQ_CI_SCOPE"
ensure_clean_postgres() {
  docker network inspect "$CI_PG_NET" >/dev/null 2>&1 || docker network create "$CI_PG_NET" >/dev/null
  if ! docker inspect "$CI_PG" >/dev/null 2>&1; then
    step "postgres: creating clean CI instance ($CI_PG)"
    docker volume create "$CI_PG_VOL" >/dev/null
    docker run -d --name "$CI_PG" --network "$CI_PG_NET" \
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
  if ! docker inspect "$CI_BACKEND" >/dev/null 2>&1; then
    step "backend: starting live MCP contract dependency ($CI_BACKEND)"
    docker run -d --name "$CI_BACKEND" --network "$CI_PG_NET" --network-alias backend \
      -e BYQ_DATABASE_URL="postgresql+psycopg://byq_test:byq-test-dev@$CI_PG:5432/byq_domain_test" \
      -e PYTHONDONTWRITEBYTECODE=1 \
      -v "$REPO_ROOT/services/backend:/app" -w /app \
      beyondquant-backend >/dev/null
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
cleanup_ci_services() {
  docker rm -f "$CI_BACKEND" >/dev/null 2>&1 || true
  [ "$KEEP_POSTGRES" -eq 1 ] && return 0
  docker rm -f "$CI_PG" >/dev/null 2>&1 || true
  docker volume rm "$CI_PG_VOL" >/dev/null 2>&1 || true
  docker network rm "$CI_PG_NET" >/dev/null 2>&1 || true
}
prepare_ci_compose_env() {
  export COMPOSE_PROJECT_NAME="byq-ci-stack-$BYQ_CI_SCOPE"
  export BYQ_PRODUCT_NETWORK_NAME="byq-ci-product-$BYQ_CI_SCOPE"
  export BYQ_SIGNAL_SANDBOX_NETWORK_NAME="byq-ci-signal-sandbox-$BYQ_CI_SCOPE"
  export BYQ_POSTGRES_VOLUME_NAME="byq-ci-postgres-$BYQ_CI_SCOPE"
  export BYQ_DOMAIN_VOLUME_NAME="byq-ci-domain-$BYQ_CI_SCOPE"
  export BYQ_DSH_SESSIONS_VOLUME_NAME="byq-ci-dsh-sessions-$BYQ_CI_SCOPE"
  export BYQ_WORKFLOW_TRACES_VOLUME_NAME="byq-ci-workflow-traces-$BYQ_CI_SCOPE"
  # An empty host-port asks Docker to allocate an available loopback port.
  # Explicit bindings remain available for local debugging.
  export BYQ_FRONTEND_BIND="${BYQ_CI_FRONTEND_BIND:-127.0.0.1:0}"
  export BYQ_GATEWAY_BIND="${BYQ_CI_GATEWAY_BIND:-127.0.0.1:0}"
  export BYQ_MCP_TOKEN="${BYQ_MCP_TOKEN:-ci-mcp-test-only}"
  export BYQ_PRODUCT_TOKEN="${BYQ_PRODUCT_TOKEN:-ci-product-test-only}"
  export BYQ_CREDENTIAL_KEYRING="${BYQ_CREDENTIAL_KEYRING:-{\"ci-v1\":\"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\"}}"
  export BYQ_CREDENTIAL_ACTIVE_KEY_ID="${BYQ_CREDENTIAL_ACTIVE_KEY_ID:-ci-v1}"
  export BYQ_CREDENTIAL_RESOLVER_TOKEN="${BYQ_CREDENTIAL_RESOLVER_TOKEN:-ci-credential-resolver-test-only}"
  export BYQ_BOOTSTRAP_ADMIN_USERNAME="${BYQ_CI_BOOTSTRAP_ADMIN_USERNAME:-ci-admin}"
  export BYQ_BOOTSTRAP_ADMIN_PASSWORD="${BYQ_CI_BOOTSTRAP_ADMIN_PASSWORD:-ci-bootstrap-test-only}"
  export BYQ_E2E_ADMIN_USERNAME="$BYQ_BOOTSTRAP_ADMIN_USERNAME"
  export BYQ_E2E_ADMIN_PASSWORD="$BYQ_BOOTSTRAP_ADMIN_PASSWORD"
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

# ------------------------------------------------------------------- checks
check_architecture() {
  step "architecture: git diff --check + unittest"
  if git diff --check "$DIFF_BASE" HEAD; then ok "git diff --check"; else bad "git diff --check"; fi
  if python3 -m unittest discover -s tests -p 'test_*.py' >/dev/null 2>&1; then
    ok "architecture tests"; else bad "architecture tests"; fi
}

check_backend() {
  step "backend: pytest against clean postgres"
  ensure_clean_postgres || { bad "clean postgres"; return; }
  if docker run --rm --network "$CI_PG_NET" \
      -e BYQ_DATABASE_URL="postgresql+psycopg://byq_test:byq-test-dev@$CI_PG:5432/byq_domain_test" \
      -e PYTHONDONTWRITEBYTECODE=1 \
      -v "$REPO_ROOT/services/backend:/app" -w /app \
      beyondquant-backend python -m pytest -q -p no:cacheprovider >/dev/null 2>&1; then
    ok "backend tests"; else bad "backend tests"; fi
}

check_gateway() {
  step "gateway: pytest (mocked backend)"
  if docker run --rm --network "$CI_PG_NET" -e PYTHONDONTWRITEBYTECODE=1 \
      -v "$REPO_ROOT/services/gateway:/app" \
      -v "$REPO_ROOT/packages:/app/packages" -w /app \
      beyondquant-gateway python -m pytest -q -p no:cacheprovider >/dev/null 2>&1; then
    ok "gateway tests"; else bad "gateway tests"; fi
}

check_runtime() {
  step "runtime-adapter: pytest"
  if docker run --rm --network "$CI_PG_NET" -e PYTHONDONTWRITEBYTECODE=1 \
      -v "$REPO_ROOT/services/runtime-adapter:/app" \
      -v "$REPO_ROOT/packages:/app/packages" -w /app \
      beyondquant-runtime-adapter python3 -m pytest -q -p no:cacheprovider >/dev/null 2>&1; then
    ok "runtime-adapter tests"; else bad "runtime-adapter tests"; fi
}

check_mcp() {
  step "mcp: npm test (tsc build + in-container server + contract tests)"
  ensure_clean_postgres || { bad "clean postgres for MCP"; return; }
  ensure_ci_backend || { bad "live backend for MCP"; return; }
  # Mount only sources so the image's complete node_modules/dist stay intact;
  # run as root so tsc can rewrite /app/dist; start the MCP server in-container
  # because the contract test connects to a live 127.0.0.1:8300 endpoint.
  if docker run --rm --network "$CI_PG_NET" -u 0 \
      -e BYQ_MCP_TOKEN=ci-phase5-test-only \
      -e BYQ_BACKEND_URL=http://backend:8000 \
      -e MCP_URL=http://127.0.0.1:8300/mcp/v1 \
      -v "$REPO_ROOT/services/mcp/src:/app/src" \
      -v "$REPO_ROOT/services/mcp/tests:/app/tests" \
      -v "$REPO_ROOT/services/mcp/package.json:/app/package.json" \
      -v "$REPO_ROOT/services/mcp/tsconfig.json:/app/tsconfig.json" \
      -w /app beyondquant-mcp \
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
    if ( cd apps/frontend && npx playwright install chromium && npm run test:e2e:mocked ); then
      ok "frontend mocked UI e2e"; else bad "frontend mocked UI e2e"; fi
  fi
}

check_smoke() {
  step "smoke: isolated full compose stack"
  prepare_ci_compose_env
  if ! docker compose up -d --wait; then
    docker compose logs --no-color || true
    bad "isolated compose startup"
    if [ "$NO_CLEANUP" -eq 0 ]; then
      docker compose down --rmi local -v >/dev/null 2>&1 || true
      cleanup_ci_services
    fi
    return
  fi
  if ! resolve_ci_compose_urls; then
    bad "isolated compose endpoint discovery"
    if [ "$NO_CLEANUP" -eq 0 ]; then
      docker compose down --rmi local -v >/dev/null 2>&1 || true
      cleanup_ci_services
    fi
    return
  fi
  if ./tests/smoke/run.sh; then ok "full smoke"; else bad "full smoke"; fi
  if (
    cd apps/frontend
    [ -x node_modules/.bin/playwright ] || npm ci --no-audit --no-fund
    npx playwright install chromium
    npm run test:e2e:real
  ); then
    ok "real Product API browser smoke"; else bad "real Product API browser smoke"; fi
  if [ "$NO_CLEANUP" -eq 0 ]; then
    docker compose down --rmi local -v >/dev/null 2>&1 || true
    cleanup_ci_services
  fi
}

check_dsh_web() {
  step "dsh-web: diagnostic profile"
  if [ "$DO_BUILD" -eq 1 ]; then
    docker compose -f compose.yml -f compose.dsh-web.yml --profile dsh-web build dsh >/dev/null 2>&1 || true
  fi
  docker compose -f compose.yml -f compose.dsh-web.yml --profile dsh-web up -d --wait >/dev/null 2>&1
  if ./tests/smoke/run-dsh-web.sh >/dev/null 2>&1; then ok "dsh-web smoke"; else bad "dsh-web smoke"; fi
  [ "$NO_CLEANUP" -eq 1 ] || docker compose -f compose.yml -f compose.dsh-web.yml --profile dsh-web down -v >/dev/null 2>&1 || true
}

# ------------------------------------------------------------------- main
compute_changed

[ "$DO_BUILD" -eq 1 ] && { step "build: docker compose build"; docker compose build >/dev/null 2>&1 || true; }

want architecture && check_architecture
want backend && check_backend
want gateway && check_gateway
want runtime && check_runtime
want mcp && check_mcp
want frontend && check_frontend
[ "$WITH_SMOKE" -eq 1 ] && check_smoke
[ "$WITH_DSH_WEB" -eq 1 ] && check_dsh_web
[ "$WITH_SMOKE" -eq 0 ] && [ "$WITH_DSH_WEB" -eq 0 ] && cleanup_ci_services

printf '\n=============================\n'
if [ "$FAIL" -gt 0 ]; then
  printf 'Local CI: %d passed, %d FAILED\n' "$PASS" "$FAIL"
  exit 1
fi
printf 'Local CI: all %d checks passed\n' "$PASS"
