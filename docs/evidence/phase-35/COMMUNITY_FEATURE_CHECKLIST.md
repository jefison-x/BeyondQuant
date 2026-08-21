# Phase 35 Community-derived Paper Trading checklist

The read-only Community implementation was inspected before Phase 35 work:
`PaperTradingView.vue`, account/order/position/snapshot models, execution/read/
repository/tracking/transfer services, migrations, and tests. Community was
evidence only; no Community file, database, API, or architecture was copied or
mutated. Detailed capability classification is in
`docs/migration/COMMUNITY_MIGRATION_INVENTORY.md`.

## Visual and interaction classification

| Community surface | Decision | BYQ result |
| --- | --- | --- |
| Account list plus detail workspace | `PORT_LAYOUT` + `PORT_UX` | Responsive owner-scoped account rail and persisted detail workspace. |
| Overview/positions/orders/ledger/snapshots | `PORT_UX` + `REFACTOR` | Six real BYQ tabs, adding a dedicated risk/migration workspace. |
| Order detail dialog | `PORT_UX` | Honest immediate `filled`/`blocked` audit with frozen inputs and provenance. |
| Manual settlement | `PORT_UX` + `PORT_TESTS` | Complete marks, monotonic date, immutable/idempotent snapshot. |
| Kill switch and maximum order notional | `PORT_UX` + `REFACTOR` | Versioned, audited controls with optimistic concurrency. |
| Broker failure circuit breaker | `DROP` | No fake external-broker failure stream. |
| Permissive JSON transfer | `REPLACE` | Canonical BYQ bundle, manifest/digests, new IDs, trusted owner rebinding. |
| Community APIs/runtime/storage | `REFERENCE_ONLY` | Gateway/Product API, PostgreSQL domain store, and BYQ contracts only. |

## Completion checklist

- [x] Owner-scoped account create/list/detail and durable persisted state.
- [x] Six tabs contain real data rather than empty or static placeholders.
- [x] Total, sellable, and T+1 locked quantities are distinct and tested.
- [x] Buy/sell cash direction, fees, fill, and persisted ledger are exact.
- [x] Account binding freezes a Stock Pool snapshot; rebind is explicit and
      limited to empty accounts.
- [x] Manual settlement requires complete marks and produces immutable daily
      snapshots without fake cash entries.
- [x] Order detail exposes result, risk evaluation, decision provenance,
      frozen snapshot, and ordered events.
- [x] Kill switch and maximum-order-notional controls persist and gate orders.
- [x] Asset export/import validates counts/digests/references, generates new
      IDs, never overwrites, and never imports authority fields.
- [x] Logical v1-to-v2 migration is repeatable and records a manifest plus
      quarantined rows.
- [x] Browser traffic uses durable login and Gateway/Product API only.
- [x] Desktop and 390x844 mobile Chrome MCP evidence uses persisted real data.
- [x] No live broker, broker credential, BaoStock, AKShare, VectorBT, raw DSH
      schema, or direct storage/provider access was introduced.

Completion evidence: [`byq-paper-trading/README.md`](./byq-paper-trading/README.md).
