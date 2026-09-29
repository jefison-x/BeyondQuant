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
| E: Runtime and Workspace reset | On the fresh Phase 15 Workspace, real browser Runtime reset returned 200 and archived two conversations while preserving data. Workspace reset then returned 409; read-only preflight found a strategy-approval Artifact tied to a ResearchTask. | Classify the approval fact without losing it, then rerun Workspace reset on this populated Workspace, verify retained global state and reseed. Golden E is `FAIL` for this attempt. |
| F: full rebuild | Core init/start/seed/test and dry-run cleanup succeeded here | Run scoped `dev-clean` apply, then init/start/seed/test and the connected Golden journeys. The current `dev-test` alone is offline. |

## Next bounded execution

1. Qualify available GPU hardware for the ML journey without exposing secrets.
   Complete Agent-led strategy change and any remaining Product detail view
   needed for the Backtest/Optimization result.
2. Fix only concrete failing Product boundaries found by those journeys; keep
   DSH as sole harness and long computation in Workers.
3. Exercise TrainingJob, session interruption, reset and scoped rebuild. Mark
   unavailable qualified dependencies `NOT_RUN` with an exact reason, never
   `PASS` by substitution with mocks or old database evidence.
4. Finish Tester → independent Sol Reviewer → Root review, then PR/CI/merge
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
E remains **FAIL/OPEN** until the approval fact is retained independently of
the disposable graph and a real reset/rerun succeeds. The earlier Phase 13
browser test passed because its fixture created a plain ResearchTask without
strategy approval.
