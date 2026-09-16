# 会话目录与续接 Backend 内部接口

2026-09-16，本地维护；Product Phase 97 不变。
审计 Backend 会话目录 `/v1/product/conversations` 与私有续接/生命周期/回执消费者共 18 条入口。

## 源码核对

- 会话目录入口经 `_conversation_owner`（可信 owner）作用域操作，读写均按 owner 过滤；
  消息追加区分 user/assistant 角色，未知角色拒绝。
- 私有 `/internal/agent-lifecycle/{conversation_id}` 与 `/internal/domain-call-evidence/{conversation_id}`：
  要求可信 owner==actor 头、workflow/workspace 身份一致，否则 401/403/422；由 `agent_store`
  校验持久归属，普通会话/Agent API 仍保留活动上下文校验（ADR-0063）。
- 私有 `/internal/task-continuation/*`：`_continuation_consumer_context` 要求 Gateway 目录消费者身份；
  claim/peek/dispatch/block/receipt 均要求精确 reservation/reason/字段，未知字段 422；
  预算/期限/取消由既有续接机制约束（ADR-0072）。
- `register_research_submission_watch` 与 `consume_research_submission_watches` 按会话消费有界回执，
  不跨租户；`record_domain_schema_rejection` 仅接受私有 Agent schema 拒绝。

## 本批验证

- Backend 测试：`test_conversation_catalog.py`、`test_agent_lifecycle_api.py`、
  `test_agent_run_lifecycle.py`、`test_continuation_scope.py`、`test_continuation_budget_ledger.py`、
  `test_continuation_notifications.py`、`test_domain_call_evidence.py`、
  `test_research_receipt_watches.py`、`test_research_submission_reconciliation.py`。
- H1–H3 验收见 [research-handoff-h2](../research-handoff-h2/AUDIT.md)、
  [research-handoff-h3](../research-handoff-h3/AUDIT.md)。

## 登记与限制

- 台账新增会话目录与续接 18 条入口（含私有内部消费者）。
- 其余 Backend 族、MCP 工具、Worker/Sandbox、人工面与 H5 完整研究不随之完成。
- 未调用真实模型、未执行生产任务；远端完整 CI 待新候选验证。
