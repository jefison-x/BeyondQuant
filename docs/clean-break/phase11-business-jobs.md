# Phase 11 — Business Job execution boundary

Status: **Phase 11 local PASS**. Backtest, training, factor, optimization and
workspace data-import Job boundaries passed their bounded gates. Base:
Phase 10 local PASS commit `ecc5bf74`. This is not a claim that full functional
fidelity has passed.

For the repository PR gate, the Phase 11 commits were replayed onto the Phase 10
merged `main` baseline. The local slice evidence below records the original
isolated checks; hosted CI and PR review apply to the replayed head.

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

This is a **global admin market-data sync**, separate from the workspace-scoped
`DataImportJob` and result Artifact described below.

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

## Training boundary qualification

The existing `ml_training_runs` store, independently started ML Worker, and
validated feature/model Artifacts satisfy the specialized TrainingJob ownership
boundary. On a fresh disposable PostgreSQL database, the focused training and
API tests passed (2/2): they covered durable store reopen, retry and stale
attempt fencing, Artifact creation, and a stable workspace-scoped common Job
read projection. The temporary database and network were removed. Independent
Tester: PASS. Independent Sol Reviewer: Functional PASS / Tests PASS / Clean
Break Architecture PASS **for this bounded qualification**. Root accepts that
qualification as local PASS; Phase 11 overall remains OPEN.

The common Job contract is now returned on submission, cancellation and
reconciliation. While data preparation is pending, `submission_ref` identifies
the frozen request; once available, the feature snapshot hash becomes the
input reference. The two focused Training tests passed again in the combined
fresh PostgreSQL rerun. A separate-process lifecycle test then killed a
Coordinator process after it claimed the Job, expired its persisted lease, and
completed the same TrainingRun on attempt two in a new process. A new trusted
Agent session read the stable Job ID, validated model Artifact, and object
bytes through the Backend API. The focused test passed on disposable PostgreSQL
(1 passed; Docker test container exit 0); the outer test wrapper returned 1
for an undetermined reason after pytest and cleanup had succeeded. Independent
Tester: PASS. Independent Sol Reviewer: Functional PASS / Tests PASS / Clean
Break Architecture PASS. Root accepts this bounded process-reclaim and
new-session qualification as **local PASS**. The test uses a synthetic trainer;
the real ML Worker entrypoint, GPU training and partial checkpoint/restart
remain Phase 16 Golden evidence.

## Optimization bounded slice and gate

`POST /v1/research/optimization-jobs` now queues a workspace-scoped Job that
ranks 2–20 completed BacktestJobs against one objective. Each caller-supplied
parameter set must match its validated strategy version; the candidates must
share frozen comparable inputs. The independent Optimization Worker reads the
immutable backtest results, computes the ranking, and commits a validated
comparison Artifact and successful Job state in one transaction. It does not
generate parameter sets or rerun backtests. MCP offers submit, exact-key/ID
get, and cancel. An existing Agent session is not required for Worker progress
or later Job lookup.

Submission and final Worker commit lock source BacktestJob rows; ordinary
backtest deletion rejects any Job referenced by an OptimizationJob, including
a completed comparison. This preserves stable source lineage. Cancellation
and expired attempts cannot leave a comparison Artifact. The role catalog
grants the new tools only to the current quant orchestrator and backtest
analyst roles; pinned older role versions do not gain them.

Fresh disposable PostgreSQL evidence: the optimization and two focused ML
tests plus two role tests passed (22 total). The final source-lock and
role-version regressions then passed 3/3, and the latest role-version test
passed again 1/1. The MCP TypeScript build, optimization helper test,
read-only-subset test, Compose config and diff check passed. Temporary
PostgreSQL and MCP containers and network were removed. Independent Tester:
PASS. Independent Sol Reviewer: Functional PASS / Tests PASS / Clean Break
Architecture PASS after re-review of the source deletion and role-version
fixes. Root accepts this bounded slice as **local PASS**; Phase 11 overall
remains OPEN. Full Agent/Product and multi-round Golden qualification remains
Phase 15–16 work.

## Workspace data-import bounded slice and gate

