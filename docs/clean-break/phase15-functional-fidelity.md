# Phase 15 — Functional fidelity on fresh state

Status: **OPEN** on `codex/clean-break-phase15`, based on Phase 14 merge
`e9c944951465fbdeae4d05cd7bb0358b32f8a041`. The current local functional
closeout is **PASS** below; required Full CI and repository gates remain open.
Phase 16 stays closed.

Current GPU gate scope: [ADR-0089](../architecture/adr/ADR-0089-clean-break-gpu-acceptance-scope.md)
excludes GPU execution and GPU checkpoint/restart from BYQ 0.10 acceptance
(`N/A`). Earlier `NOT_RUN` observations below remain historical facts; no GPU
test result is represented as a pass.

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
| B: two Backtests, optimization, comparison | A new Workspace Product API journey completed two independent BacktestJobs, one OptimizationJob and a persisted comparison Artifact. Real browser comparison of the exact two completed Backtest IDs and Artifact listing passed. A later four-turn Product Agent journey read A's completed analysis, revised B, completed both Worker-backed Jobs and persisted an exact two-Job comparison Artifact. The exact Artifact ranking was also reopened through the real browser's Product entity view. See bounded evidence below. | A formatted ranking view is not present; the existing entity view displays its JSON detail. |
| C: TrainingJob, Worker restart/reclaim | The Product Agent submitted one exactly approved CPU TrainingJob using the cached 98-session window. Its real Worker was killed during attempt 1; a normal restarted Worker reclaimed the same Job after natural lease expiry and completed attempt 2 with a unique validated Model and the reused validated Feature Artifact. See the current live C evidence below. | Golden C local PASS through Tester → independent Reviewer → Root. GPU execution and GPU checkpoint/restart are `N/A` under ADR-0089. |
| D: Agent interruption with Job continuing | A fresh isolated Agent conversation created and executed an approved BacktestTask. The exact Job remained queued after that conversation was deleted, completed once in the independent Worker, and was read with its Artifact by a new Agent. Focused Tester, independent Reviewer and Root accepted Golden D with the trace argument visibility limit recorded below. | Golden D PASS. DSH process restart is outside this scenario's defined scope. |
| E: Runtime and Workspace reset | The populated browser reset, reseed and two-turn delegated Agent/Web research passed. A separate Workspace confirmed protected identity/config and exact deletion IDs. A subsequent Product reset of the Agent-audited Workspace now also passes while retaining the exact two Web evidence audit facts and deleting their disposable Artifacts. | Golden E's specified `reset → seed → rerun A` sequence and the bounded repeated-reset fix are local PASS; this does not complete the other Phase 15 journeys. |
| F: full rebuild | Exact-scope `dev-clean` apply removed only this isolated project's 12 containers, 4 volumes and 2 networks; `dev-init`/core start/seed/test and real login passed on a fresh schema. Post-rebuild evidence covers E/A, D, B with browser comparison, and the current real CPU C. | F local evidence PASS after chronology review. The earlier claim that connected journeys were not rerun is superseded below. No repeat rebuild or A/B/D/E run is needed; required Full CI/repository gates remain open. |

## Current live Golden C and closeout evidence (2026-09-30)

The maintainer authorized two Product Agent turns and one new CPU TrainingJob,
then explicitly expanded the model budget to **three actual turns** after the
first session disappeared before its approval continuation was submitted.
All three actual turns were used; exactly one new TrainingJob was created.
The existing isolated Workspace, approved strategy, one-symbol pool and cached
`2024-01-02`–`2024-05-31` window were retained. The Data Worker stayed stopped;
no market download or existing database/backup operation was performed.

| Evidence | Stable ID |
|---|---|
| Scope / Workspace | `byq-dev-ea551690f4` / `workspace_9f180f427ac14bb7b5ccb35c4c59d1c8` |
| Current Product conversation | `conversation_3a58869e9d514aadbf9d7e196bd192d1` |
| Trace | `byq-trace-6bffcffd2aff48c78e19a1237d5dc0c9` |
| Exact frozen watch | `mlwatch_f611ed05631f4c66874be47d986a3b7a` |
| Original submission key | `mltrain-361c6049-cpuv1-20240102-20240531-000001sz-p01` |
| Current action approval | `agent_approval_f2e77aa5ae9948318cf7e34bc4aad98d` |
| Agent-submitted TrainingJob | `mlrun_bcd447d93afd46f48db7dcaf881c19ab` |
| Submitted audit / ML AgentRun | `agent_audit_5ee850f2213d48d298c11dc3e52094da` / `agent_run_71e97525767c4a4089689c866c0e92a6` |
| Reused Feature Artifact | `artifact_4ca1c68fa5614668b61ee226528bea36` |
| New Model Artifact | `artifact_9552a32103e848ce9c41502cd7e39380` |

