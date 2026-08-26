# ADR-0018：Structured WorkflowTrace Card 与 Normalization Boundary

- Status: Accepted
- Date: 2026-08-22
- Decision scope: Phase 36 Agent workbench projection 与 interaction boundary
- Related: ADR-0003、ADR-0009、ADR-0012、ADR-0014
- Contract: `docs/contracts/workflow-trace-cards.md`

## 背景

Community Agent workbench 会在 conversation 附近呈现 Strategy draft、stock candidate、
optimization plan、Backtest context、Approval state、progress step 和 page-aware assistant
affordance。这些 surface 是有用的 Product evidence，但 Community message object、Agent
API、Approval runtime 和 event schema 不是兼容的 BYQ integration boundary。

当时 Runtime Adapter normalization 将 DSH notification 压缩为小型
`WorkflowTraceEvent` envelope。Public assistant message 只保留 byte count，unknown event
变为 `session.progress`，且没有有界 card schema。透传更多 DSH object 会让 frontend
耦合 rc.6 wire type，并可能让 model-produced field 冒充 BYQ Artifact、Approval、
execution outcome 或 authorized action。

因此 Phase 36 同时需要 structured presentation Contract 和严格 normalization/authority
boundary。Contract 必须保持 ordered replay、owner isolation、Approval semantics、payload
bound 和 DSH replaceability。

## 决策

### 1. 保留 WorkflowTrace envelope

Structured card 仍是普通 append-only `WorkflowTraceEvent` record：

```text
trace_id, session_id, sequence, timestamp, kind, source, payload
```

Envelope、contiguous sequence allocation、SSE replay 和 identical-retry rule 继续具有
权威性。不引入第二个 event bus 或 frontend DSH client。只有 Gateway 用 owner-scoped
Domain projection 替换 candidate field 后，`source` 才可额外取 `byq-domain`。

### 2. 采用五种 versioned card kind

初始 kind：

- `agent.card.strategy_draft`
- `agent.card.stock_candidates`
- `agent.card.optimization`
- `agent.card.backtest_context`
- `agent.card.approval`

每张 card 使用 `schema_version = "workflow-card.v1"`、BYQ 分配的稳定 `card_id`、正数
`revision`、`authority`（`proposal` 或 `domain`），以及该 kind 的准确 allow-listed
payload。Unknown field 被拒绝，不予保留。规范 shape、enum、identifier rule 和 size
limit 定义于 `docs/contracts/workflow-trace-cards.md`。

Card 是 immutable snapshot。后续 state 使用相同 `card_id` 和更大 revision 产生新的
trace event。Frontend 可 fold 到 latest revision 显示，replay 则保留完整 ordered
history。Conflict 或 decreasing revision 被拒绝。

### 3. 分离 proposal data 与 Domain authority

Runtime Adapter 是唯一可以 inspect DSH notification 的组件。它通过准确 field allowlist
提取 card candidate、分配有界 BYQ identity，并丢弃 raw notification、tool call internal、
unknown key、arbitrary link 和 executable request data。

DSH/model content 只能产生 `authority = "proposal"`，不能断言 Artifact 已 validated、
Approval pending/approved、Backtest completed、operation executed 或 owner 有权限。
`artifact_id`、`job_id`、`pool_id`、`approval_id` 等 candidate reference 在 resolve 前均不
可信。

Gateway 持有第二 projection step。任何声称 Domain state 的 card，以及所有
`backtest_context`/`approval` card，都必须使用 authenticated session principal 通过
owner-scoped BYQ Domain/Product boundary 重新读取。Gateway 用该 projection 替换 display
field，并发出 `authority = "domain"`、`source = "byq-domain"`。Missing、cross-owner、
stale、malformed 或 forbidden reference 在相同 sequence 降级为有界
`session.progress`；raw rejection detail 不进入 browser。

Principal、bearer/session token、MCP header、provider credential 和 DSH authorization
data 绝不出现在 card 中。

### 4. Card 不是 command

Card 不含 URL、HTTP method、header、arbitrary route、tool name、tool argument 或
mutation body。它不能 grant Approval，也不能把 Approval 表示为 execution success。

Frontend 将 validated card kind 映射到固定 BYQ-owned interaction。Consequential action
前必须获取 latest owner-scoped resource，再使用现有 Product API、validation、
idempotency、optimistic concurrency 和 Approval Contract。Proposal-card action 可打开
draft/request flow，但绝不直接修改 business state。Approval decision 始终针对当前 BYQ
Approval resource，且 execution outcome 保持独立。

