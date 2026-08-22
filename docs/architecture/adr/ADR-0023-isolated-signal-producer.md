# ADR-0023: Isolated Strategy Signal Producer

- Status: Accepted
- Date: 2026-08-22
- Accepted: 2026-08-22
- Decision scope: Phase 40 strategy-version to signal-snapshot production
- Related: ADR-0007, ADR-0008, ADR-0013, ADR-0016, ADR-0017

## Context

ADR-0017 made an immutable `signal_snapshot` the only strategy signal input to
the native backtest engine, but deliberately left execution of StrategyVersion
Python source undecided. The Product flow can therefore submit a backtest only
when a keyless fixture/import has already created a matching snapshot. D-0002
requires a BYQ-owned producer before a newly authored strategy can reach a
backtest end to end.

Community executes `CustomStrategy` with Python `exec()` and a restricted
builtins/import dictionary in the backtest service process. Its useful evidence
is the synchronous `generate_signals(data, parameters)` contract and stable
`-1/0/1` signal meaning. Static AST checks and restricted builtins are not a
security boundary, and the Community process, Pandas runtime, provider access,
ORM and backtest coupling must not be copied.

## Decision

1. BYQ introduces a dedicated, durable signal-production job owned by the
   Quant Domain plane. A Product request references one validated,
   owner-matching StrategyVersion, an immutable Stock Pool snapshot, a bounded
   date range, finite JSON parameters, an execution profile and an idempotency
   key. Backend resolves and freezes canonical PostgreSQL daily bars before a
   job becomes runnable. The producer never downloads data or calls Tushare.
2. Production has two privilege tiers:
   - a trusted `signal-worker` coordinator may claim PostgreSQL jobs, read the
     frozen input and persist normalized results; it never executes strategy
     source; and
   - a dedicated `signal-sandbox` runner executes the source. It receives only
     a bounded secret-free input document and exposes only the fixed BYQ
     strategy protocol. It has no BYQ database, Provider, model, DSH, MCP,
     repository or Docker credentials and no application-source mount.
3. The sandbox is not a generic agent/code harness. Each invocation runs in a
   fresh child process as a non-root user with a read-only filesystem, empty
   writable temporary directory, dropped Linux capabilities,
   `no-new-privileges`, bounded process count/memory/CPU/wall time, a sanitized
   environment and no external network route. The coordinator treats timeout,
   crash, invalid output and resource exhaustion as stable failed outcomes.
4. The Phase 40 execution profile is `byq-signal-python-v1`. It supports exactly
   one synchronous `CustomStrategy.generate_signals(data, parameters)` entry
   point over frozen Pandas-compatible canonical bars. Imports are closed to
   deterministic data/math helpers shipped in the sandbox. Filesystem,
   subprocess, socket, reflection/dunder, dynamic compilation, clock, entropy
   and randomness access are rejected. `generate_target_weights` and arbitrary
   ML training are not in this profile; validation may describe them, but the
   producer fails closed as `execution_profile_unsupported`.
5. Output is a mapping from canonical symbol to a date-indexed series with
   values `-1`, `0` or `1`. The coordinator converts non-zero rows to stable
   `sell`/`buy` signal rows using an explicit positive, lot-aligned
   `order_quantity` from the job request. Unknown symbols/dates, duplicate
   rows, non-finite values and any other output shape are rejected. Empty
   signals are valid and remain explicit.
6. Reproducibility is contractual: input bars, universe, parameters, execution
   profile/version, interpreter/dependency lock identity and strategy source
   fingerprint are content-addressed; input and output ordering is canonical;
   deterministic environment/thread settings are fixed. Replaying an identical
   request resolves to the same validated `signal_snapshot` content identity.
7. Backend revalidates sandbox output with the existing ADR-0017 snapshot
   normalizer before it creates or reuses the immutable `signal_snapshot`
   Artifact. Artifact ownership, task lineage, approval and later backtest
   authorization remain ADR-0007/ADR-0008/ADR-0017 responsibilities. A producer
   success does not itself approve or run a backtest.
8. Product API exposes owner-scoped job create/status and a composed
   produce-and-submit flow. MCP may expose bounded job orchestration, but DSH
   never receives source-execution authority, raw bars, credentials or storage
   access. The browser uses Product API only and never submits executable code
   directly to the sandbox.

## Consequences

- The product can complete strategy version → frozen signal snapshot → native
  backtest without moving strategy execution into DSH or an HTTP request.
- The sandbox image and protocol become a security-sensitive exact dependency
  surface with isolation and escape-regression tests.
- Phase 40 does not promise compatibility with every Community Python/ML
  strategy. Unsupported execution profiles fail explicitly instead of silently
  running with broader privileges.
- The coordinator/sandbox split costs one internal service boundary but keeps
  PostgreSQL and service credentials out of the untrusted execution tier.

## Rejected alternatives

- Community-style `exec()` inside Backend/backtest worker: static filtering is
  not isolation and would expose process credentials and storage connectivity.
- Product DSH execution: violates the Agent-to-Domain and source-protection
  boundaries and turns DSH into a quantitative runtime.
- Browser signal generation or raw CSV upload: loses trusted provenance,
  ownership and reproducibility.
- Giving the sandbox PostgreSQL/Tushare access: lets strategy code bypass
  frozen inputs and exfiltrate credentials.
- A second generic code/agent harness: prohibited; the runner implements only
  the closed `byq-signal-python-v1` protocol.

## Acceptance review

The repository maintainer accepted the recommended boundary on 2026-08-22
after reviewing that the produced signal is a historical, reproducible
buy/sell/hold intent snapshot rather than an Agent event or live broker order.
Acceptance requires tests for owner isolation, input freezing, idempotency,
determinism, unsupported profiles, time/resource limits, secret absence,
network/storage denial, output normalization and the complete Product API
strategy-to-backtest journey.

## Rollback

Disable new producer job creation and remove the coordinator/sandbox services.
Existing immutable `signal_snapshot` artifacts remain readable and valid under
ADR-0017; the Product returns to the explicit keyless import path.
