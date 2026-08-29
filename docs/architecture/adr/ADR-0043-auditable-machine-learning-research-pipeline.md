# ADR-0043：可审计机器学习研究与 LightGBM 最小闭环

- Status: Accepted
- Date: 2026-08-29
- Accepted: 2026-08-29
- Decision scope: Phase 71–74 LightGBM 训练、模型制品、样本外预测和冻结信号
- Related: ADR-0017、ADR-0020、ADR-0023、ADR-0025、ADR-0028、ADR-0030

## 背景

BYQ 当前可以将 approved immutable StrategyVersion 和冻结的 point-in-time 市场输入转换为
`signal_snapshot`，并由确定性 Backtest engine 消费。现有策略静态检查能够描述部分机器学习
导入，但 `byq-signal-python-v1` 执行配置明确不允许任意训练，也不拥有模型制品、训练数据清单
或样本外预测合同。静态检查通过不能被解释为机器学习可执行。

只读 Community 实现允许用户策略在 Backtest Worker 中导入 LightGBM 等库并在策略调用中
`fit/predict`，同时以 AST 规则禁止在历史循环内重复训练。它没有独立 TrainingRun、不可变
ModelArtifact、point-in-time FeatureSnapshot、严格的 out-of-sample PredictionSnapshot 或训练与
撮合隔离。该实现是风险证据，不是可迁移架构。

维护者于 2026-08-29 授权将可靠的 LightGBM 最小闭环作为下一开发目标，并要求在证明训练、
制品、样本外预测和冻结信号全链路后再引入 HIST。

## 决策

1. 建立封闭 `ml-strategy-version.v1`。它是 BYQ Domain Artifact，不包含任意 Python source，固定
   feature set、future-return target、训练/验证/预测窗口、LightGBM 参数 allowlist、模型选择指标和
   prediction-to-signal policy。验证后不可变；生成可回测信号仍要求独立 human approval。
2. 建立 `ml-training-run.v1` 状态机：`waiting_for_data → queued → running → completed|failed|cancelled`。
   owner/workspace、幂等键、输入 identity、attempt、safe error 和结果引用必须持久化。失败或重试
   不得覆盖既有成功制品。
3. 训练只消费 BYQ Data Plane 生成的不可变 `ml-feature-snapshot.v1`。股票池 snapshot 冻结研究意图；
   index/dynamic pool 必须按每个 session 的历史 definition/materialization evidence 解析成员，不能把
   当前成员倒灌到训练历史。首版仅允许 canonical adjusted research bars、交易日历和封闭的价格/成交量
   派生特征；Browser、DSH、Web
   evidence、Provider response、任意 SQL/Python/URL 和上传数据不得成为训练输入。
4. 每一行显式保存 `feature_as_of`、split 和可选 `label_end_date`。训练/验证标签的结束时点必须不晚于
   各自 split end；预测 split 不得包含标签。三个窗口严格按时间排序，股票池成分和声明数据按当时
   可见性解析，禁止 current-membership replay、随机切分和 future fill。
5. 训练在独立 trusted ML Worker 中执行。Worker 不持有 Tushare/model/provider credential，不执行
   用户 source，不访问 DSH，也不参与 Backtest 撮合。首版 runtime 固定为 CPU、Python 3.13、
   LightGBM 4.7.0；使用固定 seed、固定 thread count、`deterministic=true` 和固定 row/column mode。
   复现承诺限定在相同输入 hash 和相同 runtime/image identity 内。
6. `ml-model-artifact.v1` 保存模型格式、feature order、target、split、参数、训练数据/运行时/image
   identity、指标、provenance 和对象 SHA-256。模型使用 LightGBM 原生文本格式，禁止 pickle/joblib、
   arbitrary Python object、任意文件路径和 Browser 上传模型。大对象保存在 BYQ object store；领域
   Artifact 只保存 content-addressed reference 和有界元数据。
7. `ml-prediction-snapshot.v1` 只由受信任 Worker 使用已验证 ModelArtifact 对冻结 prediction split
   生成，逐行保存 session、symbol、finite score、rank、model/feature identity。PredictionSnapshot
   不可修改，不把测试标签或未来实现收益暴露为预测输入。
8. 受批准的 `ml-strategy-version.v1` 按封闭、版本化 policy 将 PredictionSnapshot 转换为现有
   ADR-0017 `signal_snapshot`。Signal lineage 必须包含 ML strategy、ModelArtifact、
   FeatureSnapshot、PredictionSnapshot 和 Stock Pool snapshot；现有 Backtest Worker 继续只消费
   冻结信号，不加载 LightGBM 或重新训练。
