# Phase 0–6 gate record

## Phase 15 repository-gate authorization (2026-09-30)

After local functional PASS, the maintainer explicitly instructed
“授权推送合并”. This covers pushing `codex/clean-break-phase15`, creating its
PR, executing required Full CI and, after exact-head platform preflight PASS,
ADR-0015/0059 squash auto-merge. It grants no deployment, release/tag, existing
database/backup operation or Phase 16 implementation. The repository remains
pre-v1.0; live settings must still prove auto-merge/squash enabled and strict
`local-ci` / `ci-gate` requirements before the merge action. Repository CI and
merge results are recorded by the PR/check runs; this authorization is not a
claim that those gates already passed. Earlier local-only scope statements
below retain their historical meaning.

PR #378 was created as Draft. Initial exact-head hosted Full CI run
`36648427194` and PR run `36648406040` failed the selected operational build
identity gate before component tests: Phase 15 source inputs differed from
the selected immutable manifest. This is a real gate failure, not a component
test result. The correction must issue a new build revision and preserve the
old manifest/inputs; disabling the identity gate or reusing old images is not
permitted. Replacement exact-head CI and merge preflight remain required.

The correction selects new immutable build `dsh-0.1.5rc1-post-u8.271`
(`sha256:b16e18882b74431b25720b028a135ae1dd924382f8526cd2f87fa772c9dfecae`),
freezes `.270` without changing its manifest or Dockerfile, and updates live
Compose/CI/development references. The new Dockerfile changes only the embedded
manifest path; release descriptor, SDK/runtime and dependency locks are
unchanged. `compose.dev.yml` now belongs to the fingerprinted input closure.
The four already implemented OptimizationJob Product methods are also added
to the browser OpenAPI contract, preserving the route-coverage assertion.
These changes do not alter Product execution behavior or require another
paid model/Golden run. The old manifest mismatch remains recorded; only
replacement exact-head hosted CI can satisfy the repository gate.

Bounded correction Tester: **PASS** (13 build/current/frozen/selection checks,
one exact OpenAPI coverage test, current `.271` and frozen `.270` manifest
checks, YAML/AST/shell/diff). Independent Sol Reviewer: **Functional PASS /
Tests PASS / Clean Break Architecture PASS**. Root: **PASS for the CI
correction only**; this is not a hosted Full CI or merge pass.

Replacement Full CI run `36649851347` on `74f378c1` passed Docs, Gateway,
Runtime, MCP, Frontend and Integration. Architecture failed only its obsolete
global ML-create call-count text assertion; the accepted flow prepares a watch
and executes one exactly approved submission. The assertion now distinguishes
preparation from the single execution and explicitly retains unknown-outcome
no-retry protection. Backend failed two handoff fixtures that requested approval
for `byq_backtest_task_execute`, now `AUTO` under the already accepted Phase 15
role policy. Fixture corrections must preserve waiting/delivery/permission and
unknown-result assertions and use a still-required approval boundary. These
failures are not reclassified as passes; final exact-head Full CI is required.
The published `.271` build remains frozen, with a new `.272` for the changed
test inputs; no Product/Skill behavior is changed by these corrections.

The two repaired Backend fixtures bind `byq_strategy_approve` to a real
validated `strategy_version` Artifact in the same task. Independent focused
PostgreSQL validation used only the disposable `byq_domain_test` database,
confirmed by read-only identity preflight: **2 passed**. The corrected ML Skill
assertion also passed its one focused test. New `.272` manifest hash is
`sha256:a4ea957ef6123d1b8c80882172c89b5b0857bdb4ab163028382d89b7291e3414`.

Second bounded correction: independent Tester **PASS** (2 Backend cases,
1 ML Skill case, 3 current-build cases and 1 selection case, selected/frozen
identity, syntax and diff checks). Independent Sol Reviewer: **Functional PASS /
Tests PASS / Clean Break Architecture PASS**. Root: **PASS for the bounded
correction**; final exact-head Full CI and repository preflight remain required.

## Phase 15 PR-history secret-scan correction (2026-09-30)

Full CI run `36652051299` passed on `de30eac2`, including all seven components,
integration/browser checks, scoped cleanup and aggregate gates. Independent
Tester verified the exact head. Fresh repository preflight nevertheless blocked
merge because PR run `36652026073` failed its whole-PR Git-history secret scan.
The dispatch scan covers only the last commit and does not replace that gate.

Pinned Gitleaks 8.30.1 reported four `generic-api-key` findings in commit
`9357651`, all the same deterministic `optimization-key-1` idempotency fixture
in `services/gateway/tests/test_product_api.py`. Independent Reviewer confirmed
they are mocked request/query/forwarding assertions, not credentials. Automatic
approval review initially rejected a persistent scanning exception as outside
the existing settings authorization; no configuration change or merge occurred.
The maintainer then explicitly authorized only that file and exact value.

The correction inherits `generic-api-key` and adds an `AND` allowlist requiring
both the anchored exact test path and anchored exact extracted value. Existing
global exclusions, all other rules, files and values remain unchanged. This
configuration is outside the `.272` fingerprint closure; no build revision or
Product runtime change is needed. Final boundary tests, exact-head CI and fresh
repository preflight remain required before the authorized merge.

Independent focused Tester: **PASS** using pinned scanner 8.30.1. Whole-PR
history scan reports zero findings. Temporary controls prove the exact allowed
path/value passes, a different high-entropy synthetic value at the same path
is detected, and the exact fixture value in another file is detected. Scanner
output is redacted; no credential value is recorded. `.272` identity and
`git diff --check` also pass. Independent Sol Reviewer: **Functional PASS /
Tests PASS / Clean Break Architecture PASS**. Root: **PASS for this exact
scanner correction**; hosted exact-head checks and live preflight remain open.

## Phase 15 live Golden C and local fidelity closeout (2026-09-30)

