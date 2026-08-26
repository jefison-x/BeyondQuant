# Signal Producer Contract

Status: Accepted ADR-0023 的 Phase 40 implementation。

## Product request

`POST /api/product/signal-producer/jobs` 接受 owner-scoped validated `strategy_version_artifact_id`、immutable `stock_pool_snapshot_id`、闭区间 `start_date`/`end_date`、有限 JSON parameters、ADR-0017 execution settings、显式 lot-aligned `order_quantity`、trace identity 和 idempotency key。Browser 只向 Gateway Product API 发送。

Backend 验证 task、strategy 和 pool ownership，拒绝 inactive pools 和不支持的 `generate_target_weights` versions，并从 canonical `market_daily_bars` 读取完整有界 window。缺失 pool-member coverage 时在排队前失败；不做 provider fallback。

## Durable state

Jobs 按 `queued → running → completed|failed` 转换。Product responses 省略 strategy source/frozen bars，只暴露 profile/runtime-lock identity、symbol/bar counts、stable error fields 和 completed `result_artifact_id`。`(owner_principal, idempotency_key)` 唯一，不同 frozen input 重用时 conflict。

## Execution protocol

Trusted coordinator claim PostgreSQL jobs，并通过 internal-only sandbox network 调用无 credential 的 `signal-sandbox`。Sandbox 只接受 execution profile 为 `byq-signal-python-v1` 的 `byq-signal-sandbox-request-v1`。每个 request 启动 fresh child，使用固定 runtime lock `python-3.13/pandas-2.3.3/numpy-2.3.3`、deterministic thread/hash settings、resource limits 和 sanitized environment。

`CustomStrategy.generate_signals(data, parameters)` 接收以 `(symbol, trade_date)` 为 index 的 canonical bars Pandas DataFrame；必须返回 canonical symbols 到 date-indexed Pandas Series 的 mapping，且值只能是 `-1`、`0`、`1`。Unknown/duplicate symbols/dates、non-finite values、oversized output、timeouts 和 unsupported imports 均以 stable codes fail closed。

Coordinator 丢弃 hold rows、应用显式 order quantity，再通过 ADR-0017 `normalize_signal_snapshot` 重新校验全部 output，之后创建或复用 validated、content-addressed `signal_snapshot` Artifact。Producer completion 既不批准也不启动 backtest。

## Isolation guarantees

Sandbox 不具备 Product network、PostgreSQL URL、Tushare/model/MCP/DSH credential、Docker socket、repository mount 或 application source。Filesystem 除有界 `/tmp` 外只读；以 non-root 运行，移除全部 Linux capabilities，启用 `no-new-privileges`，并限制 PID、memory、CPU 和 wall time。Coordinator 可访问 PostgreSQL，但绝不对 strategy source 调用 `exec()`。
