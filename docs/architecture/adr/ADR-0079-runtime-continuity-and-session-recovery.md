# ADR-0079：Runtime Continuity 与 Session Recovery

- Status: Proposed
- Date: 2026-09-19
- Relates: ADR-0062（Post-U8 可靠性边界）、ADR-0064（Runtime 崩溃恢复的受限持久证据）、
  ADR-0078（Explicit Reversible Session-Lease Re-anchor）、ADR-0023（隔离信号生产者的
  执行者身份约束）、ADR-0059（开发权限与 CI 证据门禁）
- Supersedes: 待接受后替代 ADR-0064「首版实现边界」中以 Linux `boot_id` 绑定执行者证据的
  条款，以及 ADR-0078 §4「提议的持久设计修复」；不改写任何 Accepted ADR 文本。
- Decision scope: runtime-adapter lifecycle journal 的稳定 executor identity、单调 epoch
  fencing、legacy v3 journal 迁移；`scripts/ops` 运维工具；docs/architecture 生命周期模型与
  故障矩阵。不含 Gateway/Backend/MCP/Worker/DSH 版本或 composition 变更。

## Context

运行连续性缺陷在生产中每此主机重启都会复现：`LifecycleJournal` 以

```
lease_identity = sha256(boot_id : st_dev : st_ino : token)
```

绑定执行者，其中 `boot_id` 来自 `/proc/sys/kernel/random/boot_id`，**每次 host reboot
都改变**。2026-09-19 reboot 后 17 个既有 session（含活跃会话）全部 `409
stale_session_lease`。ADR-0078 的显式 re-lease 只是应急修复；根因是 lease 绑定了与业务
无关的宿主生命周期事实。

同时，runtime/session/terminal/job 的语义边界缺少统一书面模型，容易把「临时执行进程」
当作「会话身份」。本文档定义六层生命周期与故障矩阵（R0），并把 R1 作为第一个有界实现步骤：
稳定 executor identity + 单调 epoch fencing，使正常进程/容器/主机重启不再使 lease 失效，
同时保留单写者 fencing 与 fail-closed。

## Decision

### 0. 六个生命周期与不变式（R0）

定义 **Conversation → AgentSession → Run → RuntimeGeneration → TerminalAttachment →
DurableJob** 六层生命周期及其持久性；完整定义与故障矩阵见
[Runtime Continuity Failure Matrix](../RUNTIME_CONTINUITY_FAILURE_MATRIX.md)。要点：

- **Conversation**：durable 用户可见对象（PostgreSQL）。
- **AgentSession**：durable 逻辑连续性，**不是进程**；跨进程/容器/主机重启持续。
- **Run**：每次输入/续接一次；证据随 journal 持久，进程内活跃态易失。
- **RuntimeGeneration**：临时执行代际；一个 AgentSession 可有 generation-1..N，**替换是
  正常而非失败**。
- **TerminalAttachment**：独立于 Agent/Runtime；状态 ATTACHED/DETACHED/EXITED/INTERRUPTED。
- **DurableJob**：独立领域任务，独立于 Agent/Runtime/Terminal。

不变式（同步写入 `ARCHITECTURE.md` §K）：

1. Conversation identity MUST NOT depend on runtime process identity。
2. Agent session identity MUST NOT depend on host boot identity。
3. Terminal lifetime MUST NOT define conversation or durable-job lifetime。
4. Durable domain jobs MUST survive Agent runtime replacement。

**R1 是第一个有界步骤**；Supervisor、Terminal 状态机与 DurableJob 解耦是后续独立阶段，
本 ADR 的故障矩阵是其未来测试契约，不代表已实现。

### 1. 稳定 executor identity（R1）

- 新增 deployment-controlled `runtime-executor.v1` 记录（位于既有
  `/opt/byq/releases/deployment.identity.json`），包含 `deployment_id`、
  `runtime_release`、`volume_identity`、`executor_epoch`。
- lease 改为 **`lease_identity = sha256(deployment_id : executor_epoch : lock_token)`**，
  其中 `lock_token` 绑定同一卷上永不主动删除的 owner lock 对象；**不再使用 `boot_id`、
  PID、hostname 或 container id**。
