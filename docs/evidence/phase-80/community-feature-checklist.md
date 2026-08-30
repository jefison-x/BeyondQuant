# Phase 80 Community feature checklist

The BeyondQuant-Community repository and its `DataSync.vue` surface were inspected read-only
before implementation. No Community source, database, cache, credential, runtime or Git history
was changed or copied.

| Community evidence | Classification | Phase 80 result |
|---|---|---|
| User intent to describe synchronization work and observe progress | `PORT_UX` / `REFACTOR` | Xiaoba submits a bounded frozen scope; Data Center shows durable readiness-derived status. |
| Local fake progress and TODO synchronization service | `DROP` / `REPLACE` | Existing Backend repair records, session jobs and Data Worker are authoritative. |
| Direct Agent/provider synchronization path | `DROP` / `REPLACE` | Agent calls BYQ MCP; only trusted Data Worker calls Tushare or writes market data. |
| Legacy runtime/database task model | `REFERENCE_ONLY` | `data-demand.v1` is a facade over existing BYQ jobs, not a second workflow engine. |
| BaoStock, AKShare and VectorBT paths | `DROP` | No dependency, adapter, fallback or compatibility layer was added. |

The reusable invariant is “bounded need → durable task → verified completion”. Provider,
storage, readiness and authorization invariants remain BYQ-owned.
