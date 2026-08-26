# PostgreSQL Single Domain Store — SQLite Migration Runbook（ADR-0016）

本 runbook 将现有 SQLite domain database（`BYQ_DOMAIN_DB_PATH`，默认
`/tmp/byq-domain.sqlite3`，production `/var/lib/byq/domain/byq.sqlite3`）
迁移到 PostgreSQL domain store（`BYQ_DATABASE_URL`）。Migration 是
**logical、idempotent、repeatable**；SQLite file 始终以 `mode=ro` 只读，
绝不修改。

## Pipeline

```text
read-only SQLite export
  -> validation + quarantine（invalid rows 只报告，不修复）
  -> deterministic manifest（row counts + fingerprints + source SHA-256）
  -> idempotent PostgreSQL import（conflict policy，绝不 last-write-wins）
  -> 按 manifest 执行 post-import verification
```

## 1. Prerequisites

- 运行中的 PostgreSQL，具 ADR-0016 databases/roles（`byq_domain` /
  `byq_app`，由 Compose/init script 创建）。
- Backend image 中可用 `migrate_sqlite_to_pg` CLI
  （`services/backend/app/migrate_sqlite_to_pg.py`）。
- Migration 期间停止对 SQLite file 的 application writes；export 虽只读，
  但 stable snapshot 可避免 TOCTOU drift。

## 2. Dry run（不写 PostgreSQL）

```bash
BYQ_DATABASE_URL=postgresql+psycopg://byq_app:***@postgres:5432/byq_domain \
  python -m app.migrate_sqlite_to_pg \
  --sqlite-path /var/lib/byq/domain/byq.sqlite3 \
  --dry-run
```

Dry run 执行 export、validate、quarantine 并打印 manifest，不 import。必须检查
`quarantined_tables`；其中 invalid rows 会在 import 时跳过并报告。

## 3. Real import

```bash
BYQ_DATABASE_URL=postgresql+psycopg://byq_app:***@postgres:5432/byq_domain \
  python -m app.migrate_sqlite_to_pg \
  --sqlite-path /var/lib/byq/domain/byq.sqlite3 \
  --conflict-policy KEEP_NEW \
  --quarantine-path /tmp/byq-migration-quarantine.json
```

Conflict policy 永不覆盖 existing PG rows：

| Policy | Behavior |
|---|---|
| `KEEP_NEW` | Existing PG row 保留（migration 默认）。 |
| `VERIFY_EQUAL` | 保留 existing row；content mismatch 要报告。 |
| `REPORT_MISMATCH` | 报告每个 PK collision。 |

只有每个 table 的 row count/fingerprint 都通过 manifest verification，命令才
exit `0`。

## 4. Verification

```python
from app.db import create_db_engine
from app.migrate_sqlite_to_pg import migrate
report = migrate("/var/lib/byq/domain/byq.sqlite3", create_db_engine(), conflict_policy="KEEP_NEW")
assert report["verified"]
```

检查 `report["verification"][table]["ok"]` 和
`["fingerprint_matches"]`。

## 5. Rollback / re-run

- Import 幂等；以 `KEEP_NEW` 重跑会收敛到相同 rows，不产生 duplicates。
- SQLite file 未改变，因此 Stage 6 switch-over 前，rollback 可继续使用它。
- Target rollback 使用 Stage 7 `pg_dump`/`pg_restore` drill。

## 6. Notes

- Community PostgreSQL 始终是 read-only evidence，既不是此 migration source
  也不是 target（ADR-0013、ADR-0016）。
- Large blobs（backtest results、bundles）留在 filesystem
  `LocalObjectStore`；domain rows 只迁移 references。
