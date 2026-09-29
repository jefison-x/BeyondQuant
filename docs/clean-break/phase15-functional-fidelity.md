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
| A: Research, TuShare, Web Search, delegated Agent, interaction, Artifact | A fresh isolated Workspace completed a real TuShare import, two-turn DSH Product conversation with delegated research, Web Search, a saved evidence Artifact, normalized trace, and real browser replay/Artifact listing. See bounded evidence below. | The separate DSH Interaction plugin remains unqualified; ordinary Product follow-up passed. |
| B: two Backtests, optimization, comparison | A new Workspace Product API journey completed two independent BacktestJobs, one OptimizationJob and a persisted comparison Artifact. Real browser comparison of the exact two completed Backtest IDs and Artifact listing passed. See bounded evidence below. | DSH Agent-led strategy change and the OptimizationJob ranking's browser detail remain open. |
| C: TrainingJob, GPU, checkpoint/restart | Durable TrainingJob and independent ML Worker; process-reclaim tests use a fake trainer. Current host has no NVIDIA device, `nvidia-smi`, or Docker NVIDIA runtime; the current ML image installs CPU LightGBM. | Qualify CPU Worker/real checkpoint separately; GPU execution is `NOT_RUN` here and needs a GPU-capable Worker/image and host. CPU execution and simulated lease reclaim do not satisfy the GPU claim. |
| D: Agent interruption with Job continuing | In this fresh isolated stack, a separate Product API BacktestJob stayed queued after a contemporaneous Product Agent conversation was deleted; restarting its independent Worker completed the same Job in one attempt with an Artifact. After explicit authorization, a new DSH Agent used BYQ MCP read tools to find that exact Job and Artifact. | The Job was submitted through Product API, not initiated by the old Agent. Full Golden D and DSH process restart remain out of scope for this bounded check. |
| E: Runtime and Workspace reset | The populated browser reset, reseed and two-turn delegated Agent/Web research passed. A separate Workspace confirmed protected identity/config and exact deletion IDs. A subsequent Product reset of the Agent-audited Workspace now also passes while retaining the exact two Web evidence audit facts and deleting their disposable Artifacts. | Golden E's specified `reset → seed → rerun A` sequence and the bounded repeated-reset fix are local PASS; this does not complete the other Phase 15 journeys. |
| F: full rebuild | Exact-scope `dev-clean` apply removed only this isolated project's 12 containers, 4 volumes and 2 networks; `dev-init`/core start/seed/test and real login passed on a fresh schema. | The connected Golden journeys have not been rerun after rebuild. F environment lifecycle is bounded PASS; full Golden F remains OPEN. |

## Next bounded execution

1. Complete the Agent-initiated Job/interruption path and Agent-led strategy
   change. Qualify the existing CPU TrainingJob/Worker on new data; keep GPU
   execution and checkpoint/restart explicitly `NOT_RUN` until a qualified GPU
   environment is available for Phase 16.
2. Rerun connected journeys from a fresh schema after the now-proven scoped
   rebuild. Never substitute mocks or old database evidence for real Product
   functionality.
3. Finish Tester → independent Sol Reviewer → Root review, then PR/CI/merge
   before Phase 16.

## Bounded B Product API and Worker evidence (2026-09-29)

The isolated `backtest` profile first exposed two concrete failures. It omitted
the existing Optimization Worker. Once started, that Worker could not read
Backtest result objects because the writer created mode-0600 files under a
different numeric user. The profile now includes the Worker, result files are
mode 0640, and the read-only Optimization Worker belongs to the result reader
group. No world-readable object permission was introduced.

After those fixes, `scripts/evidence/phase15-backtest-optimization.py` ran
through authenticated Gateway/Product API on the new Workspace. It created two
versions of the **same** synthetic strategy with distinct parameter values and
explicit approvals; both worker-backed BacktestJobs completed and returned
their own result Artifacts. The OptimizationJob reached `SUCCEEDED` and the
Product Artifact list contained its exact `optimization_comparison` Artifact:

| Evidence | ID |
|---|---|
| Workspace | `workspace_e8de314c52a04292bd3915c9b4ae5261` |
| Backtest A | `backtest_0b0c99be8de74016a52c5d91dc176b81` |
| Backtest B | `backtest_77ba8ad5db4344a6ae5257c228470905` |
| Optimization Job | `optimizationjob_a3c3815395054836a44669291fa117c8` |
| Comparison Artifact | `artifact_675f2e2011ac491da773be5e8b5c3cd7` |

