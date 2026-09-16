# Backend 剩余领域接口（Agent/学习/工程/策略/Web证据/插件/健康）

2026-09-16，本地维护；Product Phase 97 不变。
审计 Backend 剩余 44 条接口：健康、插件部署私有消费者、Web 证据、因子计算、策略写/读入口、
Agent 角色/运行/授权/审计/审批、学习运行/信号/课程/比较、工程任务。

## 源码核对

- 领域入口经 `_required_agent_context` 解析可信 owner/actor/workspace，并从 payload 剔除身份字段；
  AgentRun 绑定要求 `actor == byq-product-agent-<session>`。
- 策略校验/因子计算经 `_domain_validation_operation`：人类 Product 路径不虚构 AgentRun/不扣纠错额度；
  Agent 路径经领域准入，schema 错误可修正 422、待证据 425、冲突 409。
- 学习/工程写入口原键/版本幂等，跨 owner 拒绝；`learning/receipts` 按 kind+原键只读核对。
- `agents/authorize` 叠加 `user_policy_store` 有效决策，策略拒绝时记录 append-only 审计。
- Web 证据经可信域边界提升为 artifact；`web-evidence-records` 原子创建任务+证据。
- 插件部署内部消费者（`/internal/plugin-center/requests/*`）不暴露 Product/MCP。

## 本批验证

- Backend 测试：`test_agent_run_lifecycle.py`、`test_learning_loop.py`、`test_learning_receipts.py`、
  `test_engineering_tasks.py`、`test_strategy_api.py`、`test_strategy_artifact.py`、
  `test_web_research_api.py`、`test_factor_research.py`、`test_user_policy_receipts.py`、
  `test_domain_correction_admission.py`。

## 登记与限制

- 台账新增 Backend 剩余 44 条接口。
- 之后仅剩 MCP 工具、Worker/Sandbox、`product_assets_import`、8 个人工面与 H5 完整研究。
- 未调用真实模型、未执行生产任务；远端完整 CI 待新候选验证。
