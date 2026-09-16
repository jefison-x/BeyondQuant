# 数据中心 Gateway 转发

2026-09-16，本地维护；Product Phase 97 不变。
审计数据中心族 19 条 Gateway Product 入口：状态/覆盖/证券主数据/就绪、需求、Tushare 凭据、
同步作业与自动化。

## 源码核对

- `_data_actor_headers` 统一派生 `x-byq-actor-principal`/`x-byq-actor-role`；管理员写入口
  （凭据、同步作业、自动化、证券主数据同步、需求创建）额外 `require_admin=True`，非管理员 403
  `product_forbidden`。普通读（状态/覆盖/就绪/证券列表/需求读取）登录即可。
- `product_data_center_status` 校验 `view ∈ {summary, full}`，非法 422 `product_data_center_view_invalid`。
- 写入口原键透传（需求、凭据、同步作业、自动化 run-now）由 Backend 按原键与完整输入摘要去重；
  凭据原提交回执、需求冻结计划与重试复用见既有证据。
- 写请求 5xx/网络失败→`operation_outcome_unknown`；读请求→`backend_unavailable`；
  Backend 4xx→`product_domain_rejected`。

## 本批验证

- `test_product_data_center_status_exposes_masked_provider_capability`：状态视图与掩码能力读取。
- `test_product_data_readiness_forwards_trusted_identity_and_bounded_request`：就绪请求身份/有界转发。
- `test_product_data_center_writes_are_admin_only_and_use_backend_boundary`：管理员写入口、非管理员拒绝、
  证券目录分页与自动化配置/run-now 路径。
- `test_historical_demand_product_route_preserves_admin_gate_and_original_key`：需求创建管理员门禁与原键。
- Backend 需求/凭据原键恢复见
  [DATA-DEMAND-RECOVERY](./DATA-DEMAND-RECOVERY.md)、[CREDENTIAL-RECOVERY](./CREDENTIAL-RECOVERY.md)、
  [CREDENTIAL-TIMEOUTS](./CREDENTIAL-TIMEOUTS.md)。
- 隔离容器（保留镜像 + 当前工作树只读挂载、`--network none`）Gateway 全量 230 项通过。

## 登记与限制

- 台账新增数据中心族 19 条 Gateway 入口。
- 仅登记这些；Backend 数据中心入口、其他 Gateway 族、人工面与 H5 完整研究不随之完成。
- 未调用真实模型、未执行生产任务；远端完整 CI 待新候选验证。
