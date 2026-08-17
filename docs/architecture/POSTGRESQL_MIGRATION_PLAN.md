# PostgreSQL Single Domain Store - Migration Plan

Status: Accepted implementation plan (ADR-0016). This document is the
engineering blueprint for moving BYQ domain persistence from SQLite to
PostgreSQL as a single engine, and for making later programming phases fast.

## 1. Current storage inventory (verified against `main` @ 2026-08-17)

All eight domain stores open SQLite connections to the same file
(`BYQ_DOMAIN_DB_PATH`, default `/tmp/byq-domain.sqlite3`, production
`/var/lib/byq/domain/byq.sqlite3`). Each store owns its schema and queries;
there is no shared SQL layer in production code yet.

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

Common SQLite pattern today (identical in every store):

- `__init__(self, path: str | Path)` -> `sqlite3.connect(..., check_same_thread=False)`,
  `row_factory = sqlite3.Row`, `PRAGMA foreign_keys/busy_timeout`,
  `_create_schema()` with `CREATE TABLE IF NOT EXISTS` + `CREATE INDEX`.
- Positional `?` placeholders, tuples of params, `fetchone()/fetchall()`.
- Column back-migrations via `ALTER TABLE ... ADD COLUMN` in
  `try/except sqlite3.OperationalError` or `PRAGMA table_info` inspection.
- JSON stored as TEXT (`*_json` columns); stores `json.dumps` on write and
  `json.loads` on read; timestamps stored as ISO-8601 TEXT strings.
- `threading.RLock` per store; `close()` closes the connection.
- Constructed in `app/main.py` at module scope via `Store.from_env()`; the
  backtest worker (`workers/backtest/worker.py`) also calls `from_env()`.
- API tests monkeypatch `main.<store>` with per-test store instances.

### 1.1 Foundation already merged (do not redo)

- `compose.yml`: `postgres:16-alpine` service with `byq_domain` / `byq_app`;
  backend `depends_on: postgres: service_healthy`; backend env
  `BYQ_DATABASE_URL`.
- `services/backend/app/db.py`: SQLAlchemy Core + psycopg shared layer
  (`create_db_engine`, `connect`, `execute`, `fetch_one`, `run_ddl`,
  `bootstrap_research_schema`); dependencies `SQLAlchemy==2.0.40`,
  `psycopg[binary]==3.2.6`.
- `services/backend/tests/test_db.py`: PostgreSQL integration test (skips
  when `BYQ_DATABASE_URL` is unset).

### 1.2 Two traps found during inspection (must be fixed during migration)

1. `db.py`'s `RESEARCH_SCHEMA_DDL` is a design sketch and does **not** match
   the current `ResearchStore` contract:
   - `research_transitions` in `research.py` has composite PK
     `(entity_type, entity_id, idempotency_key)` plus `request_hash`,
     `target_status`, `result_json`; `db.py` instead defines
     `transition_id`/`owner_principal`/`from_status`/`to_status`/`created_at`.
   - `experiments` has `input_snapshot`; `db.py` omits it.
   - `artifacts`/`experiments` idempotency indexes are scoped
     `(task_id, idempotency_key)`; `db.py` scopes them
     `(owner_principal, idempotency_key)`.
   - Decision: each store owns its translated PG DDL (`SCHEMA_DDL` list +
     `bootstrap_schema()`), exactly matching the current SQLite contract.
     `db.py`'s sketch is replaced, not reused.
2. CI stack tests currently run inside the backend container with
   `BYQ_DATABASE_URL` defaulting to the **app** database `byq_domain`
   (`docker compose exec -T backend python -m pytest`). Once stores migrate,
   tests must be pinned to `byq_domain_test`; see Stage 1.

## 2. Target topology

```text
backend -> BYQ_DATABASE_URL (postgresql+psycopg://byq_app:***@postgres:5432/byq_domain)
postgres service (compose) with databases:
  byq_domain       - application (role byq_app)
  byq_domain_test  - automated tests (role byq_test)
  byq_bootstrap    - bootstrap/admin/migrations (role byq_bootstrap)
object store       - unchanged filesystem volume (byq_domain_state/backtest-objects)
```

