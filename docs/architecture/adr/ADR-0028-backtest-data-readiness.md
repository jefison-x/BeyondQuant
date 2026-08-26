# ADR-0028：Lifecycle-Aware Backtest Data Readiness

- Status: Accepted
- Date: 2026-08-25
- Accepted: 2026-08-25
- Decision scope: Phase 55 signal/backtest 输入就绪与有界修复
- Related: ADR-0005、ADR-0008、ADR-0013、ADR-0017、ADR-0023、ADR-0026、ADR-0027

## 背景

Phase 54 推进了持久化的未复权日线数据，但每个 symbol 只有一根 bar 并不能证明 signal 或 backtest 窗口完整。缺失行可能意味着摄取缺口、停牌，或日期位于证券生命周期之外。当 provider 发布精确的每日涨跌停价时，基于阈值推导的价格并不充分。

Community 的覆盖率与修复流程提供了有用的领域证据，但其 ORM、线程 worker、provider registry、frontend 直接内部调用及 VectorBT runtime 与 BYQ 不兼容，因此不予复用。

## 决策

1. 每个 signal 请求冻结一份 `market-data-requirement.v1` manifest：canonical symbols、日期边界、pool membership fingerprint、security-master snapshot、SSE calendar，以及所需的 daily/status/price-limit datasets。
2. 覆盖率按 symbol 及其冻结上市生命周期内的 open session 评估。上市前和退市后日期不适用。只有持久化的精确 status 能够证明时，停牌 session 才可在没有 bar 的情况下视为完整。
3. Tushare `suspend_d` 和 `stk_limit` 只能通过封闭、精确日期的 BYQ contracts 使用。校验 fields、symbols、dates、uniqueness、row bounds 和 values。每日自动化持久化不含 secret 的 provenance。
4. 不完整请求创建一个幂等、有界的 repair。Data Plane worker 刷新 calendar range，并最多排队 250 个全市场 session jobs；HTTP、signal/backtest workers、browser、MCP 或 DSH 均不得执行 provider 工作。
5. Signal jobs 从 `waiting_for_data` 开始且不可 claim。无 provider 访问的 coordinator 仅在构造 `ready_input_sha256` 后才提升它们。
6. Immutable signal input 冻结精确的 `pre_close`、suspension 和 limit fields，以及 requirement 与 ready identities。Backtests 只消费由此产生的 validated snapshot，不能越过 readiness 提前运行。
7. Requirements 上限为 2,000 symbols、250 repair sessions 和 50,000 symbol-session cells。缺少证据时 fail closed，并保持可见。
8. Adjustment factors、corporate actions、benchmarks、point-in-time index membership、valuation 和 fundamentals 不属于 Phase 55。

## 影响

- Holidays 和 lifecycle dates 不会产生虚假缺口。
- 不能从缺失价格推断停牌。
- 新冻结输入使用精确 limits 取代百分比启发式规则。
- 现有 raw execution prices 保持未复权；adjustments 由 Phase 56 负责。

## 被否决的替代方案

- Signal/backtest workers 访问 provider：违反 immutable boundaries。
- 将每个缺失 bar 都视为停牌：会掩盖摄取失败。
- 按自然日或当前生命周期评估覆盖率：会产生虚假缺口。
- 复制 Community 代码：会恢复已排除的 runtime 和 frontend coupling。

## 验收证据

Provider tests 覆盖精确 status/limit mappings。Database 和 API tests 覆盖 lifecycle readiness、suspension proof、bounded repair、不可 claim 的 waiting 状态、promotion 和 immutable identity。Compose 和 browser evidence 证明 worker boundaries 以及自动准备过程可见。

## 回滚

禁用 repair creation 和 waiting promotion。既有 completed snapshots 与 backtests 仍然有效。增量 provenance 保留，bars 不删除。
