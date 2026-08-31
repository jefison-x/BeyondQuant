# Frontend list-performance maintenance Chrome review

- Date: 2026-09-01
- Source: isolated worktree frontend at `127.0.0.1:5174`
- API: local BYQ Gateway/Product API stack
- Browser: Chrome DevTools MCP
- Desktop viewport: `1920x1080`

## Verified flow

1. Logged in through durable BYQ browser authentication and opened
   `/model-research` and `/stock-pool`.
2. Measured both `ManagementWorkspace` surfaces at the same `1620px` width
   (`left=280`, `right=1900`) with no document-level horizontal overflow.
3. Opened the stock-pool `成员与权重` tab and confirmed the filter,
   `股票代码`, `股票名称（中文）`, `权重`, and server-pagination controls are
   rendered. The already-running Gateway container predated this branch, so
   row payload verification is covered by the new Backend/Gateway contract
   tests rather than claimed from that container.
4. Opened `/settings/system/overview`, then navigated in-app to
   `/settings/system/sources` and `/settings/system/database`. The browser made
   one `/api/product/operations/status` request; both subsequent sections reused
   the bounded 30-second cache.
5. Recorded a system-overview navigation trace: observed LCP `529ms`, CLS
   `0.00`, no CPU or network throttling.
6. Recorded a model-research trace and identified the remaining latency as a
   serial six-request Gateway fan-out. The branch replaces it with two
   concurrent reads: the normalized ML workspace and bounded backtest summary.

Browser traffic stayed on same-origin authentication, `/api/product/*`, and
the bounded `/v1/agent/sessions?limit=20` Product-compatible session route. No
browser request targeted Backend, MCP, DSH, PostgreSQL, Redis, or a market-data
provider directly.
