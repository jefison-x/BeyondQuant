# ADR-0016: PostgreSQL as the Single BYQ Domain Store (Drop SQLite)

- Status: Accepted
- Date: 2026-08-17
- Decision scope: Data Plane domain persistence for BeyondQuant Next
- Related: ADR-0002, ADR-0006, ADR-0013, ADR-0015

## Context

BYQ domain state currently lives in a single-file SQLite database
(`BYQ_DOMAIN_DB_PATH`), shared by ResearchStore, AgentResearchStore,
LearningLoopStore, EngineeringTaskStore, PaperTradingStore, UserAuthStore,
UserPolicyStore, and BacktestJobStore. SQLite keeps development simple but
does not provide production-grade concurrency, role isolation, point-in-time
backup, or the durable market-data target that ADR-0013 already requires.
Maintaining two SQL engines (SQLite for dev/test, PostgreSQL for prod) would
duplicate connection and dialect code across every store.

## Decision

1. PostgreSQL becomes the single BYQ domain-store engine. SQLite is removed
   from the production and test code paths after migration.
2. Environments are isolated by PostgreSQL databases and roles:
   - `byq_domain` (application), `byq_domain_test` (automated tests),
     `byq_bootstrap` (admin/bootstrap migrations), each with a dedicated role.
   - No shared credentials; the backend connects with the application role.
3. Stores migrate to a single shared SQL layer (`services/backend/app/db.py`)
   built on SQLAlchemy Core + `psycopg`, so placeholders, row mapping,
   transactions, and migrations are consistent across stores.
4. The immutable object store (backtest results, bundles) remains a
   filesystem-backed object store behind the existing
   `LocalObjectStore` interface; large blobs are never stored in PostgreSQL.
5. Existing SQLite domain data is migrated logically and idempotently
   (read-only export -> validation -> manifest -> PostgreSQL import ->
   verification), with conflict policy `KEEP_NEW`, `VERIFY_EQUAL`,
   `REPORT_MISMATCH`.
6. Community PostgreSQL remains a read-only evidence source. It is never
   mounted, copied, or used as BYQ authoritative storage.
7. Backup/restore uses `pg_dump`/`pg_restore`; a real restore drill is
   required before the durable market-data import is executed (ADR-0013).
8. DSH, MCP, Gateway, and Product boundaries are unchanged: DSH never
   accesses PostgreSQL directly; domain access remains through BYQ Backend
   and BeyondQuant MCP.

## Consequences

- One connection/dialect path across app, tests, and deployment; future
  stores are faster to add.
- CI and local dev provision a PostgreSQL service (compose) with an isolated
  test database.
- Unit tests use the same store code against the test database; SQLite is no
  longer a supported backend.
- Production deployment requires a PostgreSQL service and tested
  backup/restore; the compose topology grows by one service.

## Rejected alternatives

- Keep SQLite for dev/test and PostgreSQL for production: duplicates
  connection/dialect code and lets dialect-specific bugs escape CI.
- Store all state, including result objects, in PostgreSQL: unbounded rows
  and violates the object-integrity boundary.
- Reuse Community PostgreSQL: violates ADR-0013 and read-only evidence rules.
