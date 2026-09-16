# 回测 Backend 接口

2026-09-16，本地维护；Product Phase 97 不变。
审计 Backend 回测/回测任务 19 条接口：选项/目录/提交/核对/详情/摘要/清单/结果/分析/列表/运行/取消/删除，
以及回测任务 prepare/create/reconcile/get/execute/cancel。

## 源码核对

- 全部入口经 `_required_agent_context`（部分 `include_workspace=True`）解析可信 owner/workspace；
  跨 owner 一律 `BacktestNotFound`。
- 提交（`create_backtest_job`）校验任务/策略版本/审批/信号快照血统，冻结 manifest 并保留原键；
  `create_backtest_task` 委托既有信号准备组件并返回派生 facade（不新建第二套调度）。
- 核对（`reconcile_backtest_submission`/`reconcile_backtest_task_submission`）在 owner/workspace 内
  按 task_id+原键只读核对，返回 confirmed/outcome_unknown，不跨租户。
- 结果读取对缺失结果 409、存储对象损坏 503；分析片段有界分页并附特征诊断。
- 运行在请求内执行一次既有 Worker 迭代；删除对结果对象 best-effort GC，响应合同不变。

## 本批验证

- Backend 测试：`test_backtest_api.py`、`test_backtest.py`、`test_backtest_task.py`、
  `test_backtest_submission_reconciliation.py`、`test_backtest_task_reconciliation.py`。
- 恢复证据见 [BACKTEST-EXACT-READ](./BACKTEST-EXACT-READ.md)、[BACKTEST-GATEWAY](./BACKTEST-GATEWAY.md)。

## 登记与限制

- 台账新增回测 Backend 19 条接口。
- 其余 Backend 族、MCP 工具、Worker/Sandbox、人工面与 H5 完整研究不随之完成。
- 未调用真实模型、未执行生产任务；远端完整 CI 待新候选验证。