The approval preview freezes Task `task_be0d95aa5f8040fd82bb503693cc2106`,
Strategy `artifact_361c604902cf45f48a2ed9cdec5fcbd7` and pool snapshot
`stock_pool_snapshot_f4c8c95f57d539a1ca9844bc8a1bc72ee37038963d03debbb7f38a4e2266fe66`.
The human Strategy approval remains `artifact_a71875f84d5349b4bc19a92f9270a2b2`.
The current browser opened the authenticated exact-conversation workflow SSE,
verified all five frozen fields and an enabled approval button, and clicked
once. Gateway logs record SSE HTTP 200 and decision HTTP 200; persisted
approval is `approved / authorized / continuation submitted`. The ML Agent's
durable audit records one `byq_ml_training_create / submitted` with these
exact references, the original key and the new Job. Product replay includes
the Agent's exact Job answer. Public activity 37/38 is `started/waiting` and
does not expose arguments/results; submission is corroborated by trusted
preview, durable audit and Product Job state, rather than inferred from that
activity alone.

Two observation failures remain recorded. The first browser preview was
view-only; closing it released the old ephemeral session before the later
decision continuation. That decision committed but no model continuation or
Job was submitted. Its old grant `agent_approval_9fedeb8f627f4d5d8d91f35a29917112`
was never reused across sessions. Gateway now marks a pre-prompt session
restoration `ProductError` or `HTTPException` as failed without resubmitting. The current browser
decision succeeded, but its original receipt poll returned 404 because the
Product ML nonce endpoint prefixes a caller-supplied key and cannot look up
the Agent's original key. The observer now reads the exact approval preview
and study/run details. Its **read-only recovery passed** with 45 browser
requests, zero off-origin requests and no second decision/model/Job write.
This does not retroactively claim the first observer held SSE through receipt.
Later read-only browser navigation also recorded an automatic SSE reconnect
409 after the ephemeral session had been released; durable Job reads passed.

`scripts/evidence/phase15-golden-c-worker.py` started only the scoped real ML
Worker with a temporary 0.1 CPU quota to observe the small real workload. Before
hard stop, Product returned the exact Job `running / attempt_count=1`, Worker
`ml-worker-1`, lease expiry `2026-09-29T23:44:31.296391+00:00`. Container
`9fb9de28fcf0…` exited 137 while that same Job remained running, attempt 1,
with the unchanged lease. Normal Compose restart restored 2 CPU in new
container `35bb3ee25688…`, with the same image
`sha256:1fb9871b6a1da803114e17961e3e3c72d77a14b247800ca4476d85b11f14f810`.
Without editing Job state or leases, the Worker waited for the real five-minute
lease expiry, reclaimed that same Job and completed **attempt 2**.

Product assertions verify completed/ready/no error, exact frozen inputs,
validated Feature/Model and persisted object references, metrics and exact
Model-to-Job lineage. The owner-scoped Artifact list is below its 200-row cap;
it has one Model for the exact Job and one Feature with the terminal reference's
content hash. Identical cached input legitimately reused the baseline Feature;
no new Feature creation is claimed. The study has exactly the baseline and
this new Job. ML Worker stopped after completion; Data Worker remains stopped.
This proves durable CPU Job reclaim/re-execution, not mid-epoch checkpoint
recovery. GPU remains `N/A` under ADR-0089.

Source gates: focused Gateway regression **2 passed**; Python AST, browser Node
syntax, diff and `make dev-check` (27 syntax files) PASS. Independent source
Tester, Sol Reviewer and Root PASS cover the narrow continuation failure,
browser observer and real Worker driver. Live Tester → independent Sol Reviewer
→ Root closeout is **PASS** for Golden C and the Phase 15 local functional
fidelity gate. The independent Reviewer accepted the existing A/B/D/E evidence
and corrected F chronology; Root accepts that bounded local closeout.
At that local closeout, required Full CI was **NOT_RUN**, and push/PR/merge
were outside the initial authorization. The subsequent explicit repository
authorization and initial CI identity-gate failure are recorded at the top of
[phase-gates.md](phase-gates.md); replacement CI and merge remain pending.
Deployment is not authorized.
Phase 15 overall remains **OPEN** and Phase 16 is not started.

