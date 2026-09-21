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
  .|..|*[!A-Za-z0-9_.-]*) echo "invalid CI scope: $SCOPE" >&2; exit 2 ;;
esac

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROJECT="byq-ci-stack-$SCOPE"
PG="byq-ci-postgres-$SCOPE"
BACKEND="byq-ci-backend-$SCOPE"
BACKEND_TEST="byq-ci-backend-test-$SCOPE"
GATEWAY_TEST="byq-ci-gateway-test-$SCOPE"
RUNTIME_TEST="byq-ci-runtime-test-$SCOPE"
MCP_TEST="byq-ci-mcp-test-$SCOPE"
MCP_SERVER="byq-ci-mcp-server-$SCOPE"
RUNTIME_CANDIDATE_TEST="byq-ci-runtime-candidate-test-$SCOPE"
PG_NET="byq-ci-network-$SCOPE"
PG_VOL="byq-ci-postgres-data-$SCOPE"
RUNTIME_CANDIDATE_VOL="byq-ci-runtime-candidate-data-$SCOPE"
RUNTIME_BASELINE_BENCH_VOL="byq-ci-runtime-baseline-bench-$SCOPE"
RUNTIME_CANDIDATE_BENCH_VOL="byq-ci-runtime-candidate-bench-$SCOPE"