An authorized task-bound data demand now provides the stable `DATA_IMPORT` Job
projection using its existing `demand_id`. Submission binds the ResearchTask,
owner and workspace in one transaction; exact-key replay and a later Agent
session resolve the same ID. The Data Worker polls pending task-bound demands
and alone advances their persisted Job state. On verified readiness it commits
the validated `data_readiness` Artifact and successful Job state atomically.
The Artifact contains frozen scope, coverage and source provenance, and records
the canonical stock-pool snapshot lineage when applicable. Partial/failed
readiness produces a terminal error without a success Artifact. An inactive or
missing source reference also becomes terminal failed; transient Artifact
write failures roll back for retry. A ResearchTask cannot complete while its
data-import Job remains active. Existing admin demand permissions and no-task
behavior are retained. Global admin sync remains a separate system operation.

Independent Tester ran the final focused Backend file on disposable PostgreSQL:
8 passed, 0 failed, including owner/workspace isolation, atomic rollback,
lineage, inactive source failure, idempotency and new-session read. MCP
TypeScript build and focused data-demand translation tests passed. Exact test
containers/network were removed; no volume was created. Independent Sol
Reviewer: Functional PASS / Tests PASS / Clean Break Architecture PASS after
re-review of both lineage and terminal-failure fixes. Root accepts this slice
as **local PASS**. Live Product/DSH Golden flows remain Phases 15–16.

## Authorized cancellation and Phase 11 final gate

Factor and task-bound DataImport Jobs now expose owner/workspace-scoped cancel
commands through Product MCP. A Job row lock serializes cancellation with
Worker completion. Repeated cancellation preserves the first terminal result;
cancelled Jobs cannot produce a success Artifact. DataImport cancellation ends
only that workspace demand; shared market-data repairs can continue. Uncertain
MCP responses reconcile by the exact Job ID. New role versions authorize the
tools, while pinned older versions remain denied.

The final independent Tester ran 34 focused Backend tests on disposable
PostgreSQL (factor, data demand and role authorization), all passing. MCP
TypeScript build and focused factor/data-demand tests passed. The temporary
containers and network were removed, and no volume remained. The full live
MCP contract test was **not run** because it requires a Product stack and
token; this belongs to the later integration gate. Independent Sol Reviewer:
Functional PASS / Tests PASS / Clean Break Architecture PASS. Root inspected
the Job stores, cancel routes, MCP reconciliation, role version fence and
affected tests and accepts **Phase 11 local PASS**. Hosted CI and human PR/
merge gates remain separate; full Product/Golden qualification remains
Phases 15–16.

During repository review, Backtest Worker completion was tightened: its
validated result Artifact and terminal Job update now share one short
PostgreSQL transaction under the current attempt's Job row lock. Completion
checks the Artifact's task, owner, workspace, input and result binding.
Cancellation or an expired attempt cannot commit a success Artifact. The
focused cancellation/finalization/expired-claim regression passed on a fresh
disposable PostgreSQL 16 database (1 passed); the container, network and
temporary image were removed. An independent Tester then ran the full affected
Backend file on a second disposable PostgreSQL 16 database (8 passed in
12.21 seconds), including the concurrency regression, and removed the exact
test resources. Hosted CI remains a separate gate.

## Handoffs after Phase 11

| Type | Current state | Remaining boundary work |
|---|---|---|
| Backtest | Durable store, Artifact and independent polling Worker; first slice locally accepted | Full Product/Golden qualification remains in Phases 15–16. |
| Training | Durable `ml_training_runs`, independent ML Worker and model Artifact; common projection and separate-process reclaim/new-session read locally accepted | Real ML Worker/GPU checkpoint and restart Golden evidence remains Phase 16. |
| Factor compute | Durable workspace-scoped Job, independent Worker and validated Artifact; bounded slice locally accepted | Full Product/Golden qualification remains in Phases 15–16. |
| Optimization | Completed-candidate parameter search Job, polling Worker, validated comparison Artifact and MCP tools; bounded slice locally accepted | Full Product/Golden flow remains Phase 15–16. |
| Data import | Workspace-scoped task-bound Job, independent Data Worker and validated readiness Artifact locally accepted; global admin sync stays separate | Full Product/Golden flow remains Phase 15–16. |

These are domain Jobs, not Agent continuation state. They remain queryable by
stable business ID after an Agent session disappears. Phase 12 owns Artifact,
Approval and Audit normalization; full new-schema Golden Scenarios remain
Phase 15–16 gates.
