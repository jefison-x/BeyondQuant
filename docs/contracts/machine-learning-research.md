# Machine Learning Research Contract

本合同冻结 ADR-0043 的 LightGBM 最小闭环边界。Phase 71 定义合同，Phase 72 已实现可信训练与
ModelArtifact。本阶段实现 prediction-only inference、冻结 top-N 信号与现有 Backtest 衔接；在
Phase 73 合并门禁完成前，Phase 74 Product journey 仍不得开始。

## 领域对象与 lineage

```text
ml-strategy-version.v1（validated + approved）
  + stock_pool_snapshot（immutable）
  + ml-feature-snapshot.v1（immutable point-in-time rows）
      ↓ ml-training-run.v1
ml-model-artifact.v1（immutable model metadata + object hash）
      ↓ prediction-only inference
ml-prediction-snapshot.v1（immutable scores/ranks）
      ↓ closed signal policy
signal_snapshot（ADR-0017）
      ↓
native deterministic Backtest
```

所有对象必须绑定 trusted `owner_principal` 与 `workspace_id`。Client 提供的 owner/workspace、数据
provenance、hash、状态、model identity 和 runtime identity 一律忽略或拒绝；由 Backend/Worker 生成。

## `ml-strategy-version.v1`

允许字段：

```json
{
  "schema_version": "ml-strategy-version.v1",
  "name": "HS300 LightGBM 5日收益",
  "learner": {"kind": "lightgbm_regression", "profile": "byq-lightgbm-cpu-v1"},
  "feature_set": {"id": "price-volume-basic-v1"},
  "target": {"kind": "forward_return", "horizon_sessions": 5},
  "split": {
    "train": {"start": "2020-01-01", "end": "2023-12-31"},
    "validation": {"start": "2024-01-01", "end": "2024-12-31"},
    "prediction": {"start": "2025-01-01", "end": "2025-06-30"}
  },
  "learner_parameters": {
    "num_leaves": 31,
    "learning_rate": 0.05,
    "max_depth": -1,
    "min_data_in_leaf": 20,
    "feature_fraction": 1.0,
    "bagging_fraction": 1.0,
    "num_boost_round": 200,
    "early_stopping_rounds": 20
  },
  "signal_policy": {"kind": "top_n_equal_weight", "top_n": 20, "rebalance": "weekly"}
}
```

三个 split 必须严格按时间顺序且不重叠。`horizon_sessions` 为 `1..20`；`top_n` 为 `1..100`。
LightGBM 参数使用封闭 allowlist、有限数值和固定上限。Worker 强制注入并覆盖：

```json
{
  "objective": "regression",
  "metric": "l2",
  "device_type": "cpu",
  "deterministic": true,
  "force_col_wise": true,
  "seed": 20260829,
  "num_threads": 1,
  "verbosity": -1
}
```

不得接受 arbitrary objective/metric/callback、custom function、class path、module、Python、SQL、URL、
filesystem path、model upload 或 credential field。

## `ml-feature-snapshot.v1`

FeatureSnapshot 由 BYQ 使用冻结股票池意图、canonical trading sessions 和 adjusted research bars 构建。
custom fixed pool 必须标记 `membership_mode=fixed_snapshot`；index/dynamic pool 必须标记
`membership_mode=point_in_time`，并把每个 session 不晚于该 session 的 verified membership evidence
冻结进 source manifest。两种模式不得互相伪装；固定池研究不得声称复现历史指数成分。
`price-volume-basic-v1` 的精确 feature order 为：

```text
return_1, return_5, return_20, volatility_20, volume_ratio_5
```

每行至少包含 `session`、`symbol`、上述 finite/nullable features、`split`、`feature_as_of`；训练和验证
行还包含 `target` 与 `label_end_date`。约束：

- `feature_as_of == session`，只允许当日收盘及此前已持久化输入；
- `label_end_date <= split.end`，跨越 split end 的行直接排除；
- prediction 行禁止包含 `target`/`label_end_date`；
- 不对未来值 backfill，不以当前指数/股票池成员重建历史成员；
- 缺失历史窗口的行排除并在 completeness 中计数，不以零伪造；
- snapshot 保存 source manifests、membership fingerprint、row counts、exclusion counts 和 content hash。

