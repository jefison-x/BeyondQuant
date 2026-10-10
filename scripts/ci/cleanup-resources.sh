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
export BYQ_CI_SCOPE="$SCOPE"
export COMPOSE_FILE="$REPO_ROOT/compose.yml:$REPO_ROOT/compose.override.yml"
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
export BYQ_ACP_JUDGMENT_NETWORK_NAME="$PROJECT-acp-judgment"
export BYQ_ACP_PRODUCT_SESSIONS_VOLUME_NAME="$PROJECT-acp-product-sessions"
export BYQ_ACP_PRODUCT_STATE_VOLUME_NAME="$PROJECT-acp-product-state"
export BYQ_ACP_PRODUCT_CONTROL_VOLUME_NAME="$PROJECT-acp-product-control"
export BYQ_ACP_JUDGMENT_SESSIONS_VOLUME_NAME="$PROJECT-acp-judgment-sessions"
export BYQ_ACP_RUNNER_CONTROL_VOLUME_NAME="$PROJECT-acp-runner-control"
export BYQ_ACP_RUNNER_STATE_VOLUME_NAME="$PROJECT-acp-runner-state"

image_service_list="$(PYTHONPATH="$REPO_ROOT/scripts/release:$REPO_ROOT" python3 -c \
  'import images; assert len(images.SERVICES) == 17 and len(set(images.SERVICES)) == 17; print("\n".join(images.SERVICES))')" || {
  echo "CI cleanup cannot load the canonical 17-service release set" >&2
  exit 2
}
mapfile -t image_resources <<< "$image_service_list"
# The captured-ID allowlist is the same canonical 17-service set used by the
# release exporter. Old isolated SDK candidate tags remain cleanup-only.
legacy_image_resources=(dsh runtime-candidate)
tag_resources=("${image_resources[@]}" "${legacy_image_resources[@]}")
network_resources=("$BYQ_PRODUCT_NETWORK_NAME" "$BYQ_SIGNAL_SANDBOX_NETWORK_NAME" \
  "$BYQ_ACP_JUDGMENT_NETWORK_NAME")
[ "$KEEP_POSTGRES" -eq 1 ] || network_resources+=("$PG_NET")
volume_resources=("$BYQ_POSTGRES_VOLUME_NAME" "$BYQ_DOMAIN_VOLUME_NAME" "$BYQ_ML_MODEL_VOLUME_NAME" \
  "$BYQ_DSH_SESSIONS_VOLUME_NAME" "$BYQ_WORKFLOW_TRACES_VOLUME_NAME" \
  "$BYQ_ACP_PRODUCT_SESSIONS_VOLUME_NAME" "$BYQ_ACP_PRODUCT_STATE_VOLUME_NAME" \
  "$BYQ_ACP_PRODUCT_CONTROL_VOLUME_NAME" \
  "$PROJECT-f6-acp-product-sessions" "$PROJECT-f6-acp-product-state" \
  "$PROJECT-f6-acp-product-control" "$BYQ_ACP_JUDGMENT_SESSIONS_VOLUME_NAME" \
  "$BYQ_ACP_RUNNER_CONTROL_VOLUME_NAME" "$BYQ_ACP_RUNNER_STATE_VOLUME_NAME" \
  "$RUNTIME_CANDIDATE_VOL" "$RUNTIME_BASELINE_BENCH_VOL" "$RUNTIME_CANDIDATE_BENCH_VOL")
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
  # Release scopes always run the one full trusted-main batch. Component CI
  # scopes may carry a smaller captured subset, but release cleanup rejects
  # both missing and additional service identities before deleting captured IDs.
  if [[ "$SCOPE" == *-release ]]; then
    if [ "${#manifest_services[@]}" -ne "${#image_resources[@]}" ]; then
      echo "CI cleanup release manifest is not the full canonical service set" >&2
      manifest_ids=(); manifest_state="invalid"; return 1
    fi
    for known in "${image_resources[@]}"; do
      seen=0
      for service in "${manifest_services[@]}"; do
        if [ "$service" = "$known" ]; then seen=1; break; fi
      done
      if [ "$seen" -ne 1 ]; then
        echo "CI cleanup release manifest is missing service '$known'" >&2
        manifest_ids=(); manifest_state="invalid"; return 1
      fi
    done
  fi
  return 0
}