- `deployment_id`/`volume_identity`/`runtime_release` 是稳定部署身份；`st_dev:st_ino`
  仅用于检测卷复制/锁对象替换，跨 reboot/容器重建不变。

### 2. 单调 epoch fencing（R1）

- `executor_epoch` 是单调 fencing token：**进程/容器/主机重启都不改变它**，只有显式、
  可审计的 ownership takeover（operator takeover / executor replacement / storage
  ownership reassignment）才递增。
- **权威 epoch 存于卷拥有的状态文件** `<evidence-root>/executor-state/executor-epoch.v1.json`
  （原子写 + fsync + 目录 fsync），由 `<evidence-root>/executor-state/executor-epoch.lock`
  串行化；镜像内的 `runtime-executor.v1.executor_epoch` 只是初始化 floor。
- 写者必须满足 `journal.executor_epoch == current_epoch` 且 `deployment_id` 匹配，否则
  fail closed（`JournalIdentityMismatch` 类错误）；每次 journal 写入都在 epoch 共享锁下
  复核，takeover 在 epoch 排他锁下递增，因此 takeover 会 fence 仍存活的旧 epoch 写者。
- 显式 takeover 入口：`LifecycleJournal.takeover_executor_epoch` 与
  `scripts/ops/takeover_executor_epoch.py`（默认 audit；`--apply` 需具体 `--reason`；
  写入不可变 takeover 审计；并发 takeover 只有一个赢家，其余
  `ExecutorTakeoverBusy`）。正常启动**绝不**递增 epoch。

### 3. Fail-closed 与迁移（R1）

- 缺失/损坏 epoch 状态：若存在 v4 stable journal，则**拒绝自动重建**，要求显式 takeover/
  修复；空卷或仅有 legacy（≤v3）journal 时按 deployment floor 初始化一次（bootstrap）。
- journal schema **v3 → v4** 增加 `executor_identity`/`executor_epoch`。legacy journal 在
  **首次受控 claim**（持有排他 owner lock）时一次性迁移到稳定 lease，逐字段保留
  `sequence`/`events`/`prompts`/`terminal_acks`/`calls`/`context`/`open_root`；
  **正常 reboot 路径不需要人工 re-anchor**。
- `LifecycleJournal.reanchor_lease` 与 `scripts/ops/reanchor_session_lease.py` 保留为
  **异常修复工具**（identity 损坏 / 灾难恢复 / legacy 迁移 / takeover 后旧 epoch 修复），
  不再是 reboot 路径。
- 保留：排他 `flock`、canonical sequence 排序、事件/prompt/terminal 回执/domain-call 证据、
  prompt 幂等、失败即阻止新模型回合。

### 4. LifecycleJournal 的归属边界

`LifecycleJournal` 是 **BYQ-owned execution evidence journal**，只保存 ownership /
generation / root lifecycle / prompt identity / terminal receipt / domain-call evidence /
sequence。它 **MUST NOT** 演化为第二套 DSH session/context/tool persistence，不保存原始
prompt、模型推理、密钥、工具私有状态或应用源码。

### 5. R2 实现：durable session identity 与 RuntimeGeneration 分离（Proposed）

R1 只稳定了 lease；R2 在 runtime-adapter 内将会话模型拆分为：

- **durable AgentSession record**（`RuntimeSession`）：`session_id` / `trace_id` / owner /
  workspace、`last_sequence`（canonical sequence）、`executor_epoch`、`status`、
  conversation linkage、prompt/terminal/domain-call evidence 与 journal 归属；
- **RuntimeGeneration record**（`RuntimeGeneration`）：`generation_id`、`session_id`、
  `executor_epoch`、private native session identity、`started_at`、`state`，以及仅属于该
  代际的进程/运行态。

替换 generation（adapter restart、crash 后 rebind、resume、root-scoped 新回合）一律建模为
**新 generation**，绝不建模为 session failure；`session_id`、canonical sequence 与
lifecycle-journal 证据保持不变。

**continuity status**（`packages/contracts/runtime_continuity.py`，框架中立）：