The synthetic bars are labeled as such. This proves the Product API and Worker
portion of B on fresh state. The final script also checked the comparison
Artifact's validated status, exact Workspace, exactly two ranked candidate Job IDs and
the `reran_backtests=false` provenance field. This Product API/Worker run alone
does not prove a DSH-led journey, live market data, a browser comparison view,
or the full Phase 15 functional gate. The separate browser proof is below. A first
attempt using different strategy definitions was rejected correctly by the
optimization contract. A second attempt found the file permission defect and
ended `FAILED`; neither failure was counted as passing evidence.

## Bounded A live research evidence (2026-09-29)

The fresh Phase 15 project `byq-dev-ea551690f4` received only the TuShare and
DeepSeek credential fields from the local ignored project configuration. Its
ignored `.env.dev` remained mode 0600; no credential value was recorded here.
After the isolated research profile became healthy, authenticated Gateway /
Product API `/api/product/data-center/source/test` returned `passed` for one
real TuShare daily row (`000001.SZ`, `20240102`, environment credential source).
This only qualified provider connectivity.

An admin Product API request then created the narrow DataImport Job
`sync_06defc0e99e34fa583b28d7a7afdc904` for that one symbol and trade day.
The independent Data Worker completed it with one result. A read-only query
against this **isolated** database confirmed the persisted row's close was
`9.21` and source `tushare`. No old database or historical cache was imported.

The authenticated Gateway created Product conversation
`conversation_d8b7af2075ab4ba79dc6058d3a0693b2`. Turn one delegated market
research and answered with the same `9.21` close from BYQ's synchronized data,
while qualifying that completeness and exchange-calendar checks were not
verified. Turn two followed up in the same conversation, searched official
Chinese regulatory pages, and saved a new `web_research_evidence` Artifact
`artifact_89070b7bf2c04b7aa67a48bd91668504`. The Artifact is a persisted
`draft` research record with seven sources and the exact usage policy
`research_only=true`, `deterministic_input=false`,
`authoritative_market_data=false`; its sources are not authoritative market
data.
An earlier one-turn fresh-state Web Search smoke also saved
`artifact_187bb24a8df84f88b3d157445faeb9f2` and passed its explicit
research-only usage-policy assertion.

Product replay returned the exact `user, assistant, user, assistant` sequence,
trace `byq-trace-9ae1de60bd784adfa5117fe555726306`, and 27 BYQ-normalized
events whose public `session_id` is the conversation ID.
The first turn contained `agent.activity` events for `市场研究 Agent` using the
`子 Agent 编排插件`, moving from `started` to `completed`, plus an
`agent.run.registration` event. The second turn recorded the market research
Agent's `网页研究插件` activity from `started` to `completed`.
A read-only audit
summary in the isolated database recorded one `byq_market_daily` authorized /
success pair, one `byq_web_evidence_create` authorized / saved pair, and two
active runtime-turn bindings for that trace. This is direct evidence of BYQ MCP
domain calls beyond the Agent's prose. The earlier Web smoke removed its
temporary conversation on exit; the two-turn conversation remains for further
Product checks.

## Fresh-state browser evidence (2026-09-29)

Before this build, `.dockerignore` was tightened to exclude local `.env.*`
files from all Docker build contexts; no Dockerfile needs those files. The
isolated frontend was built against the same scoped Gateway. The repeatable
`apps/frontend/tests/e2e/phase15-browser.mjs` journey used Playwright-managed
Chromium with real Product login and no request outside the Frontend/Gateway
origin (173 observed requests, zero off-origin). It reopened the conversation
and displayed both the `9.21` market answer and the information-disclosure
follow-up; the exact four-message sequence was proven by Product replay above.
In Backtest management it selected the exact two
completed Backtest IDs listed above and displayed the metric-comparison dialog.
The browser checked a numeric `累计收益` row for both Jobs and their computed
difference, beyond the dialog's static headings. Its same-origin Product
catalog response mapped each visible short Job reference to one unique exact
completed Job ID.
In the research asset list it found both the live Web evidence Artifact and
the OptimizationJob comparison Artifact by their exact IDs. The Product API
evidence above, rather than this list view, verified the comparison ranking's
content. A first browser attempt used the hidden Element Plus input and timed
out; the visible selection control was then used, and the final exact-ID
journey passed. This browser run made no provider calls and used no mocks.

The root accepted bounded A after a focused Tester PASS and an independent
Sol Reviewer Functional PASS / Tests and Evidence PASS / Clean Break
Architecture PASS. The separate DSH Interaction plugin and full Phase 15 gate
remain open. Browser evidence is a subsequent addition and needs its own
focused Tester / Reviewer check before a larger gate claim.

