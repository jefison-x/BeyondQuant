# Product API / BFF Contract — Phase 16

## 所有权

Gateway 负责 browser-facing Product API。它暴露 normalized BYQ resource projections，不暴露 MCP、DSH、raw DSH events、Backend storage internals、provider credentials 或 bearer tokens。

## Authentication 与 session

普通 browser login 通过 `/api/auth/login` 使用 username/password，以及 durable Gateway `byq_session` HttpOnly cookie（`SameSite=Lax`、`Path=/`）。Gateway 将不透明的 Backend-owned session 解析为 owner/actor principal，只转发 trusted BYQ context headers。Legacy `Authorization: Bearer` product token 仅用于 internal/bootstrap compatibility；不是普通 browser identity，且永不转发给 Backend、MCP、Runtime Adapter 或 WorkflowTrace payloads。

## Error envelope

每个非成功 Product response 使用：

```json
{"error": {"code": "...", "message": "...", "request_id": "..."}}
```

Messages 安全且有界；不返回 internal exception text 或 storage paths。

## Bounded list policy

已实现 list routes 返回 resource-specific arrays，例如 `tasks`、`artifacts`、`backtests`、`pools` 和 `accounts`。Backend queries 施加各自 domain bounds，并在定义处使用稳定排序。不存在通用 pagination envelope。Stock Pool、Backtest、ML study 和 Product Feedback catalog/history routes 实现有界 `limit`/`offset`，并返回 `total`、`limit`、`offset` 和适用时的 `has_more`；其他 routes 在实现并测试前不得宣称支持 pagination。

## Resource projections

版本化 OpenAPI source 为 [`product-api.openapi.yaml`](product-api.openapi.yaml)。Architecture tests 要求其 browser route/method set 与已实现 Gateway surface 匹配。映射范围包括：

- Dashboard
- Agent sessions 和 WorkflowTrace
- ResearchTask / Experiment / Artifact
- Factor
- Strategy / StrategyVersion / Approval
- Backtest
- Stock Pool catalog、immutable snapshots、typed provenance、references 和 lifecycle
- Approval Inbox / Audit
- Data status / migration status
- Product Feedback owner catalog/detail/revisions/preview/submit，以及只读取脱敏 submitted snapshot 的 admin
  moderation inbox；publisher status 仅投影 fixed repository、credential kind、heartbeat/error category 和有界 queue
  counts。Gateway 不接收 GitHub credential，也不执行 Issue 发布

后续 productization phases 已实现所映射的 resource behavior。新增或移除 browser routes 必须在同一 change 更新 OpenAPI source。