9. LightGBM、数据/特征组装、组合转换和 Backtest 分属明确组件；不得建设第二 generic agent harness，
   不得让 Product DSH 或 Browser 直接训练、读 PostgreSQL、调用 Provider 或写应用 source。
10. Phase 71 只接受本 ADR、合同、Community 分类和后续 gate，不改 runtime/schema/API/UI。Phase 72
    实现训练与模型制品；Phase 73 实现严格样本外预测、冻结信号和 Backtest 衔接；Phase 74 完成
    Product API/UI、恢复/隔离/Chrome 验收。每阶段独立 worktree/branch/PR，前一阶段合并前不得开始。
11. HIST 明确不属于 Phase 71–74。只有 LightGBM golden journey 在真实 PostgreSQL 和 Product API
    下证明无泄漏、可复现、可审计并完成冻结信号回测后，维护者才能授权新的 HIST ADR/Phase。

## 首版封闭范围

- learner：LightGBM regression，仅预测未来固定交易日收益；
- features：BYQ-owned `price-volume-basic-v1`，首版固定收益、波动、量价相对值等明确字段；
- split：一个显式 chronological train/validation/prediction 定义，不支持随机 K-fold；
- selection：validation metric 选择 best iteration，prediction 完全位于 validation 之后；
- signal policy：有界 top-N、显式调仓 cadence、权重/数量与退出规则；
- limits：symbol、session、row、feature、boosting round、runtime、artifact bytes 全部有界并 fail closed。

精确字段和上限由 `docs/contracts/machine-learning-research.md` 固定；实现不得用未声明字段扩大能力。

## 后果

- 模型训练成为可恢复、可追溯的领域流程，而不是 Backtest 中的隐式副作用。
- 相同 signal snapshot 仍可由现有确定性 engine 重放；引入 LightGBM 不改变撮合语义。
- 首版能力较窄，但能真实证明数据时点、模型 identity 和样本外结果，避免用复杂模型掩盖泄漏。
- 新增受信任 CPU Worker 和 LightGBM 精确依赖会增加 image、CI 和资源治理成本。

## 外部依赖证据

2026-08-29 核对官方 [PyPI release](https://pypi.org/project/lightgbm/)：LightGBM 4.7.0 于
2026-07-18 发布，声明 Python 3.13 支持并提供 Linux x86-64/aarch64 wheel。官方
[Python package 文档](https://lightgbm.readthedocs.io/en/stable/Python-Intro.html)定义训练、预测和原生
文本 `save_model`/load 路径。Phase 72 必须在精确 build image 中重新验证 wheel、license、import、
single-thread deterministic probe 和 model round-trip；本 ADR 的观察不代替 runtime qualification。

## 拒绝的替代方案

- 在现有 signal sandbox 中开放 `lightgbm` 和 `.fit()`：混合训练/推理，缺少模型制品和资源隔离。
- 复制 Community 的回测内训练：无法证明严格样本外，且重引入旧 runtime/storage coupling。
- 保存 pickle/joblib：可执行对象边界不安全，也不利于跨版本审计。
- Browser 上传 CSV、模型文件或任意 feature Python：绕过 Data Plane provenance 和 Product 权限边界。
- 首阶段同时引入 HIST、AutoML、GPU、在线学习或强化学习：无法用最小闭环定位数据与方法问题。
- 把训练放入 DSH plugin/Agent：量化训练和领域不变量属于 BYQ，不是 generic Agent capability。

## 验收与停止条件

Phase 72–74 的最终 golden journey 必须覆盖：durable login → owner-scoped ML strategy → 冻结股票池与
时间点数据 → 可恢复训练任务 → immutable model → prediction-only split → approved policy → immutable
signal → existing Backtest，并证明 restart、idempotency、two-user isolation、no-look-ahead、tamper
rejection、secret-negative projection 和相同 runtime/input 的重复 identity。

出现以下任一情况必须停止，不 workaround：需要 Provider/Browser/DSH 直接训练或访问业务库；无法
证明 feature/label visibility；需要 pickle/joblib 或任意用户代码；LightGBM 精确版本/CPU wheel/许可
不可验证；训练结果只能依赖未冻结数据；模型制品不能内容寻址；Backtest 必须加载模型；跨 workspace
可见；或需要同时引入 HIST/AutoML/GPU/在线学习。

## 回滚

停止并移除 ML Worker 调度和 Product 入口，保留已经完成的 TrainingRun、FeatureSnapshot、
ModelArtifact、PredictionSnapshot 和 SignalSnapshot 作为只读审计记录。既有规则策略、signal producer
和 Backtest 路径不变；不得删除或重解释历史 ML Artifact。
