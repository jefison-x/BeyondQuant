# Runtime Continuity Failure Matrix

- Status: Proposed future test matrix (ADR-0079/ADR-0081)
- Date: 2026-09-19
- Scope: BYQ Runtime Continuity program (R0 lifecycle model; R1 executor lease;
  R2 durable session identity vs ephemeral runtime generations; D15 native
  continuity qualification)
- Related: ADR-0062, ADR-0064, ADR-0078, ADR-0079, ADR-0081, ADR-0023

本文档定义 Runtime Continuity 六个生命周期在故障下的期望行为，作为后续独立阶段
（Supervisor / Terminal / DurableJob）的测试矩阵来源。**R0 只定义模型，R1 只实现
AgentSession/Runtime 的稳定 lease 与 epoch fencing**；本文档不表示终端、Supervisor、
后台任务已实现。

## 1. 六个生命周期

| 生命周期 | 类型 | 身份来源 | 持久性 |
| --- | --- | --- | --- |
| **Conversation** | durable 用户可见对象 | BYQ conversation id / owner / workspace | 永久（PostgreSQL） |
| **AgentSession** | durable 逻辑连续性（不是进程） | BYQ `session_id` / `trace_id` / owner / workspace | 跨进程/容器/主机重启持续 |
| **Run** | 每次输入或续接一次 | BYQ run id（root 回合） | 证据随 journal 持久，进程内活跃态易失 |
| **RuntimeGeneration** | 临时执行代际 | 每次 DSH 进程/回合新建的 generation | 进程崩溃即失效；被替换是正常而非失败 |
| **TerminalAttachment** | 独立于 Agent/Runtime | terminal id + 连接状态 | 独立生命周期；状态 ATTACHED/DETACHED/EXITED/INTERRUPTED |
| **DurableJob** | 独立领域任务 | domain job id（Backend/Worker） | 独立于 Agent/Runtime/Terminal |

关键点：**AgentSession 是逻辑连续性，不是 DSH 进程**；一个 AgentSession 可以经历
generation-1..N，generation 被替换是正常行为。

## 2. 不变式（见 `ARCHITECTURE.md` §K）

1. Conversation identity MUST NOT depend on runtime process identity。
2. Agent session identity MUST NOT depend on host boot identity。
3. Terminal lifetime MUST NOT define conversation or durable-job lifetime。
4. Durable domain jobs MUST survive Agent runtime replacement。

## 3. 故障矩阵（期望行为）

图例：**持续** = 身份与连续性保持，可恢复；**替换** = 执行资源重建，属正常；
**降级** = 明确的状态降级/需显式恢复；**丢失** = 需外部备份恢复。

| 故障 \ 生命周期 | Conversation | AgentSession | RuntimeGeneration | TerminalAttachment | DurableJob |
| --- | --- | --- | --- | --- | --- |
| Browser disconnect | 持续 | 持续 | 持续 | DETACHED（终端独立运行） | 持续 |
| Frontend restart | 持续 | 持续 | 持续 | DETACHED，可重连 | 持续 |
| Gateway restart | 持续 | 持续（trace 以持久 sequence 续写） | 持续（若 adapter 存活） | 重连为 DETACHED/ATTACHED | 持续 |
| Adapter restart | 持续 | 持续（journal lease 稳定，按需 rehydrate） | 替换（新 generation） | 降级（连接重建） | 持续 |
| DSH crash | 持续 | 持续（lost root 显式收尾，不自动续跑模型） | 替换 | INTERRUPTED/DETACHED | 持续 |
| Supervisor crash | 持续 | 后续阶段：持续（不因 supervisor 丢失逻辑连续性） | 替换 | 后续阶段 | 后续阶段 |
| Host reboot | 持续 | **持续**（lease 不再依赖 boot_id） | 替换 | EXITED/INTERRUPTED | 持续 |
| Worker restart | 持续 | 持续 | 持续 | 持续 | 持续（job lease/重试语义） |
| Storage loss | 丢失（需备份恢复） | 丢失（journal/证据卷丢失） | 丢失 | 丢失 | 丢失（需备份恢复） |

## 4. 当前覆盖与后续阶段

- **R1 覆盖**：Adapter restart、DSH crash（既有 ADR-0064 收尾语义）、Host reboot 的
  AgentSession/RuntimeGeneration 连续性；稳定 executor identity + 单调 epoch fencing；
  legacy v3 journal 迁移。
- **后续阶段（本文档仅登记，不实现）**：Supervisor 生命周期与故障测试；TerminalAttachment
  的 ATTACHED/DETACHED/EXITED/INTERRUPTED 状态机、重连与输入回执；DurableJob 与
  Agent/Runtime/Terminal 的解耦与跨重启语义；Storage loss 的备份/恢复演练。
- **R3 冻结（ADR-0081）**：Supervisor 阶段状态为
  `PAUSED_PENDING_DSH_015_NATIVE_CONTINUITY_QUALIFICATION`。自建 DSH 进程重启编排、
  会话重建、原生会话持久化替代、subagent 持久化与持久 PTY/shell 暂停，直至 D15-G。
  这不是 R3 失败，而是 DSH 0.1.5 原生覆盖这些能力的前提。D15 的测试计划见
  [D15 stage plan](../roadmap/DSH_015RC2_UPGRADE_PLAN.md)。
- Gateway trace（`TraceStore`/`LifecycleDelivery`）已核验不依赖 lease（只按 session id +
  sequence）；R1 不修改 Gateway trace 模型。

## 5. Continuity 状态映射（R2）

R2 在 AgentSession/RuntimeGeneration 边界报告一个封闭、框架中立的 continuity status：

| 事件 | continuity | 说明 |
| --- | --- | --- |
| 新 session | `fresh` | 无既有 durable 证据 |
| create/resume 复用存活 in-process generation | `reattached` | Path A；不新建进程 |
| adapter restart / 进程消失后 rebind | `rehydrated` | Path B；新建 generation，公开上下文经既有恢复合同回灌 |
| run/generation 在崩溃、watchdog 或硬取消后被终止 | `interrupted` | 旧 generation 标记 interrupted，新 generation 接续同一 durable session |

generation 替换不改变 AgentSession identity、canonical sequence 或 lifecycle-journal 证据。
Supervisor（R3）与 TerminalAttachment（R4）状态机仍是后续阶段。

## 6. D15 原生连续性分类

D15 在既有公开 `continuity` 合同（`fresh/reattached/rehydrated/interrupted`）之下，对每个
故障矩阵行走查并允许增加**仅用于证据**的内部诊断字段，区分恢复机制：

| 机制 | 公开 continuity | 内部诊断（evidence-only） | 说明 |
| --- | --- | --- | --- |
| 存活 in-process generation 复用 | `reattached` | `native_resume_used=false` | Path A；不新建进程 |
| DSH 0.1.5 原生 session 句柄打开并恢复 loop | `rehydrated` | `native_resume_used=true` | Session V3/句柄持久化 |
| 原生不可用，走既有 BYQ conversation rehydration | `rehydrated` | `byq_fallback_used=true` | 不伪装成 native |
| run/generation 被终止 | `interrupted` | `previous_generation_state` | 新旧 generation 接续同一 durable session |

不变式：内部诊断字段 MUST NOT 取代或泄漏进框架中立的公开 continuity 值；DSH session id
MUST NOT 成为 BYQ `AgentSession` 身份。TerminalAttachment（R4）与 DurableJob（R5）状态机
仍在 D15 之后。
