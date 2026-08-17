# PostgreSQL Single Domain Store - Migration Plan

Status: Accepted implementation plan (ADR-0016). This document is the
engineering blueprint for moving BYQ domain persistence from SQLite to
PostgreSQL as a single engine, and for making later programming phases fast.

## 1. Current storage inventory

All domain stores open SQLite connections to the same file
(`BYQ_DOMAIN_DB_PATH`, default `/tmp/byq-domain.sqlite3`, production
`/var/lib/byq/domain/byq.sqlite3`). Each store owns its schema and queries.

| Store | Module | Tables |
|---|---|---|
| ResearchStore | `research.py` | `research_tasks`, `experiments`, `artifacts`, `research_transitions` |
| AgentResearchStore | `agent_research.py` | `agent_runs`, `agent_audit`, `agent_approvals` |
| LearningLoopStore | `learning_loop.py` | `learning_runs`, `learning_iterations`, `evaluation_signals`, `lessons`, `learning_history` |
| EngineeringTaskStore | `engineering.py` | `engineering_tasks`, `engineering_history` |
| PaperTradingStore | `paper_trading.py` | `paper_accounts`, `stock_pools`, `paper_positions`, `paper_orders`, `paper_fills` |
| UserAuthStore | `user_auth.py` | `users`, `auth_sessions` |
| UserPolicyStore | `user_policy.py` | `user_agent_policy` |
| BacktestJobStore | `backtest.py` | `backtest_jobs` |
| LocalObjectStore | `backtest.py` | filesystem under `BYQ_BACKTEST_OBJECT_ROOT` (unchanged) |

Connection pattern today: each store creates one `sqlite3.Connection` with
`check_same_thread=False`, a `threading.RLock`, and executes its own
`CREATE TABLE IF NOT EXISTS` DDL plus column migrations.

## 2. Target topology

```text
backend -> BYQ_DATABASE_URL (postgresql+psycopg://byq_app:***@postgres:5432/byq_domain)
postgres service (compose) with databases:
  byq_domain       - application (role byq_app)
  byq_domain_test  - automated tests (role byq_test)
  byq_bootstrap    - bootstrap/admin/migrations (role byq_bootstrap)
object store       - unchanged filesystem volume (byq_domain_state/backtest-objects)
```

## 3. Shared SQL layer contract (`services/backend/app/db.py`)

Single entry point used by every store:

- `engine = create_engine(BYQ_DATABASE_URL, pool_pre_ping=True)`
- `get_connection()` / `transaction()` context managers.
- `execute(conn, sql, params) -> list[Row]` with rows converted to `dict`.
- `fetch_one(conn, sql, params) -> dict | None`.
- `migrate_schema(engine, ddl: list[str])` idempotent bootstrap that creates
  tables and indexes (PostgreSQL `IF NOT EXISTS`).
- Optional `json` helpers because PostgreSQL uses `jsonb` for columns that
  were previously `TEXT` JSON (artifact content, manifests, provenance,
  symbols/weights).

Store refactor rule: keep the public store method names and return shapes
unchanged; only replace the SQL backend. All existing tests must pass without
rewriting assertions.

## 4. Environment matrix

| Environment | Database | Role | Notes |
|---|---|---|---|
| Local compose | `byq_domain` | `byq_app` | `docker compose up -d postgres backend ...` |
| CI stack job | `byq_domain_test` | `byq_test` | Postgres service container; backend tests run against it |
| CI frontend/architecture jobs | none | - | No DB needed |
| Bootstrap/admin | `byq_bootstrap` | `byq_bootstrap` | Scripted migration/admin only |

`BYQ_DATABASE_URL` replaces `BYQ_DOMAIN_DB_PATH` in compose/env; tests use
`BYQ_DATABASE_URL` pointing at `byq_domain_test`.

## 5. Store migration work items (one PR per store or grouped)

Order chosen to keep risk low and dependencies clear:

1. `db.py` + postgres compose service + bootstrap databases/roles + CI
   postgres service (foundation PR).
2. ResearchStore (largest, most-used).
3. UserAuthStore + UserPolicyStore (auth/policy, small).
4. PaperTradingStore + BacktestJobStore.
5. AgentResearchStore + LearningLoopStore + EngineeringTaskStore.
6. Remove SQLite code paths, drop `BYQ_DOMAIN_DB_PATH`, update
   compose/env/docs/tests.

Each work item must include:

- DDL translated to PostgreSQL (types: `BIGSERIAL`/`UUID`-style ids stay
  `TEXT` primary keys to avoid identity churn; `TIMESTAMPTZ` for times;
  `JSONB` for JSON columns; `BOOLEAN`; `NUMERIC` for money).
- Column migration parity with current SQLite `ALTER TABLE` behavior.
- Updated unit tests that run against `byq_domain_test`.
- No behavior change to public store methods.

## 6. Logical data migration from the existing SQLite volume

1. Read-only export: `sqlite3` dump of each table into canonical JSON/CSV
   files with schema/version metadata.
2. Validation: canonical ids, symbols, dates, finite numbers, JSON columns,
   owner/actor formats.
3. Manifest: per-table row counts, fingerprints, source file hashes.
4. PostgreSQL import: idempotent; conflicts use `KEEP_NEW`, `VERIFY_EQUAL`,
   `REPORT_MISMATCH` (never last-write-wins).
5. Verification: row counts and sample fingerprints match the manifest.

Tooling: a `services/backend/app/sqlite_export.py` and
`services/backend/app/pg_import.py` pair, plus `tests/` for the conflict
policy and idempotency.

## 7. Backup/restore and durable market data

- Backup: `pg_dump -Fc byq_domain`; restore drill: restore to a scratch
  database and verify counts/checksums before deleting.
- A real restore drill is a hard gate before executing ADR-0013 bulk import.
- Community PostgreSQL stays read-only evidence: `SELECT`/`COPY OUT` ->
  validation -> manifest -> BYQ import -> verification only.

## 8. Phase sequence for later coding phases

To keep later feature phases fast:

- Phase A (foundation): postgres service, `db.py`, databases/roles, CI
  wiring, migration of one representative store (ResearchStore) as the
  pattern.
- Phase B: remaining stores migrated using the Phase A pattern.
- Phase C: SQLite removal and environment/doc cleanup.
- Phase D: logical SQLite -> PostgreSQL data migration + verification.
- Phase E: backup/restore drill, then ADR-0013 market-data import.

Feature work must not start on top of mixed SQLite/PostgreSQL stores; land
Phase A+B before new domain features are built.
