# 1.0 数据基准合同（0.10 冻结草案）

Status: Draft — 依据 [ADR-0074](../architecture/adr/ADR-0074-data-baseline-and-qualification-boundaries.md) 与
[VERSION_PLAN](VERSION_PLAN.md)。本文件冻结 0.10 的可测支持范围；在维护者确认前不启动规模化特征/模型实现。

## 目的

给出 1.0 机器学习研究可复现、可审计的最小数据基准：标的、区间、频率、口径、时点来源、
单位、许可与摘要，使 0.11+ 的模型在同一数据与验证合同下公平比较。禁止用“全市场全历史”
代替本表的有限范围。

## 基准范围（提议，待冻结）

| 维度 | 提议 | 说明 |
|---|---|---|
| 市场/频率 | A 股日频 | 与现有日线/回测口径一致 |
| 标的范围 | 由冻结股票池快照定义（含历史成分资格后扩展） | 支持范围以快照 membership 为准 |
| 时间范围 | 明确起止（含预热窗口） | 不使用未来数据；区间随合同冻结 |
| 日线字段 | open/high/low/close/volume/amount、pre_close、停牌与涨跌停状态、复权因子 | 已有 `market_daily_bars`/`status`/`adjustment_factors`/`session_supplements` |
| 公司行为 | 分红/送转/拆并（`corporate_actions` + 完整性标记） | 缺失或未完成即不可用于研究 |
| 交易日历 | 每自然日一行、`is_open` 明确 | 覆盖区间必须完整，否则 `trading_calendar` 缺失 |
| 证券主数据 | 上市/退市/停牌生命周期快照 | 用于时点可见性与退市处理 |
| 估值/财务/行业 | 分批接入，须时点资格 | 披露可见日期；未通过者不进入基准 |
| 许可与来源 | 每个数据集记录 provider、endpoint、许可与摘要 | 未证明来源/单位/时点/完整性者 quarantine |

## 口径（必须显式）

- 停牌：`is_suspended` 明确；停牌日不得产生虚假收益或成交。
- 退市/上市：按生命周期快照，上市前/退市后不可见。
- 复权：使用已冻结的复权因子；价格单位与权重单位显式声明。
- 缺失：区分“无数据”“未完成”“不可用”，不得默认填零代表有效结果。
- 摘要：每个数据集保存 content digest；研究输入冻结到摘要，重放必须可核对。

## 与现有实现的关系

- 复用 `market_readiness` 的 required datasets 合同与 `market_session_supplement_completeness`。
- 复用 `index_weight` 能力（非 HIST）；历史成分资格见
  [V1_HIST_DATA_QUALIFICATION](V1_HIST_DATA_QUALIFICATION.md)。
- 数据扩容遵循 AGENTS 29–33：Community 只读、逻辑导出、验证/规范化/清单/导入/复核；
  禁止物理目录复制；BaoStock/AKShare/VectorBT 为 DROP。

## 未决项（blocked 直到证据）

- 历史股票池 membership 的时点来源与许可（依赖 HIST 调查）。
- 估值/财务/行业字段的披露可见日期与覆盖范围。
- 实际区间与预热长度：在数据扩容资格报告后冻结。
