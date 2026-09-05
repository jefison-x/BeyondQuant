#!/usr/bin/env bash
set -euo pipefail

SCOPE=""
VERIFY_ONLY=0
QUIET=0
KEEP_POSTGRES=0

for arg in "$@"; do
  case "$arg" in
    --scope=*) SCOPE="${arg#*=}" ;;
    --verify-only) VERIFY_ONLY=1 ;;
    --quiet) QUIET=1 ;;
    --keep-postgres) KEEP_POSTGRES=1 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

if [ -z "$SCOPE" ]; then
  echo "--scope is required" >&2
  exit 2
fi
case "$SCOPE" in
  *[!A-Za-z0-9_.-]*) echo "invalid CI scope: $SCOPE" >&2; exit 2 ;;
esac

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROJECT="byq-ci-stack-$SCOPE"
PG="byq-ci-postgres-$SCOPE"
BACKEND="byq-ci-backend-$SCOPE"
BACKEND_TEST="byq-ci-backend-test-$SCOPE"
GATEWAY_TEST="byq-ci-gateway-test-$SCOPE"
RUNTIME_TEST="byq-ci-runtime-test-$SCOPE"
MCP_TEST="byq-ci-mcp-test-$SCOPE"
PG_NET="byq-ci-network-$SCOPE"
PG_VOL="byq-ci-postgres-data-$SCOPE"

export COMPOSE_PROJECT_NAME="$PROJECT"
export COMPOSE_FILE="$REPO_ROOT/compose.yml"
export COMPOSE_DISABLE_ENV_FILE=1 COMPOSE_ENV_FILES=/dev/null COMPOSE_PROFILES=""
export BYQ_MCP_TOKEN=ci-mcp-test-only BYQ_PRODUCT_TOKEN=ci-product-test-only
export BYQ_POSTGRES_VOLUME_EXTERNAL=false
export BYQ_PRODUCT_NETWORK_NAME="byq-ci-product-$SCOPE"
export BYQ_SIGNAL_SANDBOX_NETWORK_NAME="byq-ci-signal-sandbox-$SCOPE"
export BYQ_POSTGRES_VOLUME_NAME="byq-ci-postgres-$SCOPE"
export BYQ_DOMAIN_VOLUME_NAME="byq-ci-domain-$SCOPE"
export BYQ_ML_MODEL_VOLUME_NAME="byq-ci-ml-model-$SCOPE"
export BYQ_DSH_SESSIONS_VOLUME_NAME="byq-ci-dsh-sessions-$SCOPE"
export BYQ_WORKFLOW_TRACES_VOLUME_NAME="byq-ci-workflow-traces-$SCOPE"

image_resources=(backend gateway runtime-adapter mcp frontend data-worker signal-worker ml-worker \
  signal-sandbox feedback-publisher feedback-hub-relay dsh)
network_resources=("$BYQ_PRODUCT_NETWORK_NAME" "$BYQ_SIGNAL_SANDBOX_NETWORK_NAME")
[ "$KEEP_POSTGRES" -eq 1 ] || network_resources+=("$PG_NET")
volume_resources=("$BYQ_POSTGRES_VOLUME_NAME" "$BYQ_DOMAIN_VOLUME_NAME" "$BYQ_ML_MODEL_VOLUME_NAME" \
  "$BYQ_DSH_SESSIONS_VOLUME_NAME" "$BYQ_WORKFLOW_TRACES_VOLUME_NAME")
[ "$KEEP_POSTGRES" -eq 1 ] || volume_resources+=("$PG_VOL")

if ! docker info >/dev/null 2>&1; then
  echo "CI cleanup verification failed: Docker daemon is unavailable" >&2
  exit 1
fi

