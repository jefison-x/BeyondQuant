# ML 研究 Gateway 转发

2026-09-16，本地维护；Product Phase 97 不变。
审计 ML 研究族 11 条 Gateway Product 入口：能力/选项/目录/工作区/回执核对/训练/预测读取与命令。

## 源码核对

- 读入口：`/ml/capabilities`、`/ml/options`、`/ml/studies`（`query/status/limit/offset` 分页）、
  `/ml/workspace`（并行聚合 workspace 与 backtests catalog，按允许字段投影，剔除内部引用）、
  `/ml/training-submissions/reconcile`（按浏览器原键核对，不新建）、`/ml/training-runs/{id}`、
  `/ml/prediction-runs/{id}`、`/ml/prediction-runs/{id}/rows`（有界分页）。
- 写入口：`POST /ml/training-runs`（202）先登记 `training-submissions` 取得回执 watch：
  已 confirmed 直接按 run_id 回读，已 rejected 返回 409，awaiting_receipt 返回 503 不重复发送；
  POST 超时后在有界窗口内按原键 reconcile，成功标记 `create_response_timeout` 而不重复创建。
  `POST /ml/prediction-runs`（202）与 `POST /ml/training-runs/{id}/cancel` 走同一 `_ml_command` 原键合同。
- 全部写命令字段白名单（多/少字段 422），服务端生成 `product-ml-<prefix>-<nonce>` 并令
  `trace_id == idempotency_key`，拒绝浏览器身份字段。读请求 5xx/网络失败→`backend_unavailable`；
  写请求→`operation_outcome_unknown`。

## 本批验证

- `test_ml_dynamic_capabilities_paged_catalog_and_lazy_detail`：能力/选项/目录/工作区详情与投影。
- `test_ml_training_reconciles_timeout_by_server_generated_idempotency_key` 与
  `test_ml_training_reuses_browser_idempotency_key_and_waits_for_commit_race`：提交登记→POST 超时→原键 reconcile。
- `test_ml_training_rejects_invalid_browser_idempotency_key`、
  `test_ml_training_does_not_resubmit_an_existing_unconfirmed_watch`、
  `test_ml_receipt_watch_query_uses_the_original_browser_key_namespace`：原键格式、重复发送与核对命名空间。
- `test_ml_commands_reject_browser_identity_fields_and_generate_them_server_side`：身份字段归属。
- `test_ml_prediction_rows_forwards_bounded_page_and_owner_context`：预测行有界分页与 owner 头。
- 隔离容器（保留镜像 + 当前工作树只读挂载、`--network none`）Gateway 全量 230 项通过。
- 前端 `mlResearch.ts` 的对应函数与 `mlResearch.spec.ts` 保持同一 Product 路径与幂等头。

## 登记与限制

- 台账新增 ML 研究族 11 条 Gateway 入口（8 读 + 3 写）。
- 仅登记这 11 条；Backend ML 入口、其他 Gateway 族、人工面与 H5 完整研究不随之完成。
- 未调用真实模型、未执行生产任务；远端完整 CI 待新候选验证。
