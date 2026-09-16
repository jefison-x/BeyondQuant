# 模拟交易、股票池与信号 Backend 接口

2026-09-16，本地维护；Product Phase 97 不变。
审计 Backend 模拟交易/股票池/信号领域 49 条接口：信号快照与生产者，账户/订单/持仓/账本，
指数池/动态池/股票池/生产器/物化/快照/生命周期/引用/就绪/导入导出。

## 源码核对

- 全部入口经 `_required_agent_context`（多数 `include_workspace=True`）解析可信 owner/workspace，
  并从 payload 剔除 `owner_principal/actor_principal/trace_id/session_id/dsh_run_id`，不接受身份覆盖。
- 账户创建、股票池创建**强制** `idempotency_key`（缺失 422）；账户导入接受原键；订单提交在
  Backend 事务内串行校验资金/持仓；`_paper_call`/`_stock_pool_producer_call`/`_ml_call` 统一错误边界。
- `paper/receipts` 与 `paper/pools/reconcile`、`paper/index-pools/reconcile` 按 operation/kind +
  idempotency_key 在 owner/workspace 内只读核对原命令，不跨租户。
- 池读取区分 custom（本地快照就绪）与生产器池（生产器就绪）；池列表/成员/快照/物化均有界分页。
- 写请求存储异常→503；未知结果不伪装成功；领域非法状态→422/409。

## 本批验证

- Backend 测试：`test_paper_api.py`、`test_paper_trading.py`、`test_paper_command_receipts.py`、
  `test_paper_import_recovery.py`、`test_paper_recovery.py`、`test_pool_creation_recovery.py`、
  `test_stock_pool_producer.py`、`test_stock_pool_closure.py`、`test_dynamic_stock_pool.py`、
  `test_signal_producer.py`、`test_signal_submission_atomicity.py`。
- 恢复证据见 [PAPER-COMMAND-RECOVERY](./PAPER-COMMAND-RECOVERY.md)、
  [PAPER-ORDER-SERIALIZATION](./PAPER-ORDER-SERIALIZATION.md)、
  [PAPER-IMPORT-RECOVERY](./PAPER-IMPORT-RECOVERY.md)、[POOL-RECOVERY](./POOL-RECOVERY.md)。

## 登记与限制

- 台账新增模拟交易/股票池/信号 Backend 49 条接口。
- 其余 Backend 族、MCP 工具、Worker/Sandbox、人工面与 H5 完整研究不随之完成。
- 未调用真实模型、未执行生产任务；远端完整 CI 待新候选验证。
