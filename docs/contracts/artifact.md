# Artifact Contract — Phase 9

## 目的

定义可审计 research artifacts（包括 evidence 和 experiment outputs）的所有权与 lifecycle 预期。完整 Phase 9 request/response contract 见 [research-domain.md](research-domain.md)。

## 所有权

BYQ 负责 artifact identity、provenance、validation、authorization、lifecycle 和 retention semantics。

## Phase 9 contract

Artifact 属于一个 ResearchTask，也可属于一个 Experiment。它具有有界 JSON `content`、由 BYQ 计算的 canonical `content_sha256`、带类型的 `lineage` references、一个 WorkflowTrace `trace_id`，并处于以下状态之一：

```text
draft → validated → superseded
  └─────────────→ superseded
```

创建和转换需要 idempotency keys。重复且匹配的请求是安全重试；同一 key 搭配不同 input 会被拒绝。

## 非目标

- 不把生成的 strategy code 视为 application source code。
- 不授予 Product DSH 直接 persistence access。
- 不定义 business approval policy；validation 是 domain state，而非 approval grant。

## 稳定性保证

Artifact consumers 应依赖 BYQ artifact contracts 和 provenance，而不是 DSH session internals 或 storage details。

## Web Research Evidence（Phase 64）

`web_research_evidence` 使用 `web-research-evidence.v1`，是现有 Artifact 的严格 content kind，
不是新数据库。它保存 research as-of、BYQ market cutoff context、有界 search queries、来源
URL/title/publisher/tier/published/retrieved time、typed claims、conflicts/limitations 和固定
research-only usage policy。

DSH Web result 在调用 `byq_web_evidence_create` 前只是 session context。晋升必须经过 trusted
owner/workspace、authorization、MCP、Backend validation、idempotency、hash、lineage 和 audit。
保存命令提交来源数组与 claim 的零基 `source_indexes`；`source_id` 由 Backend 根据已校验 URL
稳定生成，不属于模型或 Browser Contract。新建网页研究记录时，ResearchTask 与 Artifact 在同一
PostgreSQL transaction 中创建；验证或持久化任一步失败都会整体回滚，不留下孤立 task。
Artifact validation 不把网页内容升级为权威市场数据；其 `deterministic_input` 和
`authoritative_market_data` 永远为 false。Factor、Strategy、signal 与 Backtest consumers 必须
继续只接收 BYQ Data Plane 已规范化、PIT 校验并冻结的输入。
