# 回测 Gateway 转发

2026-09-16，本地维护；Product Phase 97 不变。
审计回测族 10 条 Gateway Product 入口：选项、目录/提交、详情(summary)、结果、清单、分析、
运行、取消、删除。

## 源码核对

- 全部入口经 `_product_principal` 校验浏览器会话、`_trusted_agent_headers` 派生可信 owner；
  浏览器不能覆盖 owner/workspace。
- 读入口：`/backtests/options`、`/backtests`（`catalog` 分页）、`/backtests/{id}`（`/summary` 有界投影）、
  `/backtests/{id}/result`、`/backtests/{id}/manifest`、`/backtests/{id}/analysis?section=...`。
- 写入口：`POST /backtests`（202，`projection=summary`，Backend 按原键/输入摘要去重并冻结 manifest）、
  `POST /backtests/{id}/run`（请求内执行一次 worker 迭代，受既有 worker 整次请求期限约束）、
  `POST /backtests/{id}/cancel`、`DELETE /backtests/{id}`（`projection=summary`，删除后 best-effort GC）。
- 写请求 5xx/网络失败→`operation_outcome_unknown`（不推断成功）；读请求→`backend_unavailable`；
  Backend 4xx→`product_domain_rejected` 并保留 detail。

## 本批验证

- `test_product_backtest_browser_reads_use_bounded_projections`：覆盖目录/详情/分析/清单读取、
  提交(202)/run/cancel/delete，并断言 `catalog` 查询、`/summary`、`analysis` 分页与
  `projection=summary` 路径。
- `test_product_backtest_result_...`：结果读取转发与 owner 头。
- 参数化 `test_product_business_proxy_routes_forward_owner_context`：详情/run/cancel 的 owner/actor 转发。
- 隔离容器（保留镜像 + 当前工作树只读挂载、`--network none`）Gateway 全量 230 项通过。
- Backend 精确 ID 读取与原键未知指引见 [BACKTEST-EXACT-READ](./BACKTEST-EXACT-READ.md)；
  回测提交/任务回执与恢复见 `services/backend/tests/test_backtest_api.py`、
  `test_backtest_submission_reconciliation.py`、`test_backtest_task_reconciliation.py`。

## 登记与限制

- 台账新增回测族 10 条 Gateway 入口（6 读 + 4 写）。
- 仅登记这 10 条；Backend 回测入口、其他 Gateway 族与 H5 完整研究不随之完成。
- 未调用真实模型、未执行生产任务；远端完整 CI 待新候选验证。
