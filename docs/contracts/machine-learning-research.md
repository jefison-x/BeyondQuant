# Machine Learning Research Contract

本合同冻结 ADR-0043 的 LightGBM 最小闭环边界。Phase 71 定义合同，Phase 72 实现可信训练与
ModelArtifact，Phase 73 实现 prediction-only inference、冻结 top-N 信号与现有 Backtest 衔接，
Phase 74 已完成安全 Product API/UI 与真实浏览器闭环验收。

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
  大型 row payload 以 canonical JSON + deterministic gzip 写入不可变对象存储；Research Artifact 仅保存
  有界元数据、对象 size/SHA-256、row count 和原始 snapshot hash。读取预测输入时必须同时验证 descriptor、
  object reference、解压后 snapshot hash 和 row count；不得把 raw feature rows 暴露给 Browser。

首版上限：1 个 frozen pool snapshot、1,000 symbols、2,500 sessions、2,000,000 usable rows、5 features。
具体提交仍受 MarketReadiness 防滥用边界约束；训练输入解压后最大 256 MiB，对象仍受 32 MiB
压缩载荷上限约束，任一 identity/size/row-count 校验失败均 fail closed。

## `ml-training-run.v1`

状态：

```text
waiting_for_data → queued → running → completed
                         └→ failed
failed → queued（仅 input 已冻结、attempt 未耗尽的受约束重试）
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
DSH、signal sandbox 或 Browser。该阶段没有提前增加 Product API、MCP tool、UI、prediction、signal
或 Backtest 能力。

Phase 73 implementation 增加 durable `ml-prediction-run.v1`。Backend 在排队前验证
owner/workspace、approved ML Strategy、Model/Feature/Pool lineage，并确认 MarketReadiness identity
与训练冻结值相同；ML Worker 读取对象时复验 native model size/hash/runtime/feature order，只对无标签
prediction rows 推理。Worker 以 `(score DESC, symbol ASC)` 生成不可变 PredictionSnapshot，再按批准
cadence/top-N、冻结 `execution.initial_capital`、当日 close 与 lot size 生成仅包含进入/退出的明确数量
信号。ML 信号保留 Strategy Approval、Model、Feature、Prediction、Pool 与 policy hash lineage；现有
Backtest 只构造标准 manifest，不导入 LightGBM、读取模型或重新排名。

Phase 74 增加 owner/workspace-scoped Gateway/Product API 安全投影、typed client 与模型研究工作台；
Browser 可查看有界状态、指标、排名、信号和 Backtest，但看不到模型对象路径、FeatureSnapshot/raw
rows 或 raw Backtest manifest。真实 PostgreSQL/Compose、restart、two-user 和 Chrome MCP golden
journey 已验证该边界。

Phase 78 增加 Product Agent 的最小 ML 创建与训练面。`byq_ml_capabilities` 返回封闭能力与参数界限，
`byq_ml_workspace_get` 只投影 owner/workspace-scoped 任务、股票池、安全 Artifact metadata 与训练状态；
`byq_ml_strategy_create` 只接受本文冻结的 `ml-strategy-version.v1`；`byq_ml_training_create/get/cancel`
只管理可信训练生命周期。MCP 自动绑定 trusted trace/owner/workspace，不接受 Python、SQL、URL、模型上传、
对象引用或 raw feature rows。ML Strategy Approval 仍是模型研究页中的独立人工动作，Agent 无审批工具；
训练创建与取消另外遵守 Agent action approval。Prediction、冻结信号与 ML Backtest 对话串联保留到
Phase 79。

Phase 79 增加 `byq_ml_prediction_create/get`。预测创建只接受 validated ModelArtifact、匹配的人工
ML Strategy Approval 和封闭 execution profile；可信 ML Worker 继续产生不可变 PredictionSnapshot 与
标准 `signal_snapshot`。Backend 为每个 PredictionRun 派生 `backtesttask_ml_*`，并使用既有
`backtest-task.v1` 投影、`byq_backtest_task_get/execute/cancel` 与 BacktestJob，不新增任务表或状态机。
DSH 不加载模型、不读取 raw feature/prediction rows、不排名、不构造信号；ML Agent 也不能调用通用
backtest prepare/create 来替换 ML lineage。Prediction 创建、Backtest 执行和取消各自保持独立审批与审计。
