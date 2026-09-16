# 策略投影 Gateway 转发

2026-09-16，本地维护；Product Phase 97 不变。
承接上一批 Backend `strategy_version_history` / `strategy_backtest_count` 具名登记，
审计两条对应的 Gateway Product 只读转发入口。

## 源码核对

- `product_strategy_versions`（product_api.py:1153）与 `product_strategy_backtest_count`（1163）
  均为只读转发：`_product_principal` 校验浏览器会话，`_trusted_agent_headers` 从服务端会话派生
  owner/workspace（浏览器参数不能覆盖），limit/offset 原样透传，Backend 再执行
  `_required_agent_context` 与分页边界（1..1000）。
- 错误映射由共享 `_backend_request` 决定：Backend 422（非法策略ID/分页）映射为
  `product_domain_rejected` 并保留 detail；Backend 5xx 与网络失败在读请求上映射为
  `backend_unavailable`，不得解释为空版本列表；`operation_outcome_unknown` 仅用于写请求。
- Gateway 读超时为 pooled_http 8 秒；Gateway 不自动重试。

## 本批验证

- 新增 `test_product_strategy_projection_read_failures_stay_explicit`：路由级真实 TestClient 请求，
  断言两条入口在 Backend 422、Backend 503、传输超时下分别返回 `product_domain_rejected`（保留 detail）
  与 `backend_unavailable`，且不返回 `operation_outcome_unknown`。
- 既有 `test_product_strategy_draft_and_projection_routes_forward_owner_headers` 覆盖成功转发、
  limit/offset 透传与可信 owner 头。
- 隔离容器（保留依赖镜像 + 当前工作树只读挂载、`--network none`）运行
  `services/gateway/tests/test_product_api.py`：78 项通过。
- 真实浏览器证据沿用 `.107` 的 `h4-strategy-pagination.spec.ts`（当前候选 8b4d90a 已包含该规范）：
  持久测试用户经 Gateway/Product API 读取 total=1005、首页 50 条，点击第 21 页取回 offset=1000 的末 5 条，
  无 pageerror。
- Backend 侧快照、锁等待与恢复证据见 STRATEGY-PROJECTION-ERRORS.md；本批不改变 Backend 逻辑。

## 其余只读入口

同一批继续核对三条只读 Gateway 入口：

- `product_strategy_export`（1045）：按 artifact_id 转发版本导出，只读；owner 由可信会话派生。
- `product_strategy_version_approval`（1055）：按 artifact_id 转发版本审批读取，只读。
- `product_strategies`（1073）：允许列表校验 `lifecycle ∈ {active, superseded, all}`，非法值 422
  `product_strategy_view_invalid`；limit/offset 透传。

新增 `test_product_strategy_catalog_forwards_lifecycle_and_rejects_unknown_view`：
断言合法 lifecycle/分页透传与可信 owner 头、非法 lifecycle 在 Gateway 即 422 不发下游。
既有参数化 `test_product_business_proxy_routes_forward_owner_context` 覆盖导出与审批转发身份。
隔离容器运行 `tests/test_product_api.py`：79 项通过。

## 登记与限制

- 台账新增 `product_strategy_versions`、`product_strategy_backtest_count`、`product_strategy_export`、
  `product_strategy_version_approval`、`product_strategies` 五条 Gateway 只读入口。
  与独立的 ML-STUDY-GATEWAY 三条合计后，台账由 116 增至 124/560。
- 仅具名登记这些转发；其余策略写入口、Gateway 其他族、人工面与 H5 完整研究不随之完成。
- 未调用真实模型、未执行生产任务；远端完整 CI 待新候选验证。