### Post-rebuild evidence reconciliation

Rebuild commit `2987d3c1` (2026-09-29 17:05 +08) precedes connected E and
post-reset A (`80662e2`, 18:56), Agent D (`a3114ab`, 21:00), Agent B
(`476e823`, 2026-09-30 05:23), browser comparison (`2b41763`, 05:30), and
baseline real CPU C (`3f2ec78`, 06:01). The current Agent/Worker C uses that
same rebuilt Workspace and cached data. The pre-rebuild A matrix evidence
alone is not the post-rebuild proof; the connected E section's TuShare/Web
rerun provides it. The earlier simple-reset record below retains its original
bounded claim. Existing A/B/D/E evidence is sufficient and was not repeated.

### Golden B Agent journey: first live attempt and corrected test contract

On the isolated real-data Workspace `workspace_9f180f427ac14bb7b5ccb35c4c59d1c8`, a parameterized A StrategyVersion `artifact_be7d69ccfbe7410d98d8b8b769f7ce48` was approved as `artifact_94adbe9d99c546219caefd3da9e66cc3`. Product Agent conversation `conversation_bc6fbd4d70484285a6186e54d5971bca` created BacktestTask `backtesttask_8198caaba3994d1ba0dbc31ed5292827` and BacktestJob `backtest_f1bb382765a84fe08c7c6ee78a1d4cab`; the independent Worker completed it with result Artifact `artifact_194dcf854f2044e09b7d8009ad9e4471`. The next Agent turn could read A and export its strategy, but `byq_strategy_validate` failed. No B StrategyVersion was created, and this attempt is **FAIL**, not a Golden B pass.

The root cause is the first attempt's ResearchTask `task_2483144d3e0d42a3b5d991e8f07a1eb7`: Product API created it before the Agent conversation, so its `conversation_id` is null. The domain-call contract correctly requires Agent strategy writes to use a Task bound to that same original conversation. The isolated Backend returned `425 call_evidence_pending`, and private evidence delivery rejected the conversation/Task mismatch with 401. Replaying the failed turn would not repair the binding.

The revised staged script creates a fresh ResearchTask and A StrategyVersion through BYQ MCP in the same new Product Agent conversation, then holds at exact Product approval before running A. Its remaining turns create B after A's result, then run B; one Product OptimizationJob compares the two. It uses a separate manifest. Static syntax, Product/MCP contract review, and independent Clean Break review passed before its first execution. The earlier failed conversation and Task remain isolated test evidence; neither existing databases nor backups were touched.

After test resumption, a new isolated conversation `conversation_ca36c1d8a8f543909a3278a74b6d3ae1` created its own correctly bound ResearchTask `task_2c24aba1472c4165939695867d2c31db` and validated A StrategyVersion `artifact_160c9e9d7b824942b275b3d0b047afee`. The first observer rejection was only a final newline removed from the stored script; the observer now normalizes that newline while still requiring all other strategy fields to match. Exact Product approval `artifact_f393a8147c3349f8a1c87e2d35348094` preceded Agent-started BacktestJob `backtest_04f02208c30348edb3f694ac616cdfc2`, which completed through the independent Worker. The third Agent turn produced B StrategyVersion `artifact_4ade9653f5a24a9db526d155222cf4ed`, but explicitly reported it could not read A's completed result: the `quant_orchestrator` role lacked the bounded `byq_backtest_analysis_get` permission. This attempt is **FAIL** for Agent-led result-based revision, even though B was created. No second BacktestJob or comparison was claimed.

The role catalog grants only that owner-scoped, page-budgeted analysis read to the orchestrator, advances its role version to `2.5.0`, and denies that newly granted read to old `2.4.0` AgentRuns. The evidence script requires the normalized analysis activity before accepting B. The isolated Backend image was built, the changed role was inspected inside a network-disabled container, and a focused old-run authorization regression passed (`1 passed`, isolated `byq_domain_test`; one schema reset took 0.60 s). Only the isolated Backend service was restarted. At that point a fresh end-to-end Agent rerun was **NOT_RUN** because the earlier three authorized Product Agent turns were exhausted and the four-turn expansion awaited the maintainer's decision.

