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