首版上限：1 个 frozen pool snapshot、1,000 symbols、2,500 sessions、2,000,000 usable rows、5 features。
具体提交仍受 MarketReadiness 防滥用边界约束；当前训练实现采用更小的 50,000 个输入/特征行和
32 MiB 上限，超过时 fail closed，不承诺自动拆分大规模训练。

## `ml-training-run.v1`

状态：

```text
waiting_for_data → queued → running → completed
                         └→ failed
waiting_for_data/queued → cancelled
```

运行记录保存 idempotency/request hash、strategy/feature/pool identity、attempt、lease、safe error code、
created/started/finished time 和结果 Artifact IDs。Claim 使用数据库锁并可恢复过期 lease；同一请求的
并发重试不得产生不同 authoritative result。

## `ml-model-artifact.v1`

必须包含：

- `model_format=lightgbm-text-v1`、object key/size/SHA-256；
- exact feature order、target 和 split；
- effective learner parameters、best iteration；
- train/validation row and symbol counts；
- validation RMSE、RankIC 与 coverage；
- FeatureSnapshot、Stock Pool snapshot、ML strategy 和 TrainingRun lineage；
- `runtime_lock=python-3.13/lightgbm-4.7.0/numpy-2.3.3/cpu-single-thread` 和 immutable image identity。

模型对象不得包含 pickle/joblib、Python module/class、absolute path、credential、raw Provider payload 或
DSH state。读取时必须重新验证 size/hash，失败即不可推理。

## `ml-prediction-snapshot.v1`

每行包含且仅包含有界的 `session`、`symbol`、finite `score`、positive `rank`。Snapshot 保存 model、
feature、pool identity、prediction split、row/session/symbol counts 和 content hash。每个 session 的 rank
必须由 `(score DESC, symbol ASC)` 确定；相同输入和 runtime identity 必须得到相同 content identity。

Validation 指标不属于 prediction rows；prediction split 的未来实现收益不得进入本 Artifact。

## 冻结信号转换

只有 approved `ml-strategy-version.v1` 可以把匹配的 PredictionSnapshot 转为 `signal_snapshot`。
`top_n_equal_weight` 对每个 rebalance session 选择 rank 前 N，只在进入/退出集合时产生交易意图；
目标等权必须通过冻结 capital allocation、当日可用 execution price 和 lot size 转换为明确数量，再使用
已有 execution/quantity/risk Contract 规范化，不允许 Backtest 临时重新计算权重。Signal
source/lineage 必须包含 model、prediction、
feature、pool 和 policy identity。Backtest 不加载模型，不重新排名，不重新训练。

## Product 与 Agent 边界

Browser 只访问 Gateway/Product API，看到有界状态、指标、lineage 摘要和安全错误。Browser 不接触
Backend、Worker、PostgreSQL、object path、LightGBM text 或 raw feature rows。Product Agent 如后续获得
能力，只能经 BYQ MCP 创建/读取领域意图；DSH 不训练、不推理、不读取模型对象。

Phase 72 仅新增 Backend/domain schema/API 与隔离 ML Worker；LightGBM/NumPy 不进入 Backend、MCP、
DSH、signal sandbox 或 Browser。Product API、MCP tool、UI、prediction、signal 与 Backtest 仍未新增。

Phase 73 implementation 增加 durable `ml-prediction-run.v1`。Backend 在排队前验证
owner/workspace、approved ML Strategy、Model/Feature/Pool lineage，并确认 MarketReadiness identity
与训练冻结值相同；ML Worker 读取对象时复验 native model size/hash/runtime/feature order，只对无标签
prediction rows 推理。Worker 以 `(score DESC, symbol ASC)` 生成不可变 PredictionSnapshot，再按批准
cadence/top-N、冻结 `execution.initial_capital`、当日 close 与 lot size 生成仅包含进入/退出的明确数量
信号。ML 信号保留 Strategy Approval、Model、Feature、Prediction、Pool 与 policy hash lineage；现有
Backtest 只构造标准 manifest，不导入 LightGBM、读取模型或重新排名。Product/Gateway/UI 留待
Phase 74。
