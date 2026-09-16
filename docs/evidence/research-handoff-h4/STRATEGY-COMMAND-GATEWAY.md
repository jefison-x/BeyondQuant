# 策略与 ML 策略写入口 Gateway 转发

2026-09-16，本地维护；Product Phase 97 不变。
审计策略族剩余写入口的 Gateway 转发：草稿保存/删除、校验、版本创建、审批创建，
以及 ML 策略建版/审批两条 `_ml_command` 入口。

## 源码核对

- 全部写入口先经 `_product_principal` 校验浏览器会话，再由 `_trusted_agent_headers`
  从服务端会话派生 `x-byq-owner/actor/workspace`；浏览器载荷中的身份字段不能覆盖。
- `product_strategy_draft_save`（1132）/`product_strategy_version_create`（1184）/
  `product_strategy_validate`（1173）原样转发载荷（含 `idempotency_key`/`trace_id`），
  Backend 按原键与完整输入摘要去重；validate/version 经 `_domain_validation_operation`
  领域准入（可修正 422、待证据 425、冲突 409），MCP SDK schema 错误最多一次不同输入修正。
- `product_strategy_draft_delete`（1143）转发 Backend 固定键软删除 `strategy-draft-delete-<id16>`，重复幂等。
- `product_strategy_approval_create`（1195）强制 `reviewer_principal` 为当前会话 subject，
  绑定原可信 actor；Backend 校验版本 validated 且属于同一 task。
- `product_ml_strategy`（891）/`product_ml_approval`（896）走 `_ml_command`：字段白名单
  （多/少字段 422），服务端生成 `product-ml-<prefix>-<nonce>` 同时作为 `trace_id` 与
  `idempotency_key`，拒绝浏览器提供 `trace_id`/`idempotency_key`。
- 写请求传输失败统一 `operation_outcome_unknown`，不自动重发；按原键/原命令恢复。

## 本批验证

- `test_ml_commands_reject_browser_identity_fields_and_generate_them_server_side`：
  拒绝浏览器 `trace_id`，服务端生成并令 trace=idempotency。
- `test_product_strategy_version_create_proxy`：版本创建原样转发载荷并返回 201。
- `test_product_strategy_draft_and_projection_routes_forward_owner_headers`：草稿保存/删除转发 owner 头。
- 参数化 `test_product_business_proxy_routes_forward_owner_context`：覆盖 drafts/approvals/validate 的 owner/actor 转发。
- 隔离容器（保留镜像 + 当前工作树只读挂载、`--network none`）Gateway 全量 230 项通过。
- Backend 侧领域准入、原键回执与纠错资格证据见
  [STRATEGY-VERSION-QUALIFICATION](./STRATEGY-VERSION-QUALIFICATION.md) 及
  `services/backend/tests/test_strategy_api.py`、`test_ml_strategy.py`。

## 登记与限制

- 台账新增 `product_strategy_draft_save`、`product_strategy_draft_delete`、`product_strategy_validate`、
  `product_strategy_version_create`、`product_strategy_approval_create`、`product_ml_strategy`、
  `product_ml_approval` 七条 Gateway 写入口。
- 仅登记这七条；Backend 其余写入口、其他 Gateway 族与 H5 完整研究不随之完成。
- 未调用真实模型、未执行生产任务；远端完整 CI 待新候选验证。