## Bounded D session-loss evidence (2026-09-29)

Only the isolated `backtest-worker` service was stopped. An authenticated
Product conversation `conversation_f0e7bac100814ca79afdbac6d1ea447b` was
created, then the same Workspace submitted and queued BacktestJob
`backtest_de673c799c54426d9a1fdec7f920a94b` with its Product trace.
The conversation was deleted while the Worker was stopped; Product API still
returned that separate Job as `queued`. Restarting the same isolated Worker led
to `completed` on attempt one, with result Artifact
`artifact_4c54364dd96046578a82d77a76f65651`. The deletion did not cancel
this Product API Job, and the independent Worker completed it.

The first new-Agent lookup was rejected by automatic approval review because
existing authorization did not explicitly cover sending the private Job ID
and result context to DSH/model; it was not attempted by an alternate route.
The maintainer then explicitly authorized this one isolated query. New Product
conversation `conversation_b51a8f2509df497ea72b4da36c6ce33f` used a new
trace and produced `读取回测状态` and `读取回测分析证据` BYQ MCP activity, both completed.
Its answer identified the exact same completed Job and result Artifact. The
Product API still returned that Job as `completed` on attempt one; a read-only
count found exactly one BacktestJob with this submission's name. No duplicate
of this named submission was observed.

This remains **short of full Golden D** because the Agent did not initiate the
BacktestJob: a browser-authenticated Product API call did. It does prove that
this separately submitted Job survived the contemporaneous conversation's
deletion, the Worker finished independently, and a new Agent found its result
by stable ID.

Bounded D gate: focused Tester **PASS** for documentation and local contracts;
independent Sol Reviewer **Functional PASS / Tests and Evidence PASS / Clean
Break Architecture PASS** for this scoped observation. Root accepts only that
bounded result. The full Golden D remains **OPEN**.

## Golden E first attempt and blocker (2026-09-29)

The existing real-browser Reset flow was run against the populated, fresh
Phase 15 isolated Workspace. Product Runtime reset returned HTTP 200, archived
two conversations, and left the generated ResearchTask available. The
subsequent Product Workspace reset returned HTTP 409. A read-only Backend
preflight on this exact isolated Workspace reported: `retained strategy
approval Artifact references a ResearchTask; reset would remove an
authoritative fact`. The B journey had created strategy approvals before
Backtest submission. No Workspace deletion occurred on this 409 path, and no
global or pre-existing database was involved.

This is a genuine populated-Workspace contract conflict: the current reset
deletes the ResearchTask/Artifact graph but retains authoritative approval
facts, so it refuses to remove that graph when it contains a strategy approval
Artifact. The fail-closed response is correct for the present contract. Golden
E was **FAIL/OPEN at this first attempt**. The bounded Product rerun below
resolves this approval blocker, and the later Golden E record closes its
specified sequence. The earlier Phase 13
browser test passed because its fixture created a plain ResearchTask without
strategy approval.

## Bounded E approval archive and populated Product reset (2026-09-29)

The authorized Phase 15 change adds an internal immutable archive for validated
`strategy_approval` and `ml_strategy_approval` facts. Each row retains the
complete source approval and exact validated strategy-version snapshots, both
content hashes, original timestamps, owner, Workspace and ResearchTask IDs.
The Product reset checks those relationships and versions, then archives them
before deleting the original ResearchTask/Artifact graph in the same fenced
transaction. Bad or cross-Workspace references block the reset; the archive is
not a Product Artifact and is not included in the deleted count. The offline
reset entry point assumes stopped writers; the Product path disables and fences
the Workspace before finalizing.

Two focused tests passed in disposable database `byq_domain_test_phase15_archive`
under Compose project `byq-dev-ea551690f4`: standard strategy approval with
Product release proof, and rejected ML strategy approval with a validated
version. They checked exact snapshots, a draft version blocker, a cross-Workspace
reference blocker, source removal, other-Workspace preservation, immutable
archive rows, delete counts and idempotent replay. Tester: **2 passed**; the
sole warning was a test-cache permission notice. `dev-check.py --base 2987d3c1`,
Python AST parsing and `git diff --check` passed. Independent Sol Reviewer:
**Functional PASS / Tests PASS / Clean Break Architecture PASS** for this
bounded archive slice. Root accepts that slice; Phase 15 remains open.

