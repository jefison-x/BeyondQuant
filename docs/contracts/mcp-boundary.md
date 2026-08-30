# BeyondQuant MCP Boundary Contract

## 目的

定义 Agent Plane 与 Quant Domain Plane 之间稳定的 capability boundary。

## Ownership

BYQ 持有通过 BeyondQuant MCP 暴露的 domain capability、invariant、authorization、
validation 和 business idempotency。DSH 持有通用 MCP client infrastructure。

## Phase 8 data capability

`byq_market_daily` tool 是 Phase 8 daily market-data Contract 的 Agent-to-Domain
入口。它接受 [data-provider Contract](data-provider.md) 中描述的 normalized request
field，并返回 BYQ daily bar 和 provenance metadata。

MCP service 可以调用 Backend Domain/Data endpoint 来完成该能力。它不得接收或转发
`TUSHARE_TOKEN`，也不得透传任意 Tushare endpoint name、raw parameter 或 raw
provider response envelope。

## Phase 59 point-in-time market research capability

`byq_market_valuation` 和 `byq_market_fundamentals` 只读取 BYQ Data Plane 已持久化的
ADR-0030 数据。前者要求 exact trade date，后者要求 point-in-time as-of date 并遵守公告
后次日可见。二者只接受最多 20 个 canonical A-share symbols 和封闭字段集合，返回
row/content hash、dataset completeness、missing symbol/report 和 `coverage.usable`。

MCP 不得调用 Tushare、执行 latest fallback、填充 null、透传 Backend detail，
或接收任意 Provider endpoint/field。不可用 coverage 是正常结构化结果，不是授权 Agent
臆测数据或换来源绕过的理由。

## Phase 80 data-demand capability

`byq_data_demand_create/get` 是小巴向可信数据中心表达按需准备意图的 Agent-to-Domain
入口。create 只接受管理员工作区、不可变股票池快照、最长五年日期范围、封闭用途和
BYQ 已支持的声明数据字段；Backend 将范围拆成有界 `market-data-requirement.v3`，复用
既有 repair/session job。MCP 本身仍不得调用 Tushare、读取凭据、写数据或控制 Worker。

`byq_agent_context` 可附带同一 owner/session 的终态通知；`ready` 必须来自当前 readiness
验证，不能由 repair enqueue/expand/completed 状态推断。Backend 不主动向 DSH 注入 prompt，
小巴只在下一次或恢复的用户 turn 消费通知并继续研究。

## Phase 9 research capability

Phase 9 tool `byq_research_task_create`、`byq_research_get`、
`byq_research_transition`、`byq_experiment_create` 和 `byq_artifact_create` 是持久化
research state 的 Agent-to-Domain 入口。Backend 持有 validation、state transition、
idempotency、provenance、lineage 和 persistence。MCP 只转发 normalized domain field，
并返回 normalized domain record。

MCP 不得暴露 SQL、SQLite path、database row、DSH WorkflowTrace schema 或 Backend
implementation exception。DSH 可以通过 MCP 请求 domain operation，但不能直接访问
Backend database 或 filesystem 来修改 research state。

## Phase 13 Agent capability

`byq_agent_*` tool 暴露 BYQ 自有的 role catalogue、trusted runtime context、
owner-scoped Agent run、action authorization、有界 audit view 和 Human Approval state。
MCP 从 authenticated Runtime Adapter path 派生 owner/actor/session/trace header；
model 提供的 identity field 不能覆盖它们。DSH 可以通过 native subagent seam delegate，
但不能用 prompt 或 direct storage call 绕过 BYQ authorization 或 approval。

## Phase 14 learning capability

`byq_learning_*`、`byq_evaluation_signal_*`、`byq_experiment_compare` 和
`byq_lesson_*` tool 暴露有界 learning run、ordered iteration history、确定性
evaluation-signal comparison 和 evidence-backed lesson promotion。Backend 持有 budget、
stopping rule、idempotency、validation、human review 和 promotion history。MCP 只转发
normalized domain field，且绝不暴露 SQLite path、raw row、DSH event schema、provider
credential 或 Backend implementation exception。

## Phase 34 Stock Pool capability

`byq_pool_list`、`byq_pool_get`、`byq_pool_create`、`byq_pool_snapshot_replace`、
`byq_pool_history` 和 `byq_pool_lifecycle` tool 暴露有界、owner-scoped Stock Pool
operation。MCP 派生 trusted owner/actor/run context，只创建 custom pool，不能提交
authoritative snapshot identity 或 provider provenance。Backend 计算 fingerprint、验证
准确 weight 和 optimistic concurrency、持久化 append-only snapshot，并持有 lifecycle
transition。DSH 绝不通过这些 tool 读取 PostgreSQL、Tushare 或 raw Backend schema。

## 非目标

- 本文档不定义完整 tool schema。
- 不允许 DSH 直接访问 BYQ PostgreSQL、Redis business state 或 Backend internal。
- 不定义第二套通用 Agent Harness。

## 稳定性保证

Agent-to-Domain call MUST 使用本边界。只要 domain Contract 保持兼容，storage 和
Backend implementation 的变化 SHOULD 对 DSH client 不可见。
