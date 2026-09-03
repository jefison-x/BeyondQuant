# Machine Learning Extensibility Contract

本合同落实 ADR-0048，并补充 ADR-0043；后者的 v1 合同和历史 Artifact 继续有效。

## 组件图

```text
ml-capability-registry.v2 (code + CI qualified)
  ├─ feature-set.v1
  ├─ target-definition.v1
  ├─ validation-plan.v1
  ├─ learner-profile.v1
  ├─ regime-definition.v1
  ├─ routing-policy.v1
  └─ portfolio-policy.v1
             ↓ resolved capability lock
ml-strategy-version.v2 + human approval
             ↓ frozen pool/data/benchmark
feature snapshot + fold manifest + regime snapshot
             ↓ trusted ML Worker
model artifact(s) → model bundle → routed prediction snapshot
             ↓ approved portfolio policy
signal snapshot → existing deterministic Backtest
```

## `ml-capability-registry.v2`

注册表记录以下公共字段：`id`、`kind`、`contract_version`、`display_name`、`status`、`parameters`、
`input_contract`、`output_contract`、`limits`、`runtime_profile`、`qualification` 和 `content_sha256`。
`status` 只能是 `qualified|disabled|blocked`；只有 `qualified` 可创建新研究。公共投影不包含对象路径、镜像
仓库凭据、内部命令或 qualification 原始日志。

注册表由源码静态声明和 CI 验证产生。重复 ID、未知引用、参数越界、profile/runtime 不匹配、禁止模型格式、
未验证依赖或 capability hash 漂移均 fail closed。Frontend 必须读取 Product API 投影，不维护静态能力数组。

## `ml-strategy-version.v2`

```json
{
  "schema_version": "ml-strategy-version.v2",
  "name": "沪深300市场状态专家模型",
  "feature_set": {"id": "price-volume-basic-v1", "parameters": {}},
  "target": {"id": "forward-return-v1", "parameters": {"horizon_sessions": 5}},
  "validation_plan": {
    "id": "walk-forward-purged-v1",
    "parameters": {
      "mode": "expanding",
      "train_sessions": 480,
      "validation_sessions": 60,
      "step_sessions": 60,
      "folds": 4,
      "purge_sessions": 5,
      "embargo_sessions": 0
    }
  },
  "learner": {"profile": "byq-lightgbm-cpu-v1", "parameters": {}},
  "regime": {"definition": "hs300-trend-volatility-v1", "enabled": true},
  "routing_policy": {"id": "regime-expert-map-v1", "fallback": "neutral"},
  "experts": [
    {"key": "risk_on", "learner": {"profile": "byq-ridge-cpu-v1", "parameters": {"alpha": 0.5}}, "training_regimes": ["risk_on", "neutral", "risk_off"]},
    {"key": "neutral", "learner": {"profile": "byq-ridge-cpu-v1", "parameters": {"alpha": 1.0}}, "training_regimes": ["risk_on", "neutral", "risk_off"]},
    {"key": "risk_off", "learner": {"profile": "byq-lightgbm-cpu-v1", "parameters": {}}, "training_regimes": ["risk_on", "neutral", "risk_off"]}
  ],
  "portfolio_policy": {"id": "top-n-equal-weight-v1", "parameters": {"top_n": 20, "rebalance": "weekly"}},
  "development_window": {"start": "2020-01-01", "end": "2025-12-31"},
  "prediction_window": {"start": "2026-01-01", "end": "2026-06-30"}
}
```

Backend 解析引用后冻结 `capability_lock`，其中包含每个组件的 identity/hash、有效参数、runtime lock 与
组合 hash。未知字段、未知或非 qualified capability、客户端提交 hash/runtime/object reference 一律拒绝。

## V1 兼容

`ml-strategy-version.v1` 保持原 schema、identity 和路径。`v1-compat` 只在运行边界把其固定语义映射为：

- `price-volume-basic-v1`；
- `forward-return-v1`；
- `single-chronological-v1`；
- `byq-lightgbm-cpu-v1`；
- `top-n-equal-weight-v1`；
- no regime / no routing。

适配结果不得写回或改变 v1 Artifact；兼容测试必须使用已有 golden fixtures 验证旧 identity、模型和信号不变。

## Walk-forward 与无前视