# Tri-state classification of an image id's references. A query failure is NOT
# the same as a proven foreign reference, so the two must never collapse into
# one return code:
#   0 = a foreign/shared reference is PROVEN -> retaining is safe and successful
#   1 = references are readable and exclusive to this scope -> safe to delete
#   2 = metadata is UNREADABLE -> cannot prove exclusive -> retain AND fail
# RepoDigests are conservatively treated as shared references; only RepoTags
# have the exact project/service ownership check below.
image_has_foreign_reference() {
  local image_id="$1" tag digest service ours tags_output digests_output
  if ! docker image inspect "$image_id" >/dev/null 2>&1; then
    echo "CI cleanup cannot inspect image $image_id; retaining it" >&2
    return 2
  fi
  if ! tags_output="$(docker image inspect "$image_id" \
      --format '{{range .RepoTags}}{{println .}}{{end}}' 2>/dev/null)"; then
    echo "CI cleanup cannot read RepoTags for $image_id; retaining image" >&2
    return 2
  fi
  while IFS= read -r tag; do
    [ -z "$tag" ] && continue
    ours=0
    for service in "${tag_resources[@]}"; do
      if [ "$tag" = "$PROJECT-$service" ]; then ours=1; break; fi
    done
    [ "$ours" -eq 1 ] || return 0
  done <<< "$tags_output"
  if ! digests_output="$(docker image inspect "$image_id" \
      --format '{{range .RepoDigests}}{{println .}}{{end}}' 2>/dev/null)"; then
    echo "CI cleanup cannot read RepoDigests for $image_id; retaining image" >&2
    return 2
  fi
  while IFS= read -r digest; do
    [ -z "$digest" ] || return 0
  done <<< "$digests_output"
  return 1
}

# Capture the tri-state above into $image_reference_state without tripping
# `set -e` and without letting a bare `!`/`||` collapse state 2 into the success
# state 0. A query failure (2) must stay distinguishable at every call site.
image_reference_state=0
classify_image_reference() {
  image_reference_state=0
  image_has_foreign_reference "$1" || image_reference_state=$?
  return 0
}

# Tri-state presence probe for a captured manifest image id. The exit status of
# a plain `docker image inspect <id>` cannot distinguish a genuinely absent image
# from a daemon/query error, so a failed inspect is NEVER taken as proof of
# absence. It is cross-checked against the full, untruncated image listing:
#   0 = image PROVEN absent (listing succeeded and does not contain the exact id)
#   1 = image PROVEN present (plain inspect succeeded)
#   2 = presence UNKNOWN (any query failure, or inspect failed while the id is
#       still listed, so its references cannot be read)
# Only state 0 may be treated as "already gone". State 2 must be retained and
# must make verification fail; it is never absence and never a proven shared
# reference. The RepoTags/RepoDigests classification is a separate query inside
# image_has_foreign_reference whose failure is likewise state 2, so a failing
# second inspect can never be mistaken for a clean/deletable id.
image_presence_state=2
image_presence_probe() {
  local image_id="$1" listing listing_id
  if docker image inspect "$image_id" >/dev/null 2>&1; then
    image_presence_state=1
    return 0
  fi
  image_presence_state=2
  if ! listing="$(docker image ls --all --no-trunc --format '{{.ID}}' 2>/dev/null)"; then
    return 0
  fi
  while IFS= read -r listing_id; do
    if [ "$listing_id" = "$image_id" ]; then
      # inspect failed but the image is still listed: references are unreadable
      # -> UNKNOWN, never "absent".
      image_presence_state=2
      return 0
    fi
  done <<< "$listing"
  image_presence_state=0
  return 0
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
    # Only a proven-present id is a deletion candidate. A proven-absent id
    # (state 0) needs no action, and an unreadable presence query (state 2) must
    # retain the image; the verification pass below fails closed for state 2.
    image_presence_probe "$image_id"
    case "$image_presence_state" in
      1) ;;
      *) continue ;;
    esac
    classify_image_reference "$image_id"
    # Only a proven-exclusive id (state 1) may be removed. State 0 (proven
    # shared) and state 2 (unreadable metadata) both retain the image.
    case "$image_reference_state" in
      1) ;;
      *) continue ;;
    esac
    docker image rm "$image_id" >/dev/null 2>&1 || true
  done
}

resource_is_scope_owned() {
  local kind="$1" resource="$2" project_label scope_label
  project_label="$(docker "$kind" inspect "$resource" \
    --format '{{ index .Labels "com.docker.compose.project" }}' 2>/dev/null || true)"
  scope_label="$(docker "$kind" inspect "$resource" \
    --format '{{ index .Labels "byq.ci.scope" }}' 2>/dev/null || true)"
  [ "$project_label" = "$PROJECT" ] || [ "$scope_label" = "$SCOPE" ]
}

