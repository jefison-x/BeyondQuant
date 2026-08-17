# PostgreSQL Single Domain Store — SQLite Migration Runbook (ADR-0016)

This runbook migrates the existing SQLite domain database
(`BYQ_DOMAIN_DB_PATH`, default `/tmp/byq-domain.sqlite3`, production
`/var/lib/byq/domain/byq.sqlite3`) into the PostgreSQL domain store
(`BYQ_DATABASE_URL`). The migration is **logical, idempotent, and repeatable**;
the SQLite file is only ever read (`mode=ro`) and is never modified.

## Pipeline

```text
read-only SQLite export
  -> validation + quarantine (invalid rows are reported, never repaired)
  -> deterministic manifest (row counts + fingerprints + source SHA-256)
  -> idempotent PostgreSQL import (conflict policy, never last-write-wins)
  -> post-import verification against the manifest
```

## 1. Prerequisites

- A running PostgreSQL with the ADR-0016 databases/roles
  (`byq_domain` / `byq_app`, created by compose + the init script).
- The `migrate_sqlite_to_pg` CLI available in the backend image
  (`services/backend/app/migrate_sqlite_to_pg.py`).
- Stop application writes to the SQLite file during the migration
  (the export is read-only, but a stable snapshot avoids TOCTOU drift).

## 2. Dry run (no writes to PostgreSQL)

```bash
BYQ_DATABASE_URL=postgresql+psycopg://byq_app:***@postgres:5432/byq_domain \
  python -m app.migrate_sqlite_to_pg \
  --sqlite-path /var/lib/byq/domain/byq.sqlite3 \
  --dry-run
```

The dry run exports, validates, quarantines, and prints the manifest without
importing. Review `quarantined_tables` — any invalid rows there will be skipped
on import and reported.

## 3. Real import

```bash
BYQ_DATABASE_URL=postgresql+psycopg://byq_app:***@postgres:5432/byq_domain \
  python -m app.migrate_sqlite_to_pg \
  --sqlite-path /var/lib/byq/domain/byq.sqlite3 \
  --conflict-policy KEEP_NEW \
  --quarantine-path /tmp/byq-migration-quarantine.json
```

Conflict policy (never overwrites existing PostgreSQL rows):

| Policy | Behavior |
|---|---|
| `KEEP_NEW` | Existing PG row wins silently (default for migration). |
| `VERIFY_EQUAL` | Existing row kept; a content mismatch is reported. |
| `REPORT_MISMATCH` | Every PK collision is reported. |

The command exits `0` only when every table verifies (row count +
fingerprint) against the manifest.

## 4. Verification

Re-run verification on demand:

```python
from app.db import create_db_engine
from app.migrate_sqlite_to_pg import migrate
report = migrate("/var/lib/byq/domain/byq.sqlite3", create_db_engine(), conflict_policy="KEEP_NEW")
assert report["verified"]
```

Inspect `report["verification"][table]["ok"]` and `["fingerprint_matches"]`.

## 5. Rollback / re-run

- The import is idempotent: re-running the same command converges to the same
  rows (`KEEP_NEW`). No duplicate rows are created.
- The SQLite file is untouched, so a rollback is simply "continue using the
  SQLite file" until the application switch-over (Stage 6).
- PostgreSQL backup/restore for rollback of the target is covered by the
  Stage 7 `pg_dump`/`pg_restore` drill.

## 6. Notes

- Community PostgreSQL remains read-only evidence and is never a migration
  source or target (ADR-0013, ADR-0016).
- Large blobs (backtest results, bundles) stay in `LocalObjectStore`
  (filesystem); only references are migrated in domain rows.