`BYQ_DATABASE_URL` replaces `BYQ_DOMAIN_DB_PATH` in compose/env/docs/tests.
Community PostgreSQL stays read-only evidence; it is never mounted, copied,
or used as BYQ authoritative storage (ADR-0013, ADR-0016).

## 3. Shared SQL layer contract (`services/backend/app/db.py` v2)

Single entry point used by every store. Stage 1 extends the merged layer
with exactly these helpers (nothing more):

- Keep: `create_db_engine(url)` (`pool_pre_ping=True`), `connect(engine)`,
  `execute(conn, sql, params) -> list[dict]`, `fetch_one`, `run_ddl`.
- Add `transaction(engine)` context manager wrapping `engine.begin()`
  (commit on success, rollback on exception) for multi-statement writes.
- Row normalization inside `execute()` so stores keep their current return
  shapes:
  - `datetime` / `date` -> `isoformat()` strings (preserves string
    comparisons such as `session_expires_at < now` and API output);
  - `Decimal` -> `float` (money columns return JSON-safe numbers as today);
  - JSONB values already arrive as parsed `dict`/`list` (psycopg); keep them;
  - `bool` values pass through.
- Add `ensure_column(conn, table, column, definition)` issuing
  `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` for parity with the old
  try/except column back-migrations.
- Per-store contract: each store module defines
  `SCHEMA_DDL: list[str]` (its own PG DDL) and
  `bootstrap_schema(engine)` that runs `run_ddl` inside `engine.begin()`.
  `db.py` no longer owns store-specific DDL.
- Optional small `PgStoreMixin` (engine + lock + `_execute`/`_fetch_one`/
  `_fetch_all`/`_transaction` + `close()` + `from_env()`) to make the eight
  store rewrites mechanical. Do not build anything generic beyond this; the
  stores keep their own validation, transitions, and invariants.

## 4. Store migration contract (one pattern for all eight stores)

For each store, preserve the public method names, signatures, and return
shapes exactly; only the SQL backend changes. Concrete rules:

1. `__init__(self, database_url: str | None = None)`; `from_env()` reads
   `BYQ_DATABASE_URL` (no more `BYQ_DOMAIN_DB_PATH`); `close()` calls
   `engine.dispose()`.
2. Replace `?` placeholders with named `:param` bindings and tuples with
   dicts.
3. DDL translation table:

   | SQLite | PostgreSQL |
   |---|---|
   | `TEXT PRIMARY KEY` ids | `TEXT PRIMARY KEY` (no identity churn) |
   | `TEXT` timestamps | `TIMESTAMPTZ` (ISO strings in/out) |
   | `*_json TEXT` | `JSONB` (Python objects in/out; `'{}'::jsonb` defaults) |
   | `REAL` money/price/cash/fees | `NUMERIC(18,4)` (float on read) |
   | `REAL` metrics/limits | `DOUBLE PRECISION` |
   | `INTEGER` counters/version/sequence/attempts | `INTEGER` |
   | `INTEGER` 0/1 flags (`automation_enabled`, `paused`, `self_review`) | `BOOLEAN` (cast int on write) |
   | unique indexes | `CREATE UNIQUE INDEX IF NOT EXISTS` (same columns) |
   | FK constraints | same `REFERENCES`; insert order already compliant |

4. JSON columns: pass the Python object on INSERT/UPDATE (do **not**
   `json.dumps` into JSONB); reads already return objects, so drop the
   `json.loads` at row-mapper sites (keep a tolerant helper if desired).
5. Timestamps: continue writing `datetime.now(timezone.utc).isoformat()`;
   PG casts text -> timestamptz; normalization returns identical ISO text,
   so string comparisons and API output stay byte-for-byte compatible.
6. Column back-migrations become `ensure_column(...)` /
   `ADD COLUMN IF NOT EXISTS` (e.g. `users.preferences/default_prompt`,
   `stock_pools.pool_type/description/weights_json`,
   `research_transitions.result_json`).
7. Transactions: single statements via `_execute` (auto-commit); atomic
   multi-statement flows (e.g. `disable_user`, order submission) via
   `_transaction()`.

## 5. Test and CI strategy (Stage 1, before store rewrites land)

### 5.1 Per-test isolation (parity with today's per-test SQLite file)

All store/API tests share one test database, so add
`services/backend/tests/conftest.py`:

