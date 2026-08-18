# ADR-0017: Strategy Signal Snapshot Artifact for Backtest Input

- Status: Proposed
- Date: 2026-08-18
- Decision scope: Phase 32 Backtest create-wizard input boundary
- Related: ADR-0003, ADR-0007, ADR-0008, ADR-0016

## Context

The Phase 32 Community-parity Backtest workspace requires a browser "create
backtest" wizard. The existing Backend submit boundary
(`POST /v1/research/backtests`) already requires a validated
`strategy_version_artifact_id`, a validated `approval_artifact_id`, and a
frozen input snapshot (`universe`, `bars`, `signals`, `execution`,
`corporate_actions`). ADR-0008 deliberately accepts a frozen signal snapshot
and does not execute strategy Python source in this phase.

The wizard therefore cannot produce a backtest directly from a StrategyVersion:
something must supply the frozen signal snapshot. No such producer exists in
the current architecture. This ADR decides how the wizard references the signal
input without introducing unsafe strategy-source execution.

## Decision

1. A backtest submission references an immutable `signal_snapshot` Artifact.
   The signal snapshot is a BYQ domain artifact, not application source, and
   is produced by a BYQ-owned computation boundary (not by Product DSH).
2. The `signal_snapshot` artifact kind is added to the existing Artifact
   store (PostgreSQL per ADR-0016). Its content is a secret-free, normalized,
   JSON document:
   - `strategy_version_artifact_id`
   - `strategy_version_id`
   - `universe` (frozen symbols)
   - `bars` (one canonical OHLC bar per `(symbol, trade_date)`)
   - `signals` (stable buy/sell/hold rows with `symbol`, `trade_date`,
     `side`, `quantity`)
   - `execution` (next-session-open, T+1, lot size, costs, taxes)
   - `corporate_actions` (optional)
   - `source` (provenance: producer, content hash)
3. Phase 32 does NOT implement the signal producer (the component that
   executes strategy code to derive signals). The producer remains a future
   decision with its own ADR. Until then, signal snapshots may be created by:
   - an explicit keyless fixture/import path used only in tests and demos; and
   - future BYQ computation workers, once a producer ADR is accepted.
4. The Backtest create wizard selects a validated StrategyVersion, a matching
   `signal_snapshot`, and execution parameters, then submits through Product
   API. It never generates signals in the browser or through DSH.
5. MCP gains a read-only `byq_signal_snapshot_get` tool; DSH can inspect a
   signal snapshot but never create or mutate one in this phase.
6. Ownership, approval, and idempotency semantics follow ADR-0007 and
   ADR-0008. A `signal_snapshot` must reference a validated strategy version
   and be owned by the same principal.

## Consequences

- The Phase 32 create wizard is unblocked without executing untrusted
  strategy source.
- Backtest reproducibility improves: the snapshot is content-addressed and
  immutable.
- A separate signal-producer ADR is required before users can go from a
  newly written strategy to a backtest in one flow. Until then, the wizard
  relies on pre-computed snapshots (fixtures/imports).
- DSH remains outside the computation boundary; no provider credentials or
  storage access are widened.

## Rejected alternatives

- Executing strategy Python in the Backend request or in Product DSH:
  violates ADR-0008 and the Product source-protection boundary.
- Wizard uploading raw CSV signals: poor validation, provenance, and
  reproducibility.
- Adding a signal worker now: premature; its sandbox and determinism require
  a dedicated ADR.

## Rollback

Remove the `signal_snapshot` kind and the MCP read tool; backtest submission
reverts to requiring callers to pass the frozen input inline. No data-plane
migration is required.
