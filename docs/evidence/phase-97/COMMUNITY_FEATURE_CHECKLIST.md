# Phase 97 Community Feature Checklist

The corresponding read-only Community Backtest implementation was inspected before design and implementation. Community remained unmodified.

| Feature / invariant | Community evidence | Decision | Phase 97 result |
|---|---|---|---|
| Persisted Backtest name | `BacktestRun.name` and `BacktestRequest.name` | `PORT_LOGIC` / `PORT_TESTS` / `REFACTOR` | BYQ-owned PostgreSQL metadata with bounded validation and forward repair; no Community ORM copied. |
| Name input | “回测名称” create form | `PORT_UX` / `REFACTOR` | Optional Product input; Backend owns defaults and persistence. |
| Name/ID hierarchy | List separates numeric ID and task name | `PORT_LAYOUT` / `PORT_UX` | Desktop columns, mobile primary/secondary hierarchy and full ID technical detail. |
| Search and catalogue payload | Legacy local filtering and broad object reads | `REPLACE` | Owner/workspace-scoped Product API server paging; query matches name or stable ID; large manifest remains lazy. |
| Backtest execution and identity | VectorBT/ORM/direct internal APIs | `DROP` / `REPLACE` | Existing BYQ native deterministic worker, immutable manifest, Gateway and MCP boundaries remain authoritative. |
| Agent integration | Community Agent/runtime paths | `DROP` / `REPLACE` | Existing DSH → BeyondQuant MCP → Backend task facade returns the Backend-persisted name. |
| BaoStock, AKShare and VectorBT | Community dependencies and execution paths | `DROP` | No dependency, adapter, fallback or compatibility path added. |

No Community source, PostgreSQL data, cache, credential or Git history was written, copied or adopted.