# Run/attempt-scoped manifest of the exact immutable image ids the build captured.
# The same path is derived from BYQ_CI_SCOPE by both local-ci.sh (writer) and this
# independent always-cleanup process, so cleanup can remove a dangling image whose
# mutable run-scoped tag is already gone. It is never shared across scopes.
#
# Scope is a single path component: `/` is rejected, and `.`/`..` are rejected
# above, so the manifest directory normalizes to exactly .ci-artifacts/<scope> and
# can never resolve outside .ci-artifacts/<scope>/. The explicit checks below keep
# that guarantee even if the scope validation changes.
ARTIFACT_ROOT="$REPO_ROOT/.ci-artifacts"
MANIFEST_DIR="$ARTIFACT_ROOT/$SCOPE"
case "$MANIFEST_DIR" in
  "$ARTIFACT_ROOT"/*) ;;
  *) echo "invalid CI scope path: $SCOPE" >&2; exit 2 ;;
esac
if command -v realpath >/dev/null 2>&1; then
  normalized_root="$(realpath -m "$ARTIFACT_ROOT")"
  normalized_dir="$(realpath -m "$MANIFEST_DIR")"
  if [ "$normalized_dir" != "$normalized_root/$SCOPE" ]; then
    echo "invalid CI scope path: $SCOPE" >&2; exit 2
  fi
fi
MANIFEST="$MANIFEST_DIR/image-ids.env"

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
  signal-sandbox feedback-publisher feedback-hub-relay dsh runtime-candidate)
network_resources=("$BYQ_PRODUCT_NETWORK_NAME" "$BYQ_SIGNAL_SANDBOX_NETWORK_NAME")
[ "$KEEP_POSTGRES" -eq 1 ] || network_resources+=("$PG_NET")
volume_resources=("$BYQ_POSTGRES_VOLUME_NAME" "$BYQ_DOMAIN_VOLUME_NAME" "$BYQ_ML_MODEL_VOLUME_NAME" \
  "$BYQ_DSH_SESSIONS_VOLUME_NAME" "$BYQ_WORKFLOW_TRACES_VOLUME_NAME" "$RUNTIME_CANDIDATE_VOL" \
  "$RUNTIME_BASELINE_BENCH_VOL" "$RUNTIME_CANDIDATE_BENCH_VOL")
[ "$KEEP_POSTGRES" -eq 1 ] || volume_resources+=("$PG_VOL")

manifest_ids=()
manifest_services=()
manifest_state="missing"   # missing | valid | invalid
retained_shared_ids=()

if ! docker info >/dev/null 2>&1; then
  echo "CI cleanup verification failed: Docker daemon is unavailable" >&2
  exit 1
fi

# Load and strictly validate the manifest. A missing manifest is backward
# compatible (tag-only cleanup). Invalid content fails closed: no value from the
# file is ever handed to `docker image rm`.
load_manifest_ids() {
  manifest_ids=()
  manifest_services=()
  manifest_state="missing"
  [ -f "$MANIFEST" ] || return 0
  manifest_state="valid"
  local line service image_id known allowed seen
  while IFS= read -r line || [ -n "$line" ]; do
    [ -z "$line" ] && continue
    case "$line" in
      *=*) ;;
      *)
        echo "CI cleanup manifest invalid: missing '=' in line: $line" >&2
        manifest_ids=(); manifest_state="invalid"; return 1 ;;
    esac
    service="${line%%=*}"; image_id="${line#*=}"
    case "$service" in
      ''|*[!a-z0-9-]*)
        echo "CI cleanup manifest invalid: bad service '$service'" >&2
        manifest_ids=(); manifest_state="invalid"; return 1 ;;
    esac
    # Only this run's own services may drive deletion; an unknown service is a
    # foreign or corrupt entry and fails closed.
    allowed=0
    for known in "${image_resources[@]}"; do
      if [ "$service" = "$known" ]; then allowed=1; break; fi
    done
    if [ "$allowed" -ne 1 ]; then
      echo "CI cleanup manifest invalid: service '$service' is not a run-scoped service" >&2
      manifest_ids=(); manifest_state="invalid"; return 1
    fi
    for seen in "${manifest_services[@]}"; do
      if [ "$seen" = "$service" ]; then
        echo "CI cleanup manifest invalid: duplicate service '$service'" >&2
        manifest_ids=(); manifest_state="invalid"; return 1
      fi
    done
    if [[ ! "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]]; then
      echo "CI cleanup manifest invalid: not an immutable image id: $image_id" >&2
      manifest_ids=(); manifest_state="invalid"; return 1
    fi
    manifest_ids+=("$image_id")
    manifest_services+=("$service")
  done < "$MANIFEST"
  return 0
}

# 0 when the image exists and carries at least one repo tag NOT owned by this
# scope. Such an image is shared with another scope and must never be deleted.
# Ownership is an exact `$PROJECT-<service>` match, never a prefix, so a scope
# name that is a prefix of another cannot misclassify a foreign tag as ours.
image_has_foreign_tag() {
  local image_id="$1" tag service ours
  docker image inspect "$image_id" >/dev/null 2>&1 || return 1
  while IFS= read -r tag; do
    [ -z "$tag" ] && continue
    ours=0
    for service in "${image_resources[@]}"; do
      if [ "$tag" = "$PROJECT-$service" ]; then ours=1; break; fi
    done
    [ "$ours" -eq 1 ] || return 0
  done < <(docker image inspect "$image_id" --format '{{range .RepoTags}}{{println .}}{{end}}' 2>/dev/null || true)
  return 1
}

# Remove the exact manifest image ids: only images that are dangling (tag already
# lost) or referenced exclusively by this scope's tags. Never a global prune and
# never an image another scope still references.
remove_manifest_images() {
  [ "$manifest_state" = "valid" ] || return 0
  local image_id seen=""
  for image_id in "${manifest_ids[@]}"; do
    [ -z "$image_id" ] && continue
    case " $seen " in *" $image_id "*) continue ;; esac
    seen="$seen $image_id"
    docker image inspect "$image_id" >/dev/null 2>&1 || continue
    if image_has_foreign_tag "$image_id"; then
      continue
    fi
    docker image rm "$image_id" >/dev/null 2>&1 || true
  done
}

cleanup_exact_resources() {
  if [ "$KEEP_POSTGRES" -eq 0 ]; then
    ids="$(docker ps -aq --filter "label=byq.ci.scope=$SCOPE")"
    if [ -n "$ids" ]; then
      # Docker IDs are whitespace-free daemon-generated identifiers.
      docker rm -f $ids >/dev/null 2>&1 || true
    fi
  else
    docker rm -f "$BACKEND" "$BACKEND_TEST" "$GATEWAY_TEST" "$RUNTIME_TEST" "$MCP_TEST" \
      "$MCP_SERVER" "$RUNTIME_CANDIDATE_TEST" \
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
  # With the exact tags gone, remove the exact captured ids (dangling residue).
  remove_manifest_images
  docker volume rm "$RUNTIME_CANDIDATE_VOL" "$RUNTIME_BASELINE_BENCH_VOL" \
    "$RUNTIME_CANDIDATE_BENCH_VOL" >/dev/null 2>&1 || true
  docker rm -f "$BACKEND" >/dev/null 2>&1 || true
  if [ "$KEEP_POSTGRES" -eq 0 ]; then
    docker rm -f "$PG" >/dev/null 2>&1 || true
    docker volume rm "$PG_VOL" >/dev/null 2>&1 || true
    docker network rm "$PG_NET" >/dev/null 2>&1 || true
  fi
}

scoped_resources_exist() {
  local service resource image_id
  for service in "${image_resources[@]}"; do
    docker image inspect "$PROJECT-$service" >/dev/null 2>&1 && return 0
  done
  if [ "$manifest_state" = "valid" ]; then
    for image_id in "${manifest_ids[@]}"; do
      [ -z "$image_id" ] && continue
      docker image inspect "$image_id" >/dev/null 2>&1 || continue
      image_has_foreign_tag "$image_id" || return 0
    done
  fi
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

load_manifest_ids || true   # invalid content is recorded, not fatal here

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
if [ "$manifest_state" = "invalid" ]; then
  echo "CI cleanup verification failed: invalid image-id manifest: $MANIFEST" >&2
  failures=$((failures + 1))
fi
for service in "${image_resources[@]}"; do
  if docker image inspect "$PROJECT-$service" >/dev/null 2>&1; then
    echo "CI cleanup verification failed: image tag remains: $PROJECT-$service" >&2
    failures=$((failures + 1))
  fi
done
if [ "$manifest_state" = "valid" ]; then
  for image_id in "${manifest_ids[@]}"; do
    [ -z "$image_id" ] && continue
    docker image inspect "$image_id" >/dev/null 2>&1 || continue
    if image_has_foreign_tag "$image_id"; then
      retained_shared_ids+=("$image_id")
      continue
    fi
    echo "CI cleanup verification failed: manifest image id remains: $image_id" >&2
    failures=$((failures + 1))
  done
fi
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
  if [ "$manifest_state" = "valid" ]; then
    echo "CI cleanup retained manifest for diagnostics: $MANIFEST" >&2
  fi
  exit 1
fi

# Exact-scope residue is gone; retire the manifest so it cannot be replayed.
if [ "$manifest_state" = "valid" ]; then
  rm -f "$MANIFEST"
fi
if [ "${#retained_shared_ids[@]}" -gt 0 ]; then
  printf 'CI cleanup retained shared image id(s) owned by another scope: %s\n' \
    "${retained_shared_ids[*]}"
fi
[ "$QUIET" -eq 1 ] || echo "CI cleanup verified: $SCOPE"
