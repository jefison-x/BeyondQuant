# ADR-0008: Phase 12 Native Backtest Job and Worker Boundary

- Status: Accepted
- Date: 2026-08-16
- Decision scope: Phase 12 Quant Domain backtest execution
- Supersedes: the Phase 5 backtest-worker placeholder

## Context

Phase 11 supplies immutable, validated StrategyVersion and approval artifacts,
but BYQ has no safe execution boundary. Community evidence covers useful
A-share trading rules, frozen universe authorization, content-addressed input
manifests, bounded job retries, and immutable result references. Its Pandas,
ORM, Agent workflow, optional engine, and provider integrations do not belong
in the current architecture.

Phase 12 needs durable job state and reproducible results without executing
generated strategy source in a Backend request or granting Product DSH access
to business storage.

## Decision

1. BYQ owns a native deterministic signal-snapshot engine. A submission must
   reference a validated StrategyVersion and matching approved strategy
   approval; it supplies frozen bars, signals, universe membership, corporate
   actions, and explicit execution rules. Strategy Python source is not
   executed in this phase.
2. The input boundary canonicalizes one finite OHLC bar per
   `(symbol, trade_date)`, canonical A-share symbols, a matching universe
   membership fingerprint, stable signal ordering, and secret-free execution
   parameters. The manifest identity is SHA-256 content addressed.
3. Native A-share execution enforces next-session-open timing, sells before
   buys, T+1 lots, limit-up/limit-down, suspension, lot size, cash,
   commission, stamp tax, corporate-action adjustments, and bounded wall-clock
   execution. Rejected orders retain stable reason codes.
4. Backend owns a durable SQLite job state machine and strict task-scoped
   idempotency. A worker claims one queued job, increments a maximum of three
   attempts, requeues stale running jobs after restart, and records completion
   only after the result Artifact is persisted.
5. Full results are immutable files in a Backend-owned object root. Business
   state stores namespace/object identity, media type, size, and SHA-256 plus a
   bounded summary. Deletion requires owner-scope equality and an authoritative
   live-reference check; tampered or referenced objects are retained/failed
   closed.
6. Product Agent calls use `byq_backtest_*` MCP tools. DSH never receives
   provider credentials, raw storage access, strategy source execution
   privileges, or PostgreSQL access.

## Consequences

- Keyless tests can verify deterministic execution, input identity, approval
  authorization, job retry/recovery, result integrity, and MCP translation.
- A separate `workers/backtest` process can claim and execute a durable job
  without widening Product DSH capabilities.
- Strategy source execution, distributed queues, and live trading remain
  future decisions. The signal snapshot is the explicit Phase 12 execution
  input, so this phase does not imply an unsafe Python sandbox.

## Rejected alternatives

- Copying the Community Pandas/ORM/Agent Service backtest runtime would violate
  BYQ ownership and reintroduce excluded runtime boundaries.
- Reintroducing VectorBT, BaoStock, or AKShare is explicitly prohibited.
- Executing generated source in Backend HTTP handlers is unsafe and conflicts
  with ADR-0007; an isolated source-execution boundary requires a later ADR.
- Embedding full result data in business rows is unbounded and prevents object
  integrity/lifecycle controls.

## Exit evidence

Phase 12 tests cover deterministic manifests, OHLC and duplicate rejection,
next-session execution, T+1/limit/suspension/lot/fee/tax behavior, frozen
universe containment, approval authorization, idempotent jobs, bounded retry
and stale recovery, immutable result references, tamper rejection, deletion
guards, Backend API integration, and MCP translation.
