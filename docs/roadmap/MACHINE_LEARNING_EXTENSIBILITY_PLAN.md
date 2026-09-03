# Machine Learning Extensibility Delivery Plan

本计划受 ADR-0048 和 `machine-learning-extensibility.md` 约束。Phase 83–86 严格串行，每阶段使用独立
worktree、branch、PR，完成自动验证、CI-green squash merge 和生产部署验证后才进入下一阶段。

## Phase 83 — Extensibility contract baseline（`COMPLETE`）

- 检查并分类 Community 机器学习路径；
- 接受 ADR-0048；
- 冻结 capability registry、v2 strategy、v1 adapter、walk-forward、Ridge、RegimeSnapshot、ModelBundle、
  RoutingPolicy 与 Product/Agent 边界；
- 不修改 runtime、database、API、MCP、frontend 或 Compose。

## Phase 84 — Capability registry, Ridge and walk-forward（`COMPLETE`）

- 实现代码管理且 CI qualification 的 `ml-capability-registry.v2` 与安全 Product metadata；
- 把 FeatureSet、Target、ValidationPlan、LearnerProfile、PortfolioPolicy 从固定 LightGBM 路径解耦；
- 保持 v1 identity/result compatibility；
- 实现 purged walk-forward fold manifest、Ridge JSON model、Worker profile dispatch 和 fold metrics；
- 完成 Backend/Worker/PostgreSQL restart、idempotency、tamper、no-look-ahead 和资源上限测试；
- 不实现 regime、bundle、routing、MCP 或 UI。

## Phase 85 — Regime snapshot, expert bundle and routing（`AUTHORIZED`）

- 实现 frozen HS300 trend/volatility RegimeSnapshot；
- 实现 bounded expert training、ModelBundle、fallback 和 deterministic router；
- 扩展 PredictionSnapshot/SignalSnapshot lineage，但 Backtest 继续只消费冻结信号；
- 验证 benchmark 缺失、warmup、阈值边界、route tamper、restart 和 two-user isolation；
- 不实现 Browser/Agent 入口。

## Phase 86 — Product and Xiaoba closure（`BLOCKED_BY_PHASE_85`）

- Gateway/Product API 提供动态 capability、v2 create/run/detail 和分页结果投影；
- 模型研究页去除静态能力数组，支持单模型、walk-forward 和市场状态专家方案，保持详情懒加载；
- BeyondQuant MCP 和 Xiaoba skill 使用最小权限读取/提出/执行，逐动作审批与现有任务合同不变；
- 完成真实 PostgreSQL/Compose、Worker/Gateway restart、two-user、no-mock Product API、Chrome desktop/mobile、
  same-origin、空 Console、Community checklist 和性能验收。

## 非目标

HIST、AutoML、GPU、强化学习、在线学习、任意用户模型代码/上传、实时交易和 ONNX 通用执行器均不在本计划。
