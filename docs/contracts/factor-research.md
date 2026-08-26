# Factor Research Contract

Phase 10 将 factor input boundary 定义为 BYQ domain contract。Factor request 包含 normalized security、trading-session、lifecycle-status、daily-bar、point-in-time universe 和 provider provenance snapshots。Factor service 不接受 provider-specific frames，也不执行任意 source code。

## 必需 invariants

- Symbols 为 canonical `NNNNNN.SH`、`NNNNNN.SZ` 或 `NNNNNN.BJ`。裸六位 code 只有带显式 exchange 才接受；BYQ 不按 prefix 猜测 exchange。
- Security listing/delisting dates 定义有效 lifecycle；拒绝上市前或退市后的 bar。
- Sessions 显式并按 `trade_date` 排序；拒绝 non-trading session 上的 bars。Factor lags 使用 session positions，不按 calendar-day 相减。
- 每个 `(symbol, trade_date)` 最多一根 bar。Bars 按稳定 symbol/date 顺序规范化；有限正数 OHLC 必须满足 OHLC envelope。
- Active lifecycle 中缺失 bar 是 input error。上市前、退市后或明确 suspended 的日期单独分类，不静默视为 data gap。
- 选择 `as_of_date` 当日或之前可见的最新 universe snapshot。为防 look-ahead，拒绝晚于 `as_of_date` 的 source announcement/effective dates，以及 future bars、statuses、sessions 或 snapshots。
- Normalized input snapshot 以 SHA-256 内容寻址。Retrieval time 是 provenance metadata，不属于 deterministic input ID。
- Results 有界、确定，并作为带 `factor_input` lineage reference 的 Phase 9 Artifact 持久化。Artifact idempotency 由既有 BYQ research store 提供。

## 初始 built-in factors

`daily_return` 和 `momentum` 是确定性的 close-to-close factors。二者只使用 `as_of_date` 当日或之前的 bars；`momentum` 使用显式正数 session lookback。Results 包含 BYQ engine/algorithm metadata 和确定性的 count/mean/min/max evaluation summary。任意 code execution 不属于本 contract。

## Endpoint

`POST /v1/research/factors/compute` 校验 input，返回 input manifest summary 和 coverage classification，计算 result，并将其保存为 `factor_result` Artifact。对应 MCP tool 为 `byq_factor_compute`；Agent-to-Domain 调用仍跨越 BeyondQuant MCP boundary。