### 5. 规范化 public answer/activity，不暴露 hidden reasoning

Phase 36 还升级 workbench 所需的两种 non-card projection：

- `agent.output.delta` 只承载有界、ordered fragment 形式的 public assistant answer text；
  Adapter 对 cumulative DSH message update 去重。
- `agent.activity` 为 progress visualization 承载 curated public phase、state、label 和
  optional BYQ capability name。

Hidden chain-of-thought、system/developer prompt、model provider object、token-level
reasoning、tool argument、raw tool result、stack trace 和 DSH message object 均不 projection。
因此 Community `AgentThinking` 被分类为 public operational progress UX，而不是暴露
model reasoning 的许可。

### 6. 强制 bound 并 fail closed

所有 payload 必须是 finite JSON，并在 persistence 前通过准确 schema。初始限制包括：
serialized event payload 64 KiB、answer fragment 8 KiB、50 个 stock candidate、20 个
optimization change、有界 string/metric key、每 turn 最多 32 张 card 和 256 个 activity
event，且禁止 credential-shaped field。Oversized public text 在安全时拆分；超量
structured activity 合并为有界 progress/truncation event。Invalid card 安全降级，绝不
fallback 到 raw passthrough。

Gateway 只 persistence/stream validated BYQ envelope。Frontend type 是 discriminated
BYQ union，不 import DSH SDK/wire type。

### 7. Phase ownership

Phase 36 持有其 exit criteria 所需的 Agent-specific card renderer、等价于
`AgentThinking` 的 public activity component、Approval presentation 和 assistant drawer。
Phase 40 可在后续 extract/generalize 已验证 component，但不是 Phase 36 prerequisite；
这消除了此前 circular roadmap dependency。

## 后果

- 无需信任 Community 或 DSH schema，即可实现 Community-level structured interaction。
- Runtime Adapter 增加 curated candidate extractor；Gateway 增加 schema validation、
  owner-scoped hydration、revision check 和 fail-closed degradation。
- 即使 model 发出 stale/invented identifier，Domain-backed status 仍保持权威。
- Workbench 可呈现 public progress，而不暴露 hidden reasoning。
- DSH upgrade 被隔离到 Adapter extractor 及 compatibility test；card consumer 跨 runtime
  change 保持稳定。
- 更丰富 field 或新 kind 需要 review 后更新 Contract/ADR；禁止 raw JSON escape hatch。

## Phase 36 必需证据

- 每种 accepted/rejected card shape、bound、finite metric、revision rule 和 unknown-field
  rejection 的 contract test；
- 证明 raw notification/tool/reasoning field 被丢弃的 Adapter test；
- owner-scoped hydration、cross-owner failure、stale/missing reference、安全降级、
  ordered replay 和 no-authority-promotion 的 Gateway test；
- discriminated rendering、revision folding、固定 Product action、public activity、
  reconnect replay、empty/error/truncated state 的 frontend test；
- secret-boundary test 和带 Chrome MCP network/console evidence 的真实 Product API
  browser journey；
- code work 前完成 Community feature checklist 和 migration classification。

## 拒绝的替代方案

- 向 frontend 透传 raw DSH payload 或 Community message object：违反 ADR-0003 和
  `ARCHITECTURE.md` section G。
- 允许 DSH 发出 authoritative Approval/Artifact/Backtest state：越过 Agent/Domain
  authority boundary 和 owner isolation。
- 在 card 放 executable action：形成 model-controlled Product API 和 Approval bypass。
- 将 hidden chain-of-thought 渲染为“thinking”：暴露 runtime internal，并建立不稳定、
  不安全的 Product Contract。
- 从 plain text 渲染全部 structure：失去 deterministic validation、accessibility 和可操作
  domain reference。
- 创建第二个 event bus：重复 WorkflowTrace ordering 和 replay。
- 让 Phase 36 阻塞于 Phase 40：造成 circular dependency；必须先由 Phase 36 验证专用
  component，再在后续 generalize。

## 回滚

禁用五种 card renderer 和 candidate/hydration projector。现有 card event 保持有效的
append-only evidence，可显示为 generic trace item；无需迁移 business data 或 DSH
session。Public answer/activity event 可 fallback 到现有 coarse progress view，但不能暴露
raw payload。
