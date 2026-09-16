# Worker 与信号沙箱入口

2026-09-16，本地维护；Product Phase 97 不变。
审计 4 个 Worker 进程入口与 signal-sandbox 的 2 个 HTTP 入口。

## 源码核对

- Worker 入口（`workers/{backtest,data,ml,signal}/worker.py`）为无状态轮询循环：
  以唯一 `worker_id` 从 Backend 领域队列 claim 任务，执行后把结果/回执写回同一权威存储；
  失败进入既有重试/错误路径，不伪造成功。轮询间隔由 `BYQ_*_POLL_SECONDS` 有界控制。
  - backtest：claim queued job，运行回测，写入内容寻址结果并完成转换。
  - data：claim 池物化/数据修复/自动化运行/同步作业，执行 Provider 取数并落库。
  - ml：claim 训练/预测，做数据准备、训练与预测，写回运行状态与 artifact。
  - signal：claim 信号生产者作业，调用沙箱产生冻结信号快照。
- `services/signal-sandbox/server.py`：`/healthz` 只读存活；`/v1/execute` 无凭据、限制请求体 32MiB、
  以子进程 + resource limits（CPU/AS/FSIZE/NOFILE/CORE）执行策略，墙钟超时 0.1–30 秒，
  沙箱失败返回结构化 error_code，不泄漏内部细节，不访问网络/凭据。

## 本批验证

- `tests/architecture/test_architecture.py`、`tests/test_dsh_build_revision.py`。
- signal 沙箱拓扑/探针：`tests/dsh_upgrade/test_h5_stack.py`、`tests/dsh_upgrade/h5_signal_probe.py`。
- 领域侧回执/恢复见 [PAPER-BACKEND](./PAPER-BACKEND.md)、[BACKTEST-BACKEND](./BACKTEST-BACKEND.md)、
  [ML-BACKEND](./ML-BACKEND.md)、[DATA-BACKEND](./DATA-BACKEND.md)。

## 登记与限制

- 台账新增 4 个 Worker 入口与 2 个 signal-sandbox 入口。
- 仅剩 `product_assets_import` 与 8 个人工面、H5 完整研究。
- 未调用真实模型、未执行生产任务；远端完整 CI 待新候选验证。
