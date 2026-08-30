# ADR-0044：Product Agent 产品能力目录与任务化接入边界

- Status: Accepted
- Date: 2026-08-30
- Accepted: 2026-08-30
- Decision scope: Phase 75–79 产品帮助、回测任务封装与机器学习 Agent 接入
- Related: ADR-0009、ADR-0012、ADR-0017、ADR-0018、ADR-0024、ADR-0025、ADR-0031、ADR-0033、ADR-0038、ADR-0043

## 背景

Phase 74 已完成浏览器端 LightGBM 研究闭环，但 Product Agent 的领域技能仍集中于市场、
因子、规则策略和底层回测工具。用户询问产品功能时缺少版本化的 BYQ 使用知识；回测提交仍要求
模型处理内部 Artifact、冻结 bars 和 signals；机器学习 Product API 尚未形成 MCP、角色和技能边界。

## 决策

1. BYQ 建立版本化 `product-capability-catalog.v1`，统一记录用户可见模块、固定 route、受众、
   前置条件、Product API 能力和 Agent 支持等级。目录是产品帮助的规范输入，不授予执行权限。
2. Product DSH 使用精简的 `byq-product-guide` 技能进行意图分类，并按领域按需读取构建镜像中
   的参考资料。Production Product DSH 仍不挂载应用源码。
3. Agent 查询产品说明时只使用有界、只读 MCP 投影。导航只返回 BYQ 固定 route id，不接受
   model、Browser 或外部资料提供任意 URL。
4. 明确区分 `EXPLAIN`、`NAVIGATE`、`READ`、`PROPOSE`、`EXECUTE` 和 `UNAVAILABLE`。
   说明类请求不得产生领域写；执行类请求仍逐动作授权、审批、审计。
5. 回测新增任务化 facade，聚合既有 ResearchTask、Approval、MarketReadiness、SignalProducerJob
   和 BacktestJob，不建立第二个 Workflow 或重复业务状态。模型不再构造 raw bars/signals。
6. 机器学习 Agent 只能经 BYQ MCP 创建和读取领域意图。DSH 不训练、不推理、不读取模型对象；
   trusted ML Worker、不可变 Artifact、无前视和 frozen-signal Backtest 边界保持不变。
7. 新增 ML 专业角色时使用最小工具 allowlist。策略批准、训练、预测、回测等 consequential action
   必须使用现有 BYQ Approval/action reference，不允许 Agent 自行批准。
8. WorkflowTrace 只增加封闭、版本化的 Product help、Backtest task 和 ML research 投影；card
   不是 command，Domain 状态必须由 Gateway 重新读取并 owner/workspace 校验。
9. Phase 75–79 串行交付，每阶段独立 worktree、branch、PR。Phase 75 仅合同与目录；Phase 76
   产品技能；Phase 77 回测任务；Phase 78 ML 创建/训练；Phase 79 预测/信号/回测和浏览器闭环。

## 安全与停止条件

- Browser 仍只访问 Gateway/Product API；Agent-to-Domain 仍只经 BeyondQuant MCP。
- 不增加实盘券商、HIST、AutoML、GPU、在线学习、任意 Python/SQL/URL 或模型上传。
- 不把 Product API 暴露给 DSH，不让 DSH 访问 PostgreSQL、Provider 或对象存储。
- 无法保持逐动作审批、workspace 隔离、无前视或不可变 lineage 时停止，不使用 prompt 绕过。

## 验收

- 能力目录覆盖全部稳定用户路由，并由 CI 检查唯一 identity、固定 route、受众和支持等级。
- 每个 Agent `EXECUTE` 能力必须在后续阶段对应真实 MCP、角色 allowlist、授权和审计测试。
- 真实用户问法区分“怎么用”“帮我准备”“帮我执行”，且说明类请求零 mutation。
- Phase 79 通过 PostgreSQL、restart、two-user、no-mock Product API 和 Chrome MCP 验收。

## Community 分类

只读 Community 的 Agent、Strategy、Backtest、Paper Trading、用户设置与帮助资料只提供
`PORT_UX`/`PORT_LAYOUT` 证据。旧 Agent API/SSE、PydanticAI/Hermes、direct internal API、
VectorBT、BaoStock 和 AKShare 均为 `DROP`/`REPLACE`，不复制实现。

## 回滚

按 Phase 逆序禁用新 Agent tool/role/card，并保留已产生的 BYQ Domain Artifact 和审计记录。
产品能力目录可退回上一版本；既有浏览器 ML、策略、信号和 Backtest 能力不受影响。
