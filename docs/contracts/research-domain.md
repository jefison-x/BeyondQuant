# Research Domain Contract — Phase 9

## 目的

定义 BYQ 拥有的 durable research lineage contract。这些 entities 是 Quant Domain Plane 的 business state，而非 DSH session state。

## Entities

### ResearchTask

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
