# ADR-0030：Benchmark、Point-in-Time Universe 与 Declared Research Data

- Status: Accepted
- Date: 2026-08-25
- Accepted: 2026-08-25
- Decision scope: Phase 57 benchmark、historical index membership 和可选 valuation/fundamental research inputs
- Related: ADR-0005、ADR-0013、ADR-0017、ADR-0023、ADR-0027、ADR-0028、ADR-0029

## 背景

相对表现需要与 backtest 一同冻结的 benchmark。历史指数策略需要每个 session 当时已知的 membership，而不是把今天的成分股向过去投射。Valuation 和已报告 financial indicators 也有不同的可见时间：每日 valuation 属于精确 market session，而 financial period 在公开公告前不可用。

Tushare 提供独立的 `index_daily`、`index_weight`、`daily_basic` 和 `fina_indicator` contracts。只读 Community 实现展示了领域需求，但将其耦合到 SDK、ORM、mutable synchronization state、threads 和支持 VectorBT 的 backtests。它还提供远超 strategy sandbox 应允许请求范围的 provider surface。

## 决策

1. Strategy drafts 和 immutable versions 只能声明四类可选依赖：一个 benchmark index、一个 index universe、封闭的 daily-basic fields 列表，以及封闭的 financial-indicator fields 列表。未知 datasets、fields 和非 canonical index identities 均 fail closed。该 declaration 是 domain data，并冻结到 version 和 input identity 中。
2. 仅 trusted Data Worker 调用封闭、有界的 provider contracts，以获取 index daily bars、monthly index-weight snapshots、exact-session daily-basic snapshots 和 per-symbol financial indicators。Provider credentials 和 raw responses 永不进入 Product、signal 或 backtest workers。
3. PostgreSQL 分别存储四类 datasets，并带 canonical symbols、provider provenance、content hashes 和显式 completeness evidence。只有 provider contract 允许空 snapshot 时，valid-empty result 才构成证据；malformed、duplicate、truncated 或 unbounded results 均失败。
4. `market-data-requirement.v3` 扩展现有 immutable readiness requirement。Coordinator 只在 promotion 前同步已声明的 optional data；缺少任何 required benchmark、daily-basic、membership 或 financial completeness evidence 时，拒绝冻结 ready input。
5. 某 session 的 index membership 取 snapshot date 不晚于该 session 的最新可用 provider snapshot。策略冻结的 Stock Pool 仍是有界 symbol superset；sandbox 接收 `is_universe_member` column，并拒绝 non-members 的非零输出。不得把 current membership 回填到更早日期。
6. Daily-basic values 只附加到其精确 session。Financial rows 同时保留 report period 和 announcement date，并在公告后的下一个 calendar day 对研究可见。对每个 session，选择最新可见 report period 的最新可见公告。缺失值保持显式，不得用后续报告向前虚构。
7. Benchmark series 和所有 declared research columns 随 ready input 及其 hash 一同冻结。Native backtests 从该冻结 series 计算 benchmark return、excess return 和 benchmark curve；benchmark prices 永不作为可交易 portfolio bars。
8. Daily automation 在现有 session datasets 之外，同步刷新 core CSI 300 benchmark、其当前 monthly membership 和 full-market daily-basic data。Custom declared indexes 和 financial history 由有界 pre-run repair 按需填充。Browser traffic 仍只经过 Gateway/Product API。
9. ETF 和 fund identities、任意 provider endpoints、BaoStock、AKShare 和 VectorBT 不属于本决策。

## 影响

- Relative returns 和 historical index membership 可从与 signal、backtest 相同的 immutable input 复现。
- 在保守的 next-day rule 下，financial announcements 不会泄漏到其声明发布日期当天或更早的 sessions。
- Optional data 只对声明它的策略增加 provider permission 和 repair 成本；缺少授权仍表现为可见 readiness failure。
- Dataset 或 declaration revisions 会产生新的 ready identity，不改写既有 signal snapshots 或 backtest results。

## 被否决的替代方案

- 对所有历史使用今天的 index members：引入 survivorship 和 look-ahead bias。
- 允许 strategy code 请求任意 Tushare endpoints：绕过 Data Plane、削弱边界并暴露 credentials/provider coupling。
- 仅按 report period 或 announcement day 连接 financial rows：会使数据早于保守的 public-information boundary 可见。
- 复制 Community provider/ORM/VectorBT paths：违反当前 provider、persistence 和 execution boundaries。

## 验收证据

Provider contract tests 覆盖 request bounds、closed fields、normalization 和 fail-closed rows。PostgreSQL tests 覆盖 exact-session valuation、monthly membership completeness、latest-snapshot selection、next-day announcement visibility 和 immutable hashes。Sandbox 和 engine regressions 覆盖 non-member output rejection 以及 frozen benchmark/excess performance。完整 Compose 和 desktop/mobile Chrome review 验证 worker isolation、仅 Product 的 browser requests，以及可见 dataset/benchmark evidence。

## 回滚

停止接受新的 `data_requirements`，并停止 v3 optional-input repair。既有 v1/v2 jobs 和 immutable snapshots 保持原有语义。增量 benchmark/factor evidence 可保留供审计，并可在以后重新同步。