The isolated Backtest Workspace was then rerun through authenticated Gateway /
Product API after the new Backend started. Workspace reset returned HTTP 200
with two ResearchTasks, 11 Artifacts, two BacktestJobs and one OptimizationJob
deleted. The same idempotency key returned the same receipt, while the same
user and Workspace remained available. A read-only isolated PostgreSQL check
found exactly two distinct archive rows with matching approval/version content
hashes and zero ResearchTasks or Artifacts in the Workspace. `dev-seed`
subsequently created a fresh ResearchTask and two Artifacts in that same
Workspace. The former 409 blocker is resolved in this populated Product path.
At this bounded Product check, the connected browser/research journey had not
yet run; the later Golden E record below supplies that separate evidence.

## Connected Golden E — browser reset and research rerun (2026-09-29)

The same isolated Workspace received a new synthetic Product fixture through
`phase15-backtest-optimization.py`: ResearchTask
`task_be5201adebbe4dc0bda1bc61fd58e36f`, BacktestJobs
`backtest_dc7ac1b9385e454991de9596f984115e` and
`backtest_52b7b986e2f9460f83089966886d3079`, and OptimizationJob
`optimizationjob_e1ff5eda8025420eb40bd62d3aae2ef1`. Both Backtests and
the OptimizationJob completed before reset. The repeatable Playwright journey
`apps/frontend/tests/e2e/phase15-reset-research.mjs` used the actual Frontend,
Gateway and Product API on dynamic loopback ports. It verified that those exact
Job IDs and Task existed, clicked Runtime reset and confirmed the Task still
existed, then clicked Workspace reset. Product returned HTTP 200 and reported
two BacktestJobs, one OptimizationJob, two ResearchTasks and 11 Artifacts
deleted. The browser saw the completion state, the same login and Workspace
identity, no old Job/Task/Artifact in Product lists, zero off-origin requests,
and created a fresh persisted ResearchTask
`task_07fd47b23d3742f0a644bf6fd1f279d3` through Product API.

After reset, the isolated Data Worker imported exactly one new, real TuShare
daily row for `000001.SZ` on `20240102`. Read-only PostgreSQL evidence recorded
`data_source=tushare`, `close=9.21`; no old database was mounted or used. A
new Product Agent conversation
`conversation_e5caa88750754edba4b3473355e26982` completed two turns on
trace `byq-trace-f1780ef62b87449ab6cc50a72fbdd6c4`: delegated market
research reported the same 9.21 value, then Web Search yielded official
source URLs and saved `web_research_evidence` Artifact
`artifact_b7e03959f1f442e487977612d12b199f` with research-only policy.
Product replay showed `user, assistant, user, assistant`, 16 normalized
`agent.activity` events and three Agent-run registration events. The activities
include completed market research/data read, Web Search and Web evidence save;
one evidence-save attempt failed before a later successful save. Read-only
business audit for this exact trace recorded three `byq_market_daily`
authorized/success pairs and one `byq_web_evidence_create` authorized/saved
pair. The Artifact exists in the same Workspace. An independent one-turn Web
Research smoke also succeeded after reset. The strategy approval archive now
contains four distinct exact source/version fact rows across the two resets;
the Workspace has no old approval Artifacts and two new Web Research Artifacts.

A second, read-only Playwright check reopened that exact post-reset Product
conversation. It displayed both the 9.21 market answer and information
disclosure follow-up, checked the four-message Product replay, and found the
exact new Web Artifact in the research asset UI, with zero off-origin requests.

The original Workspace later received another synthetic Backtest fixture.
A *second* Workspace reset returned fail-closed HTTP 409 because two retained
Agent-audit facts referenced its new Web Artifacts. A read-only scoped query
confirmed those two audit/Artifact references. This second reset is outside
Golden E's required order (`reset → seed → rerun A`); no Agent-audit facts were
deleted and the first reset/research chain remains valid. It also means this
evidence does **not** claim that an Agent-audited Workspace can be reset again.

To check protected state and exact identities without those retained facts,
the isolated database provisioned a separate disposable admin Workspace
`workspace_d77e695aa6ed41c5b5d059e2bc17a5f3`. New worker-backed
BacktestJobs, an OptimizationJob and comparison Artifact completed there.
The strengthened real-browser reset compared the account subject, account
role, Workspace role and the shared market-automation configuration before
and after; each was unchanged. It asserted exact Task, two BacktestJob,
OptimizationJob and comparison Artifact IDs before reset and their absence
afterward. Runtime reset retained the Task. Workspace reset returned 200,
removed one Task, nine Artifacts, two BacktestJobs and one OptimizationJob,
and a fresh Task persisted. No browser request crossed the Frontend/Gateway
origin. This checks a representative shared global configuration, not every
possible SystemConfig key. It is a separate protected-state run on the same
code, rather than an assertion made by the earlier connected research run.