cleanup_exact_resources() {
  if [ "$KEEP_POSTGRES" -eq 0 ]; then
    ids="$(docker ps -aq --filter "label=byq.ci.scope=$SCOPE")"
    if [ -n "$ids" ]; then
      # Docker IDs are whitespace-free daemon-generated identifiers.
      docker rm -f $ids >/dev/null 2>&1 || true
    fi
  else
    docker rm -f "$BACKEND" "$BACKEND_TEST" "$GATEWAY_TEST" "$RUNTIME_TEST" "$MCP_TEST" \
      >/dev/null 2>&1 || true
  fi
  (
    cd "$REPO_ROOT"
    docker compose --profile feedback-publisher down --rmi local -v --remove-orphans >/dev/null 2>&1 || true
  )
  # Component-only runs never create Compose containers; remove their exact tags too.
  for service in "${image_resources[@]}"; do
    docker image rm "$PROJECT-$service" >/dev/null 2>&1 || true
  done
  docker rm -f "$BACKEND" >/dev/null 2>&1 || true
  if [ "$KEEP_POSTGRES" -eq 0 ]; then
    docker rm -f "$PG" >/dev/null 2>&1 || true
    docker volume rm "$PG_VOL" >/dev/null 2>&1 || true
    docker network rm "$PG_NET" >/dev/null 2>&1 || true
  fi
}

scoped_resources_exist() {
  local service resource
  for service in "${image_resources[@]}"; do
    docker image inspect "$PROJECT-$service" >/dev/null 2>&1 && return 0
  done
  [ "$KEEP_POSTGRES" -eq 1 ] || [ -z "$(docker ps -aq --filter "label=byq.ci.scope=$SCOPE")" ] || return 0
  [ -z "$(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT")" ] || return 0
  for resource in "${network_resources[@]}"; do
    docker network inspect "$resource" >/dev/null 2>&1 && return 0
  done
  for resource in "${volume_resources[@]}"; do
    docker volume inspect "$resource" >/dev/null 2>&1 && return 0
  done
  return 1
}

if [ "$VERIFY_ONLY" -eq 0 ]; then
  max_attempts="${BYQ_CI_CLEANUP_MAX_ATTEMPTS:-12}"
  retry_delay="${BYQ_CI_CLEANUP_RETRY_SECONDS:-3}"
  case "$max_attempts:$retry_delay" in
    *[!0-9:]*|0:*|*: ) echo "invalid cleanup retry configuration" >&2; exit 2 ;;
  esac
  [ "$max_attempts" -le 30 ] && [ "$retry_delay" -le 10 ] || {
    echo "cleanup retry configuration exceeds safety bound" >&2
    exit 2
  }
  stable_absence=0
  for attempt in $(seq 1 "$max_attempts"); do
    cleanup_exact_resources
    if scoped_resources_exist; then
      stable_absence=0
    else
      stable_absence=$((stable_absence + 1))
      [ "$stable_absence" -lt 2 ] || break
    fi
    if [ "$attempt" -lt "$max_attempts" ]; then
      [ "$QUIET" -eq 1 ] || echo "CI cleanup settling: $SCOPE (attempt $attempt/$max_attempts)" >&2
      sleep "$retry_delay"
    fi
  done
fi

failures=0
for service in "${image_resources[@]}"; do
  if docker image inspect "$PROJECT-$service" >/dev/null 2>&1; then
    echo "CI cleanup verification failed: image tag remains: $PROJECT-$service" >&2
    failures=$((failures + 1))
  fi
done
if [ "$KEEP_POSTGRES" -eq 0 ] && [ -n "$(docker ps -aq --filter "label=byq.ci.scope=$SCOPE")" ]; then
  echo "CI cleanup verification failed: labeled containers remain for $SCOPE" >&2
  failures=$((failures + 1))
fi
if [ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT")" ]; then
  echo "CI cleanup verification failed: Compose containers remain for $PROJECT" >&2
  failures=$((failures + 1))
fi
for resource in "${network_resources[@]}"; do
  if docker network inspect "$resource" >/dev/null 2>&1; then
    echo "CI cleanup verification failed: network remains: $resource" >&2
    failures=$((failures + 1))
  fi
done
for resource in "${volume_resources[@]}"; do
  if docker volume inspect "$resource" >/dev/null 2>&1; then
    echo "CI cleanup verification failed: volume remains: $resource" >&2
    failures=$((failures + 1))
  fi
done

if [ "$failures" -gt 0 ]; then
  exit 1
fi
[ "$QUIET" -eq 1 ] || echo "CI cleanup verified: $SCOPE"
