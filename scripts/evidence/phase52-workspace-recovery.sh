#!/usr/bin/env bash
set -euo pipefail

RECOVERY_NETWORK="byq-phase52-recovery"
SOURCE_DB="byq-phase52-source-db"
RESTORED_DB="byq-phase52-restored-db"
LEGACY_DB="byq-phase52-legacy-db"
DATABASE_NAME="byq_phase52"
DATABASE_USER="byq_phase52"
DATABASE_PASSWORD="phase52-recovery-only"
BACKUP_PATH="${1:-/tmp/byq-phase52-workspace.dump}"
LEGACY_BACKUP_PATH="${2:-/tmp/byq-phase51-pre-contract.dump}"

cleanup() {
  docker rm -f "$SOURCE_DB" "$RESTORED_DB" "$LEGACY_DB" >/dev/null 2>&1 || true
  docker network rm "$RECOVERY_NETWORK" >/dev/null 2>&1 || true
}
trap cleanup EXIT
cleanup
docker network create "$RECOVERY_NETWORK" >/dev/null

start_postgres() {
  docker run -d --name "$1" --network "$RECOVERY_NETWORK" \
    -e POSTGRES_DB="$DATABASE_NAME" \
    -e POSTGRES_USER="$DATABASE_USER" \
    -e POSTGRES_PASSWORD="$DATABASE_PASSWORD" \
    postgres:16-alpine >/dev/null
  for _attempt in $(seq 1 30); do
    if docker exec "$1" pg_isready -h 127.0.0.1 -U "$DATABASE_USER" -d "$DATABASE_NAME" >/dev/null 2>&1; then
      return
    fi
    sleep 1
  done
  echo "PostgreSQL did not become ready: $1" >&2
  exit 1
}

database_url() {
  echo "postgresql+psycopg://${DATABASE_USER}:${DATABASE_PASSWORD}@${1}:5432/${DATABASE_NAME}"
}

initialize_backend() {
  docker run --rm --network "$RECOVERY_NETWORK" \
    -e BYQ_DATABASE_URL="$(database_url "$1")" \
    beyondquant-backend python -c 'from app import main; print("backend-schema-ready")'
}

start_postgres "$SOURCE_DB"
initialize_backend "$SOURCE_DB"
docker run --rm --network "$RECOVERY_NETWORK" \
  -e BYQ_DATABASE_URL="$(database_url "$SOURCE_DB")" \
  beyondquant-backend python -c 'from app.user_auth import UserAuthStore; from app.workspace_tenancy import WorkspaceTenancyStore; users=UserAuthStore(); user=users.create_user({"username":"phase52-recovery","password":"Phase52Recovery123","display_name":"Phase 52 Recovery"}, actor_role="admin"); workspaces=WorkspaceTenancyStore(); print(workspaces.public_workspace(str(user["user_id"]))["workspace_id"]); workspaces.close(); users.close()'
SOURCE_WORKSPACE="$(docker exec "$SOURCE_DB" psql -h 127.0.0.1 -U "$DATABASE_USER" -d "$DATABASE_NAME" -Atc "SELECT workspace_id FROM workspaces WHERE kind='personal'")"
test -n "$SOURCE_WORKSPACE"
docker exec "$SOURCE_DB" pg_dump -h 127.0.0.1 -U "$DATABASE_USER" -d "$DATABASE_NAME" -Fc -f /tmp/phase52.dump
docker cp "$SOURCE_DB":/tmp/phase52.dump "$BACKUP_PATH" >/dev/null

start_postgres "$RESTORED_DB"
docker cp "$BACKUP_PATH" "$RESTORED_DB":/tmp/phase52.dump >/dev/null
docker exec "$RESTORED_DB" pg_restore -h 127.0.0.1 -U "$DATABASE_USER" -d "$DATABASE_NAME" --clean --if-exists --no-owner /tmp/phase52.dump
initialize_backend "$RESTORED_DB"
docker run --rm --network "$RECOVERY_NETWORK" \
  -e BYQ_DATABASE_URL="$(database_url "$RESTORED_DB")" \
  beyondquant-backend python -m app.migrate_personal_workspaces --contract >/tmp/byq-phase52-restored-contract.json
RESTORED_WORKSPACE="$(docker exec "$RESTORED_DB" psql -h 127.0.0.1 -U "$DATABASE_USER" -d "$DATABASE_NAME" -Atc "SELECT workspace_id FROM workspaces WHERE kind='personal'")"
test "$RESTORED_WORKSPACE" = "$SOURCE_WORKSPACE"
docker restart "$RESTORED_DB" >/dev/null
for _attempt in $(seq 1 30); do
  if docker exec "$RESTORED_DB" pg_isready -h 127.0.0.1 -U "$DATABASE_USER" -d "$DATABASE_NAME" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
RESTARTED_WORKSPACE="$(docker exec "$RESTORED_DB" psql -h 127.0.0.1 -U "$DATABASE_USER" -d "$DATABASE_NAME" -Atc "SELECT workspace_id FROM workspaces WHERE kind='personal'")"
test "$RESTARTED_WORKSPACE" = "$SOURCE_WORKSPACE"

if test ! -f "$LEGACY_BACKUP_PATH"; then
  echo "Legacy-compatible backup is required: $LEGACY_BACKUP_PATH" >&2
  exit 1
fi
start_postgres "$LEGACY_DB"
docker cp "$LEGACY_BACKUP_PATH" "$LEGACY_DB":/tmp/legacy.dump >/dev/null
docker exec "$LEGACY_DB" pg_restore -h 127.0.0.1 -U "$DATABASE_USER" -d "$DATABASE_NAME" --clean --if-exists --no-owner /tmp/legacy.dump
initialize_backend "$LEGACY_DB"
docker run --rm --network "$RECOVERY_NETWORK" \
  -e BYQ_DATABASE_URL="$(database_url "$LEGACY_DB")" \
  beyondquant-backend python -m app.migrate_personal_workspaces --contract >/tmp/byq-phase52-forward-repair-contract.json
QUARANTINE_COUNT="$(docker exec "$LEGACY_DB" psql -h 127.0.0.1 -U "$DATABASE_USER" -d "$DATABASE_NAME" -Atc 'SELECT COUNT(*) FROM workspace_migration_quarantine')"
test "$QUARANTINE_COUNT" = "0"

echo "phase52 workspace recovery passed"
echo "workspace_id=$SOURCE_WORKSPACE"
echo "backup=$BACKUP_PATH"
echo "restored_contract=/tmp/byq-phase52-restored-contract.json"
echo "forward_repair_contract=/tmp/byq-phase52-forward-repair-contract.json"
echo "quarantine_count=$QUARANTINE_COUNT"
