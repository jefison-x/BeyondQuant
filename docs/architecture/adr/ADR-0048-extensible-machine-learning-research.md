# ADR-0048：可扩展机器学习研究组件、走步验证与市场状态路由

- Status: Accepted
- Date: 2026-09-03
- Accepted: 2026-09-03
- Decision scope: Phase 83–86 机器学习 V2 扩展架构
- Related: ADR-0017、ADR-0020、ADR-0023、ADR-0025、ADR-0028、ADR-0030、ADR-0043、ADR-0044

## 背景

ADR-0043 已证明 LightGBM 训练、不可变模型制品、严格样本外预测、冻结信号和确定性回测的真实闭环。
但该闭环把学习器、五个价格成交量特征、未来收益目标、单次 chronological split 和等权 Top-N
组合固化在一个合同及 Worker 路径中。生产会话提出“按市场状态使用不同模型”的研究要求后，现有系统只能
建议人工创建多个固定研究版本，不能表达 point-in-time 市场状态、多个专家模型、确定性路由或真正的
walk-forward 验证；Product Agent 也不应把这种限制描述为已经支持。

只读 Community 实现允许回测内导入 sklearn、XGBoost 和 LightGBM 并执行 `fit/predict`。它没有独立的
FeatureSet、Target、ValidationPlan、LearnerProfile、ModelBundle 或 RegimeSnapshot，也不能证明每个折的
标签可见性和模型路由时点。其机器学习 import/缓存提示分类为 `REFERENCE_ONLY`，回测内训练、任意用户
Python、VectorBT 和宽依赖 allowlist 分类为 `DROP`；不复制该运行架构。

## 决策

1. 建立 BYQ-owned、代码与 CI 管理的 `ml-capability-registry.v2`。注册表只登记封闭、版本化、已资格验证的
   FeatureSet、Target、ValidationPlan、LearnerProfile、RegimeDefinition、RoutingPolicy 和 PortfolioPolicy；
   Browser、DSH 和用户不能注册 module/class/package/path 或修改运行时能力。
2. `ml-strategy-version.v2` 只引用注册表 identity 与有界参数，并冻结解析后的 capability lock/hash。
   ADR-0043 的 `ml-strategy-version.v1`、FeatureSnapshot、ModelArtifact、PredictionSnapshot 和历史结果保持
   不可变；`v1-compat` 适配器必须产生与旧合同相同的规范化 identity，禁止批量改写历史行。
3. 特征、目标和验证计划分离。首批仍复用 `price-volume-basic-v1` 与 `forward-return-v1`，新增
   `walk-forward-purged-v1`：按交易日生成有限折，训练窗可 expanding 或 rolling，验证窗严格位于训练后，
   prediction/holdout 位于所有模型选择之后；purge 至少覆盖 target horizon，embargo 可配置且有上限。
4. 每个 fold 保存 train/validation session bounds、row/symbol counts、排除原因、source hash、label visibility
   和 metric。汇总指标不能掩盖失败折；选择规则、最小有效折数和 dispersion 必须持久化。
5. 首批 LearnerProfile 包含现有 `byq-lightgbm-cpu-v1` 和新的确定性线性基线
   `byq-ridge-cpu-v1`。每个 profile 独立声明参数 allowlist、runtime lock、输入/输出合同、资源上限、模型格式、
   qualification evidence 和 Worker 支持状态。Ridge 使用非可执行、显式 JSON 数组格式；继续禁止
   pickle/joblib 和任意对象反序列化。
6. 建立 `ml-regime-snapshot.v1`。首个 `hs300-trend-volatility-v1` 只消费 ADR-0030 已冻结的沪深300
   (`000300.SH`) benchmark 日线，以当日及此前的收益、趋势和波动阈值确定 `risk_on|neutral|risk_off`；
   阈值、lookback、缺失/暖机状态和 source hash 全部冻结。缺失证据时输出 `unknown`，不得 future fill 或从
   Web/Provider/Browser 即时补值。
7. 建立 `ml-model-bundle.v1`，引用一组独立、已验证的 expert ModelArtifact 和其训练 regime 条件；建立
   `ml-routing-policy.v1`，按 prediction session 的 RegimeSnapshot 确定性选择 expert。路由没有匹配项或
   状态为 `unknown` 时使用明确登记的 fallback 或 fail closed，不能让模型在线改参数、在线训练或自批准。
8. PredictionSnapshot 逐行增加使用的 model/expert/regime identity；ModelBundle、RegimeSnapshot、router、
   FeatureSnapshot、Stock Pool、Strategy Approval 和 PortfolioPolicy 均进入 SignalSnapshot lineage。
   Backtest 仍只消费冻结信号，不加载模型、不重新判定状态、不执行路由。
9. PortfolioPolicy 从 learner 分离。首批继续提供 `top-n-equal-weight-v1`；风险覆盖只允许以后通过独立、
   已登记、可审计的 policy 增加，不允许藏在模型预测或 prompt 中。
10. Product Agent 只能经 BeyondQuant MCP 读取注册表、提出 v2 研究和查询运行结果。DSH 不训练、不推理、
    不读取 PostgreSQL/模型对象/原始特征；能力说明必须基于注册表，不能根据 Python 包存在推断支持能力。
11. Phase 83 只接受本 ADR、合同、Community 分类和 Phase 84–86 gate，不修改 runtime/schema/API/UI。
    Phase 84 实现注册表、v1 适配、模块化合同、Ridge 和 walk-forward；Phase 85 实现 RegimeSnapshot、
    ModelBundle 和确定性路由；Phase 86 完成 Product API/MCP/Xiaoba/UI 与真实浏览器闭环。每阶段独立
    worktree/branch/PR，前一阶段合并部署验证后才能开始下一阶段。

## 安全与资源边界

- Browser 只访问 Gateway/Product API；Agent-to-Domain 只经 BeyondQuant MCP。
- Worker 不持有 Provider、模型服务、GitHub 或用户凭据，不执行用户 source，不访问 DSH。
- 不引入任意 Python/SQL/URL、上传模型、pickle/joblib、AutoML、GPU、强化学习、在线学习或实时交易。
- 所有 capabilities、fold、expert、bundle、route、rows、sessions、bytes、threads、attempts 和 wall time 有界。
- 模型格式按 profile 资格验证；ONNX 只可在未来经单独 profile qualification 引入，不是通用逃生舱。

## 验收与停止条件

最终真实闭环必须覆盖：durable login → v2 capability selection → frozen pool/benchmark/data → purged
walk-forward → qualified learner artifacts → frozen regime snapshot → model bundle → deterministic routing →
prediction → approved portfolio policy → frozen signal → existing Backtest，并证明 restart、idempotency、
two-user isolation、no-look-ahead、tamper rejection、v1 compatibility、secret-negative projection 和相同
runtime/input 的重复 identity。

若需要动态 import、用户代码、通用反序列化、DSH/Browser/Provider 直接训练、无法证明 fold 或 regime 的
point-in-time 可见性、需要重解释 v1 历史 Artifact、路由必须在 Backtest 时重新计算、跨 workspace 可见，
或单次阶段无法保持有界资源，则停止并提交新的 ADR，不以兼容层绕过。

## 回滚

按 Phase 86 → 84 逆序关闭 v2 Product/Agent 入口和新 profile 调度，保留所有已完成 Artifact 为只读审计
记录。v1 LightGBM 创建、训练、预测、冻结信号和 Backtest 路径持续可用；不得删除、迁移或重算历史 v1
对象。
