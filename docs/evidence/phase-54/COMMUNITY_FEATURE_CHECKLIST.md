# Phase 54 Community feature checklist

The corresponding Community scheduler, state-machine tests, Tushare calendar
and exact-date daily mappings, and maintenance workbench were inspected
read-only before implementation.

| Capability | Classification | Beta result |
|---|---|---|
| Database-backed scheduled jobs | `PORT_TESTS` / `REFACTOR` | Delivered with unique session jobs, atomic claims, leases, heartbeats, restart recovery, bounded retry and durable status. |
| Trading calendar plus exact-date full-market daily request | `PORT_LOGIC` / `REFACTOR` | Delivered as closed validated provider contracts and one content-addressed snapshot per open session. |
| 18:30 automatic-sync operator controls | `PORT_UX` / `PORT_LAYOUT` | Delivered as versioned Asia/Shanghai schedule, catch-up policy, optional stock-master refresh, run-now command, worker health and bounded history. |
| Community ORM, registry, internal APIs and threaded scheduler | `REPLACE` / `DROP` | Replaced by BYQ PostgreSQL contracts, trusted data worker, and same-origin Product API. |
| Adjusted bars, corporate actions, benchmark and fundamentals | `REFERENCE_ONLY` | Explicitly deferred to Phases 55–57 under separate point-in-time contracts. |
| BaoStock, AKShare and VectorBT paths | `DROP` | No dependency, adapter, fallback or compatibility layer added. |

No Community source, database, cache, runtime, credential or Git history was
modified, copied or imported.
