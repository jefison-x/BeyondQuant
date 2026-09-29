# Phase 14 — Fresh database baseline and minimal seed

Status: local Tester → independent Sol Reviewer → Root gate PASS on
`codex/clean-break-phase14`. Phase 15 stays closed until the repository merge
gate passes.

## Boundary

The 0.10 database is created empty by this worktree's scoped PostgreSQL
service. Backend-owned Store DDL creates current BYQ domain tables; the
`dev-seed` command creates only new, synthetic development fixtures. The final
pre-Clean-Break database remains a read-only archive and is not mounted,
restored, or used as schema or row migration input.

Workspace identity, membership, reset receipts, business Jobs and Artifacts,
approval, paper financial facts, and exact business authorization remain
current domain state. Old-only generic Agent runtime state and one-time migration
quarantine/manifests do not become baseline tables. `ResearchTask` stage facts
that enforce current business admission stay with BYQ even when their names
mention Agent calls.

## Cutover

1. Remove old personal-Workspace backfill/quarantine schema, CLI and tests;
   retain live Workspace provisioning, tenant stamping and reset fencing.
2. Fold required paper trading account, order, ledger, stock-pool snapshot and
   audit columns into fresh DDL, then remove startup row migrations and their
   quarantine/manifest tables. Keep financial facts and their tests.
3. Retire other migration-only schema only after checking its current callers.
4. Run `dev-seed` on a scoped empty database twice. It must return the same
   Workspace, ResearchTask, strategy draft Artifact and synthetic dataset
   Artifact IDs without producing duplicate rows or old migration tables.

The sample dataset is labelled synthetic and is not a Tushare/Community import
or a substitute for Phase 15–16 market-data and Golden scenario evidence.
The full `dev-clean → dev-init → dev-start → dev-seed → dev-test` rebuild and
Golden scenarios remain Phase 15–16 acceptance work.

## Local evidence

- A fresh PostgreSQL 16 database on a disposable `tmpfs` volume was bootstrapped
  by the current Backend Store constructors. No archived database was used.
- The focused tenancy, paper trading, backtest and fresh-schema tests passed:
  **36 passed**. The schema test confirmed current domain and financial tables
  exist and six migration-only tables do not.
- The isolated `dev-seed` script ran twice against that freshly bootstrapped
  database. Both runs returned exactly the same Workspace, ResearchTask,
  strategy draft Artifact and synthetic dataset Artifact IDs.
- The one-off database containers and networks were removed by the test trap.

The development command tests passed 12/12, Clean Break governance validation
passed 2/2, and selected build/retirement/architecture tests passed 86/86.
The frozen `.269` and selected `.270` build identities both passed their checks.
Independent Sol review concluded Functional PASS / Tests PASS / Clean Break
Architecture PASS. Root accepts the bounded local Phase 14 gate as PASS.

Existing databases are not migration inputs and the new declarative schema is
supported only from an empty database. A boot-time `ALTER ... SET NOT NULL`/
unique-index proposal was rejected by automatic approval review because it
could fail against existing data; it was not applied.
