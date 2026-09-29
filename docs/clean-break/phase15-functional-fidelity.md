# Phase 15 — Functional fidelity on fresh state

Status: **OPEN** on `codex/clean-break-phase15`, based on Phase 14 merge
`e9c944951465fbdeae4d05cd7bb0358b32f8a041`. This is an initial evidence
inventory, not the Phase 15 acceptance record. Phase 16 stays closed.

## Fresh-state foundation (2026-09-29)

- `make dev-init` created scoped project `byq-dev-ea551690f4` in this isolated
  worktree. `make dev-clean` preview found no pre-existing project resources.
- `make dev-start DEV_PROFILE=core` built and started PostgreSQL, Backend, Product
  MCP, Runtime Adapter and Gateway; all five became healthy.
- `make dev-seed` created a new Workspace, ResearchTask and two synthetic
  Artifacts. `make dev-test` passed its 2 governance and 12 development-command
  tests. It explicitly does **not** run Golden scenarios.
- A real Gateway `/api/auth/login` request with this project's generated admin
  credential returned HTTP 200. `/api/auth/me` returned HTTP 200 and the same
  Workspace ID. Neither credential nor session cookie was logged.

The project contains only newly generated development data. The archived old
database was not mounted or imported. This proves the core boot/login/seed
foundation, not a market-research or Agent journey.

## Function inventory

| Journey | Current evidence | Phase 15 gap |
|---|---|---|
| A: Research, TuShare, Web Search, delegated Agent, interaction, Artifact | Historical credentialed Web Search/Product API and browser conversation tests; component TuShare tests | Re-run one connected Product journey from this new Workspace with qualified data/search credentials and persisted Artifact/normalized trace. Historical restored-database evidence is insufficient. The DSH Interaction plugin remains separately unqualified; ordinary Product follow-up is the available interaction path. |
| B: two Backtests, optimization, comparison | Existing Product API/browser single-Backtest and scripted F6 two-Backtest evidence; Backend OptimizationJob/Worker integration | Complete two real worker Jobs plus an OptimizationJob and comparison Artifact in one fresh Product journey, with a Product-visible result. |
| C: TrainingJob, GPU, checkpoint/restart | Durable TrainingJob and independent ML Worker; process-reclaim tests use a fake trainer | Qualify a real GPU Worker and partial-training checkpoint/restart. CPU execution and simulated lease reclaim do not satisfy this claim. |
| D: Agent interruption with Job continuing | Stable Job IDs and owner-scoped reads exist; Backend process recovery test | End a real DSH session while a Job runs, then query the same Job from a new authorized session without duplicate execution. DSH process restart is out of scope. |
| E: Runtime and Workspace reset | Phase 13 disposable-DB tests and one recorded real browser reset flow | On this fresh state, generate domain data, reset, verify protected global state and rerun A after seeding. |
| F: full rebuild | Core init/start/seed/test and dry-run cleanup succeeded here | Run scoped `dev-clean` apply, then init/start/seed/test and the connected Golden journeys. The current `dev-test` alone is offline. |

## Next bounded execution

1. Qualify the full profile and available external credentials/hardware without
   exposing secrets. Run the fresh Workspace Product research and Backtest
   paths through Gateway/DSH/MCP, recording stable Job and Artifact IDs.
2. Fix only concrete failing Product boundaries found by those journeys; keep
   DSH as sole harness and long computation in Workers.
3. Exercise TrainingJob, session interruption, reset and scoped rebuild. Mark
   unavailable qualified dependencies `NOT_RUN` with an exact reason, never
   `PASS` by substitution with mocks or old database evidence.
4. Finish Tester → independent Sol Reviewer → Root review, then PR/CI/merge
   before Phase 16.
