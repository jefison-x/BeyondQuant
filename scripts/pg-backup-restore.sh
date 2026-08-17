#!/usr/bin/env sh
# ADR-0016/ADR-0013 backup + restore drill for the BYQ domain PostgreSQL.
#
# Usage:
#   PGUSER=<superuser> ./scripts/pg-backup-restore.sh [database] [scratch]
#
# Behavior:
#   1. pg_dump -Fc the application database to a timestamped backup file.
#   2. Restore the dump into a scratch database.
#   3. Verify: per-table row counts AND canonical row content match the
#      source (each table dumped to deterministic text and byte-compared),
#      then drop the scratch database.
#   Exit 0 only when the drill verifies end-to-end.
set -eu

DATABASE="${1:-byq_domain}"
SCRATCH="${2:-byq_restore_drill}"
BACKUP_DIR="${BYQ_BACKUP_DIR:-/tmp/byq-backups}"
TIMESTAMP="$(date +%Y%m%dT%H%M%S)"
DUMP_FILE="${BACKUP_DIR}/${DATABASE}-${TIMESTAMP}.dump"

mkdir -p "${BACKUP_DIR}"

echo "== backup =="
pg_dump -Fc "${DATABASE}" -f "${DUMP_FILE}"
echo "  wrote ${DUMP_FILE} ($(stat -c%s "${DUMP_FILE}") bytes)"

echo "== create scratch database =="
psql -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS ${SCRATCH} WITH (FORCE);"
psql -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE ${SCRATCH};"

echo "== restore to scratch =="
pg_restore --no-owner --role="${PGUSER:-byq_app}" -d "${SCRATCH}" "${DUMP_FILE}"

echo "== verify row counts + content =="
fail=0
for db in "${DATABASE}" "${SCRATCH}"; do
  psql -d "${db}" -tAc \
    "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename" > "/tmp/${db}.tables"
done
if ! cmp -s "/tmp/${DATABASE}.tables" "/tmp/${SCRATCH}.tables"; then
  echo "  MISMATCH: table sets differ"
  fail=1
fi
for table in $(cat "/tmp/${DATABASE}.tables"); do
  psql -d "${DATABASE}" -tA -F '|' -c "SELECT * FROM public.${table} ORDER BY 1" > "/tmp/${DATABASE}.${table}.txt" || fail=1
  psql -d "${SCRATCH}" -tA -F '|' -c "SELECT * FROM public.${table} ORDER BY 1" > "/tmp/${SCRATCH}.${table}.txt" || fail=1
  if ! cmp -s "/tmp/${DATABASE}.${table}.txt" "/tmp/${SCRATCH}.${table}.txt"; then
    echo "  MISMATCH: table ${table} differs"
    fail=1
  fi
done
if [ "${fail}" -eq 1 ]; then
  echo "  drill FAILED"
  exit 1
fi
echo "  all tables match (counts + content) across ${DATABASE} -> ${SCRATCH}"

echo "== drop scratch database =="
psql -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS ${SCRATCH} WITH (FORCE);"

echo "== drill PASS =="
echo "  backup: ${DUMP_FILE}"
