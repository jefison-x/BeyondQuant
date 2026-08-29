# Machine Learning Strategy Delivery Plan

维护者于 2026-08-29 选择先完成可靠 LightGBM 最小闭环，再评估 HIST。本计划受 ADR-0043 和
`machine-learning-research.md` 约束；每一 Phase 使用独立 worktree/branch/PR，并在合并门禁停止。

## Phase 71 — Contract baseline（`COMPLETE`）

- 检查并分类 Community ML/strategy/backtest 实现；
- 接受 ADR-0043；
- 冻结 ML strategy、TrainingRun、FeatureSnapshot、ModelArtifact、PredictionSnapshot 和冻结信号合同；
- 固定 LightGBM 4.7.0 / Python 3.13 CPU execution profile、禁止项、阶段顺序和验收/停止条件；
- 不改 runtime、database、API、MCP、frontend 或 Compose。

## Phase 72 — Trusted training and model artifact（`COMPLETE`）

- 实现 `ml-strategy-version.v1` validation/version/approval；
- 实现 owner/workspace-scoped TrainingRun、claim/lease/retry/idempotency；
- 从冻结 Data Plane input 构建 `price-volume-basic-v1` FeatureSnapshot；
- 增加独立无凭证 LightGBM CPU Worker，生成 hash-verified native text model object；
- 持久化 ModelArtifact、validation metrics 和完整 lineage；
- 只交付 Backend/domain/worker contract，不做 prediction、signal、Backtest 或 UI。

## Phase 73 — Out-of-sample prediction and signal closure（`NEXT`）

- 验证 model bytes/hash/runtime/feature order 后执行 prediction-only split；
- 生成 immutable PredictionSnapshot，按确定性 score/symbol 排名；
- 使用 approved ML strategy 的 closed top-N policy 生成 ADR-0017 SignalSnapshot；
- 接入现有 Backtest submit/approval/manifest，不让 Backtest 加载模型；
- 验证 no-look-ahead、tamper、重复 identity、restart 和端到端 regression。

## Phase 74 — Product closure（`PENDING`）

- 实现 Gateway/Product API typed contract 和模型研究界面；
- 用户可选择 frozen pool、日期窗口、封闭参数并查看训练状态、指标、预测排名、信号和 Backtest；
- 完成 Community frontend `REPLACE`/`PORT_UX` 分类、loading/error/empty/stale、desktop/mobile；
- 完成真实 PostgreSQL/Compose、two-user、restart、same-origin Network、Chrome MCP、accessibility 和
  no-mock golden journey。

## HIST gate

Phase 74 合并前不得设计或实现 HIST。之后必须以新 ADR 明确图关系来源、历史行业/概念可见性、模型
runtime、资源上限和与现有 Feature/Model/Prediction contracts 的复用关系。HIST 不得以“模型适配器”
名义绕过 point-in-time 或独立 Phase gate。
