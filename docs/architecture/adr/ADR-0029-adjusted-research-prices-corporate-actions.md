# ADR-0029: Adjusted Research Prices and Implemented Corporate Actions

- Status: Accepted
- Date: 2026-08-25
- Accepted: 2026-08-25
- Decision scope: Phase 56 adjustment factors, adjusted research input and
  corporate-action accounting
- Related: ADR-0005, ADR-0013, ADR-0017, ADR-0023, ADR-0027, ADR-0028

## Context

Raw A-share prices jump mechanically on ex-right/ex-dividend dates. Feeding
those jumps to a strategy can create false signals, while executing a backtest
on adjusted prices would invent fills that never traded. Phase 55 explicitly
left adjustment and corporate-action semantics to this phase.

Tushare documents `adj_factor` as an independent daily factor and defines A-share
forward adjustment as raw price multiplied by the day's factor divided by the
selected end-date factor. Its `dividend` contract distinguishes proposals from
implemented actions and separately identifies record, ex, payment and share
listing dates. Community demonstrates these domain needs but couples them to
its SDK, ORM, mutable cache and VectorBT-capable runtime.

## Decision

1. The trusted Data Worker obtains exact-date full-market `adj_factor` and
   `dividend(ex_date=...)` snapshots through closed BYQ contracts. Only canonical
   A-share symbols, positive finite factors, `实施` actions, valid dates and
   non-negative declared amounts/ratios are accepted.
2. PostgreSQL stores raw unadjusted daily bars, factors and implemented actions
   separately. Exact-date completeness, including a valid empty corporate-action
   result, is content-addressed. Existing execution bars are never overwritten
   or materialized as adjusted trades.
3. A `market-data-requirement.v2` requires factor and corporate-action evidence
   in addition to Phase 55 inputs. Legacy v1 waiting jobs remain executable with
   their original raw-input semantics.
4. The signal coordinator constructs a deterministic forward-adjusted research
   view using the last factor inside the frozen request as its anchor. The
   sandbox receives that research view; the immutable signal snapshot and
   native backtest retain raw execution bars.
5. The ready identity covers raw bars, factors, the adjusted view and corporate
   actions. The snapshot records the requirement, ready-input and research-view
   hashes, so replay cannot silently change its adjustment anchor or actions.
6. Corporate-action entitlement is established on the ex-date for positions
   already held. Net cash is credited no earlier than the declared pay date;
   shares are credited no earlier than the declared listing date. Missing dates
   fall back explicitly to the ex-date. Execution prices are not adjusted and
   the same economic event is not also converted through a factor.
7. Browser traffic remains Gateway/Product API only. Data Center discloses the
   synchronized dataset classes; it does not expose raw provider responses or
   credentials. Signal/backtest workers remain provider-free.

## Consequences

- Strategies no longer interpret a mechanical ex-right price jump as economic
  return, while orders still fill against auditable raw prices.
- Cash and share settlement are reproducible and date-aware.
- Tushare permission failures stay visible as incomplete readiness instead of
  silently reverting to unadjusted research data.
- Factor revisions create a new ready/research identity without overwriting an
  already frozen signal snapshot.

## Rejected alternatives

- Persist adjusted OHLC as execution data: invents historical fills and obscures
  the authoritative raw tape.
- Apply factors to held quantities and also apply corporate actions: double
  counts the same economic event.
- Accept dividend proposals or infer actions from price gaps: neither proves an
  implemented event.
- Copy Community SDK/ORM/VectorBT paths: violates current provider, storage and
  engine boundaries.

## Acceptance evidence

Provider tests cover exact parameters, field mapping, tax semantics and
fail-closed rows. PostgreSQL tests cover valid-empty completeness, adjusted-view
identity, raw/adjusted separation and frozen actions. Regression tests cover an
ex-right price discontinuity plus distinct entitlement/payment/share-listing
dates. Full Compose and desktop/mobile Chrome review verify worker isolation,
visible dataset scope, same-origin requests and a clean console.

## Rollback

Stop requesting v2 inputs and disable supplement synchronization. Existing v1
jobs and immutable snapshots remain usable. Additive factor/action evidence may
remain for audit; raw bars are unchanged.