The maintainer then instructed continuation after the four-turn need was stated. The fresh rerun used the same isolated Workspace and cached `2024-01-02` market data, with **four** Product Agent turns and no additional TuShare sync. Product conversation `conversation_d7784e11d12f4c9ea166ac22693e7157` created bound ResearchTask `task_6476626741564ed7bb60ff17915b5572`, A StrategyVersion `artifact_103ace0fc2964b1a8d4b2e3ee149658e`, and exact A approval `artifact_4b639e026c324022afeca254431793f6`. The Agent started BacktestJob A `backtest_a2d9739696bf4c6c902949b125b00c0a`; the independent Worker completed it with its result Artifact. In turn 3, normalized activity proves that the Agent read A's bounded backtest analysis and exported A's strategy before validating B StrategyVersion `artifact_fc29bfb4b0bb41d8bba1e397f7d871e2`. The snapshots and source fingerprints matched except for `parameters.threshold` (`9.20` → `9.22`). Exact B approval `artifact_c548ef67641c4982b8a77bb81a8c5161` preceded Agent-started BacktestJob B `backtest_a0dda018f9bc4e44b1442fcad54b5e34`; its Worker result and Artifact completed. The immutable signal snapshots differed as expected: A produced one signal and B zero. A single Product OptimizationJob `optimizationjob_f75745c4ff184028847c87c104816dc9` produced comparison Artifact `artifact_59a9fe87714245c3a7025cbf0bb06c54`, whose ranking references exactly the two completed Job IDs without rerunning backtests. **Golden B Agent/Job/Artifact journey: local PASS.**

Turn 4 initially stopped at a script allowlist check because the Agent read the approved B StrategyVersion through the existing `导出策略` activity before submitting the BacktestTask. Read-only inspection confirmed that exact extra activity, the single B Job, and no other unexpected call. The observer now allows that read while retaining exact-once requirements for prepare/create/execute. It resumed from the recorded accepted turn without submitting another Agent prompt or BacktestTask. This is a script correction, not a replayed success. Phase 15 overall is still **OPEN**.

The existing isolated Frontend image was started without rebuilding the stack. `apps/frontend/tests/e2e/phase15-optimization-detail.mjs` used Playwright Chromium to log in through Frontend/Gateway, open the Product `实体查询` view, and display comparison Artifact `artifact_59a9fe87714245c3a7025cbf0bb06c54`. The page rendered a validated `optimization_comparison` with exactly two ranked Job IDs, `backtest_a0dda018f9bc4e44b1442fcad54b5e34` and `backtest_a2d9739696bf4c6c902949b125b00c0a`; `candidate_count=2` and `reran_backtests=false`. The browser made 81 requests, zero off-origin. **Browser Artifact detail: PASS** via the existing JSON entity view; this does not claim a formatted ranking component.

## Historical D preparation and remaining gate

Golden D preparation was initially **BLOCKED before external execution**. A static
contract review on 2026-09-29 found that the one-symbol daily synchronization
fills only price bars. Agent BacktestTask readiness also requires a complete
trading calendar, trading status, price limits, adjustment factors and corporate
action completeness for the session, plus a security-master snapshot. The
existing session repair fetches full-market data by date, which exceeded the
initial single-symbol TuShare scope. The maintainer subsequently authorized
that repair for `20240102` in the isolated stack. No Golden D provider or model
call had been made at the time of this review. The draft staged evidence script
`scripts/evidence/phase15-golden-d.py` was subsequently revised for the
approved one-day repair and reviewed before execution. The live result is
recorded below.

This historical remaining-work list is superseded by the current closeout
above: real Agent CPU C and post-rebuild connected journeys are now observed;
their final local gate review is PASS; obtain separate authorization for
the required Full CI and repository PR/merge gate before Phase 16.

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

## Agent-initiated Golden D execution (2026-09-29)

