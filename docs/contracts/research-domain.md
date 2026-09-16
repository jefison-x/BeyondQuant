# Research Domain Contract — Phase 9

## 目的

定义 BYQ 拥有的 durable research lineage contract。这些 entities 是 Quant Domain Plane 的 business state，而非 DSH session state。

## Entities

### Post-U8 generic lineage boundary

Generic Artifact creation validates `research_task`, `experiment` and `artifact`
lineage references against trusted owner/workspace inside the receipt transaction.
`stock_pool_snapshot` references must resolve to owned, active frozen snapshots;
each distinct snapshot is registered atomically with the Artifact. The reference
identity is the Artifact ID plus a SHA-256 of the snapshot ID, supporting multiple
pools without overwriting earlier references. No additional reference grants execution.
Other provenance labels are descriptive, not verified domain authority. A missing
or foreign reference returns 404; an unavailable pool returns 409. A registration
failure rolls back the Artifact and all references. Same-key creation is serialized
and returns the original immutable receipt; historical records are not rewritten.

### ResearchTask

Post-U8 F4：通用任务创建入口从 trusted runtime context 查找精确 Product conversation，
在同一数据库事务内核对 owner/workspace/session/trace 和 active 状态并保存 `conversation_id`。
Product Agent 缺失目录时拒绝创建；模型 payload 不能指定 conversation_id。原幂等键不允许
跨会话重绑，历史无绑定任务保持 null，不按 trace/最新对象补绑。非会话领域生产器仍可创建
无绑定任务；本切片不自动授予后台续接，也不代表所有专用生产器已接通会话关联。
Agent ML 通知必须在 SQL 分页前按该关联核对会话、trace、owner/workspace 和 active 目录；
其他会话及无绑定历史训练不进入当前会话 inbox。普通领域查询不因此失去既有授权访问。

Post-U8 task checkpoints use the existing transition endpoint, with optional
`progress` on ResearchTask only: schema `research-progress.v1`, a closed `stage`,
`next_action`, optional `blocked_reason`, up to 16 exact `linked_objects` (Artifact
or Experiment), and up to 16 Artifact IDs in `completion_evidence`. References
must belong to the task and its owner/workspace; no latest-object fallback.
Stages are planning, data_preparation, research, strategy, approval, training,
prediction, backtest, comparison, blocked and completed. Progress is a durable
domain checkpoint, not an execution plan or permission grant. Job identities
remain discoverable through their exact typed Artifact lineage, not guessed.
Same-key retries return the original checkpoint; changed checkpoints need a new
key. Terminal tasks cannot acquire a new checkpoint. Generic API completion
requires a completed checkpoint, no next action/blocker, and validated same-task
result/report evidence. This checks persisted evidence, not the semantic quality
of an investment conclusion. A model-turn terminal event never completes a task.
Historical tasks are not rewritten or resumed. Automatic checkpoint updates and
authorized background continuation require their separate acceptance evidence.

`ResearchTask` 是 root research intent：

```text
task_id, owner_principal, title, objective, status,
trace_id, created_at, updated_at, version
```

创建时为 `planned`。允许按 ADR-0006 转换为 `running`、`completed`、`failed` 和 `cancelled`。

### Experiment

`Experiment` 只属于一个 ResearchTask：

```text
experiment_id, task_id, owner_principal, name, status,
input_snapshot, created_at, updated_at, version
```

`input_snapshot` 是有界 JSON object。其 `sources` list 必须含至少具有 `provider`、`endpoint` 和 `request_fingerprint` 的 references，保留 Phase 8 data-provider provenance，以复现 experiment input。

### Artifact

`Artifact` 是可审计 domain data，绝非 application source：

```text
artifact_id, task_id, experiment_id?, owner_principal, kind, status,
content, content_sha256, lineage, trace_id,
created_at, updated_at, version
```

`content` 是有界 JSON。`content_sha256` 由 BYQ 基于 canonical JSON 计算，caller 不能提供。`lineage` 包含 task、experiment、data snapshot 或 parent artifact 的 typed references。Artifact status 为 `draft`、`validated` 或 `superseded`；Phase 9 不增加 business approval。

## Mutation semantics

Post-U8 boundary correction (ADR-0062): every generic create/transition API
requires trusted owner/workspace context and checks the referenced entity before
writing. Missing identity is 401; another owner's entity is 404. Task ownership
is not inferred from a caller-supplied task ID alone.

Domain-produced Artifact kinds (rule/ML strategies and approvals, models,
features, regimes, predictions, signals, backtest/factor results and web research
evidence) cannot be created or transitioned through the generic Artifact API.
Use the existing typed validator, approval or trusted Worker producer. A generic
`validated` transition is not proof of approval, computation or research success.
Generic research notes/evidence remain available; internal trusted producers
retain their existing Store contracts. Historical rows are not rewritten.

Create/transition requests 需要 caller 提供 `idempotency_key`，按 entity 和 owner scoped。相同 key 与相同 canonical request 返回原结果，不创建第二 entity；相同 key 搭配不同 input 返回 conflict。

所有 strings 都有显式 length bounds，JSON payloads 有限且有界；MCP schema boundary 拒绝未知 fields。Backend 返回 domain validation errors，不暴露 SQL、filesystem paths 或 internal exceptions。

## MCP capabilities

Phase 9 MCP surface：

