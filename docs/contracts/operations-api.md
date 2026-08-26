# Phase 38 Operations Projection Contract

Status: Accepted ADR-0022 下的 **Implemented contract**。

## 边界

所有 browser operations requests 使用 Gateway 的 `/api/product/operations/*`，并要求 durable BYQ administrator session。Gateway 读取有界 Backend aggregates 和 Runtime Adapter 的 normalized process-local metrics。Browser 永不直接调用 Backend、Runtime Adapter、DSH、MCP、PostgreSQL、Redis 或 provider。

Contract 不得包含 database connection strings、environment values、credential envelopes、plaintext secrets、任意 URLs、raw SQL、process control commands、raw DSH notifications、hidden reasoning、prompts、tool arguments 或 tool results。

## `GET /api/product/operations/status`

返回 `schema_version = "operations.v1"`，包含以下有界 sections：

- `services`：Gateway、Backend 和 Runtime Adapter readiness labels；
- `database`：PostgreSQL identity/version/size、aggregate table/row estimates 和封闭 BYQ domain resource counts；不含 physical table names、host、port、role、password 或 connection string；
- `cache`：按 source/asset type 分组的 canonical `market_daily_bars` coverage，最多 50 groups；显式 `redis = "not_used"`；
- `sources`：仅 Tushare credential metadata/readiness；Phase 39 负责 CRUD、connection tests 和 sync jobs；
- `models`：model credential status groups、profile/binding counts 和显式 no-secret projection；
- `agents`：status groups 和最多 30 条最近 BYQ AgentRun identities；
- `graphs`：同一组 BYQ-owned AgentRun/WorkflowTrace correlations，绝不包含 DSH graph/checkpoint/event objects；
- `access`：durable user role/status counts、最多 30 条 Agent audit events 和 30 条 operations audit events；
- `budget`：当前 versioned monitoring-threshold policy；
- `runtime`：normalized current-process session counts 和 DSH token usage；
- `observability`：normalized WorkflowTrace 和 append-only audit declarations。

Runtime Adapter failure 表示为 `runtime.status = "unavailable"`、zero usage 和 `source = "unavailable"`。Backend projection failure 必须 fail closed，否则 authorization、durable audit 和 storage facts 无法验证。

## Runtime usage normalization

Runtime Adapter 只识别已记录的 DSH `assistant/message.usage` 结构，并映射以下非负整数：

| DSH field | BYQ field |
|---|---|
| `inputTokens` | `input_tokens` |
| `outputTokens` | `output_tokens` |
| `cacheReadTokens` | `cache_read_tokens` |
| `cacheWriteTokens` | `cache_write_tokens` |
| `reasoningTokens` | `reasoning_tokens` |

Counts 按 message ID 去重；无效或越界 usage 原子丢弃。`total_tokens` 是 uncached input、output、cache read 和 cache write 之和；reasoning 是 diagnostic subset，不重复加入。初始 scope 明确为 `adapter_process_lifetime`：adapter 重启时重置，不作为 durable billing evidence。Raw notifications/provider-specific objects 被丢弃；internal projection 报告 `raw_dsh_events = false`。

## `PUT /api/product/operations/budget`

此 endpoint 只更新 alerting/observation thresholds，不取消 DSH work、不改 model configuration、不施加 provider billing limits，也不授予 runtime authority。精确 request fields 为：

- `enabled`：boolean；
- `alert_total_tokens`：integer 1,000–100,000,000；
- `alert_requests`：integer 1–1,000,000；
- `expected_version`：正数 current policy version；
- `idempotency_key`：1–128 个安全字符。

拒绝未知 fields。Stale version 或冲突 idempotency replay 返回 conflict。成功 update 递增 version，并追加不含 secret 的 `budget.threshold.updated` operations audit；相同 retry 返回已记录 response。

## Authorization 与 errors

- Gateway 在请求 Backend/Runtime projections 前验证 durable user role。
- Backend 对 overview 和 writes 独立要求 `x-byq-actor-role: admin`；writes 记录 actor principal。
- Product errors 使用现有 BYQ error envelope。
- API 不提供任意 query、shell、migration、backup/restore、restart、cache rebuild、credential read 或 deployment control endpoint。
