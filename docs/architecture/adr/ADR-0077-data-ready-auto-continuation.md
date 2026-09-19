# ADR-0077：数据就绪自动续接（复用任务续接合同）

- Status: Proposed
- Date: 2026-09-19
- Relates: ADR-0045（数据需求与通知边界）、ADR-0051（审批续接）、ADR-0062（U8 可靠性边界）、ADR-0065（任务续接预算准入）、ADR-0072（长研究检查点）
- Supersedes: 无。仅对 ADR-0045 §3「默认下一回合投递」增加一个具名、有界的例外，待维护者接受。

## Context

生产观察：小巴创建回测任务后，信号生产 job 进入 `waiting_for_data`，模型回合结束；数据到位后
job 转为 `completed` 并产出 `signal_snapshot`，但没有任何机制唤醒原会话，用户必须再发一条消息。

现有任务绑定续接（F6/ADR-0062/0065）已经能在终态领域事件上生成一次续接意图，但要求任务先有
用户显式确认的 `continuation_permission` 预算许可。生产中的任务没有该许可，因此 `signal_producer_jobs`
即使 `completed` 也不会被消费。ADR-0051 的审批续接证明：服务端可以在持久领域事实上发起一次性
续接回合，而不需要额外的 token 预算许可；该回合只让 Agent 重新读取并继续原目标，不授予任何领域动作。

## Decision

1. 在既有任务绑定续接合同（`services/backend/app/research_continuation.py`）内新增**数据就绪事件**。
   当 `signal_producer_jobs` 为 `completed` 且其产出的 `signal_snapshot` artifact 为 `validated` 时，
   现有按 conversation/owner/workspace 的封闭扫描生成至多一个 `ready-v1:` 事件，身份绑定
   `(job, result_artifact, updated_at, status)`。
2. **复用而非新增**：预留写入既有 `continuation_budget` 账本，经既有
   `/internal/task-continuation/{conversation}/peek|claim`、`.../dispatch`、`.../receipt` 接口，
   由既有 Gateway `TaskContinuationDelivery` 消费者和 runtime-adapter prompt 路径投递；
   `continuation_scope.py` 继续对续接回合内的 MCP 工具做原任务范围准入。不新建通用 harness 或第二个消费者。
3. **有界**：每任务最多 `DATA_READY_MAX_TURNS=8` 个数据就绪回合；每回合保守输入上界
   `1048576+8192` token、900 秒回合期限；同一任务最多一个未结算预留；遵循
   `BYQ_F6_EXECUTOR_ENABLED` 特性开关与 Runtime 续接资格。该固定上界不是用户确认的 token 许可，
   也不授权任何领域动作；每个后续动作仍需各自审批。
4. **只在就绪时触发**：`failed`/`cancelled` 的 signal job 不产生数据就绪事件；`completed` 但没有
   `validated signal_snapshot` 也不触发。
5. **owner/workspace/conversation 隔离**：只处理精确匹配的会话与任务；外owner、外工作区、
   无关会话不产生事件。
6. 事件身份去重（`ready-v1:`）+ 任务行锁（`FOR UPDATE`）保证并发轮询、进程重启与重复投递
   最多一次；已结算事件永不再次触发。

## Consequences

- Agent 在数据就绪后被唤醒，重新读取原任务并按其既有授权继续；用户无需再发消息。
- 后台模型执行在没有用户 token 许可时在**固定保守上界**内被允许，改变了 ADR-0045 的默认；
  因此本 ADR 为 Proposed，需维护者接受后才作为当前规范。预算受限的 F6 许可路径保持不变。
- 数据就绪事件、失败可见性（handoff 投影与任务阶段）和逐动作审批边界均不改变。

## Implementation notes (post-u8.142)

`continuation_needs_attention` is an **event-scoped** block, not a task-lifetime
block. When a reservation settles `needs_attention`, the backend records the
exact blocking event key in `research_tasks.continuation_blocked_event_key`
alongside `continuation_blocked_reason`. The closed continuation scan then
suppresses only that exact event key; a later **distinct** `ready-v1:` event
(new `signal_producer_job` and snapshot) re-arms the task and reserves a new
bounded turn. At-most-once for the blocked event is still guaranteed
independently by its settled `continuation_budget` row, and re-arm remains
bounded by `DATA_READY_MAX_TURNS`/`max_turns`, the token budget, and the 900s
reservation expiry. A deliberate task-wide block (`POST
/internal/task-continuation/{task}/block` with reason
`continuation_needs_attention`) records the `*` sentinel and suppresses every
event. Legacy rows written before event scoping (empty key) recover their
blocked event from the most recent settled `needs_attention` reservation.
Authorization revocation and terminal task/conversation state continue to block
independently of this field. The backend logs the block reason, the re-arm
decision, and the new event key; no second continuation engine or worker SQL
mutation is introduced.

## Migration / rollback

无数据迁移。回退时移除数据就绪事件源或关闭 `BYQ_F6_EXECUTOR_ENABLED` 即恢复“下一回合投递”；
既有 `continuation_permission` 与预算预留不受影响。