remove_scoped_resource() {
  local kind="$1" resource="$2"
  docker "$kind" inspect "$resource" >/dev/null 2>&1 || return 0
  resource_is_scope_owned "$kind" "$resource" || return 0
  docker "$kind" rm "$resource" >/dev/null 2>&1 || true
}

compose_down_best_effort() {
  # Use the same merged ACP Compose entry point as build/test CI when its
  # required application settings are available. Release cleanup runs in a
  # fresh job without those secrets, so the exact label/name cleanup below is
  # authoritative and must still run if Compose interpolation fails.
  (
    cd "$REPO_ROOT"
    python3 "$REPO_ROOT/scripts/dsh/acp_build.py" -- docker compose \
      -f "$REPO_ROOT/compose.yml" -f "$REPO_ROOT/compose.override.yml" \
      down --remove-orphans
  ) >/dev/null 2>&1 || true
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
  compose_down_best_effort
  # Compose may fail before it can resolve ACP configuration in the standalone
  # cleanup job. Remove only containers carrying this exact Compose project
  # label; no resource name/prefix scan or global prune is used.
  ids="$(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT")"
  if [ -n "$ids" ]; then
    docker rm -f $ids >/dev/null 2>&1 || true
  fi
  # Component-only runs never create Compose containers; remove their exact tags too.
  for service in "${tag_resources[@]}"; do
    docker image rm "$PROJECT-$service" >/dev/null 2>&1 || true
  done
  # With the exact tags gone, remove the exact captured ids (dangling residue).
  remove_manifest_images
  for resource in "${volume_resources[@]}"; do
    remove_scoped_resource volume "$resource"
  done
  for resource in "${network_resources[@]}"; do
    remove_scoped_resource network "$resource"
  done
  docker rm -f "$BACKEND" >/dev/null 2>&1 || true
  [ "$KEEP_POSTGRES" -eq 1 ] || docker rm -f "$PG" >/dev/null 2>&1 || true
}

scoped_resources_exist() {
  local service resource image_id
  for service in "${tag_resources[@]}"; do
    docker image inspect "$PROJECT-$service" >/dev/null 2>&1 && return 0
  done
  if [ "$manifest_state" = "valid" ]; then
    for image_id in "${manifest_ids[@]}"; do
      [ -z "$image_id" ] && continue
      image_presence_probe "$image_id"
      case "$image_presence_state" in
        0) continue ;;   # proven absent -> not scope residue, keep scanning
        2) return 0 ;;   # unknown presence -> cannot claim stable absence
      esac
      classify_image_reference "$image_id"
      # state 0 = proven shared -> not scope residue, keep scanning.
      # state 1 (exclusive) and state 2 (unreadable) both mean the id still
      # exists as residue and cleanup cannot claim stable absence.
      if [ "$image_reference_state" -eq 0 ]; then
        continue
      fi
      return 0
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
for service in "${tag_resources[@]}"; do
  if docker image inspect "$PROJECT-$service" >/dev/null 2>&1; then
    echo "CI cleanup verification failed: image tag remains: $PROJECT-$service" >&2
    failures=$((failures + 1))
  fi
done
if [ "$manifest_state" = "valid" ]; then
  for image_id in "${manifest_ids[@]}"; do
    [ -z "$image_id" ] && continue
    image_presence_probe "$image_id"
    case "$image_presence_state" in
      0) continue ;;   # proven absent: nothing to verify for this id
      2)
        # Presence itself is unknown: the id could not be proven absent OR
        # present. Retain the image AND the manifest and fail; never "verified".
        echo "CI cleanup verification failed: cannot determine presence of manifest image id: $image_id" >&2
        failures=$((failures + 1))
        continue
        ;;
    esac
    classify_image_reference "$image_id"
    case "$image_reference_state" in
      0)
        # Proven shared reference: safe retention, not a verification failure.
        retained_shared_ids+=("$image_id")
        continue
        ;;
      2)
        # Unreadable metadata: the id could not be proven exclusive. Retain the
        # image AND the manifest and fail verification; never report "verified".
        echo "CI cleanup verification failed: cannot read reference metadata for retained manifest image id: $image_id" >&2
        failures=$((failures + 1))
        continue
        ;;
      *)
        echo "CI cleanup verification failed: manifest image id remains: $image_id" >&2
        failures=$((failures + 1))
        ;;
    esac
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
