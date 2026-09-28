# Phase 11 — Business Job execution boundary

Status: backtest, admin import, and factor bounded slices local PASS; Phase 11 overall remains open. Base:
Phase 10 local PASS commit `ecc5bf74`. This is not a claim that full functional
fidelity has passed.

## Existing owner and first slice

Specialized BYQ stores remain authoritative; no generic workflow engine or
second job database is added. The first slice projects the existing BacktestJob
and ML TrainingRun into one small public `job_id/workspace_id/type/status/
progress/input_ref/result_ref/error/timestamps` shape. It preserves their
original stable IDs (`backtest_*`, `mlrun_*`) and native status in the existing
response. Missing numeric progress remains `null`, rather than invented.

Backtest submit persists a queued Job. An independent polling `backtest-worker`
now claims and computes it, writes the result object and Artifact, and commits
the terminal Job state. Backend `/run` only acknowledges its current state;
neither Backend requests nor Agent sessions execute the backtest. The worker
uses atomic claim and attempt-fenced completion/retry, conditional cancellation
and stale recovery, and stops exhausted attempts. Owner and workspace checks
apply to the backtest Job read/command routes. A new authorized Agent session
may query the same Job ID after the original session ends.

## First-slice evidence and Root gate

On a fresh disposable PostgreSQL database, five pure Job contract tests, the
backtest attempt/cancel/stale-recovery test, and the Backend API worker test
passed. The latter launched the Worker in its default polling mode without a
Job argument or Backend `/run` request, observed queued → running → completed,
stopped the Worker cleanly, and read the same result Artifact ID from a new
Agent session. It also checked owner/workspace isolation. Compose config,
local syntax and diff checks passed; the temporary database containers and
network were removed. Independent Tester: PASS. Independent Sol Reviewer:
Functional PASS / Tests PASS / Clean Break Architecture PASS. Root accepts this
slice as **local PASS**; Phase 11 overall remains OPEN.

## Admin data import slice and gate

`POST /v1/data-sync/jobs` now persists a queued admin sync Job only. The
existing Data Worker independently polls and claims it; the Backend request
does not perform the import. Claims are atomic, have bounded attempts and a
lease token, and resume from persisted per-symbol results. A worker with an
expired claim cannot write market rows or progress: each symbol import and its
checkpoint share one PostgreSQL transaction under the locked Job row. Each poll
also retires one expired Job whose attempts are exhausted, even while fresh
work remains queued. The public response does not expose worker or lease data.

This is a **global admin market-data sync**, not yet the workspace-scoped
`DataImportJob` and result Artifact described by ADR-003. That remaining
contract must be resolved before Phase 11 overall PASS.

Fresh disposable PostgreSQL evidence: `tests/test_data_sync.py` 23 passed,
including concurrent claims, expired provider calls, import/checkpoint
rollback, restart from saved symbols, exhausted polling, and queued API
submission. Syntax, `git diff --check`, and slice `dev-check` passed. The test
container/network were removed. Independent Tester: PASS. Independent Sol
Reviewer found and re-reviewed fixes for stale market import and exhausted
Job starvation; final Functional PASS / Tests PASS / Clean Break Architecture
PASS. Root accepts this bounded slice as **local PASS**. Hosted PR CI remains
pending; Phase 11 overall remains OPEN.

## Factor computation slice and gate

`byq_factor_compute` now validates point-in-time input and atomically queues a
workspace-scoped Factor Job under the existing Agent domain-call admission.
The independent `factor-worker` computes the bounded factor and commits its
validated `factor_result` Artifact and successful Job state in one PostgreSQL
transaction while holding the Job claim. An expired attempt rolls back both.
The Job has a stable ID and exact task/idempotency lookup, so a new authorized
Agent session can retrieve its status and result Artifact ID without restoring
the submitting session. MCP unknown-write handling points to that exact Job
lookup. Artifact completion verifies the original task, owner, workspace,
experiment, trace, input manifest and Worker result key. A ResearchTask cannot
complete while its Factor Job is queued or running.

Fresh disposable PostgreSQL focused rerun: 39 core tests and four factor
ownership cases passed. Tests cover input correction, normalized idempotency,
claim competition, expired attempts, result rollback, bounded retry, the
task-completion guard, Artifact binding and read from a new session. MCP
TypeScript build and focused factor/write-outcome tests, Compose config, syntax,
diff and slice dev-check passed. The database container/network were removed.
Independent Tester: PASS. Independent Sol Reviewer: Functional PASS / Tests
PASS / Clean Break Architecture PASS after re-review of the actual diff. Root
accepts this bounded slice as **local PASS**. The live MCP contract that needs
the full Adapter stack remains a later Product integration gate. Phase 11
overall remains OPEN.

## Remaining Phase 11 work

| Type | Current state | Remaining boundary work |
|---|---|---|
| Backtest | Durable store, Artifact and independent polling Worker; first slice locally accepted | Full Product/Golden qualification remains in Phases 15–16. |
| Training | Durable `ml_training_runs`, independent ML Worker and model Artifact | Complete common public projection exposure and verify worker restart/attempt behavior at this boundary. |
| Factor compute | Durable workspace-scoped Job, independent Worker and validated Artifact; bounded slice locally accepted | Full Product/Golden qualification remains in Phases 15–16. |
| Optimization | Proposal card only; no executable domain Job | Define a bounded deterministic optimization request/Job/Worker and result Artifact. Do not treat a proposal as completed work. |
| Data import | Scheduled market-session sync and admin range sync are worker-backed; admin slice locally accepted | Define the workspace-scoped DataImportJob and Artifact boundary from ADR-003; keep global admin sync clearly separate. |

These are domain Jobs, not Agent continuation state. They must remain queryable
by stable business ID after an Agent session disappears. Full new-schema Golden
Scenarios remain Phase 15–16 gates; the next Phase 11 slices use affected
Job/Worker contracts and disposable test state.