- Guard: require `BYQ_DATABASE_URL`; refuse any URL whose database name is
  not `byq_domain_test` (prevents accidental writes to the app DB).
  Tests skip with a clear message when unset (same spirit as `test_db.py`).
- Autouse fixture per test:
  1. open one AUTOCOMMIT connection,
  2. `DROP SCHEMA public CASCADE`,
  3. `CREATE SCHEMA public`,
  4. run every registered store `SCHEMA_DDL` (imported explicitly in
     conftest; grows as stores migrate).
- API tests keep `monkeypatch.setattr(main, "<store>", Store())`; module
  scope stores in `main.py` keep working because conftest re-creates all
  tables before each test.
- Store-level tests change `Store(tmp_path / "x.sqlite3")` to `Store()`.
  `LearningLoopStore` keeps its `(research_store)` constructor dependency.

### 5.2 Compose init script (idempotent)

Mount `infra/postgres/init/10-byq-databases.sql` into the postgres service:

```sql
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'byq_test') THEN
    CREATE ROLE byq_test LOGIN PASSWORD 'byq-test-dev';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'byq_bootstrap') THEN
    CREATE ROLE byq_bootstrap LOGIN PASSWORD 'byq-bootstrap-dev';
  END IF;
END $$;
SELECT 'CREATE DATABASE byq_domain_test OWNER byq_test'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'byq_domain_test')\gexec
SELECT 'CREATE DATABASE byq_bootstrap OWNER byq_bootstrap'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'byq_bootstrap')\gexec
```

(Compose's `POSTGRES_DB/POSTGRES_USER/POSTGRES_PASSWORD` already create
`byq_domain`/`byq_app`. `CREATE DATABASE` cannot run inside a transaction
block, hence `\gexec`.)

### 5.3 CI stack job

Change the backend pytest step to the isolated test database:

```yaml
- name: Backend tests
  run: >-
    docker compose exec -T
    -e BYQ_DATABASE_URL=postgresql+psycopg://byq_test:byq-test-dev@postgres:5432/byq_domain_test
    backend python -m pytest -q -p no:cacheprovider
```

## 6. Stage checklist (one PR per stage; stop at the human merge gate)

Order chosen so each stage is small, CI-green, and later stages are copy-paste
of the previous pattern.

### Stage 0 - Foundation (MERGED)

`postgres` service, `BYQ_DATABASE_URL`, `db.py` v1, `test_db.py`. No store
migration yet.

### Stage 1 - Harness + UserAuthStore + UserPolicyStore

Why first: smallest stores, one JSON-adjacent text column, one BOOLEAN
upsert, one FK (sessions -> users), and the column back-migration pattern.

Files:

- `services/backend/app/db.py` (v2 helpers from section 3)
- `services/backend/app/user_auth.py`, `services/backend/app/user_policy.py`
- `services/backend/tests/conftest.py`, `test_user_auth.py`,
  `test_user_policy.py`, `test_db.py` (no longer skips)
- `infra/postgres/init/10-byq-databases.sql`, `compose.yml` (mount init
  script), `.github/workflows/ci.yml` (test URL override)

Acceptance:

- `users`, `auth_sessions`, `user_agent_policy` on PG; all user_auth/policy
  tests and API tests pass against `byq_domain_test`.
- Conftest guard refuses non-test URLs.
- `BYQ_DOMAIN_DB_PATH` still present in compose (architecture test 204 still
  passes); it is removed only in Stage 6.

### Stage 2 - PaperTradingStore + BacktestJobStore

Why next: money (`NUMERIC`), JSONB (`symbols/weights/provenance/request/
manifest/summary`), `ON CONFLICT ... DO UPDATE`, FK-free tables.

Files: `paper_trading.py`, `backtest.py` (job store only; `LocalObjectStore`
untouched), `test_paper_trading.py`, `test_backtest.py`, `test_paper_api.py`,
`test_backtest_api.py`.

Acceptance: all paper/backtest tests pass; `LocalObjectStore` still
filesystem-backed; worker binary path (`BacktestJobStore.from_env()`) works
against `BYQ_DATABASE_URL`.

### Stage 3 - AgentResearchStore + LearningLoopStore + EngineeringTaskStore

