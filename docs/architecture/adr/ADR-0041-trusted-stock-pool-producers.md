# ADR-0041：可信股票池生产器与时间点物化边界

- Status: Accepted
- Date: 2026-08-29
- Decision scope: Phase 66–69 指数型股票池、动态股票池、可信物化任务与下游冻结引用

## Context

ADR-0020 已定义 owner-scoped 股票池 identity、不可变 snapshot、可信 `index`/`dynamic`
provenance 和下游冻结引用，但 Phase 34 只开放了 `custom` Product write；已有 trusted
create/append seam 没有持久化定义、执行任务、调度或 Product 创建流程。ADR-0030 已提供
Tushare-only、point-in-time 的 canonical index weights、daily-basic 和 announcement-aware
financial indicators，因此指数池不得从 Browser 或股票池服务直接访问 Provider。动态池尚无
被接受的规则语言或执行 owner；Community 对动态池只有占位符。

## Decision

### 权威记录与职责

股票池保留三个不同层次：

1. `stock_pool_producer_definitions` 是 owner-scoped、versioned 的生产意图。它关联唯一 pool
   identity，记录 `producer_kind`、closed schema version、normalized definition、schedule、
   lifecycle、definition fingerprint 和 optimistic version。它不是成员事实。
2. `stock_pool_materialization_runs` 是 append-oriented 的执行事实，记录 run ID、definition
   version、requested/effective as-of、producer ID/version、input manifest/hash、状态、计数、有界
   reason/error、started/finished time 和产出的 snapshot ID。它不得包含 credential、raw provider
   payload 或 SQL。
3. ADR-0020 `stock_pool_snapshots` 继续是唯一权威成员事实。成功任务在一个事务内追加完整
   snapshot 并原子推进 current pointer；失败、取消、缺失或隔离不得产生部分 snapshot，也不得
   改变旧 pointer。

Product Browser 只能经 Gateway/Product API 创建或修改定义、预览、激活/暂停以及请求幂等刷新。
Backend 校验 owner/workspace/RBAC 和 domain invariant。独立 trusted Data Worker 领取有界任务、
读取 BYQ canonical Data Plane、确定性计算并调用 trusted snapshot write。DSH/Agent 可提出候选
定义，但不能物化、调度、提供 authoritative provenance 或绕过显式 Product/domain authorization。

### 指数型股票池

指数目录是 validated canonical Data Plane 的全局只读投影；用户选择指数后创建 owner-scoped
`index` pool definition。生产器只读取已验证的 `market_index_weights`：

- 选择 `snapshot_date <= requested_as_of` 的 latest 完整快照，禁止 look-ahead；
- 将声明为 percent 的 Tushare 权重按 versioned contract 精确转换为 fraction；
- 验证 canonical symbol、去重、finite/positive precision、成员数和权重和；
- manifest 固定 index symbol、provider/dataset、effective trade date、ingestion reference/hash；
- 相同 semantic snapshot 幂等复用；晚到的旧日期数据不得回退 current pointer；
- 不完整、来源不明或权重异常的数据进入 waiting/quarantine/failed，不生成 snapshot。

validated index-weight import 可排队刷新；Product 手动刷新只能创建同一边界内的幂等任务，不能
直接调用 Provider。首版目录只展示有完整 canonical coverage 的封闭指数集。

### 动态股票池

动态规则使用 BYQ-owned、versioned、封闭的 declarative schema，不允许 arbitrary Python、SQL、
模板、插件、网络请求或模型表达式。第一版只包含：

- base universe：canonical security master 或明确冻结的 index pool snapshot；
- allowlisted point-in-time fields：证券生命周期/市场/板块/行业、daily-basic valuation/market-cap/
  turnover、announcement-visible financial indicators，以及显式 bounded 的价格/流动性窗口；
- bounded boolean filters、deterministic ranking、`top_n` 上限、canonical symbol tie-break；
- explicit missing-value policy（默认 exclude）与 `unweighted`/`equal_weight`；
- manual/daily/weekly/monthly cadence，按 exchange calendar 和 input completeness 触发。

动态评估器是 Quant Domain/Data Worker 内小而纯的 deterministic evaluator，不是通用 rules engine，
不属于 DSH。rule fingerprint、producer version、evaluation cutoff、calendar session 和 immutable
input references 进入 manifest/provenance。preview 不是权威 snapshot；只有显式激活或已激活
schedule 可以物化。结果相同复用 snapshot；失败保留上一有效 snapshot 并投影 stale/failed 状态。

### 状态、恢复与下游消费

任务状态固定为 `queued`、`running`、`succeeded`、`waiting_for_data`、`failed`、`cancelled`；Pool
readiness 推导为 `current`、`stale`、`waiting_for_data`、`failed`、`paused`，不得由 Browser 提交。
任务 claim 使用 lease、attempt ceiling 和 stable idempotency identity；重启可重新领取过期 lease。

Research、Strategy、signal、Backtest 和 Paper Trading 只能绑定 immutable snapshot ID。历史重放
不得解析 current pointer。资产导入只恢复 inactive definition intent，必须在当前 workspace 重新
验证数据和物化，不能信任导入的 active/provenance 状态。

### 分阶段交付

- Phase 66：接受本 ADR、`stock-pool-producer.v1`、Community 分类和 Phase 67–69 gate；不改 runtime。
- Phase 67：实现指数目录、index definition、trusted materializer、任务/调度、Product API/UI。
- Phase 68：实现 closed dynamic rule、preview、trusted evaluator、调度、Product API/UI。
- Phase 69：统一目录/差异/状态、下游冻结引用、运行监控、两用户/restart/Chrome 完整验收。

每 Phase 使用独立 worktree/branch/PR；前一阶段合并且 CI 通过后才能进入下一阶段。

## Consequences

- 指数和动态股票池成为可解释、可重放的 domain artifact，而不是临时查询结果。
- Product Plane 只能请求意图；Provider access、计算和 snapshot promotion 保持 trusted。
- 动态能力刻意牺牲任意表达能力，换取时间点正确性、确定性和安全审计。

## Rejected alternatives

- 让 Browser、Gateway、DSH、MCP 或股票池 HTTP route 直接调用 Tushare/数据库。
- 允许 arbitrary Python/SQL、复制 Community service/ORM 或建设通用规则引擎。
- 每次读取时现场计算成员，或让下游引用 current pointer。
- 修改旧 snapshot、部分成功时推进 pointer、用墙钟代替交易日历。
- 重新引入 BaoStock、AKShare、VectorBT 或不明来源数据兼容层。

## Stop conditions

若 canonical 数据无法证明 provider/source、单位、完整性、时间点可见性或 integrity；动态字段无法
建立 point-in-time 语义；需要 arbitrary code/provider access、MCP bypass、DSH direct DB、第二 generic
harness；不能原子 promotion/lease recovery/owner isolation；或 UI 必须依赖 raw worker/internal schema，
对应实现阶段必须停止并提交新 ADR，而不是产生猜测性或部分权威结果。
