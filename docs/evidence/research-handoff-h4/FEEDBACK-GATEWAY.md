# 产品反馈 Gateway 转发

2026-09-16，本地维护；Product Phase 97 不变。
审计产品反馈族 15 条 Gateway Product 入口：选项/目录/创建/回执/详情/修订/预览/提交/撤回/更新，
以及管理员审核读取与动作。

## 源码核对

- 普通入口经 `_product_principal` + `_feedback_headers`：只转发粗粒度、非标识客户端上下文
  （浏览器族/OS 族），从不转发 User-Agent；owner 由可信会话派生。
- 提交/撤回/更新等写入口原键透传，Backend 保留原命令回执；缺回执按 `feedback/receipts`
  或 moderation receipts 按原键核对，不重复提交。
- 审核入口经 `_feedback_moderator_headers`：要求 admin 角色，审核权限是平台级，且**不传递**
  审核者或提交者个人 workspace 身份。
- 写请求 5xx/网络失败→`operation_outcome_unknown`；读请求→`backend_unavailable`；
  非 admin 审核→403 `product_forbidden`；Backend 4xx→`product_domain_rejected`。

## 本批验证

- `test_feedback_product_api_is_same_origin_paged_and_forwards_only_coarse_client_context`：
  同源、分页、仅转发粗粒度客户端上下文。
- `test_feedback_moderation_requires_admin_session_and_never_forwards_workspace_identity`：
  审核管理员门禁、不转发 workspace 身份、原键回执读取。
- 前端 `apps/frontend/src/api/feedback.ts` 与反馈页保持同一 Product 路径。
- 恢复证据见 [FEEDBACK-RECOVERY](./FEEDBACK-RECOVERY.md)、
  [FEEDBACK-MODERATION-RECOVERY](./FEEDBACK-MODERATION-RECOVERY.md)、
  [FEEDBACK-HUB-RECOVERY](./FEEDBACK-HUB-RECOVERY.md)。
- 隔离容器（保留镜像 + 当前工作树只读挂载、`--network none`）Gateway 全量 230 项通过。

## 登记与限制

- 台账新增反馈族 15 条 Gateway 入口（普通 9 + 审核 6）。
- 仅登记这些；Backend 反馈入口、其他 Gateway 族、人工面与 H5 完整研究不随之完成。
- 未调用真实模型、未执行生产任务；远端完整 CI 待新候选验证。