Why next: mid-size stores; FKs (`agent_audit`, `agent_approvals`,
`learning_iterations`, `engineering_history`), JSONB-heavy rows
(`detail_json`, `budget/stopping_rules/lineage/feedback/source_refs/
result_refs/content/evidence/validation`), `BOOLEAN` (`self_review`).

Files: `agent_research.py`, `learning_loop.py`, `engineering.py` + their
tests + API tests.

Acceptance: all three store suites and API tests pass; `LearningLoopStore`
still receives a `ResearchStore` (which may still be SQLite until Stage 4 -
the two stores do not share SQL).

### Stage 4 - ResearchStore + db.py DDL contract fix

Why last: largest and most-used; also the only store whose DDL exists as a
(sketchy) reference in `db.py`.

Files: `research.py`, `db.py` (replace `RESEARCH_SCHEMA_DDL` with the real
translated contract per section 1.2), `test_research.py`,
`test_research_api.py`, `test_learning_loop.py` (cross-store flows),
`workers/backtest/worker.py` (already `from_env()`; verify no SQLite path).

Acceptance: ResearchStore fully on PG with the exact current schema
(`input_snapshot`, content-addressed artifacts, composite transition PK);
all tests green.

### Stage 5 - Logical SQLite -> PostgreSQL data migration

Files (new): `services/backend/app/sqlite_export.py`,
`services/backend/app/pg_import.py`, `services/backend/app/migrate_sqlite_to_pg.py`
(CLI), `services/backend/tests/test_sqlite_export.py`,
`services/backend/tests/test_pg_import.py`, ops runbook
`docs/operations/postgres-migration-runbook.md`.

Pipeline (repeatable, idempotent):

1. Read-only export: open the SQLite file `file:...?mode=ro`, dump every
   domain table to canonical JSONL + schema/version metadata.
2. Validate: ids, symbols, dates, finite numbers, JSON columns, owner/actor
   formats (reuse store validators where possible).
3. Manifest: per-table row counts, fingerprints, source file hashes.
4. Import into PG: idempotent; conflict policy `KEEP_NEW`,
   `VERIFY_EQUAL`, `REPORT_MISMATCH` (never last-write-wins).
5. Verify: row counts and sample fingerprints match the manifest.

The export step must run against the pre-cleanup SQLite volume
(`byq_domain_state`) before Stage 6 removes the code paths.

### Stage 6 - SQLite removal and cleanup

Files: `compose.yml` (drop `BYQ_DOMAIN_DB_PATH`, keep
`BYQ_DATABASE_URL` and the `byq_domain_state` object-store volume),
`workers/backtest/README.md`, `docs/**`, `.env.example` (already clean),
`tests/architecture/test_architecture.py` (assert `BYQ_DATABASE_URL` in
backend, assert no `BYQ_DOMAIN_DB_PATH` anywhere outside migration docs).

Gate: `rg -n "BYQ_DOMAIN_DB_PATH|sqlite3|import sqlite" services compose.yml
workers docs/roadmap docs/architecture docs/DEVELOPMENT_WORKFLOW.md` returns
only historical/reference mentions (migration runbook, Community inventory).

### Stage 7 - Backup/restore drill + ADR-0013 durable market-data import

- Add `scripts/pg-backup-restore.sh`: `pg_dump -Fc byq_domain`, restore to a
  scratch database, verify counts/checksums, drop scratch.
- A real restore drill is a hard gate before executing ADR-0013 bulk import.
- Then implement ADR-0013 logical Community market-data migration
  (read-only `COPY OUT`/`SELECT` -> validate -> manifest -> BYQ import ->
  verify), reusing the Stage 5 conflict policy. BaoStock/AKShare/VectorBT
  remain DROP (rules 23-25, 33).

## 7. Store-by-store DDL checklist (translate, do not copy SQLite DDL)

- `users`: `username UNIQUE`; add `preferences`, `default_prompt` via
  `ADD COLUMN IF NOT EXISTS`.
- `auth_sessions`: FK `user_id -> users`; index `(user_id, expires_at)`.
- `user_agent_policy`: PK `owner_principal`; `BOOLEAN` flags;
  `ON CONFLICT (owner_principal) DO UPDATE`.
- `paper_accounts`: unique `(owner_principal, name)`; `cash NUMERIC(18,4)`.
- `stock_pools`: `symbols_json/weights_json/provenance_json JSONB`;
  `ADD COLUMN IF NOT EXISTS pool_type/description/weights_json`.
