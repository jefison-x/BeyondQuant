# Paper Trading Contract — Phase 35

This contract operationalizes ADR-0021. Keywords **MUST**, **MUST NOT**,
**SHOULD**, and **MAY** are normative.

## Domain invariants

- Paper Trading MUST remain simulation-only and separate from Backtest and
  live brokerage.
- Every record and mutation MUST be owner scoped; unauthorized ownership MUST
  not be disclosed.
- Account, order, fill, ledger, snapshot, and bundle IDs MUST be generated or
  remapped by Backend. Browser, DSH, and import payloads are not identity
  authorities.
- Money MUST use exact decimal semantics; quantities are non-negative integers.
- Mutations MUST be transactional, idempotent, and conflict on same-key/
  different-request reuse.
- Browser traffic MUST use Gateway/Product API. Agent mutations MUST use
  bounded MCP and an applicable ADR-0009 approval reference.

## Account and universe binding

An account exposes generated identity, name, CNY currency, initial cash,
current cash/equity, realized P&L, status, version, settlement date, frozen
Stock Pool snapshot binding, and timestamps. First accepted order MUST bind an
active owner-equal snapshot. Later orders MUST use that binding. Explicit
rebind requires an empty portfolio, expected account version, idempotency key,
and audit record.

## Orders, positions, and fills

An order MUST preserve normalized input, pool/snapshot identity, risk outcome,
stable blocked reason, cost/tax result, decision provenance, fill reference,
and immutable events. The Phase 35 terminal states are `filled` and `blocked`;
the UI MUST NOT imply asynchronous or live-broker states.

Positions MUST keep total, sellable, and locked quantities plus average cost
and last mark/provenance. Buys lock only the purchased quantity. Sells consume
only sellable quantity. Tests MUST cover mixed old and same-day holdings.

## Settlement and snapshots

Settlement requires a canonical date, expected account version, idempotency
key, and a complete positive finite mark set for all open positions. Dates are
strictly monotonic. One transaction promotes eligible locked quantity,
persists marks, appends one immutable daily snapshot and settlement audit/
ledger entry, and advances account state.

Snapshot identity MUST include canonical account/date/position/mark semantics
and exclude mutable timestamps and actor display data. Same-date identical
replay is idempotent; different content conflicts. Valuation MUST NOT be
recorded as cash movement.

## Risk controls

The persisted control projection contains versioned kill-switch state/reason
and optional maximum order notional. Updates require optimistic concurrency,
idempotency, owner/actor audit, and bounded values. Order detail records the
evaluated control version and result. No failure circuit breaker is exposed in
Phase 35.

## Ledger

The ledger MUST be append-only and Backend-generated. It records initial
funding, fill cash changes, zero-cash settlement audit events, and import
provenance with stable references and account summaries. Pagination/order are
deterministic. A persisted ledger entry cannot be updated or deleted by a
Product caller.

## Asset bundle

`paper-account-bundle-v1` export MUST be canonical, bounded, deterministic for
semantic sections, and include a manifest with SHA-256 digests and counts. It
MUST exclude owner/actor authority, secrets, tokens, DSH raw events, market
datasets, and source code.

Import MUST verify all digests, bounds, references, arithmetic, chronology,
and local frozen-universe permissions before writing. It creates a new owner-
scoped account and remaps IDs atomically. It MUST NOT overwrite, accept an
owner from the bundle, or partially import invalid data.

## Product projections

The persisted six-view workspace is Overview, Positions, Orders & Fills,
Ledger, Snapshots, and Risk & Transfer. Order detail, settlement, controls,
export, and import are real Product API flows. Collection responses are
bounded. The browser MUST NOT call Backend, MCP, DSH, PostgreSQL, Redis, or a
data provider directly.

## Community classification

| Community capability | Decision | BYQ treatment |
|---|---|---|
| Account selector/create and order workspace | `REFACTOR` | Keep UX intent; use durable identity, Product API, and BYQ state machine. |
| Overview/positions/orders/ledger/snapshot layout | `PORT_LAYOUT` + `PORT_UX` | Adapt to the six BYQ persisted projections and responsive shell. |
| T+1 sellable quantity and immutable daily settlement | `PORT_LOGIC` + `PORT_TESTS` | Reimplement exact quantities, monotonic dates, and conflict semantics. |
| Order detail lifecycle | `PORT_UX` | Render BYQ immediate fill/blocked events; do not invent broker states. |
| Kill switch and max-order notional | `PORT_UX` + `REFACTOR` | Persist/version/audit; evaluate in BYQ before execution rules. |
| Broker failure circuit breaker | `DROP` | No external failure stream exists in Phase 35. |
| Account JSON import/export | `REPLACE` | Canonical BYQ bundle, manifest/digests, new ID, owner rebinding, atomic validation. |
| ORM/repository, Agent runtime, broker adapter, old APIs | `REFERENCE_ONLY` | No code or architecture copied. |

## Required acceptance tests

Phase 35 cannot be complete until automated tests prove:

1. owner isolation across every read, mutation, bundle, and order detail;
2. first-order universe binding, frozen membership, explicit empty-account
   rebind, and historical resolution after pool lifecycle changes;
3. stable order/risk reason codes, idempotency conflicts, and exact fees/tax;
4. partial T+1 availability when older and same-day holdings coexist;
5. monotonic atomic settlement, complete marks, immutable snapshots, and
   identical-replay/different-content conflict;
6. persisted append-only funding/fill/settlement/import ledger entries;
7. versioned kill switch and max-notional enforcement with audit;
8. order detail references real request/risk/fill/event data;
9. deterministic export digests, secret/authority exclusion, tamper rejection,
   new-ID import, reference remap, owner rebinding, no overwrite, and atomic
   rollback;
10. legacy logical migration is repeatable and quarantines ambiguous rows;
11. Product API and required bounded MCP contracts preserve trusted context;
12. all six UI views and actions consume real Gateway/Product API data.

Chrome MCP evidence MUST cover desktop and mobile workspace states, account
create/select, accepted and blocked orders with detail, mixed T+1 positions,
ledger, settlement and snapshot history, kill switch/max-notional, and bundle
export/import. Completion MUST link the feature-by-feature Community checklist
and record network evidence showing browser calls only `/api/product/...`.