The isolated project was rebuilt from empty volumes and minimally seeded as
Workspace `workspace_9f180f427ac14bb7b5ccb35c4c59d1c8`. The authorized
TuShare L/P/D security-master Job `securitysync_6c3c3895ed9f4feba81681d3db7c2b54`
completed. Product readiness for only `000001.SZ` on `20240102` was unavailable.
ResearchTask `task_d9e80a2512cb4da58af3c084961c96d0` received a custom
one-symbol frozen pool, validated strategy version
`artifact_fd093176236b4752ad9dbad97ca54324`, and its exact approved
strategy Artifact `artifact_4a786843fad34ddbbc7f3bc0216b647c`.

With the isolated Data Worker and Backtest Worker stopped, old Product Agent
conversation `conversation_11dcaa622f1b49c2b325195ddba6a123` recorded
normalized `准备回测任务` and `创建回测任务` activities and reported BacktestTask
`backtesttask_77273a29ca384fc68eebeaf0bfe73b5c`. Before restoring the
Data Worker, a read-only isolated DB check found exactly one queued repair:
`000001.SZ`, start/end `20240102`, with no session sync, run-now, or ordinary
data-sync Job pending. The Data Worker then completed exactly one session Job
for `20240102`, receiving 5,329 daily rows, and the exact repair request
became completed. The Product readiness verdict became usable.

The same old Agent conversation then recorded `跟踪回测任务` and `执行回测任务`
activities. Product returned one queued BacktestJob
`backtest_ebe7f6dad7cf4caf9e3fff3661c62380` bound to the exact Task,
Workspace, frozen pool, strategy version and approval. The old conversation
was deleted; the Job still read `queued`, attempts `0`. Starting the isolated
Backtest Worker completed that same Job on attempt one and produced validated
Artifact `artifact_2169ba2cdfbc48058662c604798e8145`. New Product Agent
conversation `conversation_37cf684f534749bd9f529e4732193765` recorded
a completed `读取回测状态` activity and answered with the same Job and Artifact
IDs. The Product catalog still contained exactly one Job for this Task.
Both workers were stopped after the observation.

The normalized Product trace omits MCP arguments and results. It proves the
tool activity labels and ordering; Product Job ownership/provenance and Agent
answers provide the cross-check, but the exact per-call tool argument binding
is **not independently proven by that trace**. Focused script checks and
read-only isolated DB inspection passed; the independent Sol Reviewer returned
Functional PASS / Tests and Evidence PASS / Clean Break Architecture PASS.
**Root acceptance: Golden D PASS with this evidence limit.** The scenario does
not require DSH process restart or child rebind. Phase 15 overall remains OPEN.

Bounded D gate: focused Tester **PASS** for documentation and local contracts;
independent Sol Reviewer **Functional PASS / Tests and Evidence PASS / Clean
Break Architecture PASS** for this scoped observation. Root accepted only that
bounded result at this earlier gate; the later Agent-initiated run above closed
Golden D.

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

## BacktestTask AUTO role-policy alignment (2026-09-29)

The Clean Break approval baseline classifies authorized deterministic Backtest
compute as `AUTO`. Existing role metadata still returned `approval_required`
for `byq_backtest_task_create` and `byq_backtest_task_execute`, although these
MCP tools accept no Agent approval ID. The maintainer explicitly authorized a
bounded Phase 15 change after automatic approval review initially rejected
removal of those existing gates as a security-sensitive change.

The role catalogue now treats BacktestTask create/execute as AUTO for roles
that already possess those tools. It retains human approval for the exact
strategy version and exact BacktestTask cancellation. BYQ's strategy approval
Artifact, frozen pool, market readiness, tenant binding, idempotency and audit
checks remain on the domain path. The three affected role versions advance.
The Agent authorization endpoint denies create/execute for older role versions;
the direct BacktestTask endpoints do not perform that per-run version check, so
active old sessions must be discarded before adopting this policy. No old
session migration is part of this Clean Break. The `manual_safe` preset now
describes the remaining sensitive human approvals accurately. Its pause switch
pauses personal automatic approval rules, not platform AUTO research compute.
An isolated Chromium login opened the real Product policy page and rendered
`敏感操作人工确认` with the approved-strategy backtest AUTO wording; browser
requests remained on the Frontend/Gateway origin.
The new contract test asserts AUTO
authorization for create/execute and rejects attempts to request redundant
Agent approvals; existing continuation tests now exercise the still-gated
cancel action. This change alone did not prove an Agent-started BacktestJob;
the later live Product/DSH journey above closed Golden D.

