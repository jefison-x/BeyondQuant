# Data Provider Contract — Phase 8

## 目的

定义 BYQ 拥有的 contract，用于从已配置 market-data provider 获取 A-share 未复权 daily bars。Provider-specific authentication、response envelopes 和 retry behavior 保留在 contract 之后。

## Request semantics

首个 operation 为 `daily`：

- `ts_code` 是带 `.SH`、`.SZ` 或 `.BJ` 的一个大写六位 symbol。
- `trade_date` 是精确 `YYYYMMDD` 日期。
- `start_date` 和 `end_date` 是闭区间 `YYYYMMDD` range。
- 精确 `trade_date` 可不带 symbol，用于一个有界 market snapshot。
- Date range 必须带 `ts_code`；拒绝 open-ended ranges。
- `trade_date` 不能与 date range 组合。

Contract 不接受逗号分隔 symbols 或任意 provider parameters，以保持 request cost 和 market semantics 显式。

## Response

每根 bar 包含：

```text
ts_code, trade_date, open, high, low, close, pre_close,
change, pct_chg, vol, amount
```

Values 保留 provider 记录的 units：prices/change 为 RMB，`pct_chg` 为 percentage，`vol` 为 lots，`amount` 为 thousand RMB。Daily contract 未复权；adjusted data 属于独立 contract。

每个 response 还包含 `provenance`：

```text
provider, endpoint, request_fingerprint, retrieved_at,
cache_hit, row_count
```

`request_fingerprint` 是 normalized request parameters 的稳定 hash，绝不包含 provider token 或 raw response payload。

## 所有权与安全

Backend 负责 provider credentials 并转换 raw provider responses。MCP 只暴露 normalized BYQ data。DSH 仅经 BeyondQuant MCP 使用此能力，永不接收 `TUSHARE_TOKEN`、raw Tushare envelopes 或 provider-specific error details。
