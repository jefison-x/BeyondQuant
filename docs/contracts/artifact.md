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