- `fresh`：全新 session；
- `reattached`：原 in-process generation 仍存活并被复用（Path A）；
- `rehydrated`：原 generation 已消失，创建新 generation 并按既有 conversation
  recovery/rehydration 合同恢复公开上下文（Path B）；
- `interrupted`：run/generation 被终止并如实标记 interrupted，再由新 generation 接续。

continuity 只作为封闭字符串跨越 adapter/Gateway 响应边界；generation id、native session id
与 process identity 不回传、不进入 WorkflowTrace。带界的 per-session generation 历史记录在
`<evidence-root>/generation-ledger/<session_id>.json`（BYQ-owned、best-effort，仅保存
generation id / executor epoch / root / state / 时间），不扩展 lifecycle journal schema，也不
新增 PostgreSQL AgentSession registry。R2 不含 Supervisor 与 Terminal 状态机（R3/R4）。

## 与既有 ADR 的关系

- **ADR-0062**：本文在其恢复与失败事实边界内实现；不改 900 秒/预算/续接授权语义。
- **ADR-0064**：保留其受限持久证据、只读重放、终态不可覆盖、「不按 PID/超时猜测」和
  fail-closed；仅具名替代「以 `boot_id` 绑定执行者」的首版实现条款。
- **ADR-0078**：其显式 re-anchor 作为异常修复路径保留；其 §4 的持久设计由本文实现。
- **ADR-0023**：执行者身份隔离约束保持；lease 不再依赖宿主生命周期。

## Consequences

- 正常进程/容器/主机重启后 session 可自动恢复，**零 stale**；运维不再需要每次 reboot
  人工 re-lease。
- epoch takeover 是显式、有界、可审计的；并发 takeover 只有一个赢家，旧 epoch 写者被
  fence。
- 卷复制/锁对象替换仍 fail closed；缺少 epoch 状态且已有 stable journal 时 fail closed。
- takeover 后旧 epoch journal 需要显式修复（reanchor）才能重新 claim；这是刻意的 fencing
  代价，且仅发生在显式 ownership 变更时。
- 终端、Supervisor、DurableJob 解耦仍待后续阶段；本 ADR 的故障矩阵是其测试契约。

## Migration / rollback

- v3 → v4 迁移在首次受控 claim 时发生，保留全部证据；rollback 时旧版本无法识别 v4 journal
  将 fail closed，因此回滚必须连同稳定 identity 一起回退并保留证据审计。
- 无数据库迁移、无 domain row 变更、无 Gateway trace 刷新（`TraceStore`/`LifecycleDelivery`
  按 session id + sequence，已核验无 lease-bound 状态）。
- 若需回退到 boot-bound 行为，应另立 Accepted ADR；不得静默降级。

## 接受后验收要求（R1）

- 进程重启 / 容器重启 / 模拟 host reboot（`boot_id` 改变）→ 全部 session 恢复且
  **零 stale**。
- 第二并发写者被拒；旧 epoch 写者被拒；显式 takeover 递增 epoch 后旧写者被 fence；
  并发 takeover 单赢家；缺失/损坏 epoch fail closed。
- legacy v3 journal 迁移到 v4 且逐字段保留全部证据，迁移后可正常 claim。
- re-anchor 工具在异常场景仍可用。
- 失败矩阵登记为后续测试契约。R0/R1 证据见本 ADR 与
  [Runtime Continuity Failure Matrix](../RUNTIME_CONTINUITY_FAILURE_MATRIX.md)。

### 接受后验收要求（R2）

- fresh session 报告 `fresh`；存活 generation 的 resume 报告 `reattached` 且不新建进程。
- 进程/容器重启后 generation 消失：报告 `rehydrated`，生成 NEW generation id，旧
  generation 记入带界历史，`session_id`、sequence 与 journal 证据不变。
- 崩溃中的 generation：旧 generation 被标记 `interrupted`，新 generation 接续同一 durable
  session。
- generation 替换不改变 durable session identity，也不丢失 evidence/sequence 与续接/re-lease
  fencing 语义。
- 既有 runtime-adapter 套件与架构测试保持通过。