- `paper_positions`: PK `(account_id, symbol)`; upsert
  `ON CONFLICT (account_id, symbol) DO UPDATE`.
- `paper_orders`: unique `(account_id, idempotency_key)`; money NUMERIC.
- `paper_fills`: money NUMERIC; index `(account_id, created_at)`.
- `backtest_jobs`: unique `(task_id, idempotency_key)`;
  `request_json/input_manifest_json/result_reference_json/summary_json JSONB`.
- `agent_runs`: unique `(owner_principal, idempotency_key)`.
- `agent_audit`: FK `run_id`; `detail_json JSONB`; index `(run_id, created_at, audit_id)`.
- `agent_approvals`: FK `run_id`; unique `(run_id, idempotency_key)`.
- `learning_runs`: unique `(owner_principal, idempotency_key)`; three JSONB.
- `learning_iterations`: FK; unique `(learning_run_id, idempotency_key)`;
  unique `(learning_run_id, sequence)`; three JSONB.
- `evaluation_signals`: unique `(task_id, idempotency_key)`; `value DOUBLE PRECISION`.
- `lessons`: unique `(task_id, idempotency_key)`; three JSONB.
- `learning_history`: index `(entity_type, entity_id, created_at, history_id)`.
- `engineering_tasks`: unique `(owner_principal, idempotency_key)`;
  `self_review BOOLEAN`; `architecture_evidence_json JSONB DEFAULT '{}'::jsonb`.
- `engineering_history`: FK; index `(task_id, created_at, history_id)`.
- `research_tasks`: unique `(owner_principal, idempotency_key)`.
- `experiments`: FK `task_id`; unique `(task_id, idempotency_key)`;
  `input_snapshot JSONB`.
- `artifacts`: FK `task_id`, nullable FK `experiment_id`; unique
  `(task_id, idempotency_key)`; `content/lineage JSONB`; index `(kind)`.
- `research_transitions`: composite PK `(entity_type, entity_id,
  idempotency_key)`; `request_hash`, `target_status`, `result_json JSONB
  DEFAULT '{}'::jsonb`.

## 8. Known traps and gates

- Do not reuse `db.py`'s `RESEARCH_SCHEMA_DDL` as-is (section 1.2).
- Keep `BYQ_DOMAIN_DB_PATH` in compose until Stage 6, or architecture test
  `test_phase9_domain_state_is_backend_owned_and_mcp_only` fails; update the
  test in the same PR that removes the variable.
- CI tests must target `byq_domain_test`; a test URL guard prevents
  accidental app-DB writes (conftest).
- JSONB: never `json.dumps` into a JSONB column; never feed a JSONB read
  into `json.loads` without a tolerant helper.
- Timestamps: keep ISO text in/out; normalization must be applied centrally
  so string comparisons and API JSON stay unchanged.
- Money: `NUMERIC` read as `Decimal`; central normalization to `float`
  preserves current API/test behavior.
- FK enforcement is on in PG: keep insert order (parents before children)
  and revisit any delete flow that relied on SQLite's lax FK handling.
- `CREATE DATABASE` must run outside a transaction (init script `\gexec`).
- Community PostgreSQL is read-only evidence; `pg_dump`/restore drill and
  ADR-0013 import must never touch it.
- Large blobs (backtest results, bundles) stay in `LocalObjectStore`;
  PostgreSQL stores references only.
- Release gate: at BeyondQuant Next v1.0, disable auto-merge and restore the
  single-maintainer human merge gate (ADR-0015).

## 9. Phase 31 definition of done

- All backend tests run against `byq_domain_test`; conftest guard in place.
- No SQLite code path remains (`rg` gate passes); `BYQ_DOMAIN_DB_PATH` gone
  from compose/env/docs (except migration runbook references).
- All eight stores on PostgreSQL via `db.py`; public method shapes unchanged.
- Logical SQLite -> PG migration executed, idempotent, verified against a
  manifest (real export/import for the existing dev volume).
- `pg_dump`/`pg_restore` drill passed; scratch restore verified.
- Architecture tests, CI, and compose updated; ADR-0016 acceptance evidence
  recorded in the phase PR.