[Current evidence](phase15-functional-fidelity.md#current-live-golden-c-and-closeout-evidence-2026-09-30)
records three authorized actual Product Agent turns and exactly one new CPU
TrainingJob. Exact browser approval, original watch/key, trusted preview,
ML Agent submitted audit and Product Job state corroborate Agent initiation.
The real CPU Worker exited 137 during attempt 1 while the Job remained
nonterminal; a normal 2 CPU Worker with the same image reclaimed the same Job
after natural lease expiry and completed attempt 2. One validated Model with
metrics and exact Job lineage, the reused validated Feature, persisted object
references and the two-run study passed the observer assertions. Data and ML
Workers are stopped; no new market download occurred.

The view-only old session loss and the later post-decision receipt GET 404 are
retained as failures. Neither decision nor model prompt was retried. Read-only
browser receipt recovery passed with 45 requests and zero off-origin requests.
Public training activity reports started/waiting without argument/result
visibility; the exact submission proof uses durable audit/preview/Job state.
The CPU evidence establishes durable reclaim/re-execution, not mid-epoch
checkpoint recovery; GPU remains `N/A` under ADR-0089.

Post-rebuild E/A, D, B/browser and CPU C evidence follows scoped rebuild
`2987d3c1`; the former F summary saying journeys had not been rerun was stale.
Those passed journeys were not repeated. Independent live Tester: **PASS**
after read-only Product, Artifact and stopped-Worker checks. Final focused
Gateway regression: **2 passed**, covering pre-prompt `ProductError` and
`HTTPException`; syntax, diff and evidence links PASS. Independent Sol
Reviewer: **Functional PASS / Tests and Evidence PASS / Clean Break
Architecture PASS**, including source, live C and the sufficiency of existing
A/B/D/E plus corrected F evidence. **Root: Golden C PASS and Phase 15 local
functional fidelity PASS.**

**Phase 15 overall remains OPEN:** required Full CI is NOT_RUN for this branch,
and push/PR/human merge are outside the current authorization. Phase 16 stays
closed. The local observations do not claim hosted CI or deployment completion.

## Phase 15 Golden C exact training approval source gate (2026-09-30)

The Agent training submission now freezes its task, strategy, pool snapshot,
optional experiment, owner/workspace and idempotency key in a `prepared` watch.
The Agent approval binds that watch; Backend execution checks the persisted
grant and identical submission. Product approval displays a trusted frozen
preview and refuses a missing preview. The original key returns the same Job
on terminal replay. The bounded Golden C observer also compares the approved
key with the new Product TrainingJob.

Focused independent Tester: **PASS** (Backend exact-grant and preview contract,
Gateway projection and decision guard, MCP translation, frontend component and
production build, diff/syntax checks). Independent Sol Reviewer: **Functional
PASS / Tests PASS / Clean Break Architecture PASS** for this source slice.
Root: **PASS for the source slice only**. Real Agent initiation, real-browser
approval preview, nonterminal CPU Worker restart/reclaim and final same-Job
Artifact evidence remain **OPEN**. No new model call, market download, existing
business database or backup operation, push, PR, merge or deployment occurred.

## Current Phase 15 GPU gate scope (2026-09-30)

[ADR-0089](../architecture/adr/ADR-0089-clean-break-gpu-acceptance-scope.md)
excludes GPU execution and GPU checkpoint/restart from the BYQ 0.10 gate as
`N/A`. The real-provider CPU TrainingJob/Worker/Artifact slice passed locally;
Agent-initiated training and real CPU Worker restart/reclaim remain open.
Earlier `NOT_RUN` GPU records below describe what was observed at the time and
are not rewritten as test passes. Phase 15 overall remains OPEN.

Focused governance Tester: **PASS**, 3/3 checks; changed-document links and
`git diff --check`: **PASS**. Independent Sol Reviewer inspected the actual
decision, plan, gate and test diff: **Functional PASS / Tests PASS / Clean Break
Architecture PASS**. Root accepts this GPU-scope decision only: **PASS**.
Golden C and the Phase 15 overall gate remain **OPEN**.

## Phase 15 fresh-state Research and Backtest slices (2026-09-29)

**Golden D gate: PASS.** On the rebuilt isolated stack, an old Product Agent
created and executed one approved BacktestTask; its BacktestJob remained queued
at attempts 0 after the old conversation was deleted. The independent Worker
completed that same Job once with a validated Artifact, and a new Product Agent
identified the exact Job and Artifact by stable ID. The sole authorized repair
was for `20240102`; its one session job received 5,329 full-market daily rows.
Focused staged script checks and read-only isolated DB inspection passed.
Independent Sol Reviewer: Functional PASS / Tests and Evidence PASS / Clean Break
Architecture PASS. Root: PASS for Golden D. Normalized MCP activity omits
arguments and results, so exact execute/read arguments are corroborated by the
unique Job, durable audit, Product state and Agent answer rather than directly
shown in the public trace. This scenario excludes DSH process restart and child
rebind. **Phase 15 overall remains OPEN.** No existing DB, backups, deployment,
push or merge were touched.

After explicit maintainer authorization following an automatic approval-review
rejection, the isolated Agent role catalogue aligns BacktestTask create/execute
with Clean Break `AUTO`. Exact strategy approval and task-cancel approval remain.
The three changed role versions are bumped; `/v1/agents/authorize` denies old
versions for these actions, but direct BacktestTask endpoints have no per-run
version fence. Discard active old sessions before adopting the policy; this
development Clean Break carries no old-session migration. The personal
`manual_safe` preset now describes sensitive-action approval without promising
that authorized deterministic backtests need human confirmation. **Tester:**
five focused Backend modules on isolated PostgreSQL, 37 passed / 2 warnings;
the changed preset rendered in isolated Chromium through Frontend/Gateway with
zero off-origin requests. **Independent Sol Reviewer:** Functional PASS / Tests
PASS / Clean Break Architecture PASS after the actual diff, MCP/Backend paths,
role versions and documented adoption limit. **Root acceptance: PASS for this
bounded policy-alignment slice.** The later Agent-started Golden D gate is
recorded above. No
Product DB, deployment, push or merge.

An additional isolated ML Worker image check trained a real LightGBM CPU model
from 30/10 honestly synthetic in-memory rows, reloaded the model and checked
finite metrics. It made no Product, DB or provider call. This is a trainer
dependency smoke only; Product TrainingJob, Artifacts, Worker reclaim, GPU and
model checkpoint/restart remain **OPEN/NOT_RUN** as applicable. The Product
readiness path requires real TuShare rows and can fan out to whole-market
daily repair, so no broad provider sync was triggered for this check.
**Tester:** focused static evidence review and diff check PASS.
**Independent Sol Reviewer:** Functional PASS / Tests PASS / Clean Break
Architecture PASS for this bounded record. **Root acceptance: PASS for the
trainer smoke only; Golden C remains OPEN.**

The later Agent-audited Workspace reset blocker is resolved in a bounded
Phase 15 change. Reset retains successful Web evidence `agent_audit` facts and
their stable Artifact IDs while removing disposable Web Artifacts; other
Artifact audit and ambiguous rows still block. **Tester:** two focused isolated
PostgreSQL reset contracts PASS; slice syntax and diff checks PASS.
**Independent Sol Reviewer:** Functional PASS / Tests PASS / Clean Break
Architecture PASS after direct code/test review. Root rebuilt only the isolated
Backend and observed authenticated Product reset HTTP 200 on the previously
blocked Workspace: four Tasks, 11 Artifacts, two Backtests, one OptimizationJob
and the four-message conversation removed; both original Web audit facts still
present, login/Workspace intact, new Task persisted. **Root acceptance: PASS
for the repeated-reset slice only.** [Exact evidence](phase15-functional-fidelity.md)
records the scope. Phase 15 overall remains OPEN; no push, merge or deployment.

The later bounded session-loss observation also passed focused Tester review
and independent Sol Review (**Functional PASS / Tests and Evidence PASS / Clean
Break Architecture PASS**). A separately submitted Product API BacktestJob
remained queued when a contemporaneous conversation was deleted; its Worker
later completed it in one attempt, and a new authorized DSH Agent read the
same Job and Artifact through BYQ MCP. Root accepts this bounded D result.
The Agent did not submit that earlier Job, so Golden D was still open at this
gate; the later Agent-initiated gate above closed it. A subsequent
real-browser Runtime reset passed on the populated Phase 15 Workspace, but
Workspace reset initially returned 409 because a retained strategy-approval
Artifact referenced a ResearchTask slated for deletion. That fail-closed 409
did not delete Workspace data. See the execution record for the subsequent
archive fix and populated reset rerun.
Afterward, exact-scope `dev-clean` removed only this isolated project's 12
containers, four volumes and two networks. Core init/start/seed/test, fresh
database counts and real login passed. A simple approval-free Product reset
also passed and reseeded. Root accepts this bounded environment lifecycle
result; full Golden E/F remain **OPEN** for connected-journey reruns.

The maintainer then authorized only a Phase 15 isolated-branch archive change.
The new internal immutable archive retains each validated strategy approval
and its exact strategy version before the source ResearchTask/Artifacts are
deleted in the same Product reset transaction. **Tester:** two focused tests
PASS on a disposable database, plus syntax, diff and slice `dev-check` PASS.
**Independent Sol Reviewer:** Functional PASS / Tests PASS / Clean Break
Architecture PASS on the actual schema, reset path and tests. Root accepts
this bounded source slice. On the isolated populated Backtest Workspace,
authenticated Product reset returned 200, deleted two Tasks, 11 Artifacts,
two BacktestJobs and one OptimizationJob, while a read-only check found two
complete archive facts and no remaining research rows. Idempotent replay,
login/Workspace identity and fresh seed passed. The connected browser and
research rerun were pending at that bounded gate; see the later Golden E record below.
**Phase 15 overall remains OPEN**. No existing
database, backup, deployment, push or merge was touched.

The next isolated fixture completed two new BacktestJobs and an OptimizationJob.
Playwright Chromium then used the real Frontend and Product API to reset Runtime
and Workspace, proving the Task survived the first reset and the exact Task,
Job and Artifact graph was removed by the second. The same account/Workspace
stayed active, a new ResearchTask persisted, and browser requests stayed on
Frontend/Gateway origin. A one-row real TuShare import and a new two-turn
delegated Product Agent market/Web research produced a new research-only
Artifact after reset; exact-trace business audit confirmed market-read and Web
evidence-save calls. A separate read-only Chromium pass rendered that exact
post-reset conversation and Web Artifact. Another new disposable Workspace
passed the strengthened browser reset with exact Task/Job/Artifact IDs and
unchanged subject, account role, Workspace role and shared market-automation
configuration. A further reset of the original, Agent-audited Workspace
correctly returned 409 because two retained audit facts referenced new Web
Artifacts; that second reset is outside E's required order and is not claimed
to succeed. [Execution evidence](phase15-functional-fidelity.md)
records the separate runs, IDs and counts. **Tester:** focused static review of
both browser scripts and changed documentation PASS; the destructive live runs
were executed by Root, not independently repeated by Tester. **Independent Sol
Reviewer:** Functional PASS / Tests and Evidence PASS / Clean Break Architecture
PASS on the scripts, exact Product trace and separate-run evidence. **Root
acceptance: Golden E's specified `reset → seed → rerun A` sequence local PASS.**
The later Agent-audit 409 still needs classification before Phase 15 completion;
this gate does not claim arbitrary repeated reset. Phase 15 overall remains OPEN.

[Execution record](phase15-functional-fidelity.md): in the worktree-scoped
disposable stack, one real TuShare daily row was imported through Data Worker;
the Product DSH Agent read it through BYQ MCP in a two-turn delegated research
conversation, saved seven-source Web Search evidence, and produced normalized
trace and business audit records. Separately, two worker BacktestJobs and one
OptimizationJob produced exact result/comparison Artifacts. Playwright Chromium
used real Product login to display both Agent answers, compare the exact two
completed Backtest IDs with numeric metrics, and list the exact research and
comparison Artifact IDs. The final browser run passed with 173 same-origin
requests and zero off-origin requests. Focused contract tests for the new
Optimization Product route, shared result access and developer profile passed.
The Docker build context now excludes local `.env.*` credentials.

**Tester:** focused Product/Backend/dev tests PASS for the B code slice;
research documentation and final browser-script static checks PASS. **Independent
Sol Reviewer:** Functional PASS / Tests and Evidence PASS / Clean Break
Architecture PASS for the bounded live research and browser slices; the prior B
code review also passed its bounded triad. **Root acceptance:** PASS for these
bounded A/B Product API, Worker and browser observations only. The full Phase 15
gate remains **OPEN** for Agent-led strategy change, Job/session interruption,
reset/rebuild, and ML. GPU execution is `NOT_RUN` on this host, which has no
NVIDIA device or Docker NVIDIA runtime; the present ML image is CPU LightGBM.
Phase 16 remains closed. No existing Product database, backup or deployment was
used.

## Phase 14 repository gate and Phase 15 entry (2026-09-29)

PR #377 passed all required hosted checks, including Backend and integration,
on exact head `960235a12883e82fe710b3d252ecb216a6666146`.
The ADR-0059 read-only merge preflight passed and squash auto-merge produced
`e9c944951465fbdeae4d05cd7bb0358b32f8a041` on `main`. The Phase 14
repository gate is **PASS**. Phase 15 starts from that commit in a separate
worktree. Its full functional fidelity gate remains **OPEN**; Phase 16 is closed.

## Phase 14 fresh database baseline — bounded local gate (2026-09-29)

[Execution record](phase14-database-baseline.md): startup migrations for old
personal Workspaces, paper execution, stock-pool snapshots and backtest names
were removed; current business and financial facts stay in fresh Store DDL.
The old SQLite application import path was retired. `dev-seed` creates a small
synthetic Workspace fixture in a scoped Compose database. Disposable PostgreSQL
16 focused tests passed 36/36; repeated seed returned identical IDs. Development
command tests passed 12/12, governance 2/2 and selected build/architecture
86/86. Frozen `.269` and current `.270` build checks passed. **Independent Sol
Reviewer: Functional PASS / Tests PASS / Clean Break Architecture PASS. Root:
local Phase 14 PASS.** Repository PR/CI/merge gate remains open; Phase 15 stays
closed. Existing Product data, archives and deployments were not touched.

## Phase 13 Reset Runtime / Reset Workspace — bounded local gate (2026-09-29)

[Execution record](phase13-workspace-reset.md): Product runtime reset durably
fences one Workspace's Agent business calls before exact Gateway/Adapter
session release; pending resets keep cookie identity for retry while denying
Agent admission. Finalization requires exact release proof, closes the revoked
runs as interrupted, archives only bound conversations, and retains transcripts,
Jobs, Artifacts and unknown external outcomes. The isolated development reset
uses an explicit Workspace SQL cleanup, verified scoped runtime volumes and a
global-reference CAS object scan. **Independent Tester:** fresh disposable
PostgreSQL 16 Backend reset files 6/6 PASS; Gateway contract 7/7, development
command 12/12, object cleanup 4/4 PASS. One initial Backend container mount
omitted the plugin registry; the corrected read-only mount passed and both
attempts' exact containers and networks were removed, with no persistent
volume. Current `.266` build manifest check, 83 selected build/retirement/
architecture tests and diff check PASS. **Independent Sol Reviewer:**
Functional PASS / Tests PASS / Clean Break Architecture PASS for this tested
Backend/development slice on actual diff, SQL trigger scope, Gateway retries
and build identity. **Root acceptance: bounded slice local PASS; Phase 13
overall OPEN.** The frontend reset menu and user-facing Product Workspace
reset API are now implemented as an unmerged candidate. Focused disposable-DB
Backend tests 10/10, Gateway tests 11/11, frontend tests 10/10 and build PASS.
Independent Sol review found Functional PASS and Clean Break Architecture PASS.
Its two evidence gaps were closed with a frozen-code completed FactorJob graph
test 1/1 and a single real-browser Gateway/Product API path 1/1 on a fresh
isolated stack, exercising Runtime then Workspace reset. Independent Sol
Reviewer re-verdict: **Functional PASS / Tests PASS / Clean Break Architecture
PASS for local Phase 13 code**. The maintainer then explicitly authorized the
`.267` build metadata update. The new immutable manifest and Dockerfile are
current; `.267` and frozen `.266` checks PASS, and focused build/retirement/
architecture tests pass 86/86. Independent Sol Reviewer reconfirmed **Functional
PASS / Tests PASS / Clean Break Architecture PASS** on the final actual diff.
**Root accepts Phase 13 local gate PASS.** Product reset removes
Artifact database references; global-reference-safe object GC is separate and
physical deletion is not claimed at Product request completion. Repository
PR/CI/merge gate remains open;
Phase 14 and Golden scenarios remain closed. No existing Product database,
deployment, push or merge was performed in this turn.

## Phase 13 repository gate and Phase 14 entry (2026-09-29)

PR #376 passed all required hosted checks, including Backend and integration,
after the Workspace trigger field guard and conversation test fixture corrections.
The exact-head GitHub merge preflight passed for
`90ca69b82330c00550488261a55b2ab398106216`, and squash auto-merge produced
`2592f7255ef94746548b4c72fb9fa74f6f9897d1` on `main`. The Phase 13
repository gate is **PASS**. Phase 14 begins from this merged commit in a new
isolated worktree; its fresh-schema/seed gate is still **OPEN**. Phase 15 remains
closed.

## Phase 12 repository gate (2026-09-29)

PR #375 passed the required hosted CI after its focused Backend receipt-test
correction and was merged at `8d6929a140d4ebddc55091b43f9c8a3c9d465e4b`.
The Phase 13 isolated branch starts from that commit. Phase 14 remains closed.

## Phase 12 Artifact / Approval / Audit — final local gate (2026-09-29)

[Execution record](phase12-artifact-approval-audit.md): owner/workspace-scoped
Artifact reference, closed approval policy with exact Agent grants at the five
ACTION write boundaries, and a best-effort after-commit FactorJob AuditEvent.
Authenticated Product user review and cancellation paths remain available.
Focused disposable-DB Backend tests passed after correcting two test-only
expectations (54 initial passes; affected rerun 8/8). Gateway 4/4, MCP build
and five focused suites, DSH revision/retirement 9/9, architecture 73/74 then
the single documented-route correction 1/1, dev-check and final build revision
check passed. Independent Tester: PASS. Independent Sol Reviewer: Functional
PASS / Tests PASS / Clean Break Architecture PASS. **Root acceptance: Phase 12
local PASS.** Required PR CI and merge gate remain open; Phase 13 must not
begin until repository gate completion. Golden scenarios remain Phases 15–16.

## Phase 11 Business Job — final local gate (2026-09-28)

The five domain Job paths now have stable owner/workspace-scoped IDs, common
state projection, independent Worker execution and Artifact results. Factor
and task-bound DataImport cancellation complete ADR-003's authorized MCP
start/query/cancel contract. A Job row lock serializes cancel with Worker
completion; cancelled attempts cannot create successful Artifacts. New role
versions grant the tools without widening pinned older roles. Independent
Tester: disposable PostgreSQL focused Backend suite 34/34 PASS; MCP build and
focused Factor/DataImport tests PASS; exact test resources removed, no volume.
Full live MCP contract test NOT RUN because the Product stack/token is a later
integration gate. Independent Sol Reviewer: Functional PASS / Tests PASS /
Clean Break Architecture PASS. **Root acceptance: Phase 11 local PASS.**
Hosted CI, human PR/merge and Phases 15–16 Golden scenarios remain separate.

## Phase 11 Business Job — workspace DataImportJob bounded slice (2026-09-28)

Task-bound data demands use the existing durable demand ID as a workspace
`DATA_IMPORT` Job. The independent Data Worker persists status and commits a
validated readiness Artifact atomically. A frozen stock-pool snapshot receives
canonical Artifact lineage; unavailable references become terminal failed,
while transient Artifact writes roll back for retry. Authorized new Agent
sessions read the same Job ID and Artifact. Global admin sync remains separate.
Independent Tester: disposable PostgreSQL Backend focused file 8/8 PASS; MCP
TypeScript build and focused data-demand test PASS; exact containers/network
removed, no volume. Independent Sol Reviewer: Functional PASS / Tests PASS /
Clean Break Architecture PASS. **Root acceptance: bounded slice local PASS;
Phase 11 overall gate under review.** Full Product Golden flows remain
Phases 15–16.

## Phase 11 Business Job — Training process reclaim qualification (2026-09-28)

On disposable PostgreSQL, the focused separate-process lifecycle test passed
(1 passed; Docker test container exit 0). It killed a Coordinator process
after claim, expired the persisted lease, completed the same TrainingRun on
attempt two in another process, and read the stable Job and validated model
Artifact from a new trusted Agent session. Test containers/network were
removed with no volume created. The outer wrapper returned 1 after pytest and
cleanup for an undetermined reason; this is recorded separately from the
passing test. Independent Tester: PASS. Independent Sol Reviewer: Functional
PASS / Tests PASS / Clean Break Architecture PASS. **Root acceptance: bounded
qualification local PASS; Phase 11 overall OPEN.** Synthetic training proves
process reclaim, not real GPU checkpoint/restart; that remains Phase 16.

## Phase 11 Business Job — optimization bounded slice and Training projection (2026-09-28)

[Execution record](phase11-business-jobs.md): completed-candidate parameter
search now runs as a durable workspace-scoped OptimizationJob in an independent
Worker and yields one validated comparison Artifact. Source BacktestJobs remain
available for the comparison's lineage; cancellation and stale attempts cannot
commit an Artifact. MCP submit/get/cancel uses exact-key reconciliation and
current Agent role authority. Training create/get/cancel/reconcile now expose
the common Job projection with a stable pending input reference. Fresh
disposable PostgreSQL rerun: 22 passed; final source and role regressions:
3 passed plus the latest role gate 1 passed. MCP build and focused tests,
Compose config and diff check passed; temporary resources were removed.
Independent Tester: PASS. Independent Sol Reviewer after fixes: Functional
PASS / Tests PASS / Clean Break Architecture PASS. **Root acceptance: bounded
Optimization and Training projection slice local PASS; Phase 11 overall OPEN.**
Actual independent ML Worker interruption/new-session evidence and workspace
DataImportJob/Artifact remain Phase 11 work. GPU checkpoint/restart remains a
Phase 16 Golden gate.

## Phase 11 Business Job — training boundary qualification (2026-09-28)

[Execution record](phase11-business-jobs.md): existing persisted TrainingRun,
independent ML Worker and validated model Artifact qualify the specialized
Job ownership boundary. Two focused tests passed on a fresh disposable
PostgreSQL database; temporary resources were removed. Independent Tester:
PASS. Independent Sol Reviewer: Functional PASS / Tests PASS / Clean Break
Architecture PASS for the bounded qualification. **Root acceptance: training
boundary qualification local PASS; Phase 11 overall OPEN.** Common Job
projection on create/cancel/reconcile, a waiting input reference, actual
Worker process interruption and new-session read still require Phase 11
evidence. GPU checkpoint/restart remains a Phase 16 Golden gate.

## Phase 11 Business Job — factor bounded slice (2026-09-28)

[Execution record](phase11-business-jobs.md): factor submission now queues a
durable, workspace-scoped Job; an independent Worker commits its validated
Artifact and Job status in one transaction. Fresh disposable PostgreSQL tests:
39 core and four ownership cases passed. MCP build and focused translation
tests, Compose config, syntax, diff and slice dev-check passed; test resources
were removed. Independent Tester: PASS. Independent Sol Reviewer: Functional
PASS / Tests PASS / Clean Break Architecture PASS. **Root acceptance: factor
slice local PASS; Phase 11 overall OPEN.** Optimization, workspace data import,
and remaining ML boundary qualification are not claimed complete.

## Phase 11 Business Job — admin data import bounded slice (2026-09-28)

[Execution record](phase11-business-jobs.md): admin range sync now runs in the
independent Data Worker. Fresh disposable PostgreSQL tests: 23 passed, covering
claim competition, interrupted work, stale import rollback, checkpoint
atomicity and exhausted attempts under a continuing queue. Syntax, diff and
slice dev-check passed; test resources were removed. Independent Tester: PASS.
Independent Sol Reviewer: Functional PASS / Tests PASS / Clean Break
Architecture PASS after two defects were fixed and re-reviewed. **Root
acceptance: this slice local PASS; Phase 11 overall OPEN.** The global admin
sync is not represented as the workspace DataImportJob required by ADR-003.

## Phase 11 Business Job — first bounded slice (2026-09-28)

[Execution record](phase11-business-jobs.md): the common backtest/training Job
read projection and independent polling backtest Worker passed focused tests on
a disposable PostgreSQL database, including concurrent claim, stale attempt
fencing, cancellation, attempt exhaustion, workspace isolation and retrieval
from a new Agent session. Compose config and diff checks passed; exact test
resources were removed. Independent Tester: PASS. Independent Sol Reviewer:
Functional PASS / Tests PASS / Clean Break Architecture PASS. **Root acceptance:
first slice local PASS; Phase 11 overall OPEN.** Factor, optimization, admin
data import and remaining training boundary work are not claimed complete.

## Phase 10 thin DSH Adapter — bounded resume-removal slice (2026-09-28)

The [transport contract](phase10-dsh-contract.md) and
[execution evidence](phase10-evidence.md) record removal of Adapter-owned
same-session process reconstruction after a failed or interrupted Agent turn.
Live READY reattach, normal healthy next-root admission, exact Backend terminal
acknowledgement, and unknown-outcome protections remain. Failed and interrupted
Product errors are distinct.

**Tester:** affected Adapter 102/102, Gateway Product Agent 50/50, governance
2/2 and diff check PASS; Root additionally observed pinned DSH real-process
hard cancel 1/1. **Independent Sol Reviewer:** Functional PASS / Tests PASS /
Clean Break Architecture PASS for this bounded slice after actual diff and
ADR review. **Root acceptance:** **PASS for this slice only**.

The second bounded slice removed generic failed-turn recovery inference and
retained only bounded, completed public Product transcript input for a new
explicit DSH root. [ADR-002](adr/ADR-002-dsh-boundary.md) distinguishes that
Product data from DSH-private Agent context. **Tester:** Gateway 85/85,
Adapter 104/104, governance 2/2 and diff check PASS. **Independent Sol
Reviewer:** Functional PASS / Tests PASS / Clean Break Architecture PASS for
this slice after actual diff, deleted-code and ADR review. **Root acceptance:**
**PASS for the second slice only**. The
[field audit](phase10-adapter-ownership.md) classifies the remaining in-memory
Adapter handles as live transport correlation and exact BYQ business authority
evidence; Reviewer found that classification architecturally sound in
principle.

The [joined real Product/DSH flow](phase10-evidence.md#joined-real-productdsh-flow)
passed through Gateway/Product API with a fresh isolated PostgreSQL database,
the pinned DSH release and a scripted loopback provider. The second root
received the first persisted public answer only after exact Backend root
close/terminal acknowledgement; native DSH processes and Backend roots were
distinct. The temporary stack and data volumes were removed. Independent
Tester confirmed the runner preflight, source syntax, scope checks and empty
post-run resource inventory. Independent Sol Reviewer inspected the full diff,
ADR, interfaces and real evidence and returned **Functional PASS / Tests PASS /
Clean Break Architecture PASS** for Phase 10 overall. **Root acceptance:**
**Phase 10 local PASS.** Phase 11 Business Job may begin in a new isolated
worktree. Hosted CI and human PR/merge gates remain separate; no push, merge
or deployment occurred.

## Phase 9 rebuildable developer environment — local Root gate (2026-09-28)

[Implementation contract](phase9-dev-environment.md) and [execution evidence](phase9-evidence.md)
cover the worktree-scoped configuration, explicit service selections, scoped
preview/apply cleanup and honest Phase 13/14 dependencies. Root observed the
isolated core stack healthy (PostgreSQL, Backend, Product MCP, Runtime Adapter,
Gateway), Gateway `/readyz` HTTP 200, then stop and exact project cleanup with
no resources remaining. A second PostgreSQL cleanup run passed after the final
container mount/network checks. No old DB, backup or Product stack was used.

**Tester:** lifecycle 6/6, Clean Break governance 2/2, generated Compose config
and diff check PASS; Docker socket was unavailable in its executor, so live
Docker checks were separately run by Root. **Independent Sol Reviewer:**
Functional PASS / Tests PASS / Clean Break Architecture PASS after actual diff,
interfaces, ADR and evidence review. **Root acceptance:** **Phase 9 local PASS**
for its bounded milestone. Reset/seed and full fresh-schema Golden rebuild
remain explicitly NOT_RUN for Phases 13–16. Hosted CI and human PR/merge gates
remain separate; no push, merge or deployment occurred. Phase 10 may begin in a
new isolated worktree, but has not begun.

## Phase 8 classified old-environment cleanup (2026-09-28)

Following the maintainer's broader deletion approval, the [exact manifest](phase8-final-targets.json)
and [execution evidence](phase8-final-cleanup-evidence.md) record final-archive
verification, independent scope review, removal of 10 named old BYQ volumes
(including the archived old Product DB source) and 68 unused old BYQ
GHCR digest-only images. All removals succeeded. Five unlabeled volumes and
unrelated/unknown or retained resources were excluded.

**Tester:** PASS — live Docker inspection found all 10 target volumes and
68 target images absent, all five excluded named volumes and 28 anonymous
volumes present, backup checksum intact, retained images present, and the
unrelated container and built-in networks unchanged. Governance 2/2 and diff
check PASS. **Independent Sol Reviewer:** Functional PASS / Tests PASS /
Clean Break Architecture PASS after reviewing the actual manifest, execution
results, backup checksum, documentation and Tester evidence. **Root acceptance:**
**Phase 8 overall PASS** for classified old-environment cleanup. The excluded
resources remain out of scope; Phase 9 may begin in a separate gate, but has
not begun.

## Phase 8 first-pass resource cleanup (2026-09-28)

The maintainer expressly authorized only the five targets in the
[preview](phase8-cleanup-preview.md). [Execution evidence](phase8-first-pass-evidence.md)
records exact revalidation, removal and post-action absence for two old test
DB volumes, their two empty networks and the old recovery-MCP test image.
The old Product DB source volume and final archive remain present. **Phase 8
overall remains OPEN** while other obsolete resources are classified and
separately authorized; no Phase 9 work follows from this slice alone.

**Tester:** Functional PASS / Tests PASS for these five targets: exact absence,
43 remaining volumes and three built-in networks, retained old Product DB and
five named BYQ state volumes, archive size/mode/checksum, governance 2/2,
36 local links and diff PASS. **Independent Sol Reviewer:** Functional PASS /
Tests PASS / Clean Break Architecture PASS for the bounded operation after
actual documentation/evidence review and independent archive checksum check;
its Docker socket was unavailable, so it used the independent Tester's exact
post-action Docker verification. **Root acceptance:** **PASS for this five-target
Phase 8 slice only**. No other resource deletion, Phase 8 overall PASS or
Phase 9 entry is accepted.

## Phase 8 read-only inventory and cleanup preview (2026-09-28)

The [current inventory](environment-inventory-20260928.md) and
[first-pass preview](phase8-cleanup-preview.md) list only two detached old test
DB volume/network pairs and one old recovery-MCP image as review candidates.
The final old Product database archive's 2,102,827,616-byte file and SHA-256
match its manifest; the source volume remains present and unmounted.

**Tester:** Functional PASS / Tests PASS for planning only: exact Docker
metadata/attachments and archive checksum checked read-only, governance 2/2,
four local links and diff PASS. **Independent Sol Reviewer:** Functional PASS /
Tests PASS / Clean Break Architecture PASS for the read-only proposal, after
inspecting the documents and independently verifying archive metadata/checksum;
its Docker access was unavailable, so Root and Tester performed exact Docker
metadata checks. **Root acceptance:** **PASS for Phase 8 preflight planning
only.** Resource deletion, Phase 8 implementation and Phase 8 overall gate are
**NOT_RUN / OPEN**. Test DB contents and reclaim sizes are unverified; the P0
volume lacks an owner label, the old DB application schema revision is unknown,
and no current TOC/restore run was done. Before any cleanup, recheck exact
resource identities/attachments and obtain authorization covering the named
test data, networks and image. Existing Product DB, backup and unclassified
resources remain outside this proposal.

## Phase 7 bounded legacy-runtime removal — Root acceptance (2026-09-28)

[Exit evidence](phase7-exit-evidence.md) and [live-state classification](phase7-exit-classification.md)
close the finite Phase 7 gate below. The final slice removed the old-row
`recovery_attempts` admission scan and unwired Gateway recovery callback;
earlier accepted slices removed the old Adapter journal, disk persistence,
takeover and compatibility routes. Current BYQ business authorization and
`outcome_unknown` safeguards remain.

**Tester:** Functional PASS / Tests PASS for this bounded scope: Gateway 25/25,
Backend isolated PostgreSQL 8/8 (five authority/unknown cases plus three route
rejection cases), architecture 198/198, selected `.239`/frozen `.238` build
checks, syntax and diff PASS. Exact test containers, network and image tags
were removed and verified absent. **Independent Sol Reviewer:** Functional
PASS / Tests PASS / Clean Break Architecture PASS after direct diff, ADR,
business-boundary and build inspection. **Root acceptance:** **PASS for Phase 7
legacy-runtime removal and explicit later-phase handoff only.** The prior
`ae574cb8` FAIL below remains historical evidence under the earlier expanded
gate; it is superseded for current Phase 7 exit by this prospective gate and
new tests. Phase 8 may begin only within its separate archive/resource and
authorization gate. Adapter generic lifecycle/context ownership, Backend
mixed runtime tables, full 0.10 architecture and Golden functionality remain
unaccepted Phase 10/14/17 obligations.

## Phase 7 scope correction (2026-09-28; prospective gate)

The maintainer identified that the earlier overall review had expanded Phase 7
into a full three-service redesign. The `ae574cb8` FAIL below remains the
historical verdict under that earlier gate; it is not retroactively changed to
PASS. The current Phase 7 exit review uses this finite checklist:

1. Confirm the identified legacy Agent replay/recovery, child takeover,
   compatibility routes and dead persistence paths are removed with their
   existing bounded Tester/Reviewer evidence.
2. Inspect the remaining Adapter, Gateway and Backend live state once and
   classify each as transient DSH transport correlation, BYQ business-call
   authorization/terminal receipt, or generic Agent lifecycle ownership. Test
   ownership of session/run/generation/child status and decisions as well as
   recovery/replay; in-memory state is not automatically mere correlation. A
   symbol name or retained database table is not itself a failing finding.
3. Remove any remaining identified legacy recovery/compatibility behavior with
   a targeted contract. Keep the exact business close fence and
   `outcome_unknown`. Record any remaining generic Agent lifecycle owner as an
   explicit unresolved Phase 10 blocker; Phase 7 may pass only for its bounded
   legacy-removal scope, not for the final Clean Break architecture. Record old
   runtime schema cleanup for Phase 14.
4. Run only the affected architecture/contract checks, then independent Sol
   Reviewer and Root acceptance for Phase 7's stated scope. Phase 8 stays
   closed until this review passes. Full architecture acceptance remains gated
   on Phase 10/14 and the final simplification audit.

Do not add Job/Worker, Artifact, Approval/Audit, Workspace reset, dev rebuild,
full Golden scenarios, DSH cross-process attach/rebind, or broad Backend/Gateway
rewrites to the Phase 7 exit gate.

**Documentation correction gate:** 198 architecture checks and `git diff --check`
PASS. Independent Sol Reviewer: Functional PASS / Tests PASS / Clean Break
Architecture PASS for this prospective gate wording after inspecting the actual
diff and ADR-001/002. Root accepts the finite scope correction only. No runtime
code or Phase 7 overall acceptance is claimed; the historical FAIL below and
Phase 8 CLOSED status remain in force.

## Phase 7 overall re-review after .238 (2026-09-28)

**Reviewed HEAD:** `ae574cb8` in the isolated Clean Break branch.
The `.237` and `.238` deletion slices passed their bounded gates.
**Independent Tester:** Functional FAIL / Tests FAIL for overall acceptance /
Clean Break Architecture FAIL. **Independent Sol Reviewer:** the same overall
verdict after direct code, current ADR-002 and ownership-plan inspection.
**Root acceptance:** NO PASS for Phase 7 overall; Phase 8 remains CLOSED.
The overall Tests FAIL means the remaining live cutover has no acceptance
evidence yet; it does not negate the passing `.237`/`.238` tests.
Phase 7 does not gate on Job/Worker, Artifact, Approval/Audit, Workspace
reset, dev-environment rebuild, final schema baseline, or Golden scenarios;
those belong to later phases.

The remaining live owners are Adapter `RuntimeSession`/`ActiveRun`/generation
management, Backend `agent_runtime_turns` with domain-call authorization
dependencies, and Gateway durable lifecycle/domain-evidence delivery. The
current exact Backend root-close and ACK path is an authorization fence; its
retention is required until a tested replacement atomically revokes the exact
business root. The next bounded vertical slice cuts only the generic Agent
root-lifecycle dependency from BYQ business-call authority. It must preserve
exact boot revocation, terminal receipt, and unknown-outcome admission across
the Backend boundary and the Adapter/Gateway transport. It does not require a
general Backend or product-domain rewrite. This finding is an ownership and
evidence gap, not a finding that the retained business guard is unsafe.

## Phase 7 dead persistence deletion gate (2026-09-28)

[Bounded evidence](phase7-dead-persistence-evidence.md) records deletion of
disconnected Adapter containment/epoch disk stores and the old takeover tool,
retention of live in-process fencing and budget guards, pinned historical
provenance, selected `.238` build qualification and scoped image cleanup.

**Tester:** PASS — 131 focused historical, architecture and build tests,
selected `.238` and frozen `.237` checks, and diff check. Root's disposable
`.238` image passed embedded-identity and removed-module checks; affected
Adapter tests passed 95 with 10 skips, and the image was removed.
**Independent Sol Reviewer:** Functional PASS / Tests PASS /
Clean Break Architecture PASS after direct staged and unstaged diff,
interface, provenance, build and evidence inspection. **Root acceptance:**
PASS for this bounded dead-persistence deletion only. Phase 7 overall remains
OPEN and Phase 8 CLOSED.

## Phase 7 Adapter journal cutover gate (2026-09-28)

The maintainer explicitly accepted deleting Adapter persistence safeguards and
abandoning cross-process Adapter recovery. [Current evidence](phase7-journal-cutover-evidence.md)
records the `.237` source cutover, unit/architecture checks, three isolated
Compose scenarios, and scoped cleanup. Earlier entries below record the
historical decision before that authorization and are superseded for this
specific journal-removal question.

**Tester:** PASS for bounded live-path cutover, selected `.237` manifest,
focused checks, syntax and diff; Root's three disposable Compose scenarios
passed and their resources were removed. **Independent Sol Reviewer:**
Functional PASS / Tests PASS / Clean Break Architecture PASS after direct
diff, interface, build, test and evidence inspection. **Root acceptance:**
PASS for this bounded journal-removal slice. Disconnected containment,
executor identity, operator scripts and settlement persistence helpers remain
for separate Phase 7 deletion review. Phase 7 overall remains OPEN; Phase 8
remains CLOSED. No existing DB/backup cleanup, push, merge, or deployment.

## Phase 7 journal cutover and final old-DB archive (2026-09-28)

The maintainer authorized discarding old Agent sessions and all BYQ user-state
data, including accounts and global configuration. The current Product DB volume
selected by the local `.env` is `byq-postgres-clean-20260904`; it was shut down
and copied read-only. Its final logical archive is
`/home/jefison/backups/byq-clean-break-final-20260927T234310Z/byq-domain.dump`
(SHA-256 `0d62af957f545da40fc13083914c1d4cc614f04414fe6806d36bc772a4d06183`).
The archive's private read-only manifest records the source identity, 119
public tables and a successful isolated full restore with selected row counts.
Both temporary database volumes and containers were removed. The original DB
volume and all user data remain untouched; no Phase 8 cleanup began.

An attempted source patch to remove `LifecycleJournal` imports and stale-lease
protection was rejected by automatic approval review. The stated concern was
loss of live cross-process authorization/recovery protections and possible
duplicate or unauthorized business calls; data-cleanup authorization alone
was judged insufficient for that code-level change. No source change was made
and no workaround was attempted. **Root gate:** Phase 7 remains OPEN and
Phase 8 CLOSED pending explicit code-cutover authorization and the required
Tester → independent Reviewer → Root acceptance.

## Phase 7 lifecycle ownership cutover review (2026-09-28)

Gateway now sends lifecycle evidence from its live Adapter event collector only;
the old lifecycle delivery worker and public status route are removed. Its
same-boot reconnect uses capped backoff and stops on release or boot change.
Adapter reaps released sessions after exact domain-call and terminal receipts,
while exact ACK response-loss retries remain idempotent. Selected build `.236`
binds this worktree; `.233`–`.235` are frozen intermediate candidates.

**Tester:** PASS — Gateway 284/284, Adapter root lifecycle 10/10,
architecture/build 86/86, three named reconnect/ACK/boot-fence regressions
3/3, and `git diff --check`. Containers used cached images, disabled
networking, and mounted the worktree read-only. **Independent Sol Reviewer:**
Functional PASS / Tests PASS / Clean Break Architecture FAIL. The Adapter still
writes and reads `LifecycleJournal` and exposes `/recover-evidence`; automatic
approval review twice rejected deletion of that path because it could remove
cross-process authorization and `outcome_unknown` protections. **Root gate:**
FAIL for the ownership cutover and Phase 7 overall. Phase 8 remains CLOSED.
No database, existing data, backup, production service, push or merge changed.

## Phase 7 Gateway carrier retirement gate (2026-09-28)

[Bounded evidence](phase7-gateway-carrier-retirement.md) removes the historical
Gateway recovery-carrier module and live import. An old carrier stops after
exact original receipt reconciliation, before dispatch or prompt; ordinary
first dispatch remains. Historical evidence reads its pinned source from Git.
Focused Gateway image tests passed 31/31, historical unittest 12/12 and
observer self-check passed. Selected `.232` freezes changed source; `.231`
remains immutable.

**Tester:** PASS — historical unittest 12/12, current/frozen build tests 12/12,
architecture 74/74, historical observer self-check with 25/25 negative
controls, syntax and diff checks. Root's isolated Gateway image run passed
31/31. **Independent Sol Reviewer:** Functional PASS / Tests PASS / Clean Break
Architecture PASS after direct staged-diff, historical-source, receipt and
build review. **Root acceptance:** PASS for Gateway carrier retirement only.
The live Adapter journal, Gateway lifecycle delivery and Backend authority
fence remain; Phase 7 overall OPEN and Phase 8 CLOSED.

## Phase 7 Product MCP unknown-claim evidence gate (2026-09-27)

[Bounded evidence](phase7-product-mcp-unknown-claim-evidence.md) follows a real
Gateway Product turn and four Product MCP calls to one durable `executing`
strategy-validation claim. A test-only Backend callback exception produces
non-retryable `outcome_unknown`; Adapter PID-1 loss and a fresh boot leave the
old root/run revoked, that exact claim unchanged, zero artifacts and zero MCP
replay. The disposable stack and its images/credentials were removed. Selected
`.231` embeds its exact build identity; `.230` is frozen.

**Tester:** PASS — 12 focused build/retirement tests, 74 architecture tests,
syntax, shell and diff checks, selected `.231` and frozen `.230`. Root's
disposable Product MCP integration probe and separate `.231` image identity
check passed. **Independent Sol Reviewer:** Functional PASS / Tests PASS /
Clean Break Architecture PASS after direct staged-diff, contract, fixture,
build and evidence inspection. **Root acceptance:** PASS for this bounded
unknown-claim/Adapter-loss proof only. The injected exception does not prove
arbitrary power loss or external side-effect rollback; live journal, Gateway
lifecycle delivery and Backend authority fences remain. Phase 7 overall OPEN;
Phase 8 CLOSED.

## Phase 7 late domain-proof regression gate (2026-09-27)

[Bounded evidence](phase7-late-domain-proof-evidence.md) restores inert late
proof ingestion for exact existing-claim `unknown` receipts while new claims
and domain writes still require active root authority. Fresh isolated
PostgreSQL tests passed 47/47; current build/architecture tests passed 86/86.
Selected `.230` and frozen `.229` checks passed; disposable resources were
removed.

**Tester:** PASS for staged whitespace, syntax, docs, selected/frozen build
checks and 86 focused build/architecture tests; Root's disposable PostgreSQL
run passed 47/47. **Independent Sol Reviewer:** Functional PASS / Tests PASS /
Clean Break Architecture PASS after direct staged-diff and authority review.
**Root acceptance:** PASS for inert late evidence and exact existing-claim
reconciliation only. New claims and writes still require active authority.
The final cutover and post-deletion `outcome_unknown` proof remain unaccepted.
Phase 7 overall stays OPEN; Phase 8 stays CLOSED.

## Phase 7 executable recovery-carrier retirement gate (2026-09-27)

[Bounded evidence](phase7-carrier-retirement-build229-evidence.md) removes
Backend/Adapter recovery allocation and re-admission while keeping legacy rows
fail-closed at the domain-call and Gateway boundaries. Original reservation
reconciliation and unknown-outcome liability remain. Disposable Gateway 30/30,
Backend target 8/8, Adapter 12/12, historical evidence 24/24, and current build
and architecture 86/86 passed. Selected `.229` image identity and frozen `.228`
were verified; the disposable project was removed.

**Tester:** PASS for staged whitespace, syntax, docs, selected/frozen build
checks, 24 historical tests and 86 build/architecture tests; the recorded
Compose target runs passed Gateway 30/30, Backend 8/8, Adapter 12/12.
**Independent Sol Reviewer:** Functional PASS / Tests PASS / Clean Break
Architecture PASS for this bounded slice after direct staged-diff, boundary,
historical evidence and build-identity review. **Root acceptance:** PASS for
retirement of executable recovery-carrier paths and legacy-row rejection only.
The broader Backend run's unrelated active-root expectation failure remains
recorded; no full Backend suite PASS is claimed. The retained dead positive
contract helpers and final journal/authority cutover remain Phase 7 work.
Phase 7 overall stays OPEN; Phase 8 stays CLOSED.

## Phase 7 no-replay and build-identity repair gate (2026-09-27)

[Bounded evidence](phase7-no-replay-build227-evidence.md) removes Gateway's
automatic lost-reservation Agent prompt replay, preserves exact original
receipt/charge reconciliation and ordinary first dispatch, and creates immutable
selected build `.227` without rewriting `.226`. Isolated Gateway tests passed
30/30; 13 focused build tests and a disposable `.227` image/embedded-ID check
passed. Both test projects and temporary credentials were cleaned.

**Tester:** PASS for staged whitespace, local syntax, docs, 86 focused
root tests, and current/frozen build checks. Host Gateway/Backend tests lacked
FastAPI/SQLAlchemy; Root's isolated Gateway Compose run passed 30/30.
**Independent Sol Reviewer:** Functional PASS / Tests PASS / Clean Break
Architecture PASS for this bounded slice after inspecting the staged diff and
build identities. **Root acceptance:** PASS for no automatic lost-turn replay
and immutable `.227` selection only. Remaining Backend/Adapter recovery carrier
and final authority-fence deletion are not accepted by this gate. Phase 7
overall stays OPEN; Phase 8 stays CLOSED.

## Phase 7 overall acceptance attempt (2026-09-27)

**Reviewed HEAD:** `f418f0e3` on `clean-break/runtime-simplification`.
This is an overall phase gate, separate from the bounded slice PASS records below.
The review was read-only; no database, container, volume, backup or Product
service was changed, and no Phase 8 work began.

**Functional: FAIL for phase completion.** The accepted removal scope is not
finished. Adapter still owns `RuntimeSession`/`ActiveRun`/generation and a
session map (`services/runtime-adapter/app/runtime.py`), with a live v4
`LifecycleJournal`; Gateway still owns lifecycle recovery and durable delivery
(`services/gateway/app/main.py`, `agent_lifecycle_delivery.py`); Backend still
stores generic `agent_runtime_turns`/registration/receipt state
(`services/backend/app/agent_research.py`). Gateway's lost-reservation recovery
carrier also still has a path that submits a prompt and needs an explicit
ADR-002 disposition. The journal → Gateway → Backend path is currently a
business-call authorization fence, so none of these live pieces may be deleted
without the same-slice replacement and outcome-safety proof required by
[the authority cutover contract](phase7-authority-cutover.md).

**Tests: FAIL for overall gate.** Bounded live evidence passes Adapter death and
Product MCP silence, Gateway-only restart with an active root, and normal
`completed` exact close after a lost response. It does not test the final
post-deletion boundary or `outcome_unknown` after that cutover. The independent
Tester ran the historical archive contract (3/3 PASS) and docs check (127
changed Markdown files PASS). Current selected build revision `.226` failed
`tests/test_current_build_revision.py` (2 pass, 1 error): its manifest omits
11 Phase 7 evidence/fixture inputs and hashes drift for Backend main, the
Backend rotation test, and the MCP domain wire test. The independent Sol
Reviewer reproduced selected-build drift; local CI checks this identity before
image build. Branch-wide `git diff --check origin/main...HEAD` and
`dev-check.py --base origin/main` also fail on an inherited trailing blank line
in `services/backend/tests/test_research_plan_approval_contract.py:57`.
Focused Gateway host tests were NOT_RUN because FastAPI is unavailable in the
host environment; no full Docker or database test was rerun for this review.

**Clean Break Architecture: FAIL for phase completion.** The live generic
session/journal/replay ownership is still present, although bounded boot
rotation and exact close paths exist. The independently qualified transient
`ChildLease` watchdog is allowed by ADR-002 and is not a blocker. No current
authorization bypass was demonstrated; the blocker is that the current safety
fence has not yet been replaced and removed.

**Independent Sol Reviewer:** Functional FAIL / Tests FAIL / Clean Break
Architecture FAIL after direct code, ADR, contract, evidence and selected-build
inspection. **Root acceptance:** **NO PASS for Phase 7 overall**. Phase 7 stays
OPEN and Phase 8 stays CLOSED. Next, repair current build identity/branch gate,
resolve the lost-reservation replay disposition, complete the business-authority
cutover with unknown-outcome and concurrent-claim proof, then delete the
remaining generic Adapter/Gateway/Backend runtime owners in bounded slices and
repeat this overall gate. Prior slice PASS records remain valid only for their
stated boundaries.

## Phase 7 normal terminal close lost-response gate (2026-09-27)

[Live evidence](phase7-terminal-close-lost-response-evidence.md) exercises a fresh
six-service disposable Compose project through Product API, real Product MCP,
DSH and the Backend. A test-only private proxy forwarded the first exact root
close to Backend, received its 200 receipt, then dropped the Gateway response.
Backend root and fingerprint-bound AgentRun were already closed while Adapter
had no terminal ACK, Gateway retained one pending event, and a same-session
prompt was blocked with 409. A test-gated retry returned 503 without Backend
forwarding; after host release, an identical retry received the original
Backend receipt, Adapter journal acquired that ACK, and Gateway delivery became
`up_to_date`. The provider made no duplicate request. Six containers and all
project volumes, networks, images and temporary credentials were cleaned.

**Tester:** bounded PASS after direct six-file review, syntax/AST,
`dev-check`, docs and diff checks; the initial counter-label defect was fixed
and rechecked. **Independent Sol Reviewer:** Functional PASS / Tests PASS /
Clean Break Architecture PASS after direct interface, ADR, fixture, evidence
and incremental counter-label review. The reviewer did not rerun Docker; the
live Compose run and scoped teardown were performed by Root. **Root acceptance:**
**PASS for this normal terminal lost-response evidence slice only**. Phase 7
overall is OPEN; Phase 8 is CLOSED.

## Phase 7 active-root Gateway-only restart gate (2026-09-27)

[Live evidence](phase7-gateway-active-root-restart-evidence.md) uses a fresh,
scoped five-service Compose project. A durable test user starts a Product API
turn; real DSH calls Product MCP `byq_agent_run_start`; the Backend holds one
active root and one fingerprint-bound active AgentRun. The scripted model then
blocks. Restarting Gateway alone preserves the Adapter boot, Backend authority
epoch, root and AgentRun. The competing Product turn is rejected at Adapter
prompt admission with 409, and authenticated model request count stays 2→2.
The test project, volumes, network, images and temporary credentials were
cleaned; no Product runtime source or schema was changed.

**Tester:** bounded PASS for syntax, fail-closed runner preflight, staged diff
and evidence consistency; Docker was run by Root, not independently by Tester.
**Independent Sol Reviewer:** Functional PASS / Tests PASS / Clean Break
Architecture PASS after inspecting the actual final diff, schema, Compose,
credential boundary and ADR alignment. **Root acceptance:** **PASS for this
active-root restart evidence slice only**. Unknown-outcome roots, exact terminal
close, lost-response retry and old journal/replay removal remain open. Phase 7
overall is OPEN; Phase 8 is CLOSED.

## Phase 7 remaining authority cutover design gate (2026-09-27)

[Candidate contract](phase7-authority-cutover.md) traces the still-live Adapter
journal → Gateway lifecycle delivery → Backend root authority path. The first
candidate used a fresh per-call Adapter proof; Tester and independent Sol
Reviewer passed that **design-only** boundary, and Root accepted its safety
constraints in commit `811b12c9`. A subsequent supported-topology audit found
a simpler Compose-scoped alternative: Adapter is PID 1 in a private PID
namespace, so a killed container has no surviving DSH caller. The candidate
document now specifies this alternative, requires real container death proof,
Gateway-only restart behavior, Backend revocation-before-new-turn and exact
normal terminal close. **Tester:** revised design/static PASS (`check-docs.py
--base HEAD`, diff checks and effective Compose resolution). **Independent Sol
Reviewer:** Functional PASS / Tests PASS for design only / Clean Break
Architecture PASS after actual ADR, Compose, Dockerfile and credential-boundary
review. **Root acceptance:** PASS for the revised design boundary only. Phase 7
overall and Phase 8 remain closed; the current exact-root authorization fence
stays until the revised implementation passes its full gate.

## Phase 7 slice 10 gate — pinned foreground child process (2026-09-27)

[Slice record](phase7-live-child-process.md) adds an opt-in test against the
locked DSH 0.1.5rc1 Product composition. A real foreground child starts and
finishes; a blocked child hits its dedicated inactivity deadline or hard
cancel; each path closes the owned root process and rejects late success. No
Product runtime, DSH API, schema or status semantics changed. Current build
`.225` binds the test and CI invocation; `.224` is frozen.

**Tester:** isolated real DSH 3/3, ChildLease 6/6 and focused process cleanup
3/3 in its intended session fixture mode PASS. The initial combined cleanup
run had three fixture setup errors under root-turn mode; the corrected
session-mode run passed. Current/frozen build, 13 focused identity/CI checks,
docs, slice `dev-check` and diff checks PASS. Full Product/Backend/browser
journeys and remote CI are **NOT_RUN**. **Independent Sol Reviewer:**
Functional PASS / Tests PASS with those limits / Clean Break Architecture PASS
after direct test, CI, manifest and boundary review. **Root acceptance:**
**PASS for slice 10 only**. `ChildLease` remains the bounded, transient process
watchdog under ADR-002. Phase 7 remains open; Phase 8 remains closed.

## Phase 7 slice 9 gate — historical journal adoption and lease repair (2026-09-27)

[Slice record](phase7-journal-legacy.md) removes v1–v3 lifecycle-journal
migration, old-session lease reanchor, boot-stale archive operators and their
historical tests/runbook. The current v4 evidence journal, exact terminal ACK,
epoch write fence and Adapter → Gateway → Backend root authorization closure
remain. A missing executor epoch cannot bootstrap over any existing journal.
Current build `.224` binds the new source; `.223` is frozen. No database,
volume, container or Product API changed.

**Tester:** focused journal/executor 28/28, build identity 7/7, selected
architecture 3/3, `.223`/`.224` identity, slice `dev-check`, documentation and
diff checks PASS. Gateway lifecycle delivery 11 PASS; three host-only cases
could not import FastAPI, and focused Adapter process cleanup could not import
`deepseek_harness` on the host. The killed-Adapter → Gateway → Backend wire
journey is **NOT_RUN** because its live Backend/test environment is absent;
this is an integration limit, not a claimed PASS.
**Independent Sol Reviewer:** Functional PASS / Tests PASS with that limit /
Clean Break Architecture PASS after direct diff, caller, contract, build and
authorization-boundary review. **Root acceptance:** **PASS for slice 9 only**.
Old v1–v3 evidence must not be mounted into the fresh 0.10 environment with
active Backend roots. Phase 7 remains open; Phase 8 resource cleanup remains
closed.

## Phase 7 slice 8 gate — remove legacy terminal ACK migration (2026-09-27)

Gateway lifecycle delivery no longer scans old trace events to migrate the
pre-Clean-Break memory-only terminal ACK format, nor reports a fresh ledger as
pending solely because a migration flag is absent. Current exact Backend
receipt → Adapter terminal ACK delivery, finite retry and `outcome_unknown`
behavior remain. A fresh ledger reports `up_to_date`. The current immutable
build identity is `.223`; `.222` and earlier identities remain frozen.

**Tester:** Gateway delivery/trace 19/19 and focused Product cases 15/15 PASS;
the final fresh-ledger status assertion 1/1 PASS. Current/frozen build and 18
focused identity checks PASS; no removed production migration keys remain.
**Independent Sol Reviewer:** Functional PASS / Tests PASS / Clean Break
Architecture PASS after direct diff and exact receipt/retry review. **Root
acceptance:** **PASS for slice 8 only**. Phase 7 remains open; Phase 8 remains
closed.

## Phase 7 child watchdog disposition gate (2026-09-27)

[ADR-002](adr/ADR-002-dsh-boundary.md) and the
[ownership plan](ownership-and-deletion-plan.md) now retain the transient
`ChildLease` process watchdog under pinned DSH 0.1.5rc1. DSH executes the
child; the Adapter only validates live progress, bounds inactivity and closes
its dedicated root process on timeout. It does not persist or recover child
execution. A single root deadline cannot preserve the current long-progress
and sibling-stall behavior. This is a **KEEP qualification**, not a new runtime
implementation or approval to delete the guard.

**Tester:** docs check PASS, architecture 198/198, pinned SDK Adapter
`test_child_lease.py` 6/6 and focused cleanup 26/26, Gateway projection 31/31,
diff check PASS. Real DSH child-timeout Product journey **NOT_RUN**.
**Independent Sol Reviewer:** Functional PASS / Tests PASS for documentation
scope / Clean Break Architecture PASS after direct diff and runtime boundary
review. **Root acceptance:** **PASS for this retention decision only**. Phase 7
remains open; Phase 8 remains closed.

## Phase 7 slice 7 gate — dead restart rebase paths (2026-09-27)

After slice 6 removed old-session rebind, `RuntimeAdapter._record_containment`
and `LifecycleJournal.rebase` had no production callers. This slice deletes
those methods, the sole-use import and the obsolete rebase test. Containment
reads, terminal receipts, `outcome_unknown` and live business recovery remain.
The current immutable build identity is `.222`; `.221` is frozen.

**Tester:** pinned DSH 0.1.5rc1 Adapter focused tests 62/62 PASS, no remaining
references to the removed methods, 18 build identity checks and current/frozen
build validation PASS. **Independent Sol Reviewer:** Functional PASS / Tests
PASS / Clean Break Architecture PASS after direct diff and business recovery
review. **Root acceptance:** **PASS for slice 7 only**. Phase 7 remains open;
Phase 8 remains closed.

## Phase 7 slice 6 gate — lost Agent session does not replay (2026-09-27)

The 0.10 interruption scope now ends the old Agent session when its Adapter
process state is lost. Gateway attaches only to a surviving in-memory Adapter
session; a lost session returns `409 agent_session_interrupted` on attempted
operations and never recreates the old ID or reposts the original prompt.
Exact prompt receipts remain readable for `outcome_unknown`, and an authorized
new Agent session may query durable BYQ Jobs by `job_id`. Live resume and
child timeout/cancellation remain in place. No terminal trace event is
fabricated from an unproven process loss. The current build identity is `.221`;
frozen `.215`–`.220` are unchanged.

**Tester:** focused Gateway 54/54 and pinned DSH 0.1.5rc1 Adapter 55/55 PASS
with read-only source mounts; 18 focused build checks, `.221` current and
frozen build identities, documentation check and diff check PASS. **Independent
Sol Reviewer:** Functional PASS / Tests PASS / Clean Break Architecture PASS
after actual diff, Product identity, receipt, ADR and build review. **Root
acceptance:** **PASS for slice 6 only**. Phase 7 remains open for further
runtime simplification and live child qualification; Phase 8 remains closed.

## General development verification policy gate (2026-09-27)

The maintainer extended risk-selected verification to all later BYQ development.
The [general workflow](../DEVELOPMENT_WORKFLOW.md#通用风险分级验证门禁)
now assigns focused local checks to each slice, complete affected-component
suites to required PR CI, and clean rebuild/Golden evidence to the relevant
phase milestone. The [CI policy](../operations/ci-policy.md) still requires
its selected checks; real UI journeys, security/financial invariants, retained
user-data safety, release Full CI and human merge/deployment gates remain.

**Tester:** `check-docs.py --base HEAD` PASS (4 Markdown files after the gate
record was added),
`dev-check.py --base HEAD` PASS (0 changed code files), `git diff --check HEAD`
PASS, architecture unittest 198/198 PASS; change classifier selected docs and
architecture only. Default branch-wide diff still finds the unrelated existing
blank line documented below. Product suites and hosted PR CI were NOT_RUN for
this documentation-only local change. **Independent Sol Reviewer:** Functional
PASS / Tests PASS for policy scope / Architecture PASS after direct diff and
ADR-0070/0088, CI, UI and data-safety review. **Root acceptance:** PASS for
the general verification-policy change only. Phase 7 remains open; this does
not authorize push, merge, deployment or historical-data deletion.

## Clean Break verification policy gate (2026-09-27)

The maintainer directed a lighter development-period gate: committed source
rollback and a rebuildable fresh Compose environment, without old user/runtime
data or cache restoration. [The verification policy](verification-gates.md)
now requires a scoped local check and focused contract evidence per slice,
retains required risk-selected hosted CI and Tester → independent Sol Reviewer
→ Root PASS, and schedules full rebuild/Golden verification after the fresh
schema baseline. This changes verification timing, not Product architecture,
financial/authorization invariants, archive requirements or merge authority.

**Tester:** changed-document links and whitespace PASS; Clean Break governance
2/2 and architecture 198/198 PASS; slice-scoped `dev-check.py --base HEAD`
PASS (no changed code files; component suites NOT_RUN). Default branch-wide
`make dev-check` finds a pre-existing trailing blank line in
`services/backend/tests/test_research_plan_approval_contract.py:57`, outside
this slice. **Independent Sol Reviewer:** Functional PASS / Tests PASS for
documentation scope / Clean Break Architecture PASS after direct diff and
ADR-0088/CI/phase-plan consistency review. **Root acceptance:** PASS for
the verification-policy change only. Phase 7 overall remains open; no runtime
code, database, container, CI workflow, PR or merge changed in this slice.

## Phase 7 slice 5 design gate — historical event/P4 archive (2026-09-27)

[Candidate design](phase7-historical-event-archive.md) passed the read-only Explorer → static Tester → independent Sol Reviewer → Root **design** gate. Before deletion, the same-slice contract test ran RED: the live ResearchTask action/approval boundary passed, all eight scoped archive paths remained, and replay READMEs lacked the pinned source pointers. The exact obsolete event contract, paired test, P4-A/B/C1 script directories and top-level harness tests are now deleted. Replay docs and the runtime-adapter test docstring pin historical source to `2f8aca4a877d01481be556236c8f56d6ad7fa290`. The post-delete contract (3/3), architecture/static/build checks (95), `.220` plus frozen `.215`–`.219`, historical release inputs, H4 (570/570; zero missing/stale/fake-pass) and diff check pass. **Tester:** isolated PostgreSQL 45/45, complete Gateway 275/275, repository unittest 868 OK (11 skipped), post-delete archive contract 3/3, `.220` and frozen `.215`–`.219`, historical release inputs, H4 570/570 (zero missing/stale/fake-pass), Compose selected Dockerfile and diff checks PASS. A real temporary worktree cleanup smoke also passed after Tester found a replay README cleanup defect and Root fixed it. **Independent Sol Reviewer:** Functional PASS / Tests PASS / Clean Break Architecture PASS after actual diff, frozen manifests, historical pointers and final README review. **Root acceptance:** **PASS for slice 5 only**. Phase 7 overall remains open for DSH Agent continuation and other live ownership work; Phase 8 remains closed.

## Phase 7 slice 4 gate — ResearchTask business action (2026-09-27)

The current event-state continuation ledger and its production imports are removed. A plan-bound approval and its exact ResearchTask action now commit atomically; identical decision POSTs can retry the pending action, while conflicting replays and missing actions fail closed. Product API exposes the action status without handing settlement to DSH. Historical P4 scripts and the unused event contract remain for a later bounded archival decision.

**Tester:** isolated PostgreSQL 45/45, complete Gateway 275/275, repository unittest 918 OK (11 skipped); current `.219` build, historical release inputs, H4 570/570 with zero stale/fake entries, and diff check PASS. **Independent Sol Reviewer:** Functional PASS / Tests PASS / Clean Break Architecture PASS after direct diff, SQL, Product projection and schema review. **Root acceptance:** **PASS for slice 4 only**. Pending actions require an identical decision POST for retry; `waiting_for_agent` and `needs_attention` remain unresolved. Phase 7 overall remains open because public DSH Agent attach/resume and child rebind contracts are absent; Phase 8 remains closed.

[Candidate design](phase7-pending-business-action.md) passes the read-only Explorer → static Tester → independent Sol Reviewer → Root **design** gate. Its approved boundary replaces event-as-state only with BYQ-owned pending business action, preserves exact approval/Job proof and unknown-outcome safety, and explicitly excludes DSH Agent continuation. A subsequent transaction/schema review selected one task-owned `research_task_actions` table with an atomic approval/action write, pending-only reconciler, stale-binding fail-closed rule and common lock order; independent Sol Reviewer marked that schema design GO. The design gate was followed by the tested slice implementation above. Phase 7 overall and Phase 8 remain closed.

## Phase 7 next live deletion qualification (2026-09-27)

After slice 3, read-only Explorer audits found no further standalone safe deletion in workflow, plugin, Backend runtime receipts or current DSH compatibility. Those paths carry live ResearchTask state, domain-call authorization, Product contracts or selected SDK/build provenance. `child_lease.py` is a live timeout and correlation guard; [its qualification record](phase7-child-lifecycle-qualification.md) is **NO-GO** for removal with locked DSH 0.1.5rc1. An official tagged-release check found that v0.1.7-rc.2 also lacks the required public Python root attach/resume/cancel/status and durable child rebind/status/cancel contract. Independent Tester verified the note and sources; independent Sol Reviewer returned Functional PASS / Tests PASS for documentation / Clean Break Architecture PASS and agreed the broader deletion remains NO-GO. Root accepts this **investigation result**, not Phase 7 completion. Phase 8 remains closed. Reopen a live deletion slice only with an exact-release DSH contract and same-slice replacement tests, or a separately bounded BYQ business-state rewrite that preserves authorization and outcome safety.

## Phase 7 slice 3 gate — standalone containment/recovery URL removal (2026-09-27)

[Slice record](phase7-gateway-containment-routes.md) binds the deletion to final candidate `1a825125`. The two standalone Gateway GET paths and OpenAPI operations are removed. Owner-scoped `GET /v1/agent/sessions/{id}` remains the Product API for normalized trace replay and fail-closed containment classification; no Adapter, Backend, DSH or financial safety path changed.

**Tester:** independent focused checks PASS (33 tests, H4 570/570, historical release, frozen `.215`–`.217` and current `.218` build, Compose, diff); its separate full run encountered read-only `.ci-artifacts` write errors and a Node worker environment failure. Root verified the final candidate in the approved offline, read-only Gateway container: **274 passed**, and ran full repository unittest with writable test artifacts: **918 tests OK, 11 skipped**. **Independent Sol Reviewer:** Functional PASS / Tests PASS / Clean Break Architecture PASS after directly inspecting the corrected replacement-route H4/OpenAPI entry and `.218` source binding. **Root acceptance:** **PASS for slice 3 only**. Phase 7 overall remains open; no Phase 8 cleanup, DB change, push or merge is claimed.

## Phase 7 slice 2 gate — advisory generation history removal (2026-09-27)

[Slice record](phase7-generation-ledger.md) binds the deletion to candidate commit `a2d134ed`. The file-backed generation ledger and duplicate in-memory history are removed; active generation fencing, lifecycle journal, containment and business recovery remain. Historical `dsh-0.1.5rc1` inputs are pinned to the exact pre-Clean-Break Git tree, while current source is bound by build revision `.217`.

**Tester:** independent static/build checks PASS (architecture 195, H4 572/572, historical release, `.215`/`.216`/`.217` manifests, promotion, Compose and diff); its unprivileged environment could not access Docker. Root completed the approved offline, read-only container run: Runtime Adapter **283 passed, 52 skipped**. Post-commit full repository unittest: **918 tests OK, 11 skipped**. **Independent Sol Reviewer:** Functional PASS / Clean Break Architecture PASS on actual diff, interfaces and historical release boundary; its Tests verdict was pending the Docker run, now satisfied by Root verification. **Root acceptance:** **PASS for slice 2 only**. Phase 7 overall remains in progress. This gate does not authorize Phase 8 cleanup, old database changes, push, PR readiness or merge.

## Phase 7 slice 1 gate — Gateway private proxy removal (2026-09-25)

The maintainer explicitly approved deletion of the six private Gateway pass-through routes. [Slice record](phase7-gateway-proxy.md) names their replacement Product API and exact scope. The first gate failed on old `.215` build-source drift; it remained closed while current build `.216` was added with a revision-specific Dockerfile and tracked Compose override. Frozen `.215`, original Adapter Dockerfile, DSH release descriptor and `compose.yml` stayed byte-identical. The H4 current interface ledger now has exactly the six removed routes retired and 572 surviving interfaces reviewed with zero stale/missing/fake entries.

**Tester:** PASS — Gateway 274/274 in offline read-only container; full architecture unittest 918 OK with 11 existing skips before the final Compose override; independent post-override architecture 195/195; current `.216` and frozen `.215` build checks, DSH release historical-input and promotion checks, reliability auditor, Compose default/explicit/CI resolution, shell syntax and diff check PASS. **Independent Sol Reviewer:** Functional PASS / Tests PASS / Clean Break Architecture PASS on actual diff, build identity, frozen sources and historical-test scope. **Root acceptance:** **PASS for slice 1 only**. Phase 7 overall is still in progress; no full-stack smoke, browser Golden Scenario, Phase 8 resource cleanup or database cleanup is claimed. The next Phase 7 slice requires its own bounded design, Tester, Reviewer and Root acceptance.

## Current activation follow-up (2026-09-25)

The planning verdict below predates [ADR-0088](../architecture/adr/ADR-0088-clean-break-baseline-activation.md). ADR-0088 records the maintainer's explicit Clean Break direction and activates the six 0.10 ADRs on this branch. Of 87 old ADRs, 82 are historical Product Core records and five retain only non-product governance/security scope. The former CLOSED verdict below is the original Phase 0–6 snapshot, not the latest activation outcome.

**Activation gate:** Tester PASS (195 architecture tests, 2 explicit Clean Break governance tests, 73 legacy governance tests, 105 changed Markdown files checked, build-revision check and `git diff --check`); independent Sol Reviewer **Functional PASS / Tests PASS / Clean Break Architecture PASS** after examining the actual diff, governance/security carve-outs and build-identity regression fix; Root **PASS** for the accepted 0.10 architecture and Phase 7 entry. Phase 7 may now perform bounded code deletion only after a same-slice public-contract/replacement test and its own Tester → Reviewer → Root gate. No Phase 7 code deletion had begun when this activation decision was recorded. Phase 8 resource/data cleanup remains CLOSED until the actual DB/resource identity and verified final archive are proven. The explicit governance test lives under `docs/clean-break/validation/` and is a named phase-gate command, not part of default `unittest discover -s tests`.

## Original Phase 0–6 planning record

Recorded 2026-09-25. The first-round read-only investigations were parallel where independent; documentation was assembled in one isolated worktree. No Phase 7 destructive work began. `PASS` below certifies the stated **planning-phase deliverable**, not Product runtime functionality or activation of a Proposed ADR.

| Phase | Tester evidence | Independent Sol Reviewer | Root acceptance |
|---|---|---|---|
| 0 — Development framework | TOML parse/role assertions PASS; 195 architecture tests PASS. Current session actually used Luna max Explorers/Tester and Sol medium Reviewer with one-writer ownership. Fresh CLI strict-config loaded files, but automatic Explorer dispatch could not be proved (first attempt: thread registration error; second: claim without spawn event). | Design PASS; automatic role routing unverified. | **PASS for merged BYQ defaults and exercised manual orchestration**; fresh-session automatic routing remains an explicit follow-up before relying on it. |
| 1 — Freeze | `HEAD`, `origin/main`, local tag and Clean Break base all `d4c6a9e34f531d27dd0e94804be6ed0aa6f9fde3`; isolated worktree script PASS. | PASS; P4 branch preserved. | **PASS**; tag local only. |
| 2 — Environment inventory | TSV internal counts/columns PASS: 3 containers, 156 image refs/150 IDs, 45 volumes, 5 networks; independent Tester could not access Docker socket. | PASS as read-only snapshot with explicit unknown DB. | **PASS for inventory**; source Docker metadata was read under approved escalation; live state can change. |
| 3 — Final archive plan | Markdown link/format checks PASS; no backup claimed. | PASS as plan; DB source/backup unknown. | **PASS for plan**, not archive execution. |
| 4 — ADR baseline | Six proposed ADR links/structure checked; architecture suite PASS. | Clean Break design PASS; acceptance and canonical supersession pending. | **PASS for proposed baseline**; no old ADR is yet retired. |
| 5 — Runtime ownership audit | Evidence paths and categories checked; no product runtime test claimed. | PASS; business safety versus generic recovery distinguished. | **PASS for audit**. |
| 6 — Deletion plan | `git diff --check`, all new-file whitespace checks and links PASS. | Functional PASS; Clean Break Architecture PASS for design. Phase 7 replacement contract detail must be checked per slice. | **PASS for reviewed plan**; Phase 7 entry remains CLOSED. |

## Verification summary

- `python3 -m unittest discover -s tests/architecture`: 195 passed.
- `python3 scripts/ci/verify-worktree.py <clean-break-worktree>`: PASS.
- TOML syntax/model/effort/concurrency checks, Markdown links, TSV counts, all-file whitespace and `git diff --check`: PASS.
- `make dev-check`: exit 0, but `files: 0`/`component_tests: NOT_RUN`. The first invocation saw untracked files; a repeat after staging also reported zero because its syntax scanner covers Python, shell and JSON, while this package contains TOML, Markdown and TSV. It is not counted as coverage of those formats.
- No Product API, browser, DSH runtime or Golden Scenario was run. No DB backup or Docker cleanup was performed.

## Original planning outcome (before ADR-0088 activation)

**Functional: PASS for Phase 0–6 planning package. Tests: PASS for focused static/architecture checks. Clean Break Architecture: PASS for proposed design. Phase 7 implementation gate: CLOSED.** It opens only after the new ADR baseline is explicitly accepted and integrated, old normative docs are superseded, each live deletion has a replacement interface and passing contract test, and the actual DB/retention state is identified before any data/environment destruction. A final verified DB archive is required before old DB volume cleanup. Human PR/merge gates continue to apply.