`walk-forward-purged-v1` 限制为 2–12 folds、每折至少 60 个训练 session 和 10 个验证 session、总 session
不超过既有 2,500 上限。`purge_sessions >= target.horizon_sessions`；embargo 为 0–20。fold 必须按 canonical
trading calendar 生成，训练标签结束日早于 validation start，验证标签结束日不晚于 validation end；最终
prediction rows 无 target/label。

每折持久化 `fold_id`、窗口、purge/embargo、source identities、eligible/excluded counts、model identity、
metrics 和 safe failure；选中模型作为本次 TrainingRun 的不可变 ModelArtifact，其他折保留内容哈希而不重复
保存大对象。有效折不足计划最小值时整个 run 失败；汇总至少返回 metric median、mean、standard
deviation、worst fold 和有效折数。

## Learner profiles 与模型格式

- `byq-lightgbm-cpu-v1`：保持 ADR-0043 精确 runtime、参数和 native text 格式。
- `byq-ridge-cpu-v1`：固定 CPU/single-thread/seed，参数仅 `alpha`（有限范围）和 `fit_intercept`；训练前按
  每折训练数据冻结 mean/scale，模型用 `ridge-linear-json-v1` 保存 feature order、finite coefficients、
  intercept、normalization 和 runtime identity。禁止 pickle/joblib。

训练调度必须按注册表解析到 Worker 内部受信实现。不能从 capability 字段拼接 import、类名、命令或路径。

## 市场状态、模型包与路由

`hs300-trend-volatility-v1` 的唯一 benchmark 是 `000300.SH`。Snapshot 对每个 prediction session 只使用
该日及以前的 frozen adjusted benchmark close，计算 20/60 session return、20 session realized volatility
和 60 session moving-average distance。阈值来自已批准策略并受注册表范围限制；分类算法和边界值由测试
冻结。不足 60 个 session 或证据不完整时为 `unknown`。

Phase 85 冻结分类顺序与边界：先以 `return_20 <= risk_off_return_20_max`、
`volatility_20 >= risk_off_volatility_20_min` 或 `ma_distance_60 <= risk_off_ma_distance_60_max`
判定 `risk_off`；否则当 `return_60 >= risk_on_return_60_min` 且
`ma_distance_60 >= risk_on_ma_distance_60_min` 时判定 `risk_on`，其余为 `neutral`。比较均包含边界。
训练准备额外冻结 development start 前最多 120 个自然日，以取得 60 个 canonical session 暖机数据；
窗口外数据只参与状态/特征暖机，不产生训练标签。

`ml-model-bundle.v1` 至少包含 `risk_on|neutral|risk_off` 中两个 expert 和一个明确 fallback，最多 4 个
expert。每个 expert 是独立 ModelArtifact，使用相同 FeatureSet/Target/feature order，但允许不同 qualified
LearnerProfile 或参数。Bundle 保存 expert map、fold evidence、selection rule、source identities 和 hash。

`regime-expert-map-v1` 只根据冻结 RegimeSnapshot 查表选择 expert；不得访问当前时间、网络、Provider、账户、
未来收益或 prompt。Prediction row 保存 `regime`、`regime_snapshot_id`、`expert_key`、`model_artifact_id`、
score 和 rank。每个 session 只在相同 expert 内进行确定性 `(score DESC, symbol ASC)` 排名。

每个 expert 的 `training_regimes` 只能是 `risk_on|neutral|risk_off` 的非空子集；`unknown` 永不成为训练
条件。expert key 只可为三个已知状态，缺少精确状态 expert 时（包括 `unknown`）只使用已批准
fallback。一个 TrainingRun 可持久化多个独立 expert ModelArtifact，但其完成引用指向唯一 ModelBundle；
Bundle、expert、RegimeSnapshot 和 FeatureSnapshot 的 embedded hash/Artifact lineage 任一不一致即拒绝预测。

## Product、Agent 和性能投影

Product API 的 capability、研究目录、运行目录和结果均分页、有界；详情及预测行按选中 tab/page 懒加载。
Frontend 不可硬编码 capability。小巴先读取注册表，再说明或提出研究；用户未要求市场状态时不自动扩大为
多专家训练。小巴必须明确区分“系统支持”“本研究已配置”“本次运行已成功”。

Browser/Agent 均看不到 raw feature rows、model bytes/object key、raw fold payload、内部 Worker request 或
DSH event。公开失败返回稳定 safe code、失败阶段和可行动建议。
