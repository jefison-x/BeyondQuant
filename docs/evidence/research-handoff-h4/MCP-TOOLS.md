# DSH MCP 工具逐项审计

2026-09-16，本地维护；Product Phase 97 不变。
审计 `services/mcp/src/server.ts` 全部 81 个 `byq_*` 工具（本批新增 80；`byq_strategy_version_create`
已在策略版本资格中登记）。

## 源码核对

- 工具经 MCP 服务认证，每请求由可信 HTTP 头构造 owner/workspace/session/root；工具参数不能替代
  可信根身份。领域执行仍由 Backend 逐工具校验角色、归属与原键。
- 通用封装：`domain-admission.ts`（领域调用准入）、`continuation-admission.ts`（后台续接准入）、
  `request-validation.ts`（参数校验）、`write-outcome.ts`（写结果分类：成功/可修正/待证据/未知）。
- 写工具不生成业务身份、不自动重放；原键/回执归 Backend，同键异输入拒绝；未知结果不退还纠错额度。
- 读工具只做有界转发，不创建领域对象。因子/策略/ML 等经领域准入的工具沿用 ADR-0073 逐项资格。

## 本批验证

- MCP 测试：`contract-test.ts`、`transport-resilience-test.ts`、`domain-server-wire-test.ts`，
  以及按域 `backend-health-test.ts`、`product-help-test.ts`、`feedback-test.ts`、
  `workflow-card-test.ts`、`stock-pool-test.ts`、`paper-trading-test.ts`、`agent-test.ts`、
  `data-demand-test.ts`、`market-data-test.ts`、`backtest-test.ts`、`ml-research-test.ts`、
  `factor-research-test.ts`、`strategy-test.ts`、`learning-test.ts`、`research-test.ts`。
- 传输与恢复证据见 [MCP-TRANSPORT](./MCP-TRANSPORT.md)；策略版本资格见
  [STRATEGY-VERSION-QUALIFICATION](./STRATEGY-VERSION-QUALIFICATION.md)。

## 登记与限制

- 台账新增 80 个 MCP 工具具名条目（1 个已在策略资格登记）。
- 仅剩 Worker 4、signal-sandbox 2、`product_assets_import` 1 与 8 个人工面、H5 完整研究。
- 未调用真实模型、未执行生产任务；远端完整 CI 待新候选验证。
