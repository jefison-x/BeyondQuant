# ADR-0042：可信多指数目录与精确权重快照完整性

- Status: Accepted
- Date: 2026-08-29
- Accepted: 2026-08-29
- Decision scope: Phase 70 指数目录覆盖、可信同步和精确快照完整性
- Related: ADR-0020、ADR-0027、ADR-0030、ADR-0041

## 背景

Phase 67–69 已交付指数股票池生产器，但真实 Product 目录只有沪深300。前端没有把选项
限制为一个；目录正确地只投影具备完整权重证据的指数。缺口来自 Data Plane：每日自动化
只同步 `000300.SH`，而 Phase 67 的测试和浏览器证据也只注入该指数，因此没有验证多指数
产品覆盖。

现有 `market_index_weight_completeness` 以月份为键，但生产器选择某个精确
`snapshot_date`。月度非空不能证明被选择日期的成员、权重和内容完整。扩大目录前必须关闭
该证据粒度缺口。

只读 Community 实现曾同步 11 个代码，其中包含同一指数的沪深别名，并直接耦合 SDK、
ORM 和线程调度。可复用的是有界核心指数集合、两个月回看和逐指数失败隔离意图；代码、
Provider runtime、别名目录和存储均不复用。

## 决策

1. BYQ 持有封闭 `index-catalogue.v1`，首版 canonical 候选为上证50、沪深300、科创50、
   中证500、中证1000和创业板指。`399300.SZ`、`399905.SZ` 等别名不构成第二 Product
   identity；上证综指、深证成指等未证明有可用权重的指数不进入候选集合。
2. 只有 trusted Data Worker 可对候选集合调用 closed Tushare `index_weight` adapter。
   每次同步最多六个指数、回看不超过 62 日；逐指数失败隔离，错误只保存安全类型，不暴露
   credential、raw payload 或 Provider internal。
3. 新增精确 `(index_symbol, snapshot_date)` 完整性证据。每个 verified snapshot 必须成员
   canonical/唯一、权重 finite/positive、percent sum 位于 `[99,101]`、稳定排序，并保存成员数、
   权重和、内容哈希、来源和验证时间。月度记录继续服务历史 readiness，但不能单独授权股票池。
4. 已有月度数据通过 forward repair 逐日期重新验证；无法证明精确完整性的行不生成 verified
   evidence，不删除历史原始行，也不进入目录。
5. Product API 投影全部六个 canonical 候选及 `selectable/readiness/coverage`。只有存在 verified
   snapshot 的指数可创建；等待数据的指数可见但禁用。Browser 不能提交 provenance、同步状态
   或 Provider operation。
6. 每日/手动 run-now 调度在 trusted worker 内执行有界目录同步并保存 run summary。单指数失败
   不影响其他指数和既有 snapshot；重新运行幂等修复。

## 后果

- “选择指数”能诚实展示支持范围和数据状态，而不是把缺失数据伪装成不存在的产品能力。
- 精确快照 evidence 成为指数池创建和物化的唯一 completeness gate。
- Provider 配额从一个核心指数扩展到最多六个、有界 62 日查询；失败隔离且可观察。

## 拒绝的替代方案

- 在前端硬编码可选项：会允许无权威权重的池并绕过 Data Plane。
- 复制 Community 的 11 个代码：包含重复别名且重引入旧 runtime/storage coupling。
- 继续用月度 `row_count > 0` 授权任意日期快照：不能证明实际被物化的数据完整。
- Browser、Gateway、DSH 或股票池 service 直接调用 Tushare。

## 验收

测试必须覆盖六指数 bounded request、逐指数失败/修复、精确快照权重验证、旧月度 evidence 不再
授权、no-look-ahead、owner isolation 和既有 frozen snapshot replay。Product API/OpenAPI/typed
client 必须一致。完整 Compose 与 Chrome desktop/mobile 必须展示多个真实已验证指数、禁用等待项、
same-origin Network、无 console error，并验证 Backend/Gateway restart 后目录不丢失。

## 回滚

停止新目录同步并保留精确 snapshot evidence。既有股票池继续引用不可变 snapshot；不删除月度
数据或历史物化结果。目录可退回只显示已 verified 的条目，但不得恢复月度非空授权。
