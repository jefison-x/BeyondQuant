# HIST 历史关系数据资格调查（0.10 前置）

Status: **blocked**（Phase 99 只读核对后确认当前无可用来源）— 依据
[ADR-0074](../architecture/adr/ADR-0074-data-baseline-and-qualification-boundaries.md)。
结论用于决定 ML-12（HIST）是否具备可证明的历史关系数据；未证明前保持 `blocked`。

Phase 99 只读核对：本机无 `BeyondQuant-community` 目录、无 Community/Legacy 容器或卷，
与 S3 记录（未收到只读导出）一致 → 无法取得历史行业/概念 membership 样本。解除阻塞需
维护者提供只读逻辑导出或可用只读连接。见 [Phase 99 证据](../evidence/phase-99/QUALIFICATION-EXECUTION.md)。

## 需求

HIST 模型（`V1_ML_SUPPORT_MATRIX` ML-12）需要**时点正确**的历史行业/概念关系快照：
在任一交易日只能看到当日可见的 membership，不得用当前关系回填历史。1.0 验收要求
关系来源、历史可见性、资源上限与真实端到端闭环可证。

## 已核对事实

- 现有 `index_weight` 能力仅覆盖**指数成分**，且以“月已同步即完整”为 DROP；已有
  [S3 历史指数成分准备记录](../evidence/post-u8-r1/S3-HISTORICAL-PREPARATION.md) 显示：
  单时点准备合同、入库边界与并发正确性已在本地面板验证，但**真实历史覆盖仍缺数据**。
- Community 数据为只读参考；历史关系来源未被认证前，不迁移、不下载替代、不宣称覆盖
  （AGENTS 29–33）。

## 待证/未决（blocked）

| 项 | 状态 | 说明 |
|---|---|---|
| 历史行业 membership 来源 | `not_proven` | 需明确 provider/endpoint、许可、单位、可见日期 |
| 历史概念 membership 来源 | `not_proven` | 同上；概念定义随时间变化需快照 |
| 关系可见日期语义 | `not_proven` | 披露/调整生效日期，而非抓取日期 |
| 覆盖区间与缺口 | `not_measured` | 需要实际数据后才能给出可用区间 |
| 资源上限（快照规模/存储） | `not_measured` | 依赖覆盖区间 |
| HIST 实施 ADR | `not_accepted` | 实施前须具名 Accepted ADR |

## 判定规则

- 任一来源无法证明 provider/单位/时点/许可/完整性 → quarantine 并报告，不进入基准。
- 禁止用当前关系回填历史、禁止静默删除 ML-12、禁止用合成关系充当真实闭环。
- HIST 真正的实施与端到端闭环属于 0.15；本调查只决定“是否可证”。

## 下一步（0.10）

1. 通过既有只读通道获取历史关系的最小可用样本（限定指数/区间），核对可见日期与摘要。
2. 若可证：产出覆盖区间、缺口与资源上限报告，供 `V1_DATA_BASELINE_CONTRACT` 冻结。
3. 若不可证：登记 `blocked` 并请维护者修订 ADR-0071/VERSION_PLAN，不做替代实现。