- `byq_research_task_create`
- `byq_research_get`
- `byq_research_transition`
- `byq_experiment_create`
- `byq_artifact_create`

MCP layer 将调用转换为 Backend domain endpoints，不暴露 SQLite、SQL、raw database records 或 DSH event schemas。

## 所有权与安全

Backend 负责 identity、validation、state、idempotency、provenance、lineage 和 persistence。当前 trusted MCP service boundary 携带 immutable `owner_principal` metadata；未来 multi-user authorization policy 必须增加 ADR，不得把 agent-provided string 当作新 auth system。Product DSH 无直接 persistence 或 application-source access。


## H2：研究任务交接投影（2026-09-13）

`GET /api/product/research/tasks/{task_id}/handoff` 返回 `research-task-handoff.v1`。
Backend 对应只读路由为 `/v1/research/tasks/{task_id}/handoff`；现有任务详情同时添加
`handoff`，使 MCP 的原任务读取无需新工具即可取得同一投影。普通浏览器仍仅访问 Product API。

闭合字段为 `schema_version, task_id, task_version, task_status, objective, progress,
state, reason, references, has_more, observed_at`。`progress` 复用持久检查点，未记录时为 `{}`；
`references` 元素仅含 `kind/id/status`。原目标、检查点和依据继续保存在现有领域表中，
GET 在只读 repeatable-read 事务中取一致快照，不另存可能过期的“正在运行”缓存。
`observed_at` 是本次核对时间，不是活动续租时间；`task_version` 不是跨表事件版本。

`state` 枚举：`completed, failed, cancelled, waiting_approval, waiting_job,
conversation_active, continuation_queued, approval_continuation_queued,
needs_permission, needs_reconciliation, blocked`。状态不改变原 ResearchTask lifecycle，
不产生许可、额度、事件或模型调用。完成需要现有终态及可核对的完成检查点/制品；
历史无证据 completed 保留原记录，但交接提示需核对。

只关联同 task/owner/workspace 的 Artifact、训练、预测、信号及回测作业，以及绑定这些对象且
同 trace 的审批；不选最新任务或工作区对象。每类读取上限64，超出后标记 `has_more` 并要求核对，
不能据截断结果断言没有执行者。其他未纳入的领域执行路径不能据此推断完成或取消。
身份必须是有效 owner/workspace；外部对象与私有续接 instruction、预算账本不输出。

终态优先于迟到活动；未知提交先核对；pending 审批与已排队审批续接不同；
非终态作业只表示已有作业等待结果，不保证 Worker 当前持有有效租约。
原会话 active 只能表示会话活动，不能归属为某个任务的执行证明。
后台 queued 需要未结算 reserved 投递、未过期且未撤销的许可、未耗尽投递尝试及启用的执行器。
仅有许可、已 submitted 回执或一句“下一步继续”都不足以显示后台执行中。
无匹配执行事实时提示缺许可或阻塞；正常用户仍可在原对话手动继续。
此视图不包含 H3 的自动调度连接，不自动修复历史任务，也不判断研究结论质量。

## H3：有限交接触发接入既有 F6（2026-09-13）

按 ADR-0062 §4 的原任务恢复权限与 ADR-0065/0072 的预算、期限规则实施。
新确认许可持久记录服务端私有 `handoff_version=1`；不接受客户端指定此字段，公开许可投影不输出它。
旧许可、原幂等重放、已预留账本不添加此标记、不改变额度或期限，仍使用原来的业务作业完成触发。

新标记允许两种有限触发：

1. 初次交接：原任务有持久 next_action、无显式阻塞、检查点引用至少一个已确认制品，且尚无续接账本时，
   在条件满足后恢复一次原目标。许可确认记录是固定事件身份，不以空闲时长或聊天文本产生重复回合。
2. 审批动作交接：上一次续接预留之后新提交的、同 task/owner/workspace 且绑定已确认策略版本的
   `strategy_approval`/`ml_strategy_approval`，必须 validated、decision=approved、execution_authorized=true。
   较新的已验证决定覆盖旧决定；批准按钮、submitted 回执或模型文字不是领域动作完成证据。

原有四类终态作业事件优先，原事件幂等键保持不变。新增事件用 `handoff-v1:` 前缀区分，
沿既有 task lock、单一预算账本、Gateway consumer、Runtime qualification/准入及 MCP scope 执行。
后续审批仅选择晚于既有任务回合预留的事实，已有回合已经有机会回读的旧审批不另起一次交接。
模型回合结束且没有新业务事实不会制造下一回合，也不会完成 ResearchTask。

预留前及发送前检查原会话无 active 回合、原任务无非终态作业/待审批或未确认审批投递；
批准的策略请求还必须有其确切领域审批制品。已登记但未核对的研究创建、ML训练回执会阻止新交接。
明确阻塞的检查点不由调度器擅自清除。等待这些前置条件时，不增加发送尝试或模型回执核对次数。
已发送的 unknown/accepted 仍走原有限回执核对，不能重投、自动返还额度或扩大权限。

新入口不扩展后台工具目录：审批、训练创建等现有禁止项继续受限，后续动作仍按当前角色、
MCP、领域审批和任务范围判定。H3 不等于任意机器学习流水线或三轮研究已通过验收；完整链条属 H5。
不新增 Harness、通用队列、DSH 接口、业务数据库迁移或生产任务续跑。
