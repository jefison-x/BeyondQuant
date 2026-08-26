# WorkflowTrace structured projection contract

本 contract 对 ADR-0018 和 Phase 36 具有规范性。它定义 BYQ-owned browser projections，而非 DSH notifications、Community message objects 或 Domain mutation requests。

## Envelope 与 sources

Cards 使用现有 `WorkflowTraceEvent` envelope。`source` 接受 `dsh`、`runtime-adapter`，并增加用于 Gateway-hydrated、owner-scoped Domain projection 的 `byq-domain`。`byq-domain` event 不得含只来自 model output 的 field。

每个 serialized payload 是有限 JSON，最多 65,536 bytes。Gateway persistence/streaming 前执行精确 schema validation；拒绝 unknown fields、NaN/infinity、任意 URLs、HTTP request descriptors、credentials、raw runtime objects 和 tool arguments/results。

## Common card fields

每个 `agent.card.*` payload 包含：

| Field | Rule |
| --- | --- |
| `schema_version` | 精确字符串 `workflow-card.v1`。 |
| `card_id` | BYQ 分配；`card_` 加 32–64 个小写 hex；绝不从 model content 接受。 |
| `revision` | Integer 1–2,147,483,647；同一 card 严格单调递增。 |
| `authority` | `proposal` 或 `domain`；只有 Gateway hydration 可产生 `domain`。 |
| `title` | trim 后 1–160 Unicode characters。 |
| `summary` | 可选，最多 2,000 characters。 |
| `truncated` | Boolean；允许的 display field 被安全截短时为 true。 |

Proposal IDs 从 `(trace_id, sequence, kind)` 导出；Domain-backed card ID 从 `(trace_id, kind, canonical_resource_id)` 导出。Clients 使用 `card_id + revision` 作为 render identity，不使用 array position。

Card 不携带 executable action data。Frontend actions 是 BYQ source 中固定 mappings，并重新读取 current Product resource。

## Card schemas

### `agent.card.strategy_draft`

附加 fields：必需 `name`（1–160）和 `summary`；可选 canonical `artifact_id`、最长 128 的 `strategy_id`、`validation_status`（`unknown|draft|valid|invalid|superseded`）。排除 source code、scripts、credentials、validation evidence 和完整 artifact content；detail 经 owner-scoped Product API 获取。只有 hydrated Domain card 可声明 `unknown|draft` 之外的 status。

### `agent.card.stock_candidates`

`items` 为稳定顺序的 1–50 个唯一 items；每项精确包含 `symbol`、可选 `name`/`reason`。`symbol` 为 canonical `NNNNNN.SH|SZ|BJ`；`name` 最多 80、`reason` 最多 500。可选 `as_of` 为 `YYYYMMDD`，可选 `pool_id` 为 canonical BYQ Stock Pool reference。Proposal list 是 research guidance，不是 persisted pool；pool creation 使用 Product API lifecycle contract。

### `agent.card.optimization`

必需 `objective`（1–1,000）；`changes` 为 1–20 个精确 objects，含 `area`（1–80）、可选 `before`（0–500）、`after`（1–500）和 `reason`（1–500）；可选 `strategy_artifact_id`、`baseline_job_id`；可选 `metrics` 只允许有限数值 `total_return`、`max_drawdown`、`sharpe_ratio`、`volatility`、`win_rate`。除非全部 references 均 owner-resolved，否则是 proposal；绝不声称已保存 strategy 或执行 comparison backtest。

### `agent.card.backtest_context`

要求 `authority = domain`、`source = byq-domain`。附加 canonical `job_id`；`status` 为 `queued|running|completed|failed|cancelled`；可选有限 metrics 使用 optimization allow-list，并允许非负整数 `trade_count`/`blocked_trade_count`；可选 canonical `strategy_artifact_id`、`result_artifact_id`。所有值由 current owner-scoped Backtest projection 替换。

### `agent.card.approval`

要求 `authority = domain`、`source = byq-domain`。附加 canonical `approval_id`；最长 128 的 BYQ approval `action`；`status` 为 `pending|approved|rejected`；`execution_outcome` 为 `not_started|authorized|not_authorized`；可选 `risk_level` 为 `low|medium|high|critical`；可选 `decided_by_display` 最多 160。

Card 不含 decision endpoint/mutation arguments。Human decision 前 frontend 获取 current approval 并使用现有 Product Approval API。Approval status 与 `execution_outcome` 保持不同；`approved` 表示 authorized，不表示成功执行。扩展 outcomes 需要 reviewed contract update。

## Public answer 与 activity

`agent.output.delta` payload：

```json
{"schema_version":"workflow-answer.v1","channel":"answer","delta":"public assistant text","truncated":false}
```

每个 fragment 最多 8,192 UTF-8 bytes。Adapter 只发 public assistant answer blocks，并 deduplicate cumulative DSH updates。

`agent.activity` payload：

```json
{"schema_version":"workflow-activity.v1","activity_id":"activity_<hex>","phase":"strategy","state":"started","label":"校验策略草稿","capability":"byq_strategy_validate"}
```

`phase` 为 `understand|select|strategy|backtest|review|tool`；`state` 为 `started|progress|completed|failed|waiting_approval`；`label` 为 1–240 characters。可选 `capability` 是已知 BYQ MCP capability name，绝非 DSH tool identifier。不存在 reasoning、prompt、argument、raw result 或 stack-trace fields。

## Budgets、degradation 与 compatibility

一个 turn 最多 32 cards 和 256 activity events。超额 activity 合并为一个只含 semantic reason 和 `truncated: true` 的 `session.progress` event。Invalid/unauthorized cards 也在其 allocated sequence 转为有界 `session.progress`；projector 绝不 stringify/forward rejected input。

Gateway 保持连续 session sequence。Reconnect replay 相同 accepted snapshots，不重新 hydration。同一 trace 内 `card_id` revisions 严格递增；identical retry 仅按 existing identical-envelope rule 接受。

Optional additive fields 需要 reviewed v1 contract update。删除/重命名 field、改变 authority semantics、扩展 action capability 或接受新 card kind，需要新 schema version 和 ADR review。