## Bounded real CPU trainer check (2026-09-29)

The isolated `byq-dev-ea551690f4` Compose project built and started only its
optional `ml-worker` service. Inside that actual image, `LightGBMTrainer.fit_rows`
trained once on 30 training and 10 validation rows generated solely in memory,
with explicit synthetic values and no claim of TuShare provenance. The returned
LightGBM text model reloaded successfully with five expected features. The
runtime identified `lightgbm-4.7.0-python-3.13-linux-cpu-single-thread`, both
validation metrics were finite, and the model SHA-256 was
`d3b00975a8611dbf330af65b37fca34122010a0893d709d13641341a3d520e0c`.
No database, market provider, Product API or Agent call was made by this smoke.

This verifies the real CPU trainer dependency and model serialization only.
It does **not** establish a durable TrainingJob, Feature/Model Artifact,
prepared-input checkpoint, Worker reclaim, model checkpoint/restart or GPU run.
The Product ML readiness contract accepts only TuShare market bars. A one-symbol
real TuShare sync is available, but missing-session repair can import daily
data for the whole market over the training window. That broader provider work
was not started in this bounded check. Golden C remains **OPEN**.

On 2026-09-30, a read-only follow-up confirmed that the qualified feature set
needs 20 prior sessions for `return_20`/`volatility_20` and at least 20 usable
training plus five validation rows. The isolated provider data prepared so far
covers only the single `2024-01-02` session; submitting a TrainingJob now would
trigger the ML Worker's missing-data repair across a wider window. No such job
or provider repair was submitted under the one-day TuShare authorization.
`nvidia-smi` is unavailable and Docker lists only `runc` runtimes, so GPU and
GPU checkpoint/restart remain **NOT_RUN** on this host. The CPU trainer smoke
above remains the only ML execution evidence, and Golden C is not claimed.

## Real-provider CPU TrainingJob and Artifact (2026-09-30)

The maintainer explicitly authorized one isolated TuShare window,
`2024-01-02` through `2024-05-31`, for a real CPU TrainingJob. The existing
`byq-dev-ea551690f4` project had its automatic market scheduler disabled, one
completed market day (`2024-01-02`), a synchronized security master, and no
pending training runs. Through authenticated Gateway/Product API,
`scripts/evidence/phase15-ml-cpu.py` created one ResearchTask, a one-symbol
stock-pool snapshot, a qualified LightGBM CPU StrategyVersion and its explicit
owner approval Artifact, then submitted TrainingJob
`mlrun_625652441fda459a8b4ae917d9a82cfe` in Workspace
`workspace_9f180f427ac14bb7b5ccb35c4c59d1c8`.
Two earlier script attempts were rejected at the Product ML request-shape gate
before any TrainingJob or provider call; they left disposable Task/pool fixtures
in this isolated Workspace. The script now supplies ML idempotency through the
required header.

With the Data Worker stopped, the ML Worker recorded repair request
`datarepair_5579db1d2120452aa0938f8e27b34b4f`, whose exact bounds were
`20240102`–`20240531`. Only then was the isolated Data Worker started. It
completed all 98 open trading sessions in that window; the isolated market
store then held 523,891 daily bar rows. It scheduled **zero** sessions outside
the authorized dates. The repair request closed `completed` without error.
The exact TrainingJob reached
`completed` with readiness `ready` and no missing cells. Both Workers were
stopped after completion to prevent further provider activity.

Product API independently returned validated Feature Artifact
`artifact_4ca1c68fa5614668b61ee226528bea36` with 77 frozen rows and a
persisted object reference, and validated Model Artifact
`artifact_2b03d0b908db4de7866cd3cdb2e5456d` with its own persisted model
object, validation metrics, exact TrainingJob lineage, and runtime
`lightgbm-4.7.0-python-3.13-linux-cpu-single-thread`. The evidence script's
exact-ID Product assertions pass. **Real-provider CPU TrainingJob/Worker/Artifact:
local PASS.** GPU execution and GPU checkpoint/restart were **NOT_RUN** on this
host and are now `N/A` for the BYQ 0.10 gate under ADR-0089. Golden C remains
**OPEN** for Agent initiation and real CPU Worker restart/reclaim.

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
