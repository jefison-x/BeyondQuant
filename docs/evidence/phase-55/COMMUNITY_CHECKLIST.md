# Phase 55 Community feature checklist

| Community behavior inspected read-only | BYQ disposition | Evidence |
|---|---|---|
| Session/lifecycle-aware coverage | `PORT_TESTS` / `REFACTOR` | Frozen SSE calendar and security-master snapshot drive per-cell applicability. |
| Suspension ledger distinguishes intentional no-bar days | `PORT_TESTS` / `REFACTOR` | Exact durable status is required; absence is never suspension. |
| Preflight state and bounded repair | `PORT_UX` / `REFACTOR` | `waiting_for_data` plus durable Data Worker repair of at most 250 sessions. |
| Resume after inputs become complete | `PORT_UX` / `REFACTOR` | Provider-free promotion adds immutable input and queues the same job. |
| Exact daily limits | `PORT_LOGIC` / `REPLACE` | Closed `stk_limit` and frozen bar fields replace threshold-only preparation. |
| Community ORM, provider registry, threads and internal frontend APIs | `REPLACE` | BYQ stores, Data Worker and Gateway/Product API are authoritative. |
| VectorBT, BaoStock and AKShare | `DROP` | No dependency, adapter, fallback or compatibility path exists. |

Every reusable Phase 55 invariant/UX item is implemented or explicitly
replaced; excluded Community architecture and technologies remain dropped.
