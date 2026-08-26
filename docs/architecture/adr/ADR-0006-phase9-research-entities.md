# ADR-0006：Phase 9 Research Entity 与 Backend Persistence

- Status: Accepted
- Date: 2026-08-15
- Decision scope: Phase 9 Quant Domain research entities
- Supersedes: ResearchTask、Experiment 和 Artifact Contract placeholder

## 背景

Phase 9 需要用于 Agent-assisted research 的持久化 BYQ business entity。当时仓库还没有
PostgreSQL service，而架构已经规定 business state 属于 Backend/Domain Plane，且 DSH
不得访问。因此本 Phase 必须建立小型持久化实现，但不能让 storage detail 成为 MCP
Contract 的一部分。

这些 entity 还需要明确的 state transition、idempotency 和 lineage。DSH WorkflowTrace
可以标识发起 run，但不得持有 ResearchTask、Experiment 或 Artifact state machine。

## 决策

1. BYQ 持有 framework-neutral 的 `ResearchTask`、`Experiment` 和 `Artifact` Contract。
   identifier、state transition、idempotency behavior、provenance 和 lineage 由 Backend
   domain code 强制执行。
2. Phase 9 通过 Python standard library 使用 SQLite 作为 Backend durable repository。
   database path 由 `BYQ_DOMAIN_DB_PATH` 配置，在 Compose 中默认为
   `/var/lib/byq/domain/byq.sqlite3`；该路径只通过 named volume `byq_domain_state`
   mount 到 Backend。
3. repository 位于 Backend-owned interface 后。未来 PostgreSQL 实现可以替换 SQLite，
   而不改变 domain 或 MCP Contract。Phase 9 不宣称 horizontal-write scalability，也不
   执行 destructive migration。
4. 每个 create 和 transition mutation 都要求 idempotency key。使用同一 key 和相同
   canonical request 重试时返回原结果；以不同 input 重用则产生 conflict。state
   transition 使用 allowlist，不能被 prompt 或 storage write 绕过。
5. `ResearchTask` 是 root entity。`Experiment` 属于一个 task，并记录有界 input
   snapshot；每个 input source 必须保留 BYQ data provenance reference。`Artifact` 属于
   task，也可以属于 experiment；它保存有界 JSON content、lineage reference 和确定性
   content SHA-256。
6. Backend 在内部暴露 domain endpoint。BeyondQuant MCP 只暴露 normalized domain
   operation：create/get research entity 和执行经过验证的 transition。MCP 不暴露 SQL、
   database path、raw row 或 DSH WorkflowTrace schema。
7. Phase 9 不实现 Business Approval。Artifact 只能通过 BYQ transition Contract 标记为
   `validated`；approval policy 和 consequential-action gate 留待后续领域决策。

## State machine

```text
ResearchTask: planned → running → completed
                         ├→ failed
                         └→ cancelled
              planned ─────────→ cancelled

Experiment:   planned → running → completed
                         ├→ failed
                         └→ cancelled
              planned ─────────→ cancelled

Artifact:     draft → validated → superseded
                 └─────────────→ superseded
```

只有 transition key 与 request 相符时，重复 transition 到 entity 当前 state 才是
idempotent。其他 backward transition 或 terminal-state transition 均不接受。

## 后果

- 无密钥 test 可以使用临时 SQLite file 验证 persistence、restart recovery、
  idempotency 和 lineage。
- Backend 持有全部 business state，DSH 继续只能通过 BeyondQuant MCP 访问。
- SQLite 有意作为 single-Backend 实现；multi-instance deployment、PostgreSQL migration、
  retention 和 approval policy 需要后续 ADR。
- 有界 JSON content 和 input snapshot 防止 Agent call 形成无界 storage/cost surface。

## 拒绝的替代方案

- In-memory dictionary 无法满足 Phase 9 的 durable persistence 和 restart recovery。
- DSH 直接访问 SQLite 或 PostgreSQL 会违反 MCP 和 data ownership 边界。
- 在 domain Contract 之前增加 PostgreSQL 会扩大 topology 和 migration 范围，却不能
  改善 Phase 9 acceptance evidence。
- 将 DSH WorkflowTrace 视为 business state 会混淆 Agent Plane 与 Domain Plane
  lifecycle。

## 停止条件

如果 SQLite 无法提供所需 durability evidence、domain Contract 要求 multi-writer
semantics、provenance 无法保留，或 authorization/approval requirement 无法在没有新 ADR
的情况下表示，Phase 9 必须停止，不能扩大范围。
