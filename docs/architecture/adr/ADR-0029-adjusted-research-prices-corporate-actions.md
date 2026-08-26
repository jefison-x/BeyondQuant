# ADR-0029：Adjusted Research Prices and Implemented Corporate Actions

- Status: Accepted
- Date: 2026-08-25
- Accepted: 2026-08-25
- Decision scope: Phase 56 adjustment factors、adjusted research input 和 corporate-action accounting
- Related: ADR-0005、ADR-0013、ADR-0017、ADR-0023、ADR-0027、ADR-0028

## 背景

A-share 原始价格会在除权除息日发生机械跳变。将这些跳变提供给策略可能产生虚假 signal，而以复权价格执行 backtest 则会虚构从未成交的 fills。Phase 55 明确将 adjustment 和 corporate-action semantics 留给本阶段。

Tushare 将 `adj_factor` 定义为独立的每日因子，并将 A-share 前复权定义为原始价格乘以当日因子再除以选定结束日因子。其 `dividend` contract 区分预案与已实施动作，并分别标识登记日、除权除息日、派息日和股份上市日。Community 展示了这些领域需求，但将它们耦合到其 SDK、ORM、mutable cache 和支持 VectorBT 的 runtime。

## 决策

1. Trusted Data Worker 通过封闭的 BYQ contracts 获取精确日期的全市场 `adj_factor` 和 `dividend(ex_date=...)` snapshots。仅接受 canonical A-share symbols、正且有限的 factors、`实施` actions、有效日期及非负的已声明 amounts/ratios。
2. PostgreSQL 分别存储 raw unadjusted daily bars、factors 和 implemented actions。精确日期的完整性（包括有效的空 corporate-action result）使用内容寻址。既有 execution bars 永不覆盖，也不物化为 adjusted trades。
3. `market-data-requirement.v2` 在 Phase 55 inputs 之外要求 factor 和 corporate-action evidence。Legacy v1 waiting jobs 保持其原始 raw-input semantics，仍可执行。
4. Signal coordinator 使用冻结请求内的最后一个 factor 作为 anchor，构造确定性的 forward-adjusted research view。Sandbox 接收该 research view；immutable signal snapshot 和 native backtest 保留 raw execution bars。
5. Ready identity 覆盖 raw bars、factors、adjusted view 和 corporate actions。Snapshot 记录 requirement、ready-input 和 research-view hashes，确保 replay 不会静默改变 adjustment anchor 或 actions。
6. 对已持有 positions，在 ex-date 确立 corporate-action entitlement。Net cash 不早于已声明 pay date 入账；shares 不早于已声明 listing date 入账。日期缺失时明确回退至 ex-date。Execution prices 不复权，同一经济事件也不得再通过 factor 转换。
7. Browser traffic 仍只经过 Gateway/Product API。Data Center 披露已同步 dataset classes，但不暴露 raw provider responses 或 credentials。Signal/backtest workers 保持不访问 provider。

## 影响

- 策略不再把机械性的除权价格跳变解释为经济收益，同时 orders 仍按可审计的 raw prices 成交。
- Cash 和 share settlement 可复现且具备日期语义。
- Tushare permission failures 作为 readiness 不完整保持可见，不会静默回退到未复权 research data。
- Factor revisions 产生新的 ready/research identity，不覆盖已经冻结的 signal snapshot。

## 被否决的替代方案

- 将 adjusted OHLC 持久化为 execution data：会虚构历史 fills，并模糊 authoritative raw tape。
- 对持仓数量应用 factors，同时应用 corporate actions：会重复计算同一经济事件。
- 接受 dividend proposals 或从价格缺口推断 actions：都不能证明事件已经实施。
- 复制 Community SDK/ORM/VectorBT paths：违反当前 provider、storage 和 engine boundaries。

## 验收证据

Provider tests 覆盖精确参数、field mapping、tax semantics 和 fail-closed rows。PostgreSQL tests 覆盖 valid-empty completeness、adjusted-view identity、raw/adjusted separation 和 frozen actions。Regression tests 覆盖一次除权价格不连续，以及不同的 entitlement/payment/share-listing dates。完整 Compose 和 desktop/mobile Chrome review 验证 worker isolation、可见 dataset scope、same-origin requests 和 clean console。

## 回滚

停止请求 v2 inputs，并禁用 supplement synchronization。既有 v1 jobs 和 immutable snapshots 仍可使用。增量 factor/action evidence 可保留供审计；raw bars 不变。
