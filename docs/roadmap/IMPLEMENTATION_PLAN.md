# BeyondQuant Implementation Plan

## ADR-0084 current execution override（2026-09-21）

ADR-0084 is Accepted and supersedes historical text that made every D15 atomic item a global
prerequisite. B1 `subagent-child-crash` and B2 `subagent-byq-adapter-restart` remain truthful
`BLOCKED_EXTERNAL`; B3/B4 retain their candidate-layer PASS evidence; historical D15-G remains
`NO_GO` and is not rewritten. B1/B2 now block only native independent-child recovery claims.

The next maintenance implementation after this governance change is **BYQ session failure
containment and business recovery**, in one isolated worktree/branch/PR. Acceptance requires:

1. detect parent/runtime/executor loss and terminate the affected in-flight run as `interrupted`;
2. fence old generation/epoch writers, late settlements and attempts to reopen a terminal run;
3. preserve conversation identity, public history, durable jobs, approvals, artifacts and receipts;
4. automatically reschedule only contract-declared idempotent and reconcilable steps;
5. query exact receipts/idempotency keys for writes, orders, publication, paid calls or unknown
   outcomes, and pause with a truthful user-visible state when the outcome cannot be proven;
6. keep owner/workspace authorization, audit, budget and cancellation semantics intact;
7. produce fail-able, machine-readable evidence and a new D15 superseding assessment without
   modifying the historical D15-4/D15-G verdicts.

This slice must not implement an out-of-process DSH provider, rejected ADR-0082 Option 2, a
second generic harness/session store/PTY runtime, production selector changes, deployment or a
release/tag. Passing it permits a bounded R3 decision and 0.9 closeout assessment; it does not
claim native child-process resume and does not itself authorize R3, promotion or deployment.

**Slice status (2026-09-21): implemented as read-only containment + classification, one isolated
worktree/Draft PR.** The contract, the Runtime Adapter containment ledger/fence and the Gateway
read-only containment/classification projection are delivered with fail-able evidence
(`docs/evidence/v090-session-containment/`). Five Safety/Integrity blockers were fixed: no
client-declared step safety, tri-state authority verified from existing components (never defaulted
true), no `/tmp` attempt ledger / no second store, interruption projected only from fenced
containment matching the exact session/trace/run, and observed (not asserted) preservation. Because
no authoritative server-side step-safety/budget metadata exists yet, automatic rescheduling stays
**blocked/fail-closed to paused** and no prompt is ever submitted. The full business-recovery gate
therefore stays **`IN_PROGRESS / BLOCKED_INTERNAL`**; this PR does not claim the ADR-0084 replacement
hard gate complete. The next sole task is an **inventory + minimal design** for authoritative
server-side step-safety + budget binding + safe rescheduling.