**Golden E's specified sequence: local PASS.** Focused Tester reviewed both
browser scripts for syntax, bounded assertions and documentation; its static
review passed without rerunning the destructive flow. Root executed the two
real Chromium journeys and the Agent/Worker calls above. Independent Sol
Reviewer inspected the actual scripts and evidence and returned **Functional
PASS / Tests and Evidence PASS / Clean Break Architecture PASS**. Root accepts
Golden E's `reset → seed → rerun A` sequence only. The browser wrapper
validated this worktree's `BYQ_DEV_SCOPE` against its ignored local config;
the scripts themselves check format and loopback origin. Their network-origin
assertion covers HTTP(S), while Product API and trace evidence establish the
business calls. The retained Agent-audit 409 remains a separate unresolved
Workspace reset limitation for Phase 15. This gate does not qualify Golden B's
Agent-led Job journey, Golden C's GPU path, Golden D's Agent-initiated Job, or
full Golden F; Phase 15 overall remains **OPEN**.

## Bounded repeated Workspace reset after Agent Web research (2026-09-29)

The previous HTTP 409 was traced to exactly two retained `agent_audit` rows for
successful `byq_web_evidence_create` calls. Audit is an observational fact; its
`resource_id` records the historical Artifact ID, and it has no Artifact foreign
key. The reset preflight now exempts only this action with `resource_type=artifact`,
outcome `success` or `saved`, and an owned `web_research_evidence` target. It
keeps the audit row and ID; ordinary Artifact audit, missing resource type,
Agent approvals and unresolved business actions still block deletion.

Tester ran the new Web audit reset contract and the existing approval archive
Product reset contract in isolated PostgreSQL: **2 passed, 1 warning**. Syntax,
`dev-check.py --base 80662e24` and `git diff --check` passed. Independent Sol
Reviewer inspected the actual code and tests and returned **Functional PASS /
Tests PASS / Clean Break Architecture PASS** for this bounded source change.

Root rebuilt only Backend in isolated Compose project `byq-dev-ea551690f4`.
Authenticated Product reset of the original Agent-audited Workspace
`workspace_9d6b65154f1f438ba684875a80d3a9df` returned HTTP 200, removed
four ResearchTasks, 11 Artifacts, two BacktestJobs, one OptimizationJob and
the four-message Product conversation. The exact Web Artifact
`artifact_b7e03959f1f442e487977612d12b199f` was absent afterward; the
same account and Workspace remained usable, and a new ResearchTask
`task_e43d266b3a58440080ea092822f8af6f` persisted. A scoped read-only DB
check confirmed both original Agent audit rows remain present with their
`success` and `saved` outcomes and original Artifact IDs. The browser reset
flow had previously passed; this fix was reverified through authenticated
Product API and scoped DB checks, without a new browser run.

**Root acceptance: PASS for this bounded repeated-reset fix. Phase 15 overall
remains OPEN** for the other journeys and repository CI. No existing Product
database, backup, deployment, push or merge was touched.

## Bounded F rebuild and simple reset (2026-09-29)

The scoped `dev-clean` dry run identified exactly 12 containers, four volumes
and two networks under Compose project `byq-dev-ea551690f4`. Applying that
exact plan removed those resources and verified none remained; the ignored
`.env.dev` and reusable images were retained. `dev-init` verified that isolated
configuration, `dev-start` rebuilt the five-service core with all services
healthy, and `dev-seed` generated a new Workspace. `dev-test` passed two
governance and 13 development lifecycle tests. Read-only counts in the new
isolated PostgreSQL showed one user, one Workspace, one ResearchTask, two
Artifacts, zero Backtest/Optimization Jobs and zero market bars. Gateway login
and `/api/product/auth/me` returned HTTP 200 for the new Workspace.

On this new **approval-free seed**, Product Runtime reset returned 200 and
preserved the ResearchTask. Product Workspace reset then returned 200, removed
the seed task and Artifacts, preserved the same login and Workspace ID, and
`dev-seed` succeeded again. This verifies only the simple reset and rebuild
foundation. This simple reset alone did not resolve the populated approval
blocker; the separate populated Product rerun above did. It also does not
count as rerunning A–D or the full Golden F journeys.
