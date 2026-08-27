# ADR-0034：真实用户旅程与可复现行情闭环

- Status: Accepted
- Date: 2026-08-27
- Accepted: 2026-08-27
- Decision scope: Phase 61 user-experience acceptance closure
- Related: ADR-0018、ADR-0024、ADR-0028、ADR-0031、ADR-0032、ADR-0033

## 背景

真实用户交互专项验收共记录 14 个聚类问题。Phase 58–60 已关闭 4 项并部分改善 4 项，
但普通用户仍会在长任务、策略理解、数据可用性判断、回测后续动作和跨页面上下文上遇到
阻力。登录、CRUD、基础回测等确定性能力已有充分自动化与真实浏览器覆盖，本 Phase 不再
机械重复这些能力。

验收还暴露了一个数据边界不一致：估值、基本面、signal 和 backtest 均读取 BYQ
PostgreSQL 中已持久化、具备完整性证据的数据，而 `byq_market_daily` 仍通过
`/v1/data/daily` 实时调用 Tushare。同一对话因此可能把不同获取时点和可用范围的数据混为
一个可复现研究结论。

只读 Community 审计表明，可借鉴 Login 的浏览器语义、Strategy/Backtest 的任务导向信息
层级、Data Sync 的状态反馈和 AgentThinking 的折叠进度；其 raw Agent API、内部 ID 主导
流程、PydanticAI/Hermes、AKShare/BaoStock/VectorBT、legacy domain API 均不可迁移。

## 决策

### 1. 普通 Agent 行情只读取持久化 BYQ 数据

`byq_market_daily` 保留现有封闭参数形状，但改为调用 Backend
`/v1/data/research/daily` 并读取 `market_daily_bars`，不再自动调用 Provider。旧
`/v1/data/daily` 保留为非 Agent 的兼容接口。研究响应必须声明 `source=persisted_byq`、实际
覆盖日期、行数和缺失事实；没有数据时返回诚实的空结果/缺口说明，不用旧数据填充。

Tushare 调用只存在于 Data Center 的连接测试、显式同步和 trusted Data Worker。Agent、
signal coordinator 和 backtest worker 不得以读取为名触发下载。回滚可恢复旧 endpoint
实现，但不得改写或删除已持久化数据。

### 2. Data Center 提供面向任务的 readiness 查询

新增有界 Product API readiness query：用户提供至多 20 个 canonical A-share symbols、
日期范围和封闭的 `research` / `backtest` 使用场景。Backend 复用 ADR-0028 的
`MarketReadinessStore.requirement/assess`，依据最新 Security Master 和持久化 Data Plane
回答 ready/partial/missing、缺失数据集、日期和股票范围。

Browser 只经 Gateway/Product API，不得直接调用 Backend、Provider 或数据库。查询不会
自动同步；缺失时 UI 提供进入已有同步表单的明确下一步。全库 coverage 继续是健康概览，
不得伪装成某个任务可用性的证明。

### 3. 对话长任务状态只展示可信事实

Frontend 从 normalized `agent.activity` 中识别当前 turn，持续展示当前公开阶段、已耗时和
可见停止入口。没有可靠历史模型时不伪造 ETA；明确说明耗时取决于数据范围。取消仍使用
现有 Gateway/Runtime Adapter contract，内部 tool、reasoning 和 raw DSH event 不暴露。

DSH role skills 将用户请求分为回答、持久化研究资产和 consequential action 三类。普通
追问默认复用当前会话证据，不创建 ResearchTask/Experiment/Artifact；只有用户明确要求
保存、创建、比较或执行时才创建必要资源。Backend authorization/audit 不因减少公开噪声
而弱化。

### 4. 核心页面以用户任务而非内部对象为主

- Strategy 首屏使用名称、说明、状态、版本和下一步；Artifact ID、raw JSON/source 放入
  折叠的“技术详情”。
- Backtest 本地化指标与状态，并提供“让小巴分析”“基于结果优化”“进入模拟操盘”动作。
- Agent 接受 route 中的可审阅 draft/context，只预填、不自动发送或自动执行。
- Backtest、Strategy 和 Paper Trading 通过受控 route query 传递已授权 Product resource
  reference，用户无需复制内部 ID；目标页面仍重新经 Product API 做 owner/workspace 校验。
- Login 补齐 label/id/name/autocomplete；最近区间的 Agent 指令必须明确包含最新交易日和
  区间端点。

### 5. 技术细节保留但降级

WorkflowTrace、Artifact、manifest、hash 和内部 ID 对审计仍有价值，保留在可折叠技术详情
或 Operations surface。普通任务首屏不得要求用户理解这些概念。不得删除 provenance、
数据截止日、缺失原因、审批依据或可复现输入。

### 6. Compose 持久资源默认按项目隔离

Network 和 volume 的默认实际名称必须包含 `COMPOSE_PROJECT_NAME`；不同 worktree/project
不得在未显式声明 external resource 的情况下挂载同一 PostgreSQL volume。既有部署要复用
历史卷时，必须在其受控 `.env` 中显式设置 `BYQ_POSTGRES_VOLUME_NAME` 等兼容变量。CI 和
临时验收使用唯一 project/resource names，启动前对既有非本 project resource fail closed。

## 验收

- 原 14 项问题均有关闭状态和证据；P0/P1 无未解决项，重要 P2 不得阻断黄金旅程。
- Backend/MCP contract test 证明 Agent daily read 不调用 Provider，响应与 PostgreSQL 一致；
  缺失时不填充。
- Data readiness Backend/Gateway/frontend tests 覆盖 ready、partial/missing、越权、非法范围
  和同步下一步。
- Frontend unit/Playwright 覆盖长任务 elapsed/cancel、Login autofill、Strategy 技术详情、
  Backtest 三个上下文动作及目标页预填。
- DSH composition/static contract 与真实简单追问证明无不必要 Task/Experiment/Artifact，
  同时显式创建请求仍正常。
- 真实 Chrome/DevTools 通过研究 → 股票池 → 策略 → 审批 → 回测 → Agent 分析/优化 →
  Paper Trading 黄金旅程；记录 Console、Network、same-origin、截图和关键资源 ID。
- 两个不同 Compose project 的默认 PostgreSQL volume/network 名不同；不得再次并发挂载
  运行环境数据卷，并完成一次逻辑 backup/restore 验证。

## 非目标

- 不新增 provider、live broker、team workspace、自动投资建议或第二 Agent harness；
- 不重写 Strategy/Backtest engine、审批语义或 immutable lineage；
- 不以大规模 UI 重构替代缺陷关闭，不为全部主观 UX 建自动化；
- 不执行 v1.0 release/tag/production publication。

## 后果

普通投资者获得一致、可解释的持久数据口径和连续下一步；高级用户仍可查看审计细节。
Provider freshness 由显式同步承担，因此数据缺失会更早、更诚实地暴露，而不会在 Agent
读取时隐式下载。Phase 61 以专项复验报告记录剩余风险，不把“测试通过”夸大为投资建议。

## Acceptance record

维护者于 2026-08-27 明确授权继续全面修复和验收，本 ADR 接受上述 Phase 61 边界。
