# ADR-0032：Agent Point-in-Time 估值与基本面研究读取

- Status: Accepted
- Date: 2026-08-26
- Accepted: 2026-08-26
- Decision scope: Phase 59 Agent valuation/fundamental read path
- Related: ADR-0005、ADR-0009、ADR-0013、ADR-0024、ADR-0025、ADR-0030、ADR-0031

## 背景

Phase 57 已将 exact-session `daily_basic` 和 announcement-aware financial indicators
持久化为 BYQ PostgreSQL 权威数据，并可冻结进 strategy input。Phase 58 的真实 Agent
旅程仍只能读取价格；当用户要求“从估值和趋势两个角度比较”或比较 ROE、盈利增速时，
Agent 没有对应 MCP read capability，容易退化为只谈走势、要求外部数据或臆测指标。

只读 Community 审计证明，研究结果必须携带报告期、公告/可见日期、来源、缺失值和
coverage；固定候选的基本面读取与股票池写入也必须分离。Community 的多 Provider
在线 enrichment、进程缓存、线程、ORM、PydanticAI/Hermes、direct Backend API，及
BaoStock/AKShare 路径不兼容当前架构，不予迁移。

维护者于 2026-08-26 授权按顺序自动执行后续已知阶段。本 ADR 接受 Phase 59 的最小
只读数据边界，不授权 Phase 60 public projection 重构。

## 决策

### 1. 两个封闭的 MCP read capability

新增：

- `byq_market_valuation`：最多 20 个 canonical A-share symbol、一个精确交易日、最多
  12 个 ADR-0030 已接受的 daily-basic fields；
- `byq_market_fundamentals`：最多 20 个 canonical A-share symbol、一个 point-in-time
  research date、最多 12 个 ADR-0030 已接受的 financial-indicator fields。

两者只通过 MCP → Backend 读取已持久化 BYQ 数据，不调用 Provider、不持有凭证、不触发
同步、不接受任意 endpoint/field/SQL。Browser 仍只访问 Gateway/Product API。

### 2. 估值必须是 exact-session evidence

估值值只属于请求的交易日，不允许 latest fallback、前值填充或跨日比较替代。响应包含
请求日、字段、每个 symbol 的值、row hash，以及 exact-date dataset completeness。
`coverage.usable=true` 仅在存在完整性记录且所有请求 symbol 都有 row 时成立。缺失 symbol
和未验证 completeness 必须显式返回；Agent 不得在不可用结果上排名。

### 3. 基本面必须遵守公告后次日可见

Backend 对每个 symbol 只选择 `effective_date <= as_of_date` 的最新报告；
`effective_date` 继续是公告日期的保守次日。响应保留 report period、announcement date、
effective date、字段值、row hash 和 per-symbol completeness range。不得按 report period
直接假设信息已经公开，不得用后来报告向前填充。

### 4. 缺失是产品事实

Null、missing symbol、unverified coverage、no visible report 均保持结构化。Agent 必须
说明数据截止日/报告期和缺口，建议用户到 Data Center 同步；不得声称 MCP 调用了
Tushare，也不得用模型常识或网页数字替换 BYQ 缺失值。本 Phase 不自动触发同步，因为
Provider operation 属于可信 Data Plane 管理动作。

### 5. Role 与审计

`quant_orchestrator` 和 `market_researcher` 升级到 v1.2.0，并只增加上述两个 read tools。
每个调用使用精确 tool name 单独 authorize/audit。`factor_researcher`、
`strategy_researcher`、`backtest_analyst` 不扩权。Stock Pool、Approval、execution、Data
Worker 和 provider 权限均不改变。

### 6. 验收

- Backend contract tests：symbol/date/field bounds、exact-session、completeness、missing；
- no-look-ahead：公告当日仍选择旧报告，次日才能选择新报告；
- MCP schema/translation：closed enums、安全通用错误、不透传 Backend detail；
- role tests：仅 orchestrator/market researcher allowed，并保留现有 deny boundaries；
- 真实 Product Agent 连续比较：价格趋势 → 估值 → 基本面，回答与 persisted data 一致；
- 数据不足 journey：明确截止日/缺失并建议同步，不排名、不幻觉；
- Console/Network：Browser same-origin，无 direct Backend/MCP/DSH/PostgreSQL/Tushare。

## 非目标

- 不新增 Provider endpoint、在线 enrichment、Data Center UI 或自动同步；
- 不支持 ETF/fund、任意财务字段、预测数据、新闻或情绪；
- 不改变 strategy-declared inputs、signal/backtest identity；
- 不执行 Phase 60 public answer/activity/hidden-reasoning projection 重构；
- 不引入 PydanticAI、Hermes、第二 harness、VectorBT、BaoStock 或 AKShare。

## 停止条件

- 需要 DSH 直连 PostgreSQL、Backend internal、Provider 或 credential；
- 需要 latest fallback、前向填充或弱化公告可见边界；
- 需要新增写权限、同步权限或扩大到未知字段/资产；
- 真实旅程无法区分 verified、missing 与 stale data；
- 需要修改 Phase 60 projection 才能安全暴露 raw result。

## 后果与回滚

普通用户可在同一研究对话中用真实 BYQ 数据比较趋势、估值和已报告财务质量，并能明确
知道数据时点与缺口。回滚时移除两个 MCP tool 和两项 role permission；既有 PostgreSQL
数据、strategy inputs、audit records 与业务资源不删除、不改写。

## Acceptance record

维护者于 2026-08-26 明确授权后续已知阶段按计划顺序自动执行。该授权接受本 ADR 的
Phase 59 bounded persisted-data read path；Phase 60 仍必须独立 ADR、工作树、验收和 PR。