**Design slice status (2026-09-21): delivered as design/evidence only, one isolated worktree/Draft
PR** (`docs/evidence/v090-step-safety-design/`; no runtime code). The inventory records the existing
authorities and the missing pieces; the minimal design keeps
`packages/contracts/session_failure_containment.py` closed and adds: (1) **identity separation** —
budget authority stays the original `reservation_id`, while each recovery submission uses a
Backend-minted `recovery_attempt_key` (the Adapter otherwise returns the lost old run for a reused
prompt key and forces the key to `reservation_id`); the carrier's **closed** `recovery_attempt`
sub-record carries `{attempt_key, ordinal, trigger_key, interrupted_run_id, interrupted_generation,
containment_attempt, interrupted_executor_epoch, snapshot_tail_sequence, snapshot_digest}`, and the
Adapter validates the snapshot field shape/digest, recomputes both keys and matches the durable
containment (missing/tampered → fail closed); (2) **two epochs** — the SOURCE
`interrupted_executor_epoch` comes from the durable containment and never has to equal the live
epoch, while the Adapter reads the **live** `target_executor_epoch`/`target_generation` at admission
under `record.lock` and returns them in the accepted receipt (the Backend never pretends to know the
Adapter's live epoch; a legitimate takeover `1 → 2` is a legal positive, interrupted-as-live / stale
target receipt / mismatch are rejected); (3) **per-attempt receipts** bound to `{reservation_id,
ordinal, run_id, charged_tokens, settlement_sha256}` with the Backend row as the final aggregate;
(4) **trigger-key dedup** before ordinal allocation binding the interrupted epoch (same fenced loss
returns the existing attempt; only a new loss allocates the next ordinal, cap 3); (5)
**snapshot-anchored session-global closure** (no cross-request lock assumed: a fixed
`{snapshot_tail_sequence, snapshot_digest}` issued when `idle=true` and carried in the closed
carrier, canonicalized digest over `session_id` + `trace_id` + tail + ordered closed call rows,
item-by-item adapter↔Backend reconciliation, global `1..N` contiguous, then per-root filter; a
second root's first sequence > 1 is legal) plus an **in-`record.lock`
validate-shape-then-atomic-compare-and-start** before creating a new root
(append/idle-flip/digest-tamper/race → `paused`; the Backend aggregate stores the SAME snapshot
identity; a same-trigger+same-snapshot retry does not raise the ordinal and a snapshot change never
silently rewrites an attempt); (6) a **no-double-deduction,
self-consistent tri-state** budget decision (`blocked` for authoritative denial/conflict/ordinal
cap/known sub-floor, `None`/`paused` for unknown cost/input, `R_available = R.token_limit −
cum_exact` after the grant invariant, e.g. P=100/other=30/R=60/charge=20 → 40, not 10; unknown cost
is never 0 and never refunded; **any new recovery model run requires a known
`R_available >= model_call_floor` — read-only constrains side effects only and does not exempt the
budget; only a controller-only reconciliation may observe below the floor**); and (7) a
**recovery-mode admission envelope** (read-only, or exact reuse of the original safe call;
`may_produce_new_key=true` is conservative only and always ineligible; the model never mints new
keys; undeterminable work is not `eligible`). It concludes existing components suffice, so **no new
ADR is required**; a later slice that needs an independent recovery store, a new cross-Plane
authority interface, a DB migration, a new trust subject, or authorization for a recovery run to
mint a new key must propose an ADR first. The next sole task is the bounded exactly-once receipt-first
rearm implementation under those constraints. Per ADR-0084 migration step 4, the named D15
 superseding assessment is a **separate** follow-up only after the full gate passes; the design PR
 does not create or claim it, keeps B1/B2 `BLOCKED_EXTERNAL`, D15-G `NO_GO` and `R3_RESUME = NO`,
 keeps the gate `IN_PROGRESS / BLOCKED_INTERNAL`, and does not implement native child resume.

**Implementation slice status (2026-09-21): the #351 minimal design implemented as a real vertical
slice, one isolated worktree/Draft PR** (`codex/v090-business-recovery-impl`, base `origin/main`
`021afb5`; evidence `docs/evidence/v090-business-recovery/`). Delivered: the closed
`packages/contracts/business_recovery.py` contract (trigger/attempt identity, closed carrier,
canonical snapshot digest + closure, step-safety registry + admission envelope, tri-state budget
decision, pure trigger-keyed allocation); Backend in-row authoritative allocation/reuse folded into
the **existing** continuation seam (`claim_continuation_dispatch` with the existing `dispatch` route,
cap 3, no new store/migration and **no new cross-Plane endpoint**); server-derived step-safety/budget
facts (occurred/replayed calls from `agent_domain_call_evidence` + `agent_domain_call_claims`, the
closed registry, and the server floor constant — the request never carries them); the Gateway folded
into the existing continuation consumer (`_consume_admitted_task_continuation`) with the closed-carrier
forward (`services/gateway/app/recovery_carrier.py`); the Adapter validate/atomic-check/install
(`services/runtime-adapter/app/business_recovery.py` wired into `submit_prompt`) that recomputes and
atomically compares the CURRENT snapshot (`idle=true`) under `record.lock` before creating the new
root/target generation, returning the accepted receipt with the live target epoch/generation/run in
the existing prompt response; the accepted target written back through the existing receipt route; the
Adapter's durable guard charge bound through that same route (unknown stays paused); and a **runtime
recovery-mode invariant** (`claim_domain_call` → `_recovery_claim_gate`) that, for a Backend-bound
recovery target root, allows ONLY exact original five-tuple reuse (new key/action/task →
`recovery_envelope_violation`, which the Adapter treats as a stop) and rejects any side-effecting
claim while a recovery attempt is pending. Session-global continuity is judged over the full
session/trace closure and the replay set is scoped to the current task + exact lost root.
Acceptance is real behavior, not string tests: a Postgres-backed concurrency test proves same
trigger+same snapshot allocates exactly once and a retry reuses the original attempt/ordinal, a
snapshot change cannot rewrite/consume another ordinal, budget is not double-deducted, unknown
cost/evidence conflict/model-floor/ordinal-cap fail closed, the accepted target receipt is persisted
and stale targets are fenced, forged policy/loss facts cannot obtain a carrier, a real claim path
rejects a recovery root's new key / new-key action / foreign task, a legal non-first-root sequence
is not a false gap, and a foreign task's call is not replay authority; the adapter test injects digest
tamper, tail append, idle flip, containment mismatch, stale target fences and the recovery-violation
stop; the fail-able observer rejects 25 defect-targeting negative controls. **No new ADR was required**
(in-row authority only; no new cross-Plane authority, trust subject, DB migration or new domain key).
The retained 0.9 closeout
order is: **this gate → real recovery acceptance → formally upgrade the repo default dependency/
selector to the coherent DSH `0.1.5-rc.1` (with rollback/business verification) → D15 superseding
assessment → 0.9 closeout**. The full business-recovery gate stays **`IN_PROGRESS /
BLOCKED_INTERNAL`**; B1/B2 stay `BLOCKED_EXTERNAL`, D15-G stays `NO_GO`, `R3_RESUME = NO`, the
candidate qualification is **not** written as a completed formal upgrade, no superseding assessment
is generated (**尚未生成**), the production selector is unchanged, no deploy/release/tag/selector
switch occurs, and 0.10 is not started.

**Real acceptance slice status (2026-09-21): the merged #352 vertical slice accepted with a REAL
ISOLATED SERVICE COMBINATION, one isolated worktree/Draft PR**
(`codex/v090-business-recovery-acceptance`, base dynamic `origin/main` `d906205`; evidence
`docs/evidence/v090-business-recovery-acceptance/`). An isolated compose project
(`byq-v090-recovery`, own network/volumes, fresh PostgreSQL, loopback-only ports) runs the committed
Backend, Gateway background task-continuation consumer, Runtime Adapter (real DSH 0.1.2rc1 +
append-only lifecycle journal + containment ledger), MCP and PostgreSQL; only the model is a
controlled keyless scripted provider that cannot influence authority. Real result: a real Adapter
OS-process termination marks the exact open run `interrupted` (`executor-loss`); the real Gateway
consumer detects the fenced containment + read-only anchor, the Backend re-derives step-safety/budget
from its own evidence and mints the closed carrier, the Adapter admits it atomically and installs a
new target generation, and the accepted target is written back; authoritative row counts are
unchanged by the read-only recovery, the journal shows exactly one lost and one recovery generation,
and the retry reuses the exact accepted run with no new ordinal/generation. Real fail-closed
negatives: forged loss, existing-trigger snapshot change, unknown cost (`paused`), below the
model-call floor, ordinal cap, stale target epoch, recovery-mode new key and cross-task domain claims.
The acceptance also found and minimally fixed a real #352 defect: after a real executor loss the
Gateway never reached the recovery seam because `reconcile_prompt` reported the lost run's original
prompt `accepted`; the fix (`_reconcile_lost_receipt`) reports `outcome_unknown` when the fenced
containment proves that exact run was lost, with a real-journal regression test. The fail-able
observer re-derives every verdict from RAW fields and rejects 20 defect-targeting controls. The
retained 0.9 closeout order becomes: **this gate → real recovery acceptance (delivered by this PR) →
formally upgrade the repo default dependency/selector to the coherent DSH `0.1.5-rc.1` → D15
superseding assessment → 0.9 closeout**. B1/B2 stay `BLOCKED_EXTERNAL`, D15-G stays `NO_GO`,
`R3_RESUME = NO`, no superseding assessment is generated, the selector is unchanged, and no
deploy/release/tag occurs.


After 0.10 data/HIST/deep-environment qualification, execute a named 1.0 matrix review that
classifies planned capabilities as `core`, `extended` or `deferred`. Only the accepted `core`
set becomes the global 1.0 release gate; safety and data-integrity failures remain fail closed.

研究流程连续性维护：见[下一阶段整改目标](RESEARCH_HANDOFF_PLAN.md)，先完成审批后原目标交接，再补持久交接与授权续接连接；不推进 Product Phase。

这是 autonomous development 的 repository roadmap。普通 phase branch 只能实现当前 phase；后续 phases 是 planning constraints，不授权提前构建 Product scope。

明确指定的维护/bugfix/CI/依赖资格任务按 ADR-0059 与 DEVELOPMENT_WORKFLOW 的独立通道执行，
不要求伪造新 Product Phase。历史章节保留当时验收语义；当前合并/部署权限以具名生效规则为准。

独立长研究维护：[运行策略及验收](LONG_RESEARCH_EXECUTION_CHANGE.md)，按Accepted ADR-0072执行；不推进Product Phase。

独立维护规划：[DSH 0.1.2rc1 升级与可维护性改造](DSH_012RC1_UPGRADE_PLAN.md) 定义 U0–U8，
目前仅为待实施方案，不占用下一 Product Phase，不改变当前 Runtime baseline，也不授权自动生产升级。

## Maintenance Round（2026-09-18/19）：ADR-0047 聚合边界、运行/续接连续性与只读归档

本轮维护不推进 Product Phase。逐项构建修订与 PR 如下；详细记录见紧随其后的逐条维护段落，
以及本文件末尾的“Post-Phase 82 信号/回测分片收口”与四个“Maintenance —”小节。

1. **ADR-0047 聚合分片接入 signal/backtest 准备链**（构建修订 `dsh-0.1.2rc1-post-u8.129`，PR #298）：
   共享确定性分片规划器，aggregate readiness 由逐分片 assessment 派生，`requirement_plan_json` 持久化。
2. **delist-date 覆盖边界修正**（`…-post-u8.130`，PR #299）：`trade_date >= delist_date` 非适用，
   对齐 ADR-0028 生命周期语义，不再永久阻塞 readiness。
3. **signal sandbox 输入去重与列式编码**（`…-post-u8.131`，PR #300）：`bars_frame.v1` 单一冻结面板，
   100.24→24.10 MiB，`AGGREGATE_ROW_LIMIT=2_000_001` 为单一事实来源。
4. **snapshot/backtest 聚合边界对齐**（`…-post-u8.132`，PR #301）：`signal-snapshot-v2` 列式快照
   （41.30→13.68 MiB），`backtest.py MAX_BARS/MAX_SIGNALS` 对齐 ADR-0047 聚合上限。
5. **运行会话重启重建与 trace 连续**（`…-post-u8.133`，PR #302）。
6. **ready bars 绝对 `adjustment_factor` 与 plan-hash readiness**（`…-post-u8.134`，PR #303）。
7. **显式 stale-lease 与可逆陈旧会话归档**（`…-post-u8.135`，PR #304；生产已归档 15 个陈旧会话）。
8. **数据就绪自动续接**（`…-post-u8.136`，PR #305；ADR-0077 **仍为 Proposed**，生产已运行）。
9. **续接路由资格与 Backend allowlist 对齐**（`…-post-u8.137`，PR #306）。

本轮另新增只读运维产物（构建修订 `dsh-0.1.2rc1-post-u8.138`）：
[终态 signal job 归档审计](../operations/TERMINAL_SIGNAL_JOB_ARCHIVE.md) 与 `scripts/ops/archive_terminal_signal_jobs.py`
（audit-first，`--apply` 仅落盘可逆 manifest，不写业务表；终态 job 归档需新增具名 ADR/domain action），
以及 [重复沪深300股票池清单](../operations/HS300_DUPLICATE_POOLS.md)（仅提议，整合须经产品/domain 授权路径）。
生产结果为 round-1 HS300 momentum+Kelly 回测完成（`backtest_83cab36a…` / `artifact_c62ab34f…`，
+25.49% vs +19.65%，最大回撤 33.83%），round-2 等待 `agent_approval_4e2ecb61eca74ec1a5c6721b5204f4f5`。

Restart 存活维护（fix，构建修订 `dsh-0.1.2rc1-post-u8.133`）：runtime-adapter 容器在部署时重建后，
内存 `_sessions` 丢失但 `DSH_SESSION_ROOT` 上的 BYQ lifecycle journal 与 DSH session root 仍在。
`_rehydrate` 现在按需、幂等地从该 BYQ evidence 重建会话记录，`_get` 与 prompt/events/subscribe
不再对已有磁盘会话返回 `unknown BYQ session`；真正未知的会话仍返回干净的 404/KeyError。Gateway
以持久 WorkflowTrace 的 last sequence 作为 append authority：重绑路径调用 `TraceStore.reopen`
并把该序列用于调适 adapter public sequence，使续写从 persisted+1 连续，避免因非持久
release/recreate 事件产生 false gap。`TraceConflict` 不弱化，真实 gap/backwards/reused 仍 fail closed。
rehydrate 后的首个 prompt 绑定新的私有 DSH generation，`agent.run.registration` 继续投递，因而新回合
产生已绑定 run 而不是停留 `pending_binding`。

信号生产修复合集（fix，构建修订 `dsh-0.1.2rc1-post-u8.134`）：`build_ready_input` 的 raw 与 research
bars 现在携带持久化的绝对 `adjustment_factor`（同一 `adj_factor` 来源），并维持 `bars_frame.v1` 的
`bars_fields`/`research_fields` 对等，使 `_normalize_bars` 能区分合法除权除息的 `prev_close` 跳变与
真正不一致的行；signal sandbox 的 bar profile 同步接受该 frozen 列（未知列仍 fail closed），缺少
factor 证据的不一致 `prev_close` 仍 fail closed。`normalize_signal_snapshot` 的
`source.data_readiness` 允许 `requirement_plan_sha256`（promotion 已写入的 provenance），snapshot
identity 仍确定性。`SignalProducerCoordinator.run_next` 与 signal worker 现结构化记录异常类型、消息与
traceback（不含 secrets 或完整 payload），存储的 `error_detail` 保持安全稳定。不修改 Accepted ADR 文本。

Stale-lease 显式化与可逆归档（fix，构建修订 `dsh-0.1.2rc1-post-u8.135`）：host reboot 会改变
`/proc/sys/kernel/random/boot_id`，使 reboot 前写入的 lifecycle journal `lease_identity` 永远无法重新
claim。adapter 现将该条件（`JournalIdentityMismatch`）显式映射为 `StaleSessionLease`，经 HTTP
`409` + machine code `stale_session_lease` 返回，区别于未知会话（404）与真实存储故障（503），且不
再落入 503；新增可逆运维脚本 `scripts/ops/archive_stale_sessions.py`（默认 audit，`--apply` 时 MOVE
journal/lock/session dir/gateway trace 到时间戳归档并记录 sha256 与原始路径 manifest），只读列出
`product_conversations` 供 operator 决策，不删除任何 domain row，也不自动清理数据库。

数据就绪自动续接维护（feat，构建修订 `dsh-0.1.2rc1-post-u8.136`）：生产观察到信号 job 在
`waiting_for_data` 完成后无人唤醒原会话，因为 F6 任务绑定续接要求用户显式确认的
`continuation_permission`，而生产任务没有该许可。按 [ADR-0077](../architecture/adr/ADR-0077-data-ready-auto-continuation.md)
（Proposed），在既有任务绑定续接合同内新增数据就绪事件：`signal_producer_jobs` 为 `completed`
且产出 `validated signal_snapshot` 时，经既有 `ready-v1:` 事件身份、`continuation_budget` 账本、
`/internal/task-continuation/...` 接口、Gateway `TaskContinuationDelivery`、adapter prompt 与
`continuation_scope.py` MCP 准入生成至多一个有界续接回合；失败/取消、未验证快照、外owner/外工作区/
无关会话都不触发。该切片只新增触发器，不改数据面、sandbox、模型许可或无关服务；不推进 Product Phase。

续接路由资格对齐维护（fix，构建修订 `dsh-0.1.2rc1-post-u8.137`）：生产复现数据就绪自动续接
（ADR-0077）在 gateway 准入后仍被 `plugins/dsh-byq/runtime/byq-continuation-budget.js` 拒绝：
guard 只接受硬编码的 `provider === 'deepseek-official' && model === 'deepseek-v4-flash'`，而准入
（ADR-0075/ADR-0076）已按 Backend `RUNTIME_MODEL_ALLOWLIST` 对六个 `opencode-*` 运行时路由及其
composition 模型白名单资格化，因此当前 `opencode-go / deepseek-v4.1-flash` 档案在 guard 处以
`BYQ_CONTINUATION_ROUTE_UNQUALIFIED`（`call_count=0`）失败。guard 现查询与 Backend 权威白名单一致的
`(provider, model)` 合格表（`deepseek-official` 及六个 `opencode-*` 路由，模型必须属于该路由白名单），
未知 provider、已知路由的未白名单模型、官方路由的未知模型仍在记账前以原稳定错误闭合；预算上界、
预留/调用计数与结算保持不变。`tests/architecture/test_architecture.py` 解析 composition 的
`llm-opencode` 模型表并逐项断言与 guard 相等，Backend `test_credentials.py` 断言 guard 表等于
`RUNTIME_MODEL_ALLOWLIST`，避免第二份列表静默漂移。不修改模型白名单内容、数据面或 sandbox；
不改变 Accepted ADR 文本（ADR-0077 仍为 Proposed）。

显式可逆会话 lease re-anchor（fix，构建修订 `dsh-0.1.2rc1-post-u8.140`）：2026-09-19 host reboot
改变了 `/proc/sys/kernel/random/boot_id`，使 reboot 前写入的全部 lifecycle journal 成为 stale，
只能 `409 stale_session_lease` 或归档，无法恢复。按 [ADR-0078](../architecture/adr/ADR-0078-explicit-session-lease-reanchor.md)
（Proposed）新增 `LifecycleJournal.reanchor_lease` 与 `scripts/ops/reanchor_session_lease.py`：
在排他 owner lock 下原子地只重写 stored `lease_identity` 为当前 boot 身份，保留 sequence/events/
prompts/terminal_acks/calls/context；stored 已 current 时幂等 no-op，`expected_stored_lease`
不符或存在 live owner/未知 session 时 fail closed；写 per-session 审计与 `audit.json` +
`manifest.json`（old/new lease、prior/new sha256、reversible、无 DB 写入、无删除），并只允许显式
`--session-id`/`--session-file` 选择。Gateway 经核验不存储 lease-bound cursor/ledger，无需刷新。
`409 stale_session_lease` 分类与 `archive_stale_sessions.py` 归档工具保持不变。ADR-0078 另提议
以 boot 无关的稳定执行者身份 + 单调 epoch + 显式 takeover 作为持久修复，待维护者接受后方可实现。

Runtime Continuity R0/R1（feat/fix，构建修订 `dsh-0.1.2rc1-post-u8.141`）：R0 定义
[ADR-0079](../architecture/adr/ADR-0079-runtime-continuity-and-session-recovery.md)（Proposed）
六层生命周期与[故障矩阵](../architecture/RUNTIME_CONTINUITY_FAILURE_MATRIX.md)，并在
`ARCHITECTURE.md` §K.1 固化四条不变式。R1 将 lifecycle-journal lease 从
`sha256(boot_id:st_dev:st_ino:token)` 替换为
`sha256(deployment_id:executor_epoch:lock_token)`：deployment-controlled
`runtime-executor.v1` 记录（`config/dsh/generated/deployment.identity.json`）提供稳定
`deployment_id`/`volume_identity`/`executor_epoch` floor，权威单调 epoch 存于卷拥有的
`executor-state/executor-epoch.v1.json`，仅由显式、可审计的
`scripts/ops/takeover_executor_epoch.py` 递增；journal v3→v4 在首次受控 claim 迁移并逐字段
保留证据；写入在 epoch 共享锁下复核，takeover 排他递增，旧 epoch 写者与并发 takeover 失败方
均 fail closed。`reanchor_session_lease.py` 降级为异常修复工具。不修改 Gateway trace、
Backend/domain schema、MCP、workers、DSH 版本或 composition，不部署、不自动合并。

Runtime Continuity R2：durable session identity 与 RuntimeGeneration 分离（feat，构建修订
`dsh-0.1.2rc1-post-u8.145`）：按 [ADR-0079](../architecture/adr/ADR-0079-runtime-continuity-and-session-recovery.md)
（Proposed）R2 将 `services/runtime-adapter/app/runtime.py` 的会话模型拆为 durable
AgentSession record（`session_id`/`trace_id`/owner/workspace、canonical sequence、
`executor_epoch`、status 与 journal evidence）与 ephemeral `RuntimeGeneration`（generation
id、session id、epoch、private native session、started_at、state 及该代际的运行态）。替换
generation（adapter restart、crash rebind、resume、root-scoped 新回合）建模为 NEW
generation，不再当作 session failure；`session_id`、sequence 与 lifecycle-journal 证据不变。
新增框架中立 `packages/contracts/runtime_continuity.py`，在 create/resume/rebind 结果中报告
`fresh`/`reattached`/`rehydrated`/`interrupted`：Path A（in-process generation 存活）复用为
`reattached`；Path B（generation 消失）新建 generation 并经既有 conversation
recovery/rehydration 合同恢复为 `rehydrated`；被终止的 run/generation 如实报告
`interrupted`，绝不伪造 reattach。continuity 经 Gateway `/v1/agent/sessions`（create）与
`/v1/agent/sessions/{id}/resume` 响应暴露，只含封闭字符串，不含 generation/native session/
process id，也不进入 WorkflowTrace。带界 per-session generation 历史写入
`<evidence-root>/generation-ledger/<session_id>.json`（BYQ-owned、best-effort，仅 generation
id/epoch/root/state/时间），不扩展 journal schema、不新增 PostgreSQL registry。保留 flock/
epoch fencing、`LifecycleJournal` 证据边界、prompt 幂等、at-most-once 与全部既有恢复行为；
不改 Gateway trace 模型、Backend/domain schema、MCP、workers、DSH 版本或续接预算。不含
Supervisor（R3）与 Terminal（R4）。不部署、不自动合并。

DSH 0.1.5-rc.1 原生连续性资格阶段 D15（feat/docs，构建修订 `dsh-0.1.2rc1-post-u8.155`）：
按 [ADR-0081](../architecture/adr/ADR-0081-dsh-native-continuity-and-d15-stage.md)（Accepted，2026-09-19）与
[D15 阶段计划](DSH_015RC1_UPGRADE_PLAN.md)，将 Runtime Continuity 的下一个原生能力步骤
插在 R2 之后、R3 之前：`R0 → R1 → R2 → D15 → R3 → R4 → R5 → R6 → 独立 Production Go/No-Go`。
R3 冻结（非回滚）为 `PAUSED_PENDING_DSH_015_NATIVE_CONTINUITY_QUALIFICATION`：保留既有
代码/测试/合同，暂停自建进程重启编排、会话重建、原生会话持久化替代、subagent 持久化与持久
PTY/shell。维护者决定资格目标为 coherent 配对 `dsh-v0.1.5-rc.1`/Python `0.1.5rc1`/npm
`0.1.5-rc.1`（`docs/evidence/d15/target-decision.v1.json`）；请求的 npm `0.1.5-rc.2` 无匹配
Python `0.1.5rc2`，保留为 not-a-coherent-pairing，D15-0-F1 据此解决。D15-0 交付机器可读升级台账
`docs/evidence/d15/compatibility-ledger.v1.json` 与 recon（27 个 BYQ 依赖接口；D15-1 探测后
changed 12/new 5/compatible 8/unknown 0/unchanged 2），记录 0.1.5 原生 Session V2/V3 迁移、
`SessionHandle`、跨进程写租约、continuable subagent 与 persistent terminal。D15-1 交付独立候选
声明 `config/dsh/candidates/dsh-0.1.5rc1/`、校验/selector `scripts/dsh/candidate_registry.py`、
compat 边界 `services/runtime-adapter/app/compat/dsh_015.py`，并新增候选 Dockerfile/requirements 锁，
构建隔离镜像 `byq-d15-1-0.1.5rc1-candidate:local` 后以 `--network none` keyless 启动并跑通 scripted
turn + tool call（事件序列连续，含 `tool/call`/`tool/result`，BYQ profile patch 加载成功），证据
`docs/evidence/d15/d15-1/`。生产默认 `dsh-0.1.2rc1`、`compose.yml`、`Dockerfile.post-u8-candidate`
与既有 0.1.2 制品/证据不变，候选不 push 且在不可变 `config/dsh/releases` 注册表之外，回滚目标
`dsh-0.1.2rc1`，无 DB/Worker 变更。D15 改变 runtime build inputs，故推进构建修订
`.145→.146`，D15-1 再推进 `.146→.147`，历史清单与全部证据保留。D15-2 提交 9 个不可变
session fixtures（`docs/evidence/d15/fixtures/sessions/index.v1.json`，含 sha256；`f-normal`
为隔离运行官方 0.1.2-rc.1 runtime 产生的真实 v0 会话，其余为 released-v2 codec 确定性构造）
与隔离 Node harness（`scripts/d15/harness/migration_harness.mjs`），经第一方
`@deepseek-ai/dsh-session-format-catalog`（`sessionFormatV2ToV3`）执行
`read → resume → append → close → reopen`，9/9 全阶段 pass、0 blocker、序列连续、message id 与
system prompt/provider context 保留，`f-forked` inherited cut 保留，迁移后 v3 不可降级（9/9），
fail-closed 拒绝不转为新会话。**D15-2 是格式层资格，不是 runtime 恢复**（`resume`=
`Session.fromRestore`、`append`= 手工编码事件、`close`/`reopen`= 文件/codec）。累计 verdict v2 显式
要求全部不变量/拒绝用例/blocker 通过并据此决定退出码，`negative-controls.v2.json` 证明注入的
sequence/id/context/reopen/blocker/fail-closed 破坏会失败而修复前的阶段门禁会误报 PASS；台账
`session_format_v2_v3` 增加 `observed_status=compatible` 并移出 `not_yet_probed`，
acceptance-matrix D15-2 置 PASS，证据 `docs/evidence/d15/d15-2/`。D15-2 仅新增测试/证据/文档，
但 `scripts/` 与 `tests/` 属于 BYQ build-input inventory，故按仓库规则构建修订推进
`.147→.148`（仅重建身份，不改 selector/deployment）。D15-3 交付隔离 Node harness
`scripts/d15/harness/native_resume_harness.mjs`（+ `native_resume_worker.mjs`/
`native_resume_common.mjs`）与分类器 `scripts/d15/native_resume_qualification.py`
（经 `packages/contracts/runtime_continuity.py::classify_generation_transition`）：以真实
0.1.5-rc.1 session-persistence seam（`SessionPersistence.create/open`、`SessionHandle`
read/append/flush/close、跨进程 `SessionWriteLease` flock、`readColdSessionLog`）驱动，
每个 runtime generation 一个 OS 进程，覆盖 8 个 failure-matrix 行。结果 8/8 持久化行可由新
generation 原生恢复同一 session（同 id、事件保留、序列连续）：browser/frontend/gateway 为
`reattached`，adapter restart/generation replacement/host reboot/executor takeover 为
`rehydrated` 原生恢复，DSH crash 为 `interrupted`（丢失 run 如实标记且仍可原生恢复）；native
不可用对照（未过 `flush()` 的未物化 session）正确不可恢复并需 BYQ fallback。公开
`fresh/reattached/rehydrated/interrupted` 合同不变，native/fallback 机制仅存于内部 evidence-only
诊断字段，DSH session id 不成为 BYQ AgentSession 身份。**证明边界**：D15-3 证明原生持久层恢复
（新 OS 进程重开同一 session），未运行 browser/frontend/Gateway/runtime-adapter 服务，也不证明
runtime 语义恢复：原目标保持、domain action 不重复、approval 仍有效、结果可追溯仍需一次真实隔离
runtime 资格，属必需下一步且尚未完成。结论：原生 session resume 可用、R3 不得
重复实现；R3 冻结与 `R3_RESUME = NO` 不变直至 D15-G。台账 `native_session_resume` 置 compatible
并移入 probed，acceptance-matrix D15-3 置 PASS，证据 `docs/evidence/d15/d15-3/`。D15-3 新增
`scripts/`、`tests/`、`packages/contracts` 与证据均属 build-input inventory，故构建修订推进
`.148→.149`（仅重建身份，不改 selector/deployment）。本轮 D15 资格完整性/验收措辞整改新增
`scripts/d15/harness`、`tests/` 与证据，先推进 `.150→.151`；CI-A `#326` 并入 `main`（`.154`）后，
本分支合并 `origin/main` 并改用未使用 id `post-u8.155`（仅重建身份）。D15-4..D15-G（subagent/fork、
persistent terminal、Go/No-Go）仍为 PLANNED。不部署、不自动合并。

D15-4 原生 subagent/fork 连续性资格（构建修订 `post-u8.165`，维护，不推进 Product Phase）：
维护者授权 develop/隔离测试/feature push/Draft PR。以固定 `dsh-0.1.5rc1` 候选闭包启动
**evidence-only Node harness**（`scripts/d15/subagent/native_subagent_harness.mjs`，真实
`@deepseek-ai/dsh-agent-loop` + JSONL session persistence + `@deepseek-ai/dsh-subagent` +
spawn/fork in-process provider，每代一个 OS 进程，scripted keyless adapter，标注
`real_llm_quality=false`），直接驱动原生 `startContinuable`/`Activation`/`authorizeLineage`/
`listChildren`/`sendMessage`/fork。6 个必需场景 `PASS`：parent/child 身份（`d15-4-parent` 与
不同 durable child，`header.parentSession`/`origin=subagent`）、v3 continuable descriptor、
新 OS 进程 cold resume 同一 child 且恰好一次 settlement、seeded fork（`inheritedEventCount=11`、
parent 不变）、provider/model/reasoning-effort/persona 继承并在 cold resume 重放、SIGKILL 执行
进程后 parent 身份仍在且 child 可原生恢复；6 个 runtime 反例被拒（non-direct/stale parent
`UNAUTHORIZED`、unmaterialized `NOT_RESUMABLE`、`maxDepth` `SubagentDepthError`、
child-claims-root `DUPLICATE_CHILD`、out-of-filter tool）。fail-able observer 以合同为准、
必需项 `NOT_RUN`/`BLOCKED` 一律非零退出；`negative-controls.v1.json` 23 项控制全部失败，其中
22 项证明修复前 result-only 门禁会误报 `all_pass=true`（含 required-blocked 场景）。reachability
probe 真实确认：提交的 BYQ 组合 5 个 `byq_delegate_*` 均 `enableRunInBackground: false`，候选
`@deepseek-ai/dsh-tool-subagent@0.1.5-rc.1` 仅在 background+continuable 分支调用
`startContinuable()`，故 continuable 冷恢复路径**不从 BYQ 可达**；`child-crash`（in-process child
不可单独 SIGKILL）与 BYQ `adapter-restart` 必需项 `BLOCKED`，保留最小具体选项（隔离 compose 栈 +
tool-aware scripted provider，不改生产组合、不新增 BYQ subagent 持久化），host reboot `NOT_RUN`。
**不主张完整 D15-4/D15-G/full-D15，`R3_RESUME = NO`。** 新增 `scripts/d15/subagent/`、`tests/` 与
证据均属 build-input inventory，构建修订推进 `post-u8.164 → .165`（仅重建身份，不改
selector/deployment/immutable registry/0.1.2 制品与证据）。不部署、不自动合并。

D15-4 早期评审缺陷整改 v2（构建修订 `post-u8.166`，维护，不推进 Product Phase）：`child-crash`
与 `byq-adapter-restart` 保持 required 且记为具名 `BLOCKED`（不得通过删除必需项或复用
owning-process SIGKILL 结案）；新增真实支撑场景 `child-run-fault`（child 模型流失败、parent 进程存活，
settlement 如实 "failed before it finished"、child id 保留且可原生恢复，SLATE 非 SIGKILL 替代）。
fork-lineage 改为精确不变量：`inheritedEventCount ==` parent 平衡完成回合前缀 cut（`last turn/end
seq + 1`，实测 `10 → 11`）、父日志**全哈希与长度**前后相等、child 序列连续；observer 新增
off-by-one/zero/payload-drift/length-mismatch/child-gap 负例控制，全部证明修复前 result-only 门禁
误报而修复后失败。每个临时根（主根与每个 negative 根）在 `finally` 中删除（含 worker 异常/超时
路径），`cleanup`/`root_cleaned` 记录实删；移除“native 拒绝即证明不存在的前置门禁会放过”的无依据
历史断言，唯一 pre-fix 比较仍是 observer 内真实重建的 legacy 算法。证据 v2 追加
`native-observations.v2.json`/`verdict.v2.json`/`negative-controls.v2.json`/`scenarios/*.v2.json`，
v1 全部保留不覆盖。新增 build inputs 属 inventory，构建修订推进 `post-u8.165 → .166`（仅重建身份）。
不部署、不自动合并。

D15-4 早期评审后续：CI 合同测试修正 + 原生接口/接线影响调查（构建修订 `post-u8.167`，维护）：
`tests/test_dsh_d15_candidate.py` 的 acceptance-matrix 断言不再要求 D15-4 `NOT_RUN`，而是严格接受
`BLOCKED` **仅当**其携带具名 `uncovered_items`（每项含 status+reason，必须覆盖 child-crash/
byq-adapter-restart/host-reboot），并断言 D15-G 未开启、`R3_RESUME stays NO`；不回退证据、不宽泛
接受任意状态。新增 `scripts/d15/subagent/routing_probe.mjs` 真实试验（boot 真实候选
`@deepseek-ai/dsh-subagent`+spawn provider+`@deepseek-ai/dsh-tool-subagent`，经
`ctx.tools.execute` 执行并计数 `start`/`startContinuable`）：提交的 BYQ 委派配置
（`enableRunInBackground:false`、无 `backgroundMode`）为 foreground（start=1、startContinuable=0）；
`backgroundMode: continuable` 仅 in-process `spawn` provider 可达（startContinuable=1）；无
`prepareContinuable` 的 out-of-process provider（模型化 dsh-sdk/ACP/Codex/Claude Code）被拒
`does not support \`backgroundMode: continuable\``。结论：BYQ 到 `startContinuable` 的接线是产品语义
变更（foreground 结果 → durable background child；影响组合 5 个 delegate 工具、工具结果契约、
runtime-adapter child-lease 观察、dsh_015 compat 边界），超出本 PR 资格范围，且 0.1.5rc1 无独立进程
continuable child provider，仍不能解决 child-crash/adapter restart；故 D15-4 保持 `BLOCKED`，
最小候选兼容 hookup 计划在独立 worktree/feature PR 实施（普通实现，非需授权事项）。证据
`docs/evidence/d15/d15-4/routing.v1.json` 且 v1/v2 不覆盖。routing probe 采用每 trial 一个 OS 进程
并在 `finally` 中重试删除根（`runtime_root_cleaned=true`，无泄漏），该清理修订推进构建身份
`.167 → .168`（仅重建身份）。不部署、不自动合并。

D15-5 原生 persistent terminal（PTY）连续性资格（构建修订 `post-u8.170`，维护，不推进 Product
Phase）：以真实隔离候选闭包启动 evidence-only Node harness（`scripts/d15/terminal/native_terminal_harness.mjs`），
驱动真实 `@deepseek-ai/dsh-terminal` owner-scoped `TerminalSessionService` + `dsh-terminal-bash`
`shell` backend（`bwrap --die-with-parent`），**每个 runtime generation 一个 OS 进程**、每个客户端动作
一个独立 OS 进程（Unix socket），外层为 evidence-only BYQ `TerminalAttachment` gate（身份/状态/授权/
reconnect，不拥有 PTY/shell/IO）；不调用任何模型（`llm.class=not-applicable`）。显式区分四项：
PTY/进程存在、attachment 存在、I/O rebind、稳定 terminal 身份。四行 `PASS`：page refresh /
browser disconnect / frontend restart / gateway restart，另一客户端 OS 进程重绑同一
attachment/session/pid。跨进程唯一 marker 测试 `PASS`：首标记在首个客户端 viewport 出现一次、
在 rebind send delta 出现 0 次（不重放）、在 scrollback 出现一次（不丢失），第二标记一次；
`permission-boundary`（`FOREIGN_SESSION`/`UNAUTHORIZED_PRINCIPAL`）、`wrong-terminal-rejected`
（`NO_SESSION`）、`stale-generation-fenced`（`STALE_GENERATION`/`STALE_EPOCH`）、
`cleanup-no-orphans`（pid 全灭、shutdown orphans=0）与 `pty-attachment-separation`（真实 bwrap pid
≠ registry attachment id；丢 attachment 后 pid 仍活、rebind 被拒；kill 结束 PTY）全部 `PASS`。
必需项 `adapter-restart` 与 `dsh-runtime-restart` 保持 `BLOCKED`：native sessions 文档为
process-local，提交的 BYQ 树未 compose terminal、未持久化 `TerminalAttachment`，`interface-probe.v1.json`
证实无 PTY/attachment 产品面（唯一 `terminal-receipt` 路由是 AgentRun 终态证据）；记录真实拒绝证据
而非伪造 reattach；host reboot `NOT_RUN`。fail-able observer（`scripts/d15/terminal/observer.py`）
区分格式有效与资格通过、必需 `BLOCKED` 非零退出，24 项负例控制（23 项 defect-targeting）证明修复前
result-only 门禁误报。框架中立合同
`packages/contracts/terminal_attachment.py`（`attached/reattached/rehydrated/lost/interrupted/fenced`
与 BYQ/DSH 所有权划分）。跨进程 reattach 边界以 Proposed、未实现的
[ADR-0083](../architecture/adr/ADR-0083-terminal-attachment-boundary.md) 记录。**D15-5 保持
`PARTIAL/BLOCKED`，不主张完整 D15-5/D15-G/full-D15，`R3_RESUME = NO`。** 新增 build inputs 属
inventory，构建修订推进 `post-u8.169 → .170`（仅重建身份）。不部署、不自动合并。

D15-G architecture Go/No-Go（构建修订 `post-u8.171`，维护，不推进 Product Phase）：先定义
fail-able decision contract（`scripts/d15/go_no_go/contract.v1.json`）与 observer
（`scripts/d15/go_no_go/observer.py`），再计算结论。observer 从已提交 D15-2..D15-5 证据独立
推导每个必需 capability 状态并校验 provenance sha256；GO 仅当全部必需 atomic capability
`PASS`，任一必需项非 PASS 强制 `NO_GO` 且必须具名 actionable blocker；只有 atomic required
capability 可作 blocker，aggregate capability 为 display-only（由 atomic 成员推导，不得重复
计为独立 blocker），optional capability 为 limitation（不 gate GO、不作 blocker）。observer
拒绝部分 PASS 聚合为 GO、claimed 与 derived 不一致、缺失 blocker/证据/自声明 verdict/coverage
字段，以及把 aggregate/optional 列为 blocker。`negative-controls.v1.json` 19 项控制全部被拒
（18 项 defect-targeting，修复前 result-trusting 门禁误报），已知“全部必需 PASS 且 optional
host-reboot NOT_RUN”的合成 fixture 得到诚实 GO 并通过。capability/failure matrix
（`docs/evidence/d15/d15-g/capability-matrix.v1.json`）按 required-atomic / derived-aggregate /
optional-limitation 覆盖 D15-2..D15-5 每项 DSH-native 结果/BYQ fallback/R-series owner/证据。
推导结论：root-session-persistence、process-restart-resume、fork-continuity、
terminal-client-reattach `PASS`；四个 atomic 必需项 subagent-child-crash、
subagent-byq-adapter-restart、terminal-adapter-restart、terminal-dsh-runtime-restart `BLOCKED`；
aggregate subagent-resume/terminal-persistence 因成员 `BLOCKED` 而 display `BLOCKED`；optional
host-reboot-resume 为 `NOT_RUN` limitation。**结论 `NO_GO`（NOT-PASS）仅由四个 atomic 必需
blocker 决定：child-crash、BYQ adapter restart、terminal adapter restart、DSH runtime restart；
host reboot 为 optional limitation `NOT_RUN`，不决定结论；不得聚合部分 PASS 为 GO。** 生产
selector/default 不变、R3 冻结且 `R3_RESUME = NO`、Proposed ADR-0082/0083 未接受未实现、无
部署/发布/tag/付费/重启主机。新增 build inputs 属 inventory，构建修订推进
`post-u8.170 → .171`（仅重建身份）。不部署、不自动合并。

数据就绪续接 needs_attention 重挂（fix，构建修订 `dsh-0.1.2rc1-post-u8.142`）：生产 round-2
数据就绪续接回合结算为 `needs_attention` 后，`research_tasks.continuation_blocked_reason` 被写成
`continuation_needs_attention`；原预算路径的按任务级 `continue` 使其永久阻止后续**不同**的
`ready-v1:` 事件，因此即使新的 signal job 完成并产出新的 validated snapshot，也不再自动续接
（ADR-0077 Proposed）。现按 [ADR-0077](../architecture/adr/ADR-0077-data-ready-auto-continuation.md)
将阻塞改为**事件作用域**：新增持久列 `research_tasks.continuation_blocked_event_key`，在结算
`needs_attention` 与 `continuation_scope` 范围违例时记录触发阻塞的确切事件键；
`claim_conversation_continuation` 只在候选事件键等于被阻塞键时继续抑制，遇到新的不同事件即重新
挂起并走既有 `continuation_budget` 预留。同一事件仍由已结算账本行保证 at-most-once，回合计仍受
`DATA_READY_MAX_TURNS`/`max_turns`、token 预算与 900 秒期限约束；显式 `block_continuation` 写
`*` 任务级哨兵继续阻止所有事件，授权撤销、任务/会话终态仍按原门禁阻止。部署前的历史行（事件键
为空）从最近一条已结算 `needs_attention` 账本行恢复其事件键，使已阻塞的存量任务也能在新事件上
重挂。新增结构化日志记录阻塞原因、重挂决策与新事件键；没有新增第二个续接引擎，也没有 worker
SQL 写入。不改变 Accepted ADR 文本；ADR-0077 仍为 Proposed。

数据就绪续接多调用预算（fix，构建修订 `dsh-0.1.2rc1-post-u8.144`）：生产 ADR-0077 数据就绪
自动续接已能触发，但续接回合一旦需要第二次模型调用即失败（`turn.completed reason=cancelled`
→ `session.failed code=model-run-failed`）。根因是预算记账：guard
`plugins/dsh-byq/runtime/byq-continuation-budget.js` 每次 `llm/stream` 保守计入
`1048576 + options.maxTokens`，而 Backend `DATA_READY_TOKEN_LIMIT` 仅按单次调用预留
`1048576+8192`，首次调用即耗尽全部额度，第二次调用以 `BYQ_CONTINUATION_BUDGET_EXHAUSTED`
闭合。现按 [ADR-0077](../architecture/adr/ADR-0077-data-ready-auto-continuation.md) 将数据就绪
单回合扩为**有界多调用**：以 guard 导出常量为唯一来源，`DATA_READY_MAX_CALLS=8`、每调用输入
上界 `1048576` 与输出上限 `8192`，合计 `DATA_READY_TOKEN_LIMIT=8*(1048576+8192)`；Backend 预留
与 runtime-adapter `CONTINUATION_MAX_OUTPUT_TOKENS` 随同更新，架构漂移测试断言三者一致。guard
同时强制预留级调用次数上限（由总预算与最小单次记账推导，并以 `MAX_CALLS=256` 绝对封顶）与总
token 上限，任一项超限仍以稳定错误失败闭合；900 秒期限、单调硬截止、路由资格与每事件最多一次
均不变。单次调用回合与普通非续接回合不受影响。不部署、不自动合并。

从 Phase 9 起，永久 migration source of truth 为 `docs/migration/COMMUNITY_MIGRATION_INVENTORY.md`。实现 phase 前必须先检查、分类其 Community candidates。可在 BYQ-owned contracts 中重新实现 provider/engine-independent semantics，但不得复制 Community runtime、storage、provider 或 engine architecture。BaoStock、AKShare、VectorBT、PydanticAI 和 Hermes 保持排除，除非未来 Accepted ADR 明确反转。

所有 phases 遵循 `docs/DEVELOPMENT_WORKFLOW.md`：只执行 `STATUS.md` 指定的 next phase；每 phase 使用 isolated worktree/branch/PR；contract/test 优先；保持 Product/Agent/Quant/Data/Engineering boundaries；CI 与 evidence 完成后才进入 merge gate。

## 1.0 版本规划（Accepted planning baseline）

维护者于2026-09-11接受 [ADR-0071](../architecture/adr/ADR-0071-v1-machine-learning-release-plan.md)。
[版本里程碑](VERSION_PLAN.md)、[模块支持矩阵](V1_ML_SUPPORT_MATRIX.md) 和
[稳定性发布门槛](V1_RELEASE_ACCEPTANCE.md) 定义后续0.x至1.0范围。
它们补充历史Phase计划，不把历史RC开放结论视为当前1.0可发布，也不预授权新阶段。
新增模型、GPU、有限调参、HIST和Worker边界仍须具名实施ADR及STATUS下一阶段授权；Phase97保持完成。

## Phase 6 — Runtime seam、ADR-0003 与 development framework

- **目标/范围**：验证 Gateway → Runtime Adapter → official DSH SDK → explicit DSH runtime seam；研究 official npm/PyPI rc.6；评估 Options A/B/C 并接受 ADR-0003；实现 Python/FastAPI Runtime Adapter 的 keyless initialize、MCP startup、lifecycle、normalization、internal SSE prototype 与最小 `WorkflowTraceEvent`；补 architecture/unit/contract/smoke CI 和 workflow docs。
- **边界**：dedicated Runtime Adapter；Gateway 无 DSH imports/raw events；domain access 走 BeyondQuant MCP；Product DSH coding capability 为 NONE；DSH persistence 留 Agent Plane；rc.6 exact-pin。无 public chat、frontend、real model turn、DSH fork/Web proxy/domain feature。
- **验收/停止**：ADR-0003 Accepted；initialize/MCP/cleanup 与全部 Phase 5/6 CI 通过，STATUS 指向 Phase 7。缺 official evidence、boundary violation、unreliable cancellation、要求 DSH fork 或 workflow stop 时停止。

## Phase 7 — First Product Agent Turn + WorkflowTrace

- **目标/范围**：经 accepted seam 交付第一个 authenticated Product Agent turn 和 BYQ-owned end-to-end WorkflowTrace；覆盖 model/provider secret、prompt flow、resume/interrupted、trace persistence/ordering 和 Gateway internal streaming。
- **边界**：Gateway 只见 BYQ envelopes；domain calls 走 MCP；Product DSH 无 coding/source-write；business state 归 BYQ。无 quant tools 扩展、frontend workflow UI 或 multi-agent research。
- **验收/停止**：真实 model-keyed turn 可从 Gateway→adapter→MCP→返回追踪；cancel/resume/secret tests 通过；keyless CI 无 secrets。发现 secret leakage、raw DSH 跨 Gateway、resume ownership 不清或需扩大 capability 时停止。

## Phase 8 — Data Provider Abstraction + Tushare

- **目标/范围**：引入 BYQ-owned provider contract 和安全 Tushare integration，定义 authentication/configuration、symbol/date semantics、rate limits、cache 和 provenance。
- **边界**：provider 属于 Data/Domain planes；DSH 只经 MCP 访问；不得直接访问 PostgreSQL。无 factor、strategy、backtest 或 agent credential autonomy。
- **验收/停止**：provider/Tushare contract tests、redacted fixtures、retry/rate limit、audit/provenance 通过。A-share semantics 模糊、cost 无界、secret 暴露或 provider 无法 contract-test 时停止。

## Phase 9 — ResearchTask + Experiment + Artifact

- **目标/范围**：定义 durable BYQ research entities、provenance、lineage、state transitions、idempotency、validation 和 MCP contracts。
- **边界**：domain invariants/business state 归 BYQ；DSH workflow state 与 artifact state 分离；artifact 是 auditable domain data。无 factor library、strategy runtime、backtest worker 或第二套 DSH state machine。
- **验收/停止**：versioned state/lineage 由 Backend 持久化，并经 MCP/contract tests 验证。ownership/provenance、DSH/domain state 或 idempotency 不清时停止。

## Phase 10 — Factor Research

- **目标/范围**：在 data/artifact 基础上建立 reproducible factor research。BYQ input boundary 必须覆盖 canonical A-share symbol/exchange/asset type；listing/delisting/suspension lifecycle；区分 missing/not-listed/delisted/suspended/boundary/non-trading；trading-session windows/lags；每 `(symbol, trade_date)` 一个 deterministic bar、duplicate policy、stable ordering、finite/OHLC validation；dataset identity/provenance/reproducibility/effective/announcement/`as_of`；point-in-time universe/index membership。
- **边界**：compute 在 BYQ workers/services；DSH 仅经 MCP propose/invoke；inputs/provenance immutable。Tushare 在 Data Provider Contract 后；不得引入 BaoStock、AKShare 或 Community provider engine。若 Phase 8 hardening 实现 duplicate/order/OHLC，只能限于 contract。
- **验收/停止**：deterministic fixtures、lifecycle/calendar/coverage、PIT/no-lookahead、provenance/lineage 可复现；input identity/visibility/coverage 模糊时不接受 factor。Look-ahead、undefined as-of、missing lifecycle/calendar、malformed bars 或 prompt-only invariants 时停止。

## Phase 11 — Strategy Artifact + Validation

- **目标/范围**：将 strategy code/configuration 表示为 validated、auditable domain artifact；定义 StrategyDraft/Artifact、immutable content-addressed StrategyVersion、validation evidence、approval gates、provenance、version/export 和 MCP。
- **边界**：version identity 来自 deterministic semantic snapshot/source fingerprint，排除 mutable timestamps；export 不含 credentials/runtime/Agent internals；validation、approval、execution outcome 分离。Strategy code 不是 application source，Product DSH 不写 repository，也不 unrestricted execute。
- **验收/停止**：invalid strategy 返回 contract error；versions immutable、replay 精确；exports deterministic/secret-free；evidence/approval auditable 且不把 approval 当 execution success。出现 source access、mutable version、secret export 或 unsafe execution 时停止。

## Phase 12 — Backtest Job + Worker

- **目标/范围**：以 durable isolated jobs 执行 validated strategy artifacts。BYQ native deterministic engine、A-share rules、frozen universe/version authorization、content-addressed input/result manifests、queue/state/retry/idempotency、resource bounds、object lifecycle/audit。
- **规则**：engine 明确测试 T+1、limit-up/down、suspension、lot size、fees、stamp tax、cash、corporate actions 和 stable blocked reasons。Manifest 冻结 signals/prices/status/actions/universe/version/engine/reproducibility。Result rows 仅存 namespace/object ID/media type/size/SHA-256 reference。
- **边界/验收**：worker independently deployable；DSH 不访问 storage/worker；VectorBT 不作为 dependency；owner/live-reference 决定 universe/deletion。Jobs isolated/restartable/idempotent/bounded；golden tests 覆盖 rules、manifests、retry、references 和 fail-closed deletion。Unbounded execution、mutable input、universe escape 或 unsafe artifact 时停止。

## Phase 13 — Quant Research Agents

- **目标/范围**：以 DSH presets/skills/subagents 增加 specialized roles，覆盖 tool permission、delegation、multi-agent trace、owner/actor authorization、human approval、audit 和 DSH correlation。
- **边界**：generic roles/orchestration 归 DSH；domain invariants、authorization、approval、audit、evidence promotion 归 BYQ 并经 MCP。无第二 generic harness、direct DB tools 或 Product Engineering privileges。
- **验收/停止**：least-privilege capabilities、isolation/E2E tests；audit 关联 owner/actor/DSH run/domain action/result/failure；approval failure 与 execution 分离；不能 bypass invariants/promote unreviewed evidence。Privilege escalation、duplicate BYQ invariants 或新 harness 时停止。

## Phase 14 — Quant Learning Loop

- **目标/范围**：闭合 research→experiment→artifact→validation→backtest learning loop，覆盖 evaluation signals、comparison、feedback lineage、repair/retry、evidence promotion 和 bounded iteration。
- **边界/验收**：每步 bounded、reproducible、auditable，经 BYQ contract；prompt 不替代 approval。Runs 有 budgets、stopping rules、human gates 和 replay；promoted lessons 保留 evidence/validation/review/provenance/history，chat 不能直接变 trusted knowledge。Unbounded autonomy、无 rollback/approval 或 feedback 不可复现时停止。

## Phase 15 — Engineering Plane / Code Improvement

- **目标/范围**：在不削弱 Product isolation 的前提下，支持 EngineeringTask、diagnostics、isolated worktrees、tests、Draft PR、CI evidence 和 human merge workflow。
- **边界/验收**：Product/Engineering privileges 分离；不 direct main push/merge、production deploy、destructive migration 或赋予 Product DSH source-write。EngineeringTask 可产出 tested Draft PR、architecture evidence、CI/self-review，并停 human gate。缺 isolation、privilege expansion、CI bypass 或要求 direct main 时停止。

## BeyondQuant Productization Program（Phase 16–23）

Phases 6–15 是 Headless Quant Research Platform Core，不等于 product completion。Phases 16–23 按以下顺序 productize：

```text
Product API + durable data → frontend shell → Agent workbench → Quant workspace
→ user/platform settings → Stock Pool/Paper Trading
→ operations/deployment → parity matrix/release candidate
```

Community 始终是只读 behavioral/visual evidence；不是复制架构的授权。

## Phase 16 — Product API / BFF + Durable Data Migration Foundation

- **目标/范围**：建立 browser-facing Gateway Product API/BFF、auth/session owner/actor、safe error、bounded pagination/filter/sort、versioned OpenAPI/TS types、dashboard/research/factor/strategy/backtest/approval/audit/Agent/WorkflowTrace/data-status projections；接受 Durable Market Data Storage ADR；设计 Community logical cache migration、manifest/validation 和 frontend inventory。
- **Migration invariants**：Community PostgreSQL read-only；仅 logical `SELECT`/`COPY OUT`/data-only export→validate/normalize→manifest→idempotent BYQ import→verify。禁止 physical directory copy/mount。只允许 proven `tushare` 或 provider-independent rows；排除 BaoStock/AKShare。验证 canonical symbols、`YYYYMMDD`、units、finite/OHLC、non-negative vol/amount、adjustment/asset/source、duplicates/order、lifecycle/PIT；invalid rows quarantine/report。Conflict policy 为 `KEEP_NEW`、`VERIFY_EQUAL`、`REPORT_MISMATCH`。
- **边界/验收**：frontend 只用 Product API，不暴露 MCP/DSH/raw events/tokens/storage schema；migration 可 dry-run 出 manifest/quarantine，Community 不变，不在 acceptance 中 bulk import。Ownership/auth、storage ADR、provenance、determinism 或 read-only 被破坏时停止。

## Phase 17 — Frontend Foundation

- **目标/范围**：创建 `apps/frontend` Vue 3+Vite+TypeScript，使用 Vue Router、Pinia、Element Plus、ECharts、typed client、OpenAPI types、Playwright。交付 shell/header/sidebar/mobile nav/router/auth bootstrap/design tokens/responsive/errors/loading/empty/toasts/dialog/chart；首批 Login、Dashboard、System Status、user menu。
- **边界/验收**：先检查分类 Community UI，复用 architecture-neutral visual language，重写 auth/API。Frontend 不直连 MCP/DSH/Backend/provider/database，也不依赖 raw events；core stack change 需 ADR。App boots、responsive states、Playwright CI 和 Community workflow-level review 通过；不得 wholesale copy。Direct coupling、missing auth ownership 或未经 ADR 换 stack 时停止。

## Phase 18 — Agent Research Workbench

- **目标/范围**：围绕 DSH、WorkflowTrace、ResearchTask、Experiment、Artifact、Approval 重设计 Community Agent UX；支持 session create/resume、conversation/stream/cancel/recovery、task/subagent/tool/domain visualization、trace、artifacts/evidence/approval/audit。
- **边界/验收**：browser 只收 normalized Product events，不显示 raw DSH/secret；唯一 path 为 Frontend→Product API→Gateway/Runtime Adapter→DSH/MCP。BYQ 拥有 domain state，DSH 拥有 generic session/orchestration。Core conversation/approval Playwright、stable replay/order 和 secret/raw-schema tests 通过。Raw event/browser DSH access、model identity/approval、unbounded stream 或 capability escalation 时停止。

## Phase 19 — Quant Workspace

- **目标/范围**：用真实 Product API 交付 ResearchTask/Experiment/Factor/Strategy/Backtest workspace。Factor 包含 definition/universe/date/compute/coverage/distribution/metrics/evaluation/lineage；Strategy 包含 draft/editor/validation/immutable version/approval/history/provenance；Backtest 包含 submit/state、equity/benchmark/drawdown/annual return/Sharpe/volatility/win rate、trades/positions/blocked reasons/fees/tax/artifacts/manifest/reproducibility。
- **边界/验收**：invariants 归 BYQ；strategy 是 domain artifact；results 为 immutable authorized references。ECharts states/large results tested；browser 可从 research 到 approved backtest，无 raw APIs/fake charts。Input identity/look-ahead/coverage、mutable history、unbounded results 或 excluded engine/provider 回归时停止。

## Phase 20 — User & Platform Settings

- **目标/范围**：Product API-backed Profile、Model Settings、Data Provider/Tushare capability、Agent Preferences、Approval Inbox、Assets、Storage/System Preferences。
- **边界/验收**：secret fields write-only/masked；browser 只收 `configured`、status/capability/permission/masked metadata，绝不收 `DEEPSEEK_API_KEY`、`TUSHARE_TOKEN`、`BYQ_PRODUCT_TOKEN`、MCP/bearer/decrypted credential。Settings 不授予 Operations/Engineering privilege。Owner isolation、audit 和 secret-boundary network/log/error tests 通过；secret exposure/privilege confusion/cross-owner/internal schema dependency 时停止。

## Phase 21 — Stock Pool & Paper Trading

- **目标/范围**：Stock Pool 支持 watchlists/research/candidates/tags/rankings/Agent recommendations/provenance/snapshot history；只复用 provider-independent semantics。Paper Trading 为独立 BYQ simulation domain，定义 portfolio/cash/positions/orders/fills/fees/tax/T+1/limits/suspension/lots/audit/version/provenance，无 live broker。
- **边界/验收**：paper 不是隐藏 Backtest engine；Product DSH 只经 MCP propose，mutation 受 BYQ idempotency/approval/owner/audit。Versioned pools、historical identity 和 simulation accounts/orders/fills/blocked reasons 真实；golden tests 覆盖规则，无 broker call。State conflation、missing invariants、non-deterministic fills 或 credential exposure 时停止。

## Phase 22 — Operations and Deployment

- **目标/范围**：role-protected、secret-safe、read-mostly Operations projection，覆盖 Gateway、Runtime Adapter、DSH、MCP、Backend、workers、provider、queues、object store、database、Redis、WorkflowTrace、audit、disk/migration；交付 production topology、volumes、backup/restore/migration、health、limits、logs、upgrade/rollback。
- **边界/验收**：operations permission 与 normal Product 分离；destructive actions explicit/audited/fail closed；DSH 不访问 business storage；services 独立升级隔离。Health/backup/real restore/migration procedures 可执行；logical Community migration repeatable/rollback-safe；observability 可关联 request/trace/DSH/domain/job/artifact/audit，不泄 raw events/secrets。Untested restore/destructive defaults/topology drift/unverifiable migration 时停止。

## Phase 23 — Community Feature Parity and BeyondQuant Next Release

- **目标/范围**：维护 `COMMUNITY_FEATURE_PARITY_MATRIX.md`，将每个 page/capability/component/dialog/chart/setting/operations surface 标记 `PORTED`、`REDESIGNED`、`REPLACED`、`DROP` 或 `DEFERRED`，并为每项给理由/target/acceptance。明确 PydanticAI/Hermes、raw Agent coupling、BaoStock/AKShare/VectorBT 被 drop/replace。
- **Product acceptance**：ordinary user 能完成 Login→Dashboard→小巴→ResearchTask/agents/WorkflowTrace→Tushare/cache→Factor→Strategy Draft/Version→human Approval→Backtest/charts/trades→Artifact/Evidence/Lineage→Stock Pool/Paper Trading→Settings→Operations，且 traceable/reproducible/auditable/secret-safe。
- **Golden gate**：Playwright 真实路径 `Login → Dashboard → 小巴 → ResearchTask → Factor → Strategy → Approval → Backtest → Result → Artifact → Stock Pool / Paper Trading`；CI 覆盖 API、secret、migration、responsive、architecture，最后停 human review。Missing journey/unresolved classification/failed secret-trace-restore 或 bypass human gate 时停止。

## BeyondQuant Product Completion Program（Phase 24–30）

Phase 23 只形成 Product Skeleton。Phases 24–30 每 phase 一 isolated worktree/branch/Draft PR/human review，UI phase 还需 Chrome MCP。Vue file/endpoint/placeholder 存在不等于完成；必须经真实 Product API/browser/persistence/states/checklist。

### Phase 24 — Durable User Identity & Authentication

以 BYQ-owned User/password hashing、Gateway username/password、secure HttpOnly session（或 ADR-approved equivalent）、logout/revoke/expiry/change-password、bootstrap admin、roles/disabled-user 和全资源 owner isolation 取代 Product Token browser login。Browser 表单不得使用 Product Token；该 token 仅 internal/service bootstrap。

### Phase 25 — Community Frontend Full UX Restoration

恢复熟悉 shell/navigation、real-data dashboard、shared cards/tables/pagination/dialogs/forms/status/empty/loading/error/charts；使用 BYQ contracts，并记录 Chrome MCP visual comparison。

### Phase 26 — Full Quant Workspace

交付真实 Factor create/compute/coverage/results/history；Strategy draft/editor/validation/version/history/approval/backtest links；Backtest create/status/retry/metrics/ECharts/trades/positions/blocked/fees/tax/manifest/lineage。禁止 fake metrics/charts。

### Phase 27 — Research、Artifact 与 Approval Center

可视化、管理 ResearchTasks、Experiments、Artifacts、Evidence、Lineage、Approvals；artifact browser 展示真实 metadata/hash/lineage/provenance 而不嵌大对象；Approval Inbox 支持 pending/approved/rejected 和 human decisions，并保持 execution outcome 分离。

### Phase 28 — Historical Market Data Migration & Data Center

执行 read-only Community audit 的真实 counts/date/symbol/source；完成 validation/normalization/quarantine/manifest/import/verification 且幂等；禁止 physical PG copy，BaoStock/AKShare/VectorBT 保持 DROP；Data Center 显示真实 datasets/coverage/sync/provider/quality/migration/quarantine/refresh，无 secrets。

### Phase 29 — Platform Administration & Operations Completion

交付 user/model/data/agent management、runtime operations、真实 backup/restore test，以及不泄 credential 的 logging/WorkflowTrace/audit/job-failure lookup。

### Phase 30 — True Community Feature Parity & BeyondQuant Next v1.0 RC

`COMMUNITY_FEATURE_PARITY_MATRIX_V2.md` 对每 feature 使用 `PASS`/`REDESIGNED_PASS`/`INTENTIONAL_DROP`/`FAIL`；release conclusion 无 `DEFERRED`；执行 Community Chrome comparison、无 mock/direct internal call 的真实 Product API golden journey 和 multi-user isolation E2E。Required item 缺失时不得完成。

## Phase 31 — PostgreSQL Single Domain Store（ADR-0016）

- **目标/范围**：以 PostgreSQL 作为唯一 BYQ domain-store engine。增加 `byq_domain`、`byq_domain_test`、`byq_bootstrap`；引入 `services/backend/app/db.py`（SQLAlchemy Core + psycopg），以 ResearchStore 为 pattern 迁移全部 stores；移除 SQLite/`BYQ_DOMAIN_DB_PATH`；提供 idempotent SQLite→PG logical migration（`KEEP_NEW`/`VERIFY_EQUAL`/`REPORT_MISMATCH`）、verification 和 `pg_dump`/`pg_restore` drill。LocalObjectStore 不变，不把 large blobs 存 PG。
- **边界/验收**：DSH/MCP/Gateway/Product boundaries 不变；Community PG 只读。全部 backend tests 使用 PG test DB，无 SQLite path，public store methods 不变；migration 幂等验证、restore drill/Compose/docs 通过。详细计划见 `docs/architecture/POSTGRESQL_MIGRATION_PLAN.md`。

## Phase 32–40 — Community Product-Depth Completion

这些 phases 延续 Product Completion Program；`STATUS.md` 只选择一个 next phase。每 phase 真实 Product API、owner isolation tests、Chrome MCP 和 Community checklist；mock-only Playwright 不是 acceptance evidence。详细清单/依赖见 `COMMUNITY_FULL_PARITY_PHASE_DETAILS.md`、`COMMUNITY_FULL_PARITY_PLAN.md`。

- **Phase 32 Backtest depth（`COMPLETE`）**：交付 `signal_snapshot` submit/wizard、result depth、compare/delete/mobile；producer 由 ADR-0017 排除并转 D-0002。
- **Phase 33 Strategy depth（`COMPLETE`）**：durable drafts、soft-supersede、immutable versions/history/counts/read-only、Product API/MCP/evidence；D-0009–D-0012 转 Phase 40。
- **Phase 34 Stock Pool（`COMPLETE`）**：ADR-0020 mutable identity/immutable snapshots/fingerprint/types/provenance/weights/lifecycle/references；五 detail tabs、`byq_pool_*`、evidence 在 `docs/evidence/phase-34/`。
- **Phase 35 Paper Trading（`COMPLETE`）**：六 tabs、T+1/cash ledger、immutable settlement、frozen pool、controls、order audit、digested bundles、Product API/MCP/E2E；无 live broker。
- **Phase 36 Agent workbench（`COMPLETE`）**：ADR-0018 curated cards/activity/answer、Gateway hydration、approvals/starters/Xiaoba drawer；evidence `phase-36/`。
- **Phase 37 My Space（`COMPLETE`）**：ADR-0019 encrypted credential lifecycle/private resolution、model binding、asset re-import/new IDs、policy rules/audit；evidence `phase-37/`。
- **Phase 38 Operations（`COMPLETE`）**：ADR-0019/0022 下九个 workbenches、`operations.v1`、normalized DSH usage、audited threshold；无 secret/raw events/SQL control/Redis；evidence `phase-38/`。
- **Phase 39 Data Center（`COMPLETE`）**：Tushare-only credential/test/durable jobs/PG import/coverage；BaoStock/AKShare DROP；evidence `phase-39/`。
- **Phase 40 parity closure（`COMPLETE`）**：ADR-0023 isolated producer；关闭 D-0002、D-0009–12，zero-orphan 后 drop D-0003；shared state/pagination/deep strategy；no-mock two-user/Chrome evidence `phase-40/`，重新开放 v1.0 RC gate。
- **Post-Phase 40 DSH Upgrade Lane（`COMPLETE`）**：Python `0.1.1rc1` + exact npm `0.1.1-rc.1` qualified，rc.6 rollback；不改 Product phase/capability。

## Post-parity Product Experience Program（Phase 41–48）

Maintainer 于 2026-08-23 延后 RC，选择 ADR-0024 conversation-first；详细 source 为 `FRONTEND_EXPERIENCE_PLAN.md`。

- **Phase 41 baseline（`COMPLETE`）**：接受 ADR-0024，分类 shell/session/theme/settings，固定 IA、conversation ownership、appearance contract、42–48 sequence/preview；不声称 implementation。
- **Phase 42 shell（`COMPLETE`）**：single-level sidebar/toolbar、Xiaoba default、current sessions、account menu/mobile drawer，保留 routes/admin；durable title 留 Phase 43。
- **Phase 43 conversations（`COMPLETE`）**：owner-scoped catalog、titles/lifecycle/search、restart-safe normalized replay、centered workspace。
- **Phase 44 user center/appearance（`COMPLETE`）**：consolidate Profile/Assets/Models/Policy/Paper；`ui-preferences.v1`、system/light/dark、closed accents/cross-device。
- **Phase 45 System Settings（`COMPLETE`）**：route-backed desktop dialog/mobile full-screen operations/Data Center，不弱化 RBAC/audit。
- **Phase 46 management redesign（`COMPLETE`）**：统一 Pool/Strategy/Backtest catalog/detail、deep links/charts/responsive，保留 domain invariants/results。
- **Phase 47 interaction/accessibility（`COMPLETE`）**：global states、unsaved changes、keyboard/focus/responsive/theme/chart matrix。
- **Phase 48 golden journey（`COMPLETE`）**：fresh no-mock two-user desktop/tablet/mobile journey 覆盖完整 Product；无 crossover/unexplained gap，修复 dark mobile selector contrast，Lighthouse Accessibility/Best Practices 100；human RC open/pending。

## Personal Workspace Tenancy Program（Phase 49–52）

Maintainer 于 2026-08-24 再次延后 RC，以 ADR-0025/`PERSONAL_WORKSPACE_TENANCY_PLAN.md` 建立 explicit personal workspace boundary。

- **Phase 49 boundary（`COMPLETE`）**：分类 Community tenancy；接受 ADR-0025/`personal-workspace.v1`；区分 user/workspace/platform/Engineering，固定 context/migration/rollback/future-team；不声称 schema runtime 完成。
- **Phase 50 foundation/backfill（`COMPLETE`）**：durable workspaces/memberships、atomic provisioning、nullable indexed keys、transactional dry-run/execute backfill；ambiguous rows quarantine/report；authorization 暂保持 owner-based。
- **Phase 51 authorization cutover（`COMPLETE`）**：session workspace resolution、browser-header stripping、Gateway→Runtime Adapter→DSH→MCP→Backend trusted propagation、membership fail closed、write stamping/mismatch rejection、workspace idempotency、31-table non-null；evidence `phase-51/`。
- **Phase 52 closure（`COMPLETE`）**：bounded workspace projection/orientation、bundle diagnostics/Paper not-found；fresh provisioning/restore/restart/forward repair，31 enforced tables、22 zero checks/no quarantine；two-workspace/Product/Chrome evidence `phase-52/`，无 team affordance。

## Beta Data Plane Completion（Phase 53–57）

- **Phase 53 Security Master（`COMPLETE`）**：ADR-0026 closed Tushare `stock_basic` L/P/D，atomic content-addressed snapshots/current catalog，bounded Product search/admin jobs；daily selection `explicit`/`selected`/`security_master`/`stock_pool`，真实 per-symbol incremental。无 ETF/index/fundamental/calendar/alternate provider。Evidence `phase-53/`。
- **Phase 54 Daily automation（`COMPLETE`）**：ADR-0027 Asia/Shanghai schedule、closed trading calendar、exact-date full-market daily snapshot、bounded catch-up/retry/lease、optional security refresh、independent `data-worker`、Product config/run-now/health/history；保留 manual/KEEP_NEW。无 suspension/limit/adjustment/action/benchmark/fundamental。
- **Phase 55 Data readiness（`COMPLETE`）**：ADR-0028 typed requirement manifest、session/lifecycle-aware coverage、bounded repair、`waiting_for_data`、immutable ready identity、exact suspension/status/limits；signal/backtest workers provider-free。Evidence `phase-55/`。
- **Phase 56 Adjusted research/actions（`COMPLETE`）**：ADR-0029 durable factors/implemented actions/effective dates；raw execution prices 不复权，构造 content-addressed research view；actions 冻结进 manifests，并测试 dividends/share ratios/false ex-right signals。Evidence `phase-56/`。
- **Phase 57 Benchmark/PIT/declared data（`COMPLETE`）**：ADR-0030 closed benchmark/index-weight/daily-basic/financial-indicator contracts、daily automation、bounded declared-input repair、immutable v3 readiness、historical membership/announcement no-lookahead、sandbox membership、frozen benchmark/excess performance。ETF/fund 排除；evidence `phase-57/`。

## Post-Acceptance Agent Completion（Phase 58）

- **Phase 58 Agent Domain Action Contract（`COMPLETE`）**
  - **目标/范围**：依据 ADR-0031 打通真实用户的候选股票 → owner-scoped custom Stock
    Pool → validated StrategyDraft/StrategyVersion。升级 BYQ role catalogue，仅为
    `quant_orchestrator` 增加 pool list/get/create；`market_researcher` 保持 evidence-only。
    对齐 MCP、DSH skill 与 Backend 的唯一 `CustomStrategy`/`data_requirements` schema，
    投影安全、有界、可修复的校验信息，并将同类 Domain validation 修正限制为一次。
  - **边界**：不增加 pool snapshot/lifecycle/delete、index/dynamic writer、数据工具、
    public-answer 重构、signal/backtest 语义或第二 Agent harness；不信任 Browser/model
    owner/workspace/provenance；Agent-to-Domain 仍只经 MCP，Backend 仍持有全部 invariant。
  - **验收/停止**：role/owner/workspace/audit contract tests、真实有效最小策略 MCP test、
    planned task validate→version integration、无 403/422 风暴的真实 Product Agent journey、
    Chrome DevTools/Playwright same-origin/secret-boundary evidence。出现 privilege widening、
    raw Backend/DSH leakage、无法安全投影错误、需要 direct DB/source access 或需要改动
    Phase 59/60 scope 时停止。

## Point-in-Time Agent Research（Phase 59–60）

- **Phase 59 persisted valuation/fundamentals read path（`COMPLETE`）**：ADR-0032
  定义最多 20 个 canonical A-share symbols 的 exact-session valuation 和
  announcement-next-day fundamentals reads；只读 BYQ PostgreSQL evidence，经 Backend
  与 MCP 返回 completeness/missing/hash，不调用 Provider、不填值。角色、MCP、完整
  Backend/MCP tests 和真实成功/缺失 Agent journey 均通过；evidence `phase-59/`。
- **Phase 60 public answer/activity projection（`COMPLETE`）**：以 Phase 59 真实旅程中
  英文内部前言、authorize/audit mechanics、raw coverage/field terminology 泄漏为基线；
  先接受独立 ADR，再在 Runtime Adapter/Gateway normalized projection 与 DSH skills
  边界修复。不得隐藏用户有价值的数据时点/失败原因，不得暴露 hidden reasoning、raw
  MCP/DSH schema，不得修改 Domain result 或引入第二 agent harness。

## Machine-readable phase status markers

以下稳定 markers 供 CI 校验 Phase ID 与完成状态；说明正文仍以各 program section 为准。

### Phase 34 — Stock Pool depth(`COMPLETE`)
### Phase 35 — Paper Trading depth(`COMPLETE`)
### Phase 36 — Agent workbench depth(`COMPLETE`)
### Phase 37 — My Space depth(`COMPLETE`)
### Phase 38 — Operations workbenches(`COMPLETE`)
### Phase 39 — Data Center / Data Sync depth(`COMPLETE`)
### Phase 40 — Shared components and parity closure(`COMPLETE`)
### Phase 41 — Product experience baseline(`COMPLETE`)
### Phase 42 — Conversation-first Product shell(`COMPLETE`)
### Phase 43 — Durable conversations and Xiaoba workspace(`COMPLETE`)
### Phase 44 — User center and durable appearance(`COMPLETE`)
### Phase 45 — System Settings dialog(`COMPLETE`)
### Phase 46 — Core management workspace redesign(`COMPLETE`)
### Phase 47 — Interaction, responsive and accessibility closure(`COMPLETE`)
### Phase 48 — Product coherence golden journey(`COMPLETE`)
### Phase 49 — Personal workspace boundary(`COMPLETE`)
### Phase 50 — Workspace foundation and verified backfill(`COMPLETE`)
### Phase 51 — Trusted context and authorization cutover(`COMPLETE`)
### Phase 52 — Product orientation and isolation closure(`COMPLETE`)
### Phase 53 — Security master and bounded synchronization(`COMPLETE`)
### Phase 54 — Daily market synchronization automation(`COMPLETE`)
### Phase 55 — Backtest data readiness and execution status(`COMPLETE`)
### Phase 56 — Adjusted research prices and corporate actions(`COMPLETE`)
### Phase 57 — Benchmark, point-in-time universe and declared data(`COMPLETE`)
### Phase 58 — Agent domain action contract(`COMPLETE`)
### Phase 59 — Agent point-in-time valuation and fundamentals(`COMPLETE`)
### Phase 60 — Public answer and activity projection(`COMPLETE`)
### Phase 61 — User experience acceptance closure(`COMPLETE`)

Phase 61 依据 ADR-0034 关闭专项验收中 Phase 58–60 后仍未关闭或仅部分关闭的问题。
范围限定为 Agent 长任务与调用预算、持久化日线口径、任务 readiness、Strategy/Backtest
普通用户信息层级、回测后续上下文、Login 浏览器语义、最近区间表达和完整黄金旅程复验。
基础 CRUD、登录和普通 API 只做 smoke，不机械重复既有 Evidence。

Browser 只访问 Gateway/Product API；Agent 日线只读 BYQ PostgreSQL，Provider 仅由 Data
Center/Data Worker 调用；内部 ID/manifest 不删除但降级到技术详情；不改审批、backtest
和 domain invariant，不新增 runtime/provider/broker。先完成 Community 分类和原验收报告
入库，再通过 Backend/MCP/frontend/DSH contract tests 与真实 Chrome/DevTools 黄金旅程。

### Phase 62 — User experience P3 polish(`COMPLETE`)

依据 ADR-0035 收口 Phase 61 后剩余非阻断体验项：Data Center 从 owner-scoped 股票池
snapshot 选择至多 20 只成分执行 readiness；普通工作台和导航清除首屏工程术语并统一
中文状态；ECharts 使用实际所需模块，消除回测相关大包 warning。保留管理员诊断术语和
全部审计详情，不改变 Backend/MCP/DSH/domain Contract。

验收包括 frontend 单元测试/build、默认 500 kB chunk gate、architecture、mock/real
Product browser smoke，以及真实 Data Center 股票池→readiness same-origin 旅程。Community
硬编码股票池、TODO API、假进度和旧 provider/runtime 路径全部 DROP。

## Phase 63 — DSH Plugin Registry + Qualification Framework (`COMPLETE`)

- **目标/范围**：依据 ADR-0038 建立 BYQ-owned、声明式、版本化的 Plugin Registry、
  qualification state、capability/risk metadata、独立 Agent assignment、exact manifest/lock
  validation、deterministic Composition Builder、profile/hash identity 和 qualification
  evidence。以 official Web Search、Guard、Compaction、Spill、Interaction 为首批真实样板。
- **边界/非目标**：不建设 Marketplace、用户上传、runtime `npm install`、hot install、
  extensions/self-modification、任意 package/URL/GitHub source、shell、terminal、filesystem
  mutation、coding/Engineering capability或数据库/provider直连。Frontend→Product API→
  Gateway→Runtime Adapter→DSH→BYQ MCP 不变；DSH plugin 不拥有 BYQ authorization/domain
  invariant。Web evidence 不成为 deterministic Factor/Strategy/Backtest input；spill 不成为
  Artifact/database；DSH interaction/approval 不替代 BYQ authorization。
- **验收/停止**：Registry schema 和 qualification runner 拒绝 duplicate/unknown/range/
  integrity/peer/rc-mixing/risk/capability/assignment 错误；Builder 稳定生成 composition、
  profile/hash/plugin/version identity，并拒绝 unqualified/prohibited/disabled escalation；
  Runtime Adapter keyless initialize、MCP/session/lifecycle、Agent Web least privilege、secret
  absence、architecture/unit/contract/security/integration tests 通过。单个 sample 因 runtime
  或 security boundary 失败时只标记 BLOCKED，不 fork/patch/upgrade/workaround。

## Post-Phase 63 development sequence

后续两个阶段固定按以下顺序推进：

```text
Phase 63  Plugin Registry + Qualification Framework（COMPLETE）
    ↓
Phase 64  Research Agent Web Search 深化（COMPLETE）
    ↓
Phase 65  DSH Plugin Center Admin UI（COMPLETE）
```

`STATUS.md` 仍是阶段授权的唯一事实来源。两个阶段不得并行，不得共用 worktree/branch/PR。Phase 64 必须
在 Phase 63 已完成且 Web Search 对当前精确 DSH baseline 保持真实 QUALIFIED 后才能获批；
Phase 65 必须等待 Phase 64 合并，并吸收其实际运行中形成的插件状态、证据和管理需求。

## Phase 64 — Research Agent Web Search 深化（`COMPLETE`）

### 目标

把 Phase 63 已 qualification 的 search-only DSH Web Search 转化为 Market Research Agent
可控、可追溯、时间安全的互联网研究能力。Market Research Agent 可以综合 BYQ MCP 的
结构化、已持久化数据与 Web research evidence；BYQ 继续拥有 evidence promotion、Artifact、
authorization、audit、point-in-time 和金融 Domain invariant。

正式实现前必须接受一份 Phase 64 ADR，确定网页 evidence schema、来源等级、冲突处理、
时间截点、Artifact promotion 与 retention。不得只靠 prompt 定义这些 invariants；若现有
Artifact 有界 JSON contract 不足以准确保存这些语义，应对既有 ResearchTask/Experiment/
Artifact contract 做版本化扩展，而不是新建第二套 Research Database。

### 范围

1. **搜索策略与预算**
   - 只在用户要求当前公开背景、新闻、政策、监管/交易所/公司公告，或 BYQ persisted data
     无法回答解释性问题时搜索；确定性计算和已由 BYQ structured data 完整回答的问题不搜索。
   - 每次 run 明确 query/result/retry/time budget、相同 tool+arguments 去重、相似查询收敛、
     domain/result 去重和停止条件；Repeat Guard 只能提供 advisory，BYQ/role policy 负责预算。
   - 中英文 query 按实体、地域和目标来源拆分；不得无条件把每个查询翻译后重复搜索。每个
     query 保存原始语言、目的及其与 evidence 的关联。
   - 搜索失败、无结果或预算耗尽时安全结束并如实说明，不循环、不扩大 capability。

2. **来源治理与 provenance**
   - 来源等级至少为：`PRIMARY`（监管、政府、交易所、公司法定公告/官方站点）、
     `SECONDARY`（可识别的专业财经媒体）和 `AUXILIARY`（论坛、自媒体及其他非权威来源）。
     未能可靠分类的来源不得伪装成官方来源。
   - 关键结论优先引用 PRIMARY；SECONDARY 用于补充报道与交叉验证；AUXILIARY 只用于线索和
     候选发现，不能单独支持确定性事实或因果结论。
   - 每条被采用 evidence 至少保留规范化 URL、标题、发布者/domain、发布时间（可缺失但必须
     显式）、检索时间、来源等级、query identity、provider/plugin provenance 和有界摘要。
     不保存 credential、raw DSH object、hidden reasoning、完整网页副本或任意 HTML。
   - 来源冲突必须并列呈现来源、时间和分歧；不能静默选择更符合模型结论的一条。

3. **时间语义与 no-look-ahead**
   - 明确区分 `published_at`、`retrieved_at`、research `as_of`、BYQ trading session 与
     persisted-data cutoff；缺失发布时间不能由检索时间或自然语言猜测补齐。
   - 历史 as-of 研究不得使用 as-of 后发布的内容支持当时可知结论。后来检索到的历史网页
     只有在其可见性与发布时间可证明时，才能作为该历史时点的辅助 evidence。
   - Web 页面、系统自然时间和模型记忆均不得推断交易日、公告生效日或数据可见性；这些语义
     继续来自 BYQ exchange calendar、announcement/effective-date 与 trusted time contract。
   - 当前 Web evidence 与 BYQ persisted-data cutoff 不一致时必须标记差异，不得写回或冒充
     Data Plane 的权威快照。

4. **Research Evidence / Artifact promotion**
   - DSH Web result 首先只是 session-scoped evidence candidate。需要持久化时，Agent 必须经
     既有 BYQ MCP、trusted owner/workspace context、authorization 和 audit 创建/关联有
     provenance 的 Research Artifact；Web plugin 本身不得直接访问 Backend 或数据库。
   - Artifact 明确区分 claim、supporting source、conflict、time context、检索失败和缺失字段，
     并保持 content hash、lineage、ResearchTask/Experiment 与 WorkflowTrace correlation。
   - Web evidence 只用于解释、研究和候选发现。未经 BYQ Data Plane 采集、规范化、PIT 校验、
     provenance 和冻结的数据，永远不得成为 Factor、Strategy calculation、signal snapshot 或
     Backtest deterministic input。

5. **Agent 融合与最小权限**
   - `market_researcher` 可读取 BYQ MCP structured data 并调用 `web_search`，在最终回答中清楚
     区分权威结构化数据、网页证据与推断。
   - `factor_researcher`、`strategy_researcher`、`backtest_analyst` 的 toolFilter 与执行限制
     均保持 Web Search DENY，不因 delegation、subagent inheritance、resume 或 profile 切换串权。
   - Phase 63 因 rc.1 root tool registry seam 显式允许 `quant_orchestrator` 看见 Web Search；
     Phase 64 必须将专业研究委派给 `market_researcher`，并验证 Coordinator 不自行扩大查询或把
     Web evidence 传成 deterministic input。若无法可靠约束 root capability，则停止并进入 DSH
     Upgrade Lane，不能创建 BYQ 第二工具运行时。
   - 搜索和 evidence promotion 不替代 `byq_agent_authorize`、owner/workspace、role、approval、
     idempotency 或 audit。

6. **防幻觉与公开回答**
   - Agent 只能基于本次实际检索结果与 BYQ structured data 陈述事实；不得用模型记忆补齐未查到
     的事件、数字、引用或因果链。
   - 无可靠来源、只有低等级来源、来源互相冲突或时点不成立时，必须明确说明“现有证据无法建立
     原因”及缺口，不得输出貌似确定的解释。
   - Product public answer/WorkflowTrace 只投影有界、用户可理解的来源卡片与结果摘要，不暴露
     query credential、raw tool arguments/results、raw DSH schema、内部 token 或 hidden reasoning。

### 非目标

- `web_fetch`、任意 URL 下载、浏览器自动化、通用爬虫/新闻平台或网页全文仓库；
- 用网页数据直接计算 Factor、Strategy、signal 或 Backtest；
- 新建第二套 Research Database、Artifact Store、search index 或通用 Agent harness；
- 让 DSH 直连 Provider、PostgreSQL、Redis、BYQ Backend，或由 Web Search 定义 Domain policy；
- 在本阶段升级 DSH、patch/fork upstream、扩大 Product filesystem/shell/code capability；
- Phase 65 Plugin Center、在线插件启停或任何 frontend 插件管理功能。

### 架构边界

```text
Frontend
  → Gateway / Product API
  → Runtime Adapter
  → DSH market_researcher
       ├─ qualified search-only web_search → bounded evidence candidate
       └─ BYQ MCP → structured data / authorized Artifact promotion
  → normalized public answer + WorkflowTrace projection
```

Browser 不接触 DSH；Web Search 不接触 BYQ domain storage；持久 evidence 只通过 BYQ MCP 与
Backend domain contract。DSH 决定 generic search/tool orchestration，BYQ 决定 capability 是否
允许、Agent assignment、证据是否可晋升、时间/数据可见性、authorization 与 audit。

### 验收标准

- Phase 64 ADR Accepted，versioned Web Research Evidence contract、source tiers、time fields、
  conflict/missing semantics、retention 和 Artifact promotion 均有 contract tests。
- Search policy 对需要/不需要搜索、中英文拆分、预算、完全重复和语义重复查询有 deterministic
  tests；重复或无结果不会形成无限 loop。
- 测试覆盖官方与媒体冲突、AUXILIARY-only、过期新闻、无发布时间、无结果、错误 trading-day
  推断、future-information rejection 和 persisted-data cutoff 冲突。
- Market Research Agent 可综合 BYQ MCP + Web evidence；Factor/Strategy/Backtest 在 visibility、
  direct invocation、delegation、resume 和 profile tests 中均无法访问 Web Search。
- Evidence/Artifact 保留 URL、title、publisher、published/retrieved time、source tier、query、
  provenance、hash/lineage/trace；确定性研究 input manifest 明确排除未晋升网页数据。
- keyless CI 验证 package/init/tool registration/policy/error contract；credentialed smoke 使用外部
  secret，真实执行 Web Search 并验证来源，不提交 secret、不把公网结果作为 golden fixture。
- 至少完成一条真实 Product Agent journey：durable login → Market Research request → BYQ
  structured data + credentialed Web Search → normalized sources/evidence → conversation resume；
  Network/WorkflowTrace/error/readiness 均无 secret 或 raw DSH schema。
- architecture、unit、contract、security、Product Agent integration、DSH compatibility、existing
  regression、`git diff --check` 全部通过；若影响现有 UI，按仓库纪律完成 Community 分类和
  desktop/mobile Chrome MCP review。

### STOP CONDITIONS

出现以下任一条件时停止对应路径，不 workaround：Web Search 不再对当前 exact baseline
QUALIFIED；需要启用 fetch/arbitrary URL、shell/filesystem/code runtime；无法可靠保留 URL/
时间/provenance 或隔离危险 capability；无法区分发布时间、研究 as-of、trading session 与
persisted-data cutoff；网页结果将进入 deterministic Factor/Strategy/Backtest；需要绕过 MCP、
authorization 或 Artifact contract；Agent assignment 可串权；需要用模型记忆补齐事实；secret、
raw DSH schema 或内部 token 可能进入 Browser/WorkflowTrace/log/error；需要混合 DSH prerelease、
fork/patch upstream 或建立第二 harness。上游变化只能触发 Upgrade Lane，不得在本阶段自动升级。

## Phase 65 — DSH Plugin Center Admin UI（`COMPLETE`）

### 目标与前置决策

将 Phase 63 稳定的 Registry/Qualification/Composition identity 以 admin-only Product surface
产品化，使管理员能查看真实插件状态、证据、风险和 Agent assignment，并通过受控变更请求
发起 enable/disable、assignment 和 qualification workflow。Plugin Center 是治理与部署状态
界面，不是 Marketplace、package installer 或 DSH runtime console。

Phase 65 已在 Phase 64 合并后完成。ADR-0040 已接受并明确新的
control-plane ADR，明确：

- Git-managed Registry/qualification evidence、期望 Product policy、generated composition 与
  当前运行 composition 各自的 authoritative source 和版本关系；
- admin change request 的 durable persistence、RBAC、idempotency、optimistic concurrency、
  approval/audit、worker ownership、失败状态与取消语义；
- 由哪个 trusted deployment/Engineering component 生成 policy snapshot、运行 qualification/
  builder/CI、构建 image、正常 deploy/restart、验证 active hash 并执行 rollback；
- 如何保证 Browser、Gateway、Backend 和 Product DSH 都不直接写 Git/source、执行 npm/shell、
  控制 Docker 或修改正在运行的 Cordis composition。

在该 ADR Accepted 前，Phase 63 的 Git-managed registry/profile 继续是唯一 deployment input；
不得先做一个看似可用、实际只改内存/数据库或直接改 runtime 的启停按钮。

### 范围

1. **Plugin Overview**
   - 展示 normalized DSH runtime version、active plugin profile、composition hash、enabled plugin
     IDs，以及 AVAILABLE/QUALIFIED/ENABLED/BLOCKED/REJECTED/DEPRECATED 计数。
   - 区分 desired、generated/validated、deploying 和 active runtime identity；仅在 Runtime Adapter
     readiness 报告匹配 hash/profile 后显示 Active。
   - update 状态只表达 verified upstream observation 与 compatibility/qualification 差异，不提供
     一键升级或自动下载；未知/过期 discovery 必须显式。

2. **Plugin Catalog 与 Detail**
   - Catalog 投影 plugin id/display name、official publisher、package、qualified/current/upstream
     observed exact version、qualification/enabled state、risk、capabilities、Agent assignments、
     credential configured boolean、compatibility/block reason。
   - Detail 展示 versioned qualification evidence summary、integrity/closure result、当前与上游版本、
     capability/risk reasons、allowed/denied agents、profile/composition membership 和最近 qualification
     request/result。证据链接/摘要有界、可审计且不泄内部路径或可执行配置。
   - 所有投影由 Gateway Product API 组合 BYQ services 的有界 contract；Browser 不解析 registry
     YAML、Cordis YAML、lockfile、raw DSH metadata/event 或 Runtime Adapter private response。

3. **Admin Actions**
   - 对已 `QUALIFIED` 且 risk/capability policy 允许的 registered plugin 发起 enable/disable change；
     对 descriptor 允许范围内的已知 Agent 发起 assignment change。请求之外的 package/version/
     capability/agent field 一律拒绝，不能通过 assignment 提升插件 capability。
   - 发起已登记 exact package/version 的 Qualification Request；请求只排队执行既有 qualification
     gates，结果不会自动 enable。unknown package、arbitrary version/source/URL/GitHub 均拒绝。
   - 所有 mutation 要求 durable admin session、expected version、idempotency key、actor、reason、
     append-only audit 和状态机；普通用户即使知道 ID 也不能读取 admin projection 或发起动作。
   - “Enable”在 UI 中必须表达为 deployment change request：

     ```text
     Product Policy request
       → validate registered/qualified/risk/assignment
       → deterministic composition generation + exact lock validation
       → normal CI/image build/deploy/restart
       → active profile/hash verification
     ```

     请求被接受不等于已 enabled；只有新 runtime 以目标 hash readiness 后才成为 active。失败保留
     旧 active composition，并展示有界失败原因和可审计 rollback 状态。

4. **Product UI**
   - 在既有 administrator System Settings/Operations 信息架构内增加 Plugin Center，而不是创建
     第二套 admin shell。实现前按 `AGENTS.md` 检查并分类 Community 对应页面/组件；没有对应物
     时记录 `REPLACE`/new BYQ surface，而不是臆造 Community parity。
   - 支持 desktop/mobile、loading/error/empty/stale/partial-unavailable、权限拒绝、长 package 名、
     状态/风险不可只靠颜色表达、危险动作确认和 deployment progress/recovery。
   - 所有 browser traffic 为 same-origin `Frontend → Gateway/Product API → BYQ services`；无
     Frontend→DSH/Runtime Adapter/Backend direct path。

### 非目标

- 开放 Marketplace、第三方开发者平台、评分/推荐/付费、用户上传或任意 package/source；
- runtime `npm install`、hot install/hot reload、GitHub URL、arbitrary Cordis YAML、DSH extensions/
  self-modification、自动 baseline/plugin upgrade；
- Browser/Gateway/Product Backend shell、terminal、Git/source write、Docker socket、code runtime、
  process control、任意 filesystem、database 或 provider access；
- 在页面读取/显示 credential value、environment secret、internal token、connection string、raw
  executable config、internal filesystem path 或 qualification command；
- 用 DSH approval 替代 BYQ admin authorization/deployment approval，或把 qualification success
  当作 enable/deploy success；
- 与 Phase 65 无关的完整 Operations/Marketplace 重构。

### 架构边界

```text
Admin Browser
  → Gateway Product API（durable admin RBAC）
  → BYQ Plugin governance projection / audited change request
  → trusted deployment control plane（ADR-defined, Product DSH 之外）
  → qualification + deterministic builder + CI/image/deploy/restart
  → Runtime Adapter readiness（active profile/hash）
```

Plugin Center 只管理 BYQ Product policy 允许的 registered generic capability。Plugin descriptor
不能定义 BYQ owner/workspace/role/domain authorization；Agent `toolFilter` 仍须镜像独立 assignment，
BYQ authorization 仍是 Domain ceiling。Credential 通过既有 encrypted store/reference 注入，只向
Browser 返回 `configured`/health boolean，不把 secret 放入 Registry、request、composition identity、
evidence、WorkflowTrace、audit、log 或 error。

### 验收标准

- Phase 65 control-plane ADR Accepted；versioned Plugin Center read/write Product API contract 明确
  desired/generated/active/request/result 状态，OpenAPI/typed client 与 secret-negative schema tests
  完成。
- Overview/Catalog/Detail 对 Phase 63/64 真实 registry、qualification evidence、runtime readiness
  和 update observation 投影准确；blocked reason、risk、assignments 与 credential configured 状态
  可解释，partial runtime failure 不伪造 healthy/active。
- duplicate/stale/idempotent admin requests deterministic；ordinary user/disabled user/cross-workspace
  被拒；audit 可关联 actor、request、old/new policy version、composition hash、deployment result，
  但不含 secret/raw config。
- AVAILABLE/BLOCKED/REJECTED/DEPRECATED、HIGH/PROHIBITED、unknown package/version/agent、invalid
  assignment 和 capability escalation 都无法进入 composition；disabled plugin 缺席，qualified +
  policy-enabled + valid assignment plugin 才出现。
- Qualification Request 执行 exact version/integrity/closure/runtime/capability/security gates；失败不
  自动升级、不自动 enable、不改变 active runtime。
- 完整 admin journey：登录 → Overview → Catalog/Detail → 发起允许的 policy/assignment change →
  观察 validation/deployment/restart → active hash 匹配；失败 journey 验证旧 composition 保持 active
  且 rollback/audit 可见。另有普通用户 403、two-user isolation 和 restart recovery。
- architecture tests 明确拒绝 online install、extensions、shell/terminal/source write、Docker/runtime
  direct control、frontend→DSH、MCP bypass、direct DB/provider 和 secret projection。
- Community feature classification、desktop/mobile Chrome MCP、loading/error/empty/stale、accessibility、
  real Product API Network review，以及 frontend/backend/unit/contract/security/integration/runtime/
  DSH compatibility/regression、`git diff --check` 全部通过。

### STOP CONDITIONS

出现以下任一条件时停止，不实现伪控制面或 workaround：Phase 63 Registry Contract 尚不稳定或
Phase 64 尚未合并；无法在 ADR 中确定 policy/qualification/deployment 的权威 owner；需要 Browser、
Gateway、Backend 或 Product DSH 直接执行 npm/shell/Git/Docker、写 source/YAML 或修改 running
runtime；enable 无法区分 requested 与 active；需要启用未 QUALIFIED、危险 capability 或越权 Agent；
需要 arbitrary package/version/source/URL；qualification metadata 无法准确验证；正常 build/deploy/
restart 或 rollback 不可审计；credential/raw config/internal path 可能泄漏；需要 DSH extension、fork/
patch、prerelease 混用、MCP/authorization bypass 或第二 generic harness。单个插件不兼容只进入
BLOCKED，不阻塞 Plugin Center 的只读治理能力。

## Stock Pool Producer Completion（Phase 66–69）

### Phase 66 — Trusted producer contract（`COMPLETE`）

接受 ADR-0041 和 `stock-pool-producer.v1`，冻结 definition/run/snapshot 分离、trusted Data Worker、
index no-look-ahead、closed dynamic rule、atomic promotion/recovery 和 Product intent boundary。完成
Community index `PORT_LOGIC`/`PORT_UX` 与 dynamic placeholder `DROP` 分类；本阶段不改 runtime。

### Phase 67 — Index stock pools（`COMPLETE`）

实现 validated canonical index catalog、owner-scoped index definition、持久化 materialization run、
trusted worker、import-trigger/manual idempotent refresh、as-of/history/diff Product API 和 responsive UI。
只开放 coverage 完整的 closed index set；不得从 Browser/股票池 service 直接访问 Provider。

### Phase 68 — Dynamic stock pools（`COMPLETE`）

实现 ADR-0041 closed rule schema、point-in-time preview、deterministic evaluator、交易日历 cadence、
waiting/stale/failure recovery、definition/run/history/diff Product API 和可访问 UI。不允许 arbitrary
Python/SQL/URL、DSH evaluator 或第二 rules harness。

### Phase 69 — Integration and product closure（`COMPLETE`）

统一 catalog/readiness/diff，验证 Research/Strategy/Backtest/Paper immutable snapshot 消费、资产导入
重新验证、监控/audit/restart/two-user isolation；完成 real Product API desktop/mobile Chrome、same-origin
Network、Community checklist 与完整 regression evidence。

### Phase 70 — Index catalogue coverage closure（`COMPLETE`）

依据 ADR-0042 将单一沪深300供给扩展为六个 canonical 候选的可信目录同步；Data Worker 以最多
62 日窗口逐指数隔离刷新。新增精确 snapshot-level completeness evidence 和旧数据 forward repair，
月度非空记录不再授权股票池。Product API/UI 展示可用与等待同步状态，只有 verified snapshot 可创建。
验收覆盖多指数、失败修复、no-look-ahead、完整 Compose、真实 Product API desktop/mobile Chrome、
same-origin Network、restart 和 Community checklist。

## Machine Learning Strategy Program（Phase 71–74）

详细合同和逐阶段 gate 位于 `MACHINE_LEARNING_STRATEGY_PLAN.md`，架构边界由 ADR-0043 固定。

### Phase 71 — Auditable ML contract baseline（`COMPLETE`）

检查并分类 Community 的 ML import、runtime probe、回测内训练与设计说明；接受 ADR-0043，冻结
ML StrategyVersion、TrainingRun、FeatureSnapshot、ModelArtifact、PredictionSnapshot 和现有
SignalSnapshot/Backtest 衔接合同。固定 Python 3.13 / LightGBM 4.7.0 CPU profile 和禁止项；
不改 runtime/schema/API/UI。

### Phase 72 — Trusted training and model artifact（`COMPLETE`）

实现 owner/workspace-scoped ML strategy validation/approval、TrainingRun、point-in-time
`price-volume-basic-v1` FeatureSnapshot、独立无凭证 LightGBM CPU Worker、native text model object、
ModelArtifact/metrics/lineage 和 restart/idempotency/tamper tests。不实现预测、信号、Backtest 或 UI。

### Phase 73 — Out-of-sample prediction and signal closure（`COMPLETE`）

实现 prediction-only inference、immutable PredictionSnapshot、确定性 ranking、approved closed top-N
policy → ADR-0017 SignalSnapshot，以及现有 Backtest approval/manifest 衔接。Backtest 不加载模型或
重新训练；验收 no-look-ahead、重复 identity、tamper 和 restart。

### Phase 74 — Product closure（`COMPLETE`）

实现 Gateway/Product API、typed client 和真实模型研究界面；完成 frozen pool → training → model →
prediction → signal → Backtest 的 PostgreSQL/Compose/two-user/restart/Chrome MCP/no-mock golden
journey。HIST 不在本阶段范围内，后续必须由新的 Accepted ADR 和明确授权启动。

## Product Agent Capability Completion（Phase 75–79）

架构边界由 ADR-0044 固定。五个阶段严格串行，每阶段使用独立 worktree、branch 和 PR。

### Phase 75 — Product capability contract baseline（`COMPLETE`）

建立 `product-capability-catalog.v1`，覆盖稳定用户路由、受众、前置条件、Agent 支持等级、MCP tool
映射和限制；CI 拒绝重复 identity、无效 route、未知 tool 与越权声明。本阶段不改 runtime/schema/API/UI。

### Phase 76 — Xiaoba product guide（`COMPLETE`）

实现精简 `byq-product-guide` skill、按领域 references、只读 `byq_product_help_query` MCP 和固定
Product route 投影。说明类请求不得产生领域 mutation；Production Product DSH 不挂载源码。

### Phase 77 — Backtest task facade（`COMPLETE`）

以 `backtest-task.v1` 聚合既有 ResearchTask、Approval、MarketReadiness、SignalProducerJob 和
BacktestJob，提供 prepare/create/execute/get/cancel MCP。不得新建第二工作流或让模型构造 raw bars/signals。

### Phase 78 — ML create and training Agent（`COMPLETE`）

增加最小权限 ML researcher role/skill/delegate 和 capability/workspace/strategy/training MCP；DSH 不训练、
不推理、不读取模型对象，策略批准保持人工边界。

### Phase 79 — ML prediction, frozen signal and Backtest conversation closure（`COMPLETE`）

增加 prediction/status MCP、封闭 WorkflowTrace 投影并接入 Phase 77 Backtest task；完成真实 PostgreSQL、
restart、two-user、no-mock Product API、desktop/mobile Chrome MCP 与说明/准备/执行行为评测。

### Phase 80 — Xiaoba data demand and automation-channel repair（`COMPLETE`）

修复 DSH delegate `toolFilter` 与实际 `mcp__byq__*` 注册名漂移；新增 `data-demand.v1`，由小巴用冻结
股票池、日期、用途和封闭数据声明向 Backend 表达按需准备需求。Backend 复用既有 repair/readiness，
Data Worker 独占 Provider 与行情写入；完成状态在下一次 Agent context 中通知小巴，并由 Product API
投影到数据中心。不得新增第二同步引擎、Provider 直连或 Backend 主动触发无用户回合的模型执行。

### Phase 81 — Durable conversation runtime rehydration（`COMPLETE`）

依据 ADR-0046 修复 Product durable conversation 在 DSH idle process release/reopen 后的首个 follow-up。
稳定 BYQ identity 与私有 DSH generation 分离；Gateway 从 durable catalog 提供 bounded completed public
messages，Runtime Adapter 在新 generation 第一次 prompt 恢复语义上下文。不得读取 raw DSH log、patch/
fork/upgrade DSH、无限保留 idle process 或重建第二 Agent harness。DSH error fail closed 为 failed，并以
Runtime/Gateway/Frontend contract、真实 release/reopen 多轮 Product journey、Chrome 与 cleanup evidence 验收。

### Phase 82 — Provider-aware scalable data tasks（`COMPLETE`）

依据 ADR-0047，将 50,000 单元明确为单个 readiness/repair 分片上限，而非 Tushare 或完整 ML
准备上限。ML 创建复用确定性分片和既有 repair/session job，单任务错误隔离且不再重启 Worker；Data
Worker 按配置的 Tushare 2,000 积分预算保守节流。新增由现有持久状态派生的 `data-task.v1` Product
投影和数据中心进度界面，展示阶段、完成/总单元、行数、失败原因与更新时间，不新增第二任务引擎。

验收必须覆盖 300 只×五年分片、单个坏任务不阻塞队列、重启恢复、额度单元测试、Gateway 安全投影、
真实 Product API/Chrome 桌面与移动端流程，以及 Community 功能清单。Browser 不得调用 Backend、MCP、
DSH、PostgreSQL 或 Tushare；Data Worker 仍是唯一 Provider caller。

Post-Phase 82 信号/回测分片收口（维护，不新增阶段；构建修订 `dsh-0.1.2rc1-post-u8.129`，PR #298）：`signal_producer_jobs` 的 signal/backtest
准备链已与 ML 一样接入 ADR-0047。共享确定性分片规划器（`services/backend/app/market_plan.py`）
由 data demand、ML training 和 signal/backtest prepare 复用；aggregate readiness 只从各分片
assessment 派生，每个未就绪分片各自产生既有 repair 请求，仅当全部分片 ready 时 Worker 才用
`build_partitioned_ready_input` 冻结连续 ready input。计划持久化为 `requirement_plan_json`
（含稳定的 `requirement_plan_sha256` 与逐分片 requirement 身份）；无计划的历史 job 保持原单
requirement 行为。`MAX_REQUIRED_CELLS`、MCP schema、Gateway 路由与前端均未变更。

## Extensible Machine Learning Program（Phase 83–86）

详细合同和逐阶段 gate 位于 `MACHINE_LEARNING_EXTENSIBILITY_PLAN.md`，架构边界由 ADR-0048 固定。

### Phase 83 — Extensibility contract baseline（`COMPLETE`）

检查并分类 Community ML 路径；接受 ADR-0048；冻结 capability registry、v2 strategy、v1 adapter、
purged walk-forward、Ridge profile、HS300 RegimeSnapshot、ModelBundle、RoutingPolicy 和 Product/Agent
边界。本阶段不改 runtime/schema/API/MCP/UI。

### Phase 84 — Capability registry, Ridge and walk-forward（`COMPLETE`）

实现代码管理与 CI qualification 的注册表、模块化 Feature/Target/Validation/Learner/Portfolio 合同、
v1 compatibility、Ridge JSON model 和 purged walk-forward Worker/Artifact；不实现 regime、routing 或 UI。

### Phase 85 — Regime snapshot, expert bundle and routing（`COMPLETE`）

实现冻结沪深300状态、专家模型包、fallback 和确定性路由；扩展 prediction/signal lineage，Backtest 继续
只消费冻结信号；不提前开放 Browser/Agent。

### Phase 86 — Product and Xiaoba closure（`COMPLETE`）

实现动态 capability Product API、模型研究 UI、MCP/Xiaoba 最小权限能力和真实 PostgreSQL/Compose/
Chrome/two-user/restart/performance 闭环。

## Built-in Product Feedback Program（Phase 87+）

详细合同和逐阶段 gate 位于 `PRODUCT_FEEDBACK_DELIVERY_PLAN.md`，架构边界由 ADR-0049 固定。普通用户
无需 GitHub 账号或 Token；只有部署维护者为固定仓库进行一次服务级配置。

### Phase 87 — Feedback contract and trusted-publisher baseline（`COMPLETE`）

形成完整设计档案和后续分阶段 gate：普通用户仅提交 BYQ 内部反馈，部署维护者一次性配置 GitHub App 或
服务级凭据；BYQ 持久化、去敏、去重、审批/策略和 outbox，独立 trusted publisher worker 才可发布到固定仓库。
小巴只能经 BeyondQuant MCP 提出/查询反馈，不直接访问 GitHub。

### Phase 88 — Durable feedback domain and Product API（`COMPLETE`）

实现 workspace-owned Product Feedback、不可变 revisions/publication snapshot、预览确认、脱敏/去重/配额、
审核、transactional outbox、分页 Product API 与 PostgreSQL/restart/two-user tests。本阶段不连接 GitHub，
不实现 publisher、frontend、MCP 或 Xiaoba，也不把反馈转换成 EngineeringTask。

### Phase 89 — Trusted GitHub publisher and operations（`COMPLETE`）

实现无源码/Git/Docker/数据库/DSH 权限的独立 publisher、固定仓库 GitHub App/单仓库 token、internal
lease/fence、renderer、reconciliation、有限重试、Compose 与运维；required CI 只使用 fake GitHub。

### Phase 90 — Product UI and Xiaoba closure（`COMPLETE`）

实现 owner 反馈工作台、管理员审核、隐私预览/明确提交、MCP/Xiaoba 最小权限能力，以及真实 Product API、
Chrome desktop/mobile、懒加载分页、two-user/restart/unconfigured publisher 闭环。

## Agent Approval Continuation（Phase 91）

### Phase 91 — Global approval center and durable conversation continuation（`COMPLETE`）

依据 ADR-0051 将 Agent 批准/拒绝控件收敛到全局审批中心，移除策略和模型研究页的审批步骤；用户主动开始回测或训练
时仍由 BYQ 记录必要的领域审批。Agent approval 精确绑定资源和原 runtime session，Gateway 映射公开 durable
conversation 并以幂等 continuation prompt 续接；失败按持久状态恢复而不使用固定调用次数上限。审批列表使用 owner/
status 服务端分页，铃铛只显示 pending 数，活动角标为中性灰色。验收覆盖 Backend/Gateway/MCP/Runtime/frontend、
DSH composition、真实 Product API、Chrome desktop/mobile、same-origin、restart 与部署健康。

## Central Feedback Hub（Phase 92）

### Phase 92 — Official central intake and conversation-first submission（`COMPLETE`）

依据 ADR-0052，把开源部署的默认反馈路径改为 local transactional outbox → 无数据库/GitHub 凭据 relay → 中央
Feedback Hub。Hub 以匿名 installation/event HMAC、双层 schema/secret/PII 校验、限流、capability-token 状态查询、
中央审核和固定 `jefison-x/BeyondQuant` GitHub App publisher 隔离不可信安装。小巴在会话中生成草稿和公开预览后只请求
一次精确绑定 `product_feedback` 的全局审批，批准后续接原 durable conversation 并提交同一 version/hash；普通用户不配置
GitHub 账号、Token、仓库或 Hub secret。验收覆盖 Backend/MCP/skill/frontend、Hub/relay、PostgreSQL、Compose、Chrome
desktop/mobile、same-origin 与未配置/断网降级。

## Cloudflare Central Feedback Hub（Phase 93）

### Phase 93 — Free-plan serverless central Hub（`COMPLETE`）

依据 ADR-0053，在不改变 Phase 92 relay/receipt/status wire contract、会话审批或本地 Product topology 的前提下，将未启用的
中央 FastAPI/PostgreSQL/Publisher Compose 替换为两个隔离 TypeScript Workers。Hub 使用 D1 transactional outbox、按
installation/receipt 分片的 SQLite Durable Objects、Cron 和 Queue producer；不可公开的 Publisher 使用 Queue/DLQ、Hub
Service Binding、WebCrypto GitHub App JWT 和固定 Issue route，且没有 D1/Product/DSH/source/Git/Docker 权限。交付精确依赖
锁、D1 migration、Free-plan 安装/恢复 runbook、真实 workerd/D1/DO/Queue/fake-GitHub tests 和双 Worker deploy dry-run。

## Cloudflare Git Delivery（Phase 94）

### Phase 94 — Git-connected automatic Worker deployment（`COMPLETE`）

依据 ADR-0054，将中央 Hub 的维护者部署入口收敛到 Cloudflare Workers Builds 直接读取官方 GitHub 仓库。Hub/Publisher 保持
两个隔离 project；只从 `main` 发布，PR 只验证。D1/DO/Queue 使用无账号 ID 的自动配置，Hub deploy 在 code activation 前按
binding 应用 migration，两个 config 声明不同 required runtime secrets。交付机器可检验 build/deploy contract、monorepo
root/command/watch-path 清单、首次 secret fail-closed 流程、自动更新/回滚说明和 CLI fallback；不修改 Product runtime。

## Central Feedback Moderation Console（Phase 95）

### Phase 95 — Maintainer operator console（`COMPLETE`）

依据 ADR-0055，在 Hub Worker 内提供维护者中文审核控制台，使用服务端状态过滤/分页和当前页懒加载详情调用既有中央管理合同。
Admin Token 只做同源 HTTPS session exchange，Hub 签发最长八小时的 Secure/HttpOnly/SameSite=Strict HMAC Cookie；页面不使用
URL、普通 Cookie、local/session storage 或第三方资源持久 secret。Cookie mutation 还要求 exact Origin 和封闭 UI header；
Bearer CLI 保持兼容。正式自定义域名关闭 `workers.dev` 备用路由，`/admin*` 与 `/v1/admin/*` 由 Cloudflare Access 外层保护，
公开 intake/status/health 不受影响。Issue 创建仍只属于隔离 Publisher，不改变 Product/DSH/MCP/PostgreSQL 或反馈 wire contract。

## Central Feedback Direct Admin Login（Phase 96）

### Phase 96 — Direct password login and persistent throttling（`COMPLETE`）

依据 ADR-0056，将 Phase 95 的 Cloudflare Access 强制前置改为可选 MFA/IdP 增强；Hub 默认使用已有加密 admin secret 作为单一
管理员密码直接登录，不增加用户名、用户表、找回流程或 Product identity。所有 UI password exchange 与 Bearer CLI 认证均经
按 `CF-Connecting-IP` 的 HMAC key 分片的 SQLite Durable Object：15 分钟内第五次失败锁定来源 15 分钟，成功原子清零，原始
IP 不持久化，window/lock 到期 alarm 清理废弃状态。v2 HttpOnly session 由高熵 status secret 和密码版本共同签名，密码轮换使
旧会话失效。保持同源 mutation、`workers.dev` 关闭、D1/outbox 状态机、Publisher-only GitHub writer 和普通用户零配置边界。

## Backtest Readable Catalog Identity（Phase 97）

### Phase 97 — Readable task names and separate Backtest IDs（`COMPLETE`）

依据 ADR-0057 和 GitHub Issue #240，为 `backtest_jobs` 增加 owner-scoped 持久名称及生产 PostgreSQL forward repair；创建请求
可提供 1–120 字符名称，缺省由 Backend 根据已验证策略生成可读默认值。bounded Backend/Product API/MCP projection 与搜索同时
保留 `name` 和稳定 `job_id`。桌面目录拆分“任务名称/回测 ID”，移动端名称为主、短 ID 为辅助，创建向导可自定义名称，技术详情
保留完整 ID。名称不得进入 signal snapshot、input/result hash、Artifact identity、执行规则或 idempotency identity。

验收必须覆盖 fresh schema 与 Phase 96 forward repair、历史 identity 不变、Backend create/get/list/name+ID search/idempotency/
owner isolation、Backtest task/MCP projection、frontend 单元与 production build、真实 Product API Chrome desktop/mobile、
same-origin Network、Community checklist、architecture/full CI。不得增加第二 Backtest workflow、浏览器直连 Backend、DSH 数据库
访问、Community ORM/Agent runtime 或 VectorBT/BaoStock/AKShare compatibility。

## Data Baseline and Qualification（Phase 98）

### Phase 98 — 0.10 prerequisite qualification and frozen data baseline（`IN_PROGRESS`）

依据 [ADR-0074](../architecture/adr/ADR-0074-data-baseline-and-qualification-boundaries.md) 与
[VERSION_PLAN](VERSION_PLAN.md)，在实施 0.10 数据扩容与任何模型前，先冻结可测的数据基准合同并完成
HIST 历史关系可行性调查与深度学习环境资格调查。交付物：

- [V1_DATA_BASELINE_CONTRACT](V1_DATA_BASELINE_CONTRACT.md)：标的/区间/口径/时点来源/单位/许可/摘要；
- [V1_HIST_DATA_QUALIFICATION](V1_HIST_DATA_QUALIFICATION.md)：历史行业/概念关系来源、可见性与缺口；
- [V1_DEEP_LEARNING_ENVIRONMENT_QUALIFICATION](V1_DEEP_LEARNING_ENVIRONMENT_QUALIFICATION.md)：候选
  Python/PyTorch、模型格式、CPU/GPU profile、镜像大小、耗时与峰值内存。

验收：三份文档存在且结论明确区分 `proven`/`not_measured`/`blocked`；不得以“包可安装”或当前关系回填
历史冒充支持；不实现数据扩容、不引入 HIST、不授权 GPU/有限调参/新 Worker 拓扑、不改运行能力。
无法证明来源/单位/时点/许可/完整性者登记 `blocked`，由维护者修订 ADR-0071/VERSION_PLAN。

### Phase 99 — Execute 0.10 qualification investigations（`COMPLETE`）

执行 Phase 98/ADR-0074 的两项调查：

- 深度学习环境 CPU profile 实测（隔离 `python:3.11-slim` + `torch 2.14.0+cpu`）：MLP/LSTM 训练与
  推理耗时、峰值 RSS 352.8 MB、torch 安装 773 MB；GPU/故障矩阵/数值容差仍 `not_measured`。
- HIST 历史关系来源只读核对：本机无 Community 仓库/容器/卷，无法取得样本，
  `V1_HIST_DATA_QUALIFICATION` 维持 `blocked`，不做替代或回填。

证据见 [QUALIFICATION-EXECUTION](../evidence/phase-99/QUALIFICATION-EXECUTION.md)。不实现数据扩容、
不引入 HIST、不授权 GPU/有限调参/新 Worker 拓扑、不改运行能力。HIST 解除阻塞需维护者提供只读导出/连接。

## Data Center Comprehensiveness（Phase 100）

<!-- byq:phase-100-p100-c=paused-not-delivery -->
<!-- byq:phase-100-slices-frozen=P100-C,P100-D,P100-E -->

### Phase 100 — 0.10 data baseline implementation (`PAUSED`)

> 2026-09-20：Phase 100 冻结为 `PAUSED`，当前步骤改为 **0.9 closeout governance & gap ledger
> audit**（见下方同名小节）。P100-A（#286）与 P100-B（#337，已并入 base）为已完成事实；P100-C
> 仅在隔离分支 `codex/phase-100c`（Draft PR #338）存在**未审查实现提交**，**paused、not delivered、
> 未审查、不并入 `main`**，不得从该分支推断业务完成；P100-D/P100-E 冻结。维护者未明确恢复前不得继续任一
> Phase 100 切片。S3/历史成分准备属 0.10.0，由本 Phase 100 解决（Tushare P100-C/P100-D 时点证据；
> 不申请 Community 豁免、不用当前关系回填）。

依据 ADR-0074、[V1_DATA_BASELINE_CONTRACT](V1_DATA_BASELINE_CONTRACT.md) 与维护者的 Tushare 6000 分账号，
在 BYQ Data Plane 内（仅 Tushare，不使用 Community）实现有限、可测、可复现的数据全面性。拆分为可独立验收的切片：

1. **P100-A 基金数据**（已完成，#286）：`fund_basic`/`fund_nav`/`fund_daily`/`fund_share`/`fund_div`/`fund_adj`/`fund_portfolio`
   的 provider 合同、存储、readiness 与覆盖审计（ETF 场内 + 场外基金）。
2. **P100-B 指数每日指标**（已完成，已并入 `main` #337）：`index_dailybasic` 的 provider 合同（canonical 指数/日期/单位/
   provenance）、权威存储与按 `idempotency_key` 去重的增量同步、coverage/readiness 与真实 Tushare 验证证据
   （`docs/evidence/phase-100b/INDEX-DAILYBASIC-VERIFICATION.json`）。计量单位为 Tushare 文档口径（市值/股本为
   元/股并显式记录 units，`index_dailybasic` 与 `daily_basic` 的万元/万股口径不同），不接入分钟/实时/港股/特色数据。
3. **P100-C 行业关系（申万）**（**paused / not delivered**）：`index_classify`/`index_member_all` 合同与时点可见性实测；
   仅在隔离分支 `codex/phase-100c`（Draft PR #338）存在**未审查实现提交**，未并入 `main`、未审查，
   维护者未授权恢复前不得继续；不得据此声明 P100-C 完成。
4. **P100-D 概念关系（同花顺）**（冻结）：`ths_index`/`ths_member`；因 `in_date/out_date` 官方“暂无”，
   必须先证明历史可见性再接入，否则维持 blocked。
5. **P100-E Product 呈现**（冻结）：Data Center 覆盖/质量/就绪的 UI/小巴可见与可操作（不改边界）。

每个切片独立 worktree/Draft PR；不得以“接口可调用/单次拉取成功”代替完整覆盖、时点、单位、许可与摘要证据；
不得支持分钟/实时/港股/特色数据；不改运行能力或生产状态除非另有部署授权。

## Dynamic Model Catalogue（Phase 101）

### Phase 101 — Credential-driven dynamic model catalogue and continuation qualification (`COMPLETE`)

依据 [ADR-0075](../architecture/adr/ADR-0075-dynamic-model-catalogue-and-credential-discovery.md)，让建档案按凭据自动刷新 provider 可用模型，并允许新发现模型用于后台续接。验收证据见
[docs/evidence/phase-101d](../evidence/phase-101d/README.md)。

- **P101-A（已完成，#287/#288）**：ADR-0075；Backend `GET /v1/users/model-credentials/{credential_id}/models`
  发现接口（解密凭据→封闭 provider `{base}/models`→有界/去重/失败闭合、密钥不回显）+ 有界客户端标识与传输族映射 + 测试。
- **P101-B（已完成，#289）**：档案创建以发现结果校验 `model`；`resolve_model()` 不再仅认静态 `_CATALOG`；
  `credential_discovered_models` 持久化已支持模型。
- **P101-C（已完成，#290）**：`runtime.py` 后台续接资格从单一 `deepseek-v4-flash` 放宽为封闭 provider 路由
  （deepseek-official 与六个 opencode 路由），并补资格/回退测试。
- **P101-D（已完成，#291）**：Product Gateway 转发 + 前端“选中凭据→刷新模型”；真实浏览器经 Product API 验收，
  不可用凭据闭合失败并保留已审阅静态目录。
- **P101-E（本切片，#待定）**：依据 [ADR-0076](../architecture/adr/ADR-0076-model-profile-lifecycle-and-runtime-allowlist.md)
  收紧运行时边界并修正档案生命周期：Backend 新增 `RUNTIME_MODEL_ALLOWLIST`（Backend 副本须逐项等于
  composition 与版本化 profile，drift 测试守门），发现与建档案失败闭合；新增
  `disable_profile`/`enable_profile`（`active ⇄ disabled`，`deleted` legacy 终态，disable 自动解绑、
  enable 不重绑，幂等 + 审计 + additive `model_profile_status_receipts`），Gateway/Product API、前端
  禁用/启用动作与状态列同步。不修改既有 `model_command_receipts` 约束，不硬删除任何行。

边界：不外泄密钥、不引入新 SDK、未知 provider/失败闭合；每切片独立 worktree/Draft PR。

## 0.9 Closeout Governance & Gap Ledger Audit (maintenance, 2026-09-20)

This maintenance batch executes the 0.9 closeout fact audit. It does **not** advance a
Product Phase, does **not** implement Proposed ADR-0082/0083, does **not** switch the
production selector, does **not** deploy, and does **not** create or move any tag/release.
It freezes Phase 100 (`PAUSED`) with P100-A/P100-B as completed facts and P100-C paused on
its isolated branch (unreviewed implementation commits, not delivered). S3 / historical
constituent preparation is a **0.10.0** deliverable: the historical Post-U8 investigation is
a `blocked` fact but does **not** gate the 0.9 closeout (ADR-0068/AGENTS rule 21), and it is
resolved by frozen Phase 100 with Tushare P100-C/P100-D point-in-time evidence (no Community
exemption, no current-relation backfill).

Deliverables (machine-readable under `docs/evidence/v090-closeout/`):

- Gap ledger mapping F2, S3, the full-interface audit, the composite research fault
  regression, H1–H5, U8 and D15 to `covered | superseded | open | blocked`, citing the
  precise evidence path and the base `origin/main` commit. S3 is `superseded → 0.10.0`.
- Acceptance matrix for the formal 0.9.0 manifest, the remaining 0.9.x gates, the serial
  DSH 0.1.5-rc.1 closeout slices (per-blocker owner/reproduction/acceptance/failure-closure),
  the machine-readable `dag`, and the ADR-0082/0083 sufficiency items.
- Consistency asserted by `tests/test_v090_closeout_governance.py`, including DAG acyclicity
  and owner-before-gate for every blocker.

0.9 strict order (does **not** start with S3): (1) this audit → Draft; (2) full-interface
re-baseline to `complete=true`; (3) composite research fault regression; (4) ADR-0082/0083
maintainer decisions; (5) the D15 pre-gate blocker slices, each owned by a pre-gate D15
candidate-qualification node (B1 `subagent-child-crash` is an external blocker if no
out-of-process provider exists); (6) D15-G re-run; (7) R3 → R4 → R5 → R6 → independent
production Go/No-Go. Every slice stops at a Draft PR; blockers may not be deleted or
downgraded; "upgrade dependency" is never "switch the production default"; if B1 stays an
external blocker the maintainer must explicitly choose a gate-order option (keep / split /
reorder / reclassify).

Build revision: this batch adds `tests/test_v090_closeout_governance.py` (a build input) and
advances the production runtime build identity `post-u8.174 → post-u8.177` (`.175` is held by
the paused `codex/phase-100c` branch; the earlier in-branch `.176` revision is retained
unchanged as a historical build identity after the P1 matrix/route corrections changed the
same build inputs). Rebuild identity only: no selector, `compose.yml`,
`deployment.json`, immutable release registry or 0.1.2 artifact/evidence change and no
deployment.

## 0.9 Full-Interface Re-Baseline (maintenance, 2026-09-21)

This maintenance batch executes step (2) of the 0.9 strict order: re-do the candidate
`main` full-interface reliability ledger to a real `complete=true`. It does **not**
advance a Product Phase, does **not** implement Proposed ADR-0082/0083, does **not**
switch the production selector, does **not** deploy, and does **not** create or move any
tag/release. It does not inspect or copy the Community repository and does not resume
frozen Phase 100.

The H4 ledger (`docs/evidence/research-handoff-h4/INTERFACE-REVIEW.json`) recorded 560
reviewed rows at its own commit; the current tree discovers 566. The six missing rows are
the Phase 101 model-catalogue endpoints (Backend discovery + profile disable/enable and
their Gateway/Product API proxies). Twenty files drifted: 17 changed after the H4 commit
and three recorded digests never matched the committed H4 tree (MCP `server.ts`,
`backtest.ts`, Gateway `main.py`). `scripts/ci/check-reliability-review.py` is now a
fail-closed auditor: missing rows, stale source/dependency digests and fake PASS rows each
exit non-zero. The re-verified per-interface semantics and the full drift breakdown are in
`docs/evidence/v090-full-interface-rebaseline/`; consistency and the fail-closed behavior
are asserted by `tests/test_reliability_review_audit.py`.

Build revision: this batch changes `scripts/ci/check-reliability-review.py` and adds
`tests/test_reliability_review_audit.py` (build inputs) and advances the production
runtime build identity `post-u8.177 → post-u8.178` (unused id). Rebuild identity only: the
historical `.177` manifest and evidence are preserved unchanged; no selector,
`compose.yml`, `deployment.json`, immutable release registry or 0.1.2 artifact/evidence
change and no deployment.

## 0.9 Composite Research Fault Regression (maintenance, 2026-09-21)

This maintenance batch executes step (3) of the 0.9 strict order: a real
composite research journey plus the R1–R5 fault matrix on a synthetic user and
an isolated stack. It does **not** advance a Product Phase, does **not**
implement Proposed ADR-0082/0083, does **not** switch the production selector,
does **not** deploy, does **not** create or move any tag/release, does **not**
resume Phase 100 and does **not** inspect or copy the Community repository.

**v1 is superseded and is not qualification evidence.** The v1 fault rows
hardcoded generation/epoch, reused one trace/run for unrelated fault actions and
over-claimed scenario names (approval 3-in-1, data-wait). v1 must not be read as
9/9 PASS.

**v2 is the current rectified evidence** (P1-1..P1-8). The acceptance matrix was
frozen before execution
(`docs/evidence/v090-composite-research/acceptance-matrix.v2.json`). The closed
contract (`scripts/v090/composite_research/contract.v2.json`) is the observer's
only source of truth for allowed final states, required assertions, required
coverage, per-scenario boundary and allowed provenance sources. The composite
journey (improve strategy → approval-required action → execute with the original
key → training → out-of-sample prediction → frozen signal → native backtest →
old-vs-new comparison → original-task terminal) ran end-to-end on the isolated
stack with real persisted objects and a consistent validated comparison report.
Every PASS scenario carries real per-scenario provenance (trace from the
authoritative `ml_training_runs.trace_id`, associated with its receipt;
run/generation/epoch explicit `not_applicable` + reason at the ML boundary; pid
measured per restarted service). The scenario set is split and boundary-labelled:
`process-restart-backend/gateway/ml-worker` exercise three boundaries separately;
`cancel-terminal` must end `cancelled` and not reverse; `late-success` requires a
strictly zero downstream delta; `queue-worker-resume` is a real queue resume;
`approval-rejected` and `approval-stale-reuse` are independent real rows. Result:
the journey passes and **13 exercisable required rows PASS; four required rows are
honestly BLOCKED** (`approval-revoked` — no revoke path exists;
`timeout-terminal` — no deterministic timeout boundary; `data-ready-continuation`
— ADR-0077 data_ready not exercised; `runtime-adapter-tool-boundary` — D15
tool-call fault injection scope). The observer is therefore
`format_valid=true` and `all_pass=false` (exit 1); it does not claim 9/9 PASS.
The fail-able observer (`observer.py --selfcheck`, 58 controls, 21
defect-targeting) and the capture negatives (`capture_negatives.py`, 12 cases)
both exit non-zero on every fault. P1-1: the over-broad evidence-directory
gitleaks allowlist was removed and `.gitleaks.toml`/`.gitleaksignore` have no
changes vs `main`; the trigger was removed at the source (high-entropy
content-addressed idempotency keys redacted to a short `sha256:` digest, offending
variable renamed) and the CI gitleaks version/config reports 0 findings over
`origin/main..HEAD`. No 0.9-scope defect was reproduced, so this batch makes no
implementation change. Evidence: `docs/evidence/v090-composite-research/`;
asserted by `tests/test_v090_composite_research.py`. Provider is scripted keyless,
so this is service-boundary fault-regression evidence, not real-LLM-quality
semantics.

Build revision: this batch adds `scripts/v090/composite_research/` and
`tests/test_v090_composite_research.py` (build inputs) and advances the
production runtime build identity `post-u8.178 → post-u8.179` (unused id).
Rebuild identity only: the historical `.178` manifest and evidence are preserved
unchanged; no selector, `compose.yml`, `deployment.json`, immutable release
registry or 0.1.2 artifact/evidence change and no deployment.

## 0.9 ADR-0082/0083 Maintainer Decision (maintenance, 2026-09-21)

This maintenance batch executes step (4) of the 0.9 strict order: record the
maintainer's human decision on ADR-0082 and ADR-0083. It is a **decision/record**
batch only. It does **not** implement the provider, the child bridge, the
`TerminalAttachment` API/persistence, does **not** unfreeze D15/R3, does **not**
switch the production selector, does **not** deploy, and does **not** create or
move any tag/release. It does not inspect or copy the Community repository and
does not resume frozen Phase 100.

- **ADR-0082 — Accepted, modified (Option 1 only).** DSH provides, in the future,
  an independent-process continuable provider / `prepareContinuable`; generic child
  resume and independent child-crash recovery belong to DSH. The BYQ
  runtime-adapter child-resume bridge (Option 2) is **rejected** for the current
  architecture direction; BYQ does not build a second session store or a generic
  harness. `subagent-child-crash` stays BLOCKED until a qualifying out-of-process
  provider exists; the escape path is to keep foreground delegation.
- **ADR-0083 — Accepted, as proposed.** BYQ persists only bounded
  `TerminalAttachment` identity/permission/generation/epoch/state and exposes bounded
  Gateway/Product API interfaces; DSH continues to own PTY/shell/IO. Native
  process-local state loss MUST be reported as truthful `lost`/`interrupted`, never a
  fabricated `reattached`; the ADR does not promise PTY continuity across a runtime
  restart.
- **Not resolved, not closed.** The four D15-G atomic blockers
  (`subagent-child-crash`, `subagent-byq-adapter-restart`,
  `terminal-adapter-restart`, `terminal-dsh-runtime-restart`) remain BLOCKED;
  D15-G remains NO_GO; 0.9 is **not** closed. R3 stays frozen and `R3_RESUME = NO`.
- Decision record: `docs/evidence/v090-adr-decisions/README.md` and
  `decision-record.v1.json`. No GitHub approval is claimed.
- Consistency is asserted by the updated/added governance tests in
  `tests/test_v090_closeout_governance.py`.

Build revision: this batch changes `scripts/dsh/build_revision.py`,
`tests/test_v090_closeout_governance.py` and the candidate Dockerfile (build inputs)
and advances the production runtime build identity
`post-u8.179 → post-u8.180` (unused id). Rebuild identity only: the historical
`.179` manifest and evidence are preserved unchanged; no selector, `compose.yml`,
`deployment.json`, immutable release registry or 0.1.2 artifact/evidence change and no
deployment.

## 0.9 step-5 B1 `subagent-child-crash` remediation (maintenance, 2026-09-21)

This maintenance batch executes the FIRST and ONLY slice of step-5 of the 0.9 strict
order: B1 `subagent-child-crash`, owner `d15-4-child-provider-remediation`. It is an
evidence/qualification batch. It does **not** implement ADR-0082 Option 1 (that is
upstream DSH work), does **not** build a BYQ child-resume bridge (Option 2 is
rejected), does **not** substitute a same-process provider, an owning-process SIGKILL
or a label-only PASS, does **not** unfreeze D15/R3, does **not** switch the production
selector, does **not** deploy, and does **not** create or move any tag/release. It does
not inspect or copy the Community repository and does not resume frozen Phase 100.

- **Read-only capability discovery + isolated qualification (real).**
  `scripts/d15/subagent/child_provider_discovery.mjs` boots the real candidate cordis
  context + real `SubagentRuntime`, registers the real candidate providers and calls
  the real native `SubagentRuntime.prepareContinuable` gate. The only continuable
  providers are in-process `spawn`/`fork`; `acp`/`codex`/`claude-code` (candidate
  bundled) and `dsh-sdk` (not bundled) have no `prepareContinuable` and are rejected
  with `UNSUPPORTED_CAPABILITY`. Candidate source archive sha256
  `23af26a7…8262c` matches the declaration; the upstream source scan agrees.
- **Result — external BLOCKED.** An in-process continuable child shares the executor
  OS process, so it cannot be independently SIGKILLed while the parent stays alive.
  No out-of-process continuable provider exists. `subagent-child-crash` stays
  **BLOCKED** as an external dependency on future upstream DSH work; D15-G stays
  `NO_GO`; 0.9 is **not** closed. R3 stays frozen and `R3_RESUME = NO`.
- **Not started:** `subagent-byq-adapter-restart`, the terminal slices, the D15-G
  re-run, and R3/R4/R5/R6.
- **Maintainer gate-order decision required:** `G-keep` / `G-split` / `G-reorder` /
  `G-reclassify` (see `docs/evidence/v090-closeout/DSH-015RC1-CLOSEOUT-SLICES.md`).
  A strict serial step-5 order cannot be both honest and executable while B1 is an
  external blocker.
- Evidence: `docs/evidence/v090-d15-child-provider-remediation/`, asserted by
  `tests/test_v090_d15_child_provider_remediation.py`.

Build revision: this batch adds `scripts/` and `tests/` build inputs and advances the
production runtime build identity `post-u8.180 → post-u8.181` (unused id). Rebuild
identity only: the historical `.180` manifest and evidence are preserved unchanged; no
selector, `compose.yml`, `deployment.json`, immutable release registry or 0.1.2
artifact/evidence change and no deployment.

## 0.9 step-5 G-split gate-order decision (maintenance, 2026-09-21)

This maintenance batch records the maintainer's `G-split` gate-order decision for the
0.9 strict-order step-5 B1 external blocker. It is a **decision/record** batch only. It
does **not** implement B2 `subagent-byq-adapter-restart` or any runtime/provider/
child-bridge/`TerminalAttachment` code, does **not** unfreeze D15/R3, does **not** switch
the production selector, does **not** deploy, and does **not** create or move any
tag/release. It does not inspect or copy the Community repository and does not resume
frozen Phase 100.

- **B1 `subagent-child-crash` stays a MANDATORY external blocker** — not downgraded, not
  deleted, not made optional; the D15-G required-atomic condition is unchanged.
- **G-split** separates the external B1 from the independently executable internal
  pre-gate fixes, allowing the strict internal order B2 `subagent-byq-adapter-restart` →
  `terminal-adapter-restart` → `terminal-dsh-runtime-restart`.
- **D15-G stays `NO_GO` until B1 truly PASSes.** A B2/B3/B4 `PASS` does not make D15-G
  `GO` while B1 is `BLOCKED`. `R3_RESUME = NO`; D15/R3 stay frozen; 0.9 is **not** closed.
- **Next sole task:** B2 `subagent-byq-adapter-restart`, owner node
  `d15-4-candidate-composition-hookup` (pre-gate; never post-GO R6). It is **not started**
  here.
- Machine-readable record: `docs/evidence/v090-closeout/gsplit-decision.v1.json`.

Build revision: this batch changes `scripts/dsh/build_revision.py`, `tests/` and the
candidate Dockerfile (build inputs) and advances the production runtime build identity
`post-u8.181 → post-u8.182` (unused id). Rebuild identity only: the historical `.181`
manifest and evidence are preserved unchanged; no selector, `compose.yml`,
`deployment.json`, immutable release registry or 0.1.2 artifact/evidence change and no
deployment.

## 0.9 step-5 B2 `subagent-byq-adapter-restart` (maintenance/qualification, 2026-09-21)

This maintenance batch executes B2 `subagent-byq-adapter-restart` (owner node
`d15-4-candidate-composition-hookup`) as the first internal item of the G-split strict
order. It is **qualification/evidence only**: it does **not** implement ADR-0082
Option 2 (a BYQ child-resume bridge, rejected), adds no provider, no second session
store, no second generic harness, no `TerminalAttachment`, does not unfreeze D15/R3,
does not switch the production selector, does not deploy and does not create or move
any tag/release. It does not inspect or copy the Community repository and does not
resume frozen Phase 100.

- A real isolated composition/restart probe
  (`scripts/d15/subagent/byq_adapter_restart_probe.py`) runs the committed candidate
  image `byq-d15-4-continuable-candidate:local` (real `RuntimeAdapter` + real bundled
  DSH 0.1.5-rc.1 runtime + candidate continuable composition, `--network none`, keyless
  scripted provider) with generation A and generation B as separate OS
  processes/containers over one durable session root.
- Result: generation A really reaches `startContinuable` and persists exactly one child
  linked to the original delegation/goal, but a fresh OS process has **no committed BYQ
  composition surface** to rebind/message/resume that child; the composition itself
  forbids the native child messaging tools (`subagent`/`send_message`/`list_agents`).
  B2 therefore stays **BLOCKED (external/dependency)** until ADR-0082 Option 1 (an
  upstream out-of-process `prepareContinuable` provider) exists and is qualified.
- A fail-able observer (`scripts/d15/subagent/byq_adapter_restart_observer.py`, 27
  focused non-zero controls, 25 defect-targeting) derives the verdict; the committed
  verdict is `format_valid=true`, `all_pass=false`, `external_blocked=true`, exit 1.
- Evidence: `docs/evidence/v090-step5-b2-adapter-restart/`, asserted by
  `tests/test_v090_step5_b2_adapter_restart.py`. Next in the G-split strict internal
  order: `terminal-adapter-restart` (owner `d15-5-candidate-attachment-layer`), **not
  started** here. D15-G stays `NO_GO` until B1 truly PASSes; `R3_RESUME = NO`; 0.9 is
  **not** closed.

Build revision: this batch changes `scripts/`, `tests/` and the candidate Dockerfile
(build inputs) and advances the production runtime build identity
`post-u8.182 → post-u8.183` (unused id). Rebuild identity only: the historical `.182`
manifest and all evidence are preserved unchanged; no selector, `compose.yml`,
`deployment.json`, immutable release registry or 0.1.2 artifact/evidence change and no
deployment.

## 0.9 step-5 B3 `terminal-adapter-restart` (maintenance/qualification, 2026-09-21)

This maintenance batch executes B3 `terminal-adapter-restart` (owner node
`d15-5-candidate-attachment-layer`) as the second internal item of the G-split strict
order (after B2 stayed BLOCKED-external). It is **candidate/qualification-layer** work:
it implements and verifies the minimal BYQ `TerminalAttachment` lifecycle accepted by
ADR-0083 but does **not** productize it (no R4), does not switch the production selector,
does not deploy and does not create or move any tag/release. It does not start
`terminal-dsh-runtime-restart` (B4), D15-G re-run or R3/R4/R5/R6, does not inspect or copy
the Community repository and does not resume frozen Phase 100.

- BYQ owns only a bounded durable attachment record (BYQ-minted attachment id, owner
  principal/authorization, runtime generation, executor epoch, state and audit linkage);
  DSH continues to own the PTY/shell/process/IO. BYQ builds no PTY runtime, copies no DSH
  terminal, builds no second generic harness/store and never persists or fabricates the
  native PTY (`scripts/d15/terminal/adapter_restart_harness.mjs`).
- Generation A establishes a real native persistent terminal plus a durable BYQ attachment
  in separate OS processes. Aborting the BYQ adapter OS process and starting a fresh
  adapter generation B is exercised in two real branches:
  - **native reachable** -> generation B reloads the same durable attachment, authorizes
    and generation-validates it and rebinds the SAME attachment/native session/PTY pid with
    a unique marker (no replay, no loss);
  - **native lost** (committed topology: the adapter restart takes the native runtime with
    it) -> generation B deterministically reports `lost`/`interrupted` and rejects a fake
    reattach. Per ADR-0083 this honest state is the acceptance.
- A fail-able observer (`scripts/d15/terminal/adapter_restart_observer.py`, 32 focused
  non-zero controls, 29 defect-targeting) derives the verdict and explicitly distinguishes
  a correct honest `lost`/`interrupted` from a not-implemented/label-only PASS by requiring
  the positive fresh-adapter rebind of a durable attachment before the honest loss can pass.
  The committed verdict is `format_valid=true`, `all_pass=true`, exit 0.
- Evidence: `docs/evidence/v090-step5-b3-terminal-adapter-restart/` (native observations,
  verdict, negative controls, scope probe, provenance), asserted by
  `tests/test_v090_step5_b3_terminal_adapter_restart.py`. Next in the G-split strict
  internal order: `terminal-dsh-runtime-restart` (B4), **not started** here. D15-G stays
  `NO_GO` until B1 truly PASSes; `R3_RESUME = NO`; 0.9 is **not** closed.

Build revision: this batch changes `scripts/`, `tests/` and the candidate Dockerfile
(build inputs) and advances the production runtime build identity
`post-u8.183 → post-u8.184` (unused id). Rebuild identity only: the historical `.183`
manifest and all evidence are preserved unchanged; no selector, `compose.yml`,
`deployment.json`, immutable release registry or 0.1.2 artifact/evidence change and no
deployment.

## 0.9 step-5 B4 `terminal-dsh-runtime-restart` (maintenance/qualification, 2026-09-21)

This maintenance batch executes B4 `terminal-dsh-runtime-restart` (owner node
`d15-5-candidate-attachment-layer`) as the fourth and final internal item of the G-split
strict order (after B2 stayed BLOCKED-external and B3 PASSed). It is
**candidate/qualification-layer** work: it reuses the committed B3 native runtime role and
the minimal BYQ `TerminalAttachment` store schema, adds the DSH-runtime-restart fault and
orphan reconcile, and implements no production wiring/R4. It does not re-run D15-G, start
R3/R4/R5/R6, switch the production selector, deploy, create/move any tag/release, inspect or
copy the Community repository, or resume frozen Phase 100.

- BYQ owns only the bounded durable attachment + reconcile; DSH owns the PTY/shell/process/IO.
  BYQ builds no PTY runtime, copies no DSH terminal, builds no second generic harness/store and
  never persists or fabricates the native PTY (`scripts/d15/terminal/dsh_runtime_restart_harness.mjs`).
- A real isolated native probe reuses the committed B3 runtime role and truly terminates the
  **DSH runtime OS process**, then starts a genuinely fresh OS process as runtime generation B:
  - `dsh-runtime-restart-terminal-lost` **PASS** — generation A establishes a real native PTY
    (unique marker echoed) plus a durable BYQ attachment; after SIGKILL and restart of the DSH
    runtime (runtime pid changed, generation `1→2`, old PTY pid dead, 0 sessions in the new
    runtime) a fresh adapter generation B reloads the same durable attachment, authorizes and
    generation-validates it and deterministically records `lost` (`NATIVE_SESSION_UNAVAILABLE`),
    rejecting a fake reattach; a retry returns the same loss.
  - `surviving-pty-without-attachment-lost` **PASS** — a genuinely surviving PTY with no BYQ
    attachment is reconciled as an orphan `lost`, is never silently reused/adopted, the stale
    attachment id is rejected and cleanup leaves no orphan PTY.
- Terminal lifetime never defines conversation or durable-job lifetime: the BYQ conversation/job
  identities stay `active` and unchanged across both faults.
- A fail-able observer (`scripts/d15/terminal/dsh_runtime_restart_observer.py`, 48 focused
  non-zero controls, 45 defect-targeting) derives the verdict from raw pids/generations/counters
  and rejects fake reattach, label-only PASS, no-real-restart, terminal-driven conversation/job
  termination and orphan reuse. The committed verdict is `format_valid=true`, `all_pass=true`, exit 0.
- Evidence: `docs/evidence/v090-step5-b4-terminal-dsh-runtime-restart/` (native observations,
  verdict, negative controls, scope probe, provenance, current overlay distinguishing the
  historical D15-5/D15-G committed snapshot from the B4 current overlay), asserted by
  `tests/test_v090_step5_b4_terminal_dsh_runtime_restart.py`.
- The G-split strict internal order (B2/B3/B4) is complete. D15-G must not be re-run while B1
  is BLOCKED and stays `NO_GO`; `R3_RESUME = NO`; 0.9 is **not** closed.

Build revision: this batch changes `scripts/`, `tests/` and the candidate Dockerfile
(build inputs) and advances the production runtime build identity `post-u8.184 → post-u8.185`
(unused id). Rebuild identity only: the historical `.184` manifest and all evidence are
preserved unchanged; no selector, `compose.yml`, `deployment.json`, immutable release registry
or 0.1.2 artifact/evidence change and no deployment.

## 0.9 formal repo default dependency/selector upgrade to DSH 0.1.5-rc.1 (maintenance, 2026-09-22)

This maintenance batch executes the retained 0.9 closeout step **"formally upgrade the
repository default dependency/selector to the coherent DSH `0.1.5-rc.1`"**, in an isolated
worktree/branch/Draft PR based on dynamic `origin/main`. It is maintenance/qualification; it
does **not** advance a Product Phase, does **not** deploy to production, does **not** create or
move any tag/release, does **not** resume Phase 100, does **not** inspect or copy the Community
repository, does **not** generate a D15 superseding assessment and does **not** start 0.10. It
reimplements no DSH code, adds no cross-process continuable provider and adds no second agent
harness.

- **Reused candidate assets** (no re-qualification): the D15-1 candidate declaration + Python
  lock, the isolated candidate Dockerfile/requirements lock, the `dsh_015` compat shim and the
  D15/B2/B3/B4 evidence.
- **Default move**: `config/dsh/deployment.json` default `dsh-0.1.5rc1` with `dsh-0.1.2rc1` as
  the rollback candidate; a new registered `dsh-0.1.5rc1` release descriptor + exact Python lock
  (upstream tag/commit/archive from D15-0); the promoted candidate declaration; the default
  selector identity (`config/dsh/generated/deployment.identity.json`) and the rollback identity;
  `Dockerfile.post-u8-candidate` selector/build-manifest/assert; `requirements.candidate.lock`
  and `pyproject.toml`; `compose.yml`; the compat default branch; `build_revision` current
  release and build id `dsh-0.1.5rc1-post-u8.200`; and the F6 continuation gate accepting the
  coherent 0.1.5 pair so no qualified capability is silently disabled.
- **Verifiable rollback**: the 0.1.2 release descriptor, Python lock and
  `dsh-0.1.2rc1-post-u8.199` build manifest are byte-identical to the base commit; the archived
  0.1.2 identity and prior deployed image digest are recorded; a fail-closed verifier rejects
  any rollback drift.
- **Targeted real verification** (keyless): upgraded image build, `/readyz`
  `release_identity=matched` for `dsh-0.1.5rc1`, in-image runtime/domain-wire suite 244 passed /
  40 skipped, F6 continuation budget 10 passed, and the D15 start probe `ready`/`idle` with a
  real `mcp__byq` tool call and contiguous events.
- **Evidence**: `docs/evidence/v090-dsh-015rc1-default-upgrade/`, with the fail-closed
  `scripts/v090/dsh_default_upgrade/verify.py` (13 defect-targeting negatives) asserted by
  `tests/test_v090_dsh_default_upgrade.py`. The two v090 evidence bundles and the H4 interface
  ledger that bind `runtime.py` are refreshed **digest-only** with unchanged verdicts.
- **Boundaries unchanged**: B1/B2 `BLOCKED_EXTERNAL`, historical D15-G `NO_GO` (not rewritten),
  no D15 superseding assessment, `R3_RESUME = NO`, no production deployment, no tag/release, no
  Phase 100 resume, no 0.10.

Build revision: this batch changes `scripts/`, `tests/`, `services/runtime-adapter` and config
(build inputs) and advances the production runtime build identity `post-u8.199 → post-u8.200`
(unused id). The historical `.199` manifest and all evidence are preserved.

## Maintenance — Delist-boundary coverage correction (ADR-0028)（构建修订 `dsh-0.1.2rc1-post-u8.130`，PR #299）

ADR-0028 point 2 evaluates coverage over each symbol's frozen listing lifecycle. The market-readiness
applicability filter in `services/backend/app/market_readiness.py` previously treated `delist_date` as an
applicable session (`trade_date > delist_date`), so a mid-window delisting's delist date was required
without bar/status proof and permanently blocked readiness and partition promotion. The boundary is now
exclusive: a session is not applicable when `trade_date < list_date`, or when `delist_date` is present and
`trade_date >= delist_date`. Bars/status on or after `delist_date` are never required and never appear in
`missing`; symbols without `delist_date` and sessions strictly before `list_date` are unchanged. This
matches the lifecycle semantics already used by stock-pool selection (`delist_date > :date`). No Accepted
ADR text is changed.

## Maintenance — Bounded signal sandbox input encoding (ADR-0023)（构建修订 `dsh-0.1.2rc1-post-u8.131`，PR #300）

Promoting a frozen signal/backtest job for a 300-symbol × ~727-session panel overflowed ADR-0023's
32 MiB `MAX_JOB_BYTES`/`MAX_REQUEST_BYTES` envelope because `prepare_signal_job_input` embedded the raw
execution bars and the adjusted research bars as two full lists of per-row mappings, while the sandbox
consumes only the research view. The frozen panel is now stored once as a deterministic `bars_frame.v1`
columnar frame (`packages/contracts/bars_frame.py`): canonical symbol/date index lists, per-field primitive
arrays, finite floats, and the per-row adjustment multiplier that reconstructs the adjusted research view
exactly. The coordinator (ADR-0029 decision 4) materializes the research frame for the sandbox request,
while the raw execution panel is preserved for the immutable signal snapshot. Legacy row-dict documents
remain decodable by both the sandbox runner and the coordinator. Both `MAX_JOB_BYTES` and
`MAX_REQUEST_BYTES` stay at 32 MiB and the credential-free sandbox resource envelope is unchanged. No
Accepted ADR text is changed.

## Maintenance — ADR-0047 aggregate bound in snapshot/backtest normalization（构建修订 `dsh-0.1.2rc1-post-u8.132`，PR #301）

After the columnar encoding fix, a promoted 300-symbol × ~727-session aggregate still failed at
`services/backend/app/backtest.py` with `BacktestResourceExceeded: bars exceeds 50000 rows`. `MAX_BARS`
and `MAX_SIGNALS` had kept the retired ADR-0028 single-partition "50,000 symbol-session cells" cap even
though ADR-0047 decoupled that cap from aggregates. Both now reference the shared
`AGGREGATE_ROW_LIMIT = 2_000_001` in `packages/contracts/bars_frame.py` (the same documented constant the
sandbox runner and `build_partitioned_ready_input(row_limit=...)` use), so one source of truth covers the
data-readiness builder, the signal sandbox, and signal-snapshot/backtest normalization. The per-partition
`MAX_REQUIRED_CELLS`/`market_plan` 50,000-cell invariant, the 32 MiB object/transport caps
(`MAX_JOB_BYTES`/`MAX_REQUEST_BYTES`/`MAX_RESULT_BYTES`/`MAX_SNAPSHOT_BYTES`), the MCP schema, Gateway and
frontend are unchanged; genuinely oversized input still fails closed with a stable
`bars exceeds ...`/`signals exceeds ...` message. No Accepted ADR text is changed.

## Maintenance — Columnar immutable signal snapshot (ADR-0017/ADR-0023)（构建修订 `dsh-0.1.2rc1-post-u8.132`，PR #301）

A real production `signal_snapshot` for 300 symbols × 727 sessions with the full `market-data-requirement.v3`
field set serialized to ~41 MiB, dominated by the row-mapping `bars` panel, and exceeded the unchanged
32 MiB `MAX_SNAPSHOT_BYTES`/`MAX_ARTIFACT_JSON_BYTES` object bounds even after the `MAX_BARS` alignment.
`normalize_signal_snapshot` now stores the frozen execution panel once with the same deterministic
`bars_frame.v1` columnar encoding used for the sandbox/job document (`basis="snapshot"`, no adjustment
multiplier), so the 300×727 aggregate serializes to ~14.2 MiB inside the existing caps. `signal-snapshot-v2`
is the current shape; `snapshot_bars` decodes both v2 frames and legacy v1 row lists. Encoding is canonical
across row order and the content-addressed identity is unchanged for identical logical input; corrupt or
oversized frames and rows fail closed with the stable `bars exceeds ...`/frame-shape errors. The 32 MiB
caps, sandbox resource envelope, MCP schema, Gateway and frontend are unchanged. No Accepted ADR text is
changed.
