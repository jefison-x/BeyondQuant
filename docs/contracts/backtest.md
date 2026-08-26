# Backtest Job 与 Worker Contract — Phase 12

Phase 12 使用 native deterministic engine 执行由 BYQ 拥有的冻结 signal snapshot。它不执行 StrategyVersion Python source。Strategy version 及其已批准的 `strategy_approval` artifact 授权这次尝试；input manifest 冻结实际 execution data。

## 提交

`POST /v1/research/backtests` 和 `byq_backtest_submit` 要求：

- `validated` `strategy_version` artifact，以及匹配且已批准、状态为 `execution_authorized` 的 `strategy_approval` artifact；
- 包含 canonical symbols、`version_id` 及与排序 symbol set 相符 membership SHA-256 的 frozen universe；
- 每个 `(symbol, trade_date)` 一根 deterministic OHLC bar，以及 stable signal snapshot；
- 显式 execution rules，或 BYQ 对 capital、fees、lot size、position limit、slippage、A-share rules 和 runtime bound 的默认值。

提供 `stock_pool_snapshot_id` 时，Backend 解析该 immutable owner-scoped snapshot，要求其 pool 对新 reference 处于 active，并验证 frozen backtest universe 和每个 signal 均属于其 membership。Input manifest 将 snapshot ID 记录为 universe version；replay 永远不解析 pool 的 mutable current pointer。此 reference 不能与独立 index-universe selector 组合。

生成的 `backtest-input-v1` manifest 使用内容寻址。它包含 strategy/approval identities、universe、bars、signals、corporate actions、execution rules 和 native engine contract version；不包含 credentials、mutable timestamps、prompts、Agent runtime state 或 strategy source。

## Native execution rules

- 某 session 观察到的 signals 在下一个可用 session open 执行。
- Orders 按 symbol 顺序处理，先 sells 后 buys。
- A-share mode 强制执行 T+1 lots、limit-up/limit-down、suspension、lot size、cash、commission、sell-side stamp tax 和 active-position limit。
- Corporate actions 冻结在 input 中，并在 ex-date orders 前应用 share/cash adjustments。
- 每个 rejected order 发出稳定 reason code，例如 `t_plus_one`、`limit_up`、`limit_down`、`suspended`、`insufficient_capital` 或 `max_positions`。

结果是确定性的，包含 equity curve、trades、blocked trades、corporate-action events、summary metrics、engine contract version 和 input manifest identity。

## Jobs 与 result objects

Jobs 使用以下 state machine：

```text
queued → running → completed
             ├──→ queued  (bounded retry)
             ├──→ failed
             └──→ cancelled
queued ─────────→ cancelled
```

相同 task/idempotency key 和 request 返回原 job。用同一 key 提交不同 request 会冲突。Worker claim 一个 queued job，并增加其有界 attempt count（1–3 attempts）。Worker 重启后，stale running jobs 会重新入队。Business state 仍归 Backend/Domain 所有；完整 result 是 immutable object reference，包含 namespace、object identity、media type、size 和 SHA-256。`backtest_result` Artifact 仅存 reference 和有界 summary。

删除 object 需要匹配 owner scope 和 authoritative live reference set。Referenced、missing 或 tampered objects 均 fail closed。

Phase 12 worker 可作为独立进程运行 `workers/backtest/worker.py`。HTTP run operation 是 keyless contract fixture 和 operator control path，不是 strategy-source execution shortcut。
