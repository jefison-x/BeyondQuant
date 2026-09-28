# Backtest Worker

Phase 12 提供 BYQ-owned deterministic worker boundary。Worker 获取一个
queued `backtest_*` job，只执行其 frozen signal snapshot；不执行 strategy
Python source、不访问 DSH state，也不接收 provider credentials。Durable
job/result artifact 仍归 Backend 所有；worker 经 Backend store layer
（ADR-0016 的 PostgreSQL `BYQ_DATABASE_URL`）读取 job，将完整 result 存为
immutable content-addressed object，domain row 只记录 reference/summary。

Compose 的 `backtest-worker` 持续读取 durable queued Job。Backend 的 `/run`
接口仅确认当前 Job 状态，不执行计算；Agent 会话结束不影响 Worker。

本地定向运行一个 job（测试或操作员调试）：

```text
BYQ_DATABASE_URL=postgresql+psycopg://byq_app:byq-app-dev@postgres:5432/byq_domain \
BYQ_BACKTEST_OBJECT_ROOT=/var/lib/byq/domain/backtest-objects \
python worker.py --job-id backtest_<32-hex-digits>
```

重启后的 Worker 会重新排队超过 900 秒仍处于 running 的 Job；回测引擎的
单次运行上限为 300 秒。结果仍通过稳定 `job_id` 和 Artifact ID 读取。
