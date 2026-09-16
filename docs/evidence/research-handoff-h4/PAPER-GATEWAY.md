# 模拟交易与股票池 Gateway 转发

2026-09-16，本地维护；Product Phase 97 不变。
审计模拟交易/股票池族 41 条 Gateway Product 入口：账户、订单、持仓/成交/账本/快照/控制/导出/导入，
指数池/动态池、股票池元数据/成员/快照/生产器/物化/生命周期/引用/就绪。

## 源码核对

- 全部入口经 `_product_principal` + `_trusted_agent_headers` 派生可信 owner；浏览器不能覆盖。
- 写入口原键透传，Backend 按原键与领域状态去重：
  账户创建/删除、订单创建（并发资金校验）、结算、控制/绑定更新、账户导入、
  股票池创建/元数据/快照替换/生命周期/删除、生产器更新、物化创建。
- `product_stock_pool_delete`（2306）在缺失浏览器原键时注入 `delete-<pool_id>`，使重复删除幂等。
- 读入口含 `paper/receipts`、`paper/pools/reconcile` 按原键回执核对；池成员/快照/物化/物化列表有界分页。
- 写请求 5xx/网络失败→`operation_outcome_unknown`；读请求→`backend_unavailable`；Backend 4xx→`product_domain_rejected`。

## 本批验证

- `test_product_paper_depth_routes_forward_methods_and_owner`：账户订单/快照/结算/控制/绑定/导出/删除/导入
  的方法与 owner 头转发。
- 订单创建转发 owner 头（`product_paper_order_create` 用例）。
- 既有恢复证据：[PAPER-COMMAND-RECOVERY](./PAPER-COMMAND-RECOVERY.md)、
  [PAPER-ORDER-SERIALIZATION](./PAPER-ORDER-SERIALIZATION.md)、
  [PAPER-IMPORT-RECOVERY](./PAPER-IMPORT-RECOVERY.md)、[POOL-RECOVERY](./POOL-RECOVERY.md)、
  [INDEX-REPAIR-CACHE](./INDEX-REPAIR-CACHE.md)。
- 隔离容器（保留镜像 + 当前工作树只读挂载、`--network none`）Gateway 全量 230 项通过。

## 登记与限制

- 台账新增模拟交易/股票池族 41 条 Gateway 入口。
- 仅登记这些；Backend 对应入口、其他 Gateway 族、人工面与 H5 完整研究不随之完成。
- 未调用真实模型、未执行生产任务；远端完整 CI 待新候选验证。
