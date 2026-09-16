# ML 研究对象 Gateway 转发

2026-09-16，本地维护；Product Phase 97 不变。
审计三条 ML 研究对象的 Gateway Product 入口：详情读取、生命周期、删除。

## 源码核对

- `product_ml_study`（product_api.py:751，GET）：只读转发，经 `_ml_artifact_projection`
  仅保留每种 kind 的允许字段，`object_reference`、`python`、`rows`、`target_weight`、`signals/universe`
  等内部内容不下发 Product。
- `product_ml_study_lifecycle`（775，POST）：仅接受 `{"status"}` 且 status ∈ {active, archived}，
  否则 422 `product_request_invalid`；`x-idempotency-key` 经 `_ml_nonce` 规范为
  `product-ml-study-lifecycle-<key>` 作为原键透传，缺省生成一次性键。
- `product_ml_study_delete`（792，DELETE）：转发 Backend `supersede_unexecuted_ml_study`，
  由 Backend 按 owner/workspace 与训练/预测/回测执行事实守卫；已有执行历史则拒绝，已 superseded 幂等返回。
- 三条入口均由 `_product_principal` 校验会话、`_trusted_agent_headers` 派生可信 owner/workspace，
  浏览器头不能覆盖；写请求传输失败按 `operation_outcome_unknown`，读请求按 `backend_unavailable`。

## 本批验证

- 既有真实组件测试覆盖：详情投影的字段白名单与敏感内容剔除、目录分页、
  lifecycle 允许列表/原键/伪装 owner 拒绝、delete 只转发可信上下文
  （`services/gateway/tests/test_product_api.py` 中 305/360/384 三处用例）。
- 隔离容器（保留依赖镜像 + 当前工作树只读挂载、`--network none`）运行 Gateway 全量：
  229 项通过，含上述三条入口。
- 前端消费方 `apps/frontend/src/api/mlResearch.ts` 的 `getMLStudy` / `setMLStudyLifecycle` /
  `deleteMLStudy` 与 `mlResearch.spec.ts` 保持同一 Product 路径与幂等头。

## 登记与限制

- 台账新增 `product_ml_study`、`product_ml_study_lifecycle`、`product_ml_study_delete` 三条 Gateway 入口。
- 仅登记这三条；Backend 对应入口、其他 ML Gateway 入口与 H5 完整研究不随之完成。
- 未调用真实模型、未执行生产任务；远端完整 CI 待新候选验证。
