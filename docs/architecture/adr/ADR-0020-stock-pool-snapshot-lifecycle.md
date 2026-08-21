# ADR-0020: Stock Pool Identity, Snapshot, and Lifecycle Contract

- Status: Accepted
- Date: 2026-08-21
- Accepted: 2026-08-21
- Decision scope: Phase 34 Stock Pool depth
- Related: ADR-0005, ADR-0006, ADR-0008, ADR-0012, ADR-0014,
  ADR-0016, ADR-0017

## Context

Phase 34 must turn the existing create/list Stock Pool surface into a durable
domain capability. The current BYQ `stock_pools` row stores mutable symbols,
weights, provenance, and a constant `v1` label together. Paper orders validate
against whichever membership is current when the order is submitted, and no
historical membership can be resolved. The browser can also claim `index` or
`dynamic` provenance even though it is not a trusted producer.

The read-only Community implementation proves useful behaviors: canonicalize,
deduplicate, and sort symbols; fingerprint membership; reuse identical
versions; retain historical versions; select an index snapshot without
look-ahead; and prevent requested symbols or signals from escaping a frozen
universe. Its storage and lifecycle cannot be copied. Community includes pool
name, description, strategy, and activation in a version hash, and deleting a
pool leaves detached version records. Those semantics mix catalog state with
reproducible domain input.

## Decision

### 1. Separate mutable identity from immutable snapshots

`stock_pools` is the owner-scoped catalog identity. It contains a globally
generated `pool_id`, immutable `pool_type`, mutable name and description,
lifecycle status, and the current snapshot pointer. Name and description are
not reproducibility inputs.

`stock_pool_snapshots` and `stock_pool_snapshot_members` are append-only
PostgreSQL domain records. A snapshot contains the canonical membership,
weights, definition, provenance, effective-time semantics, schema version,
monotonic per-pool version number, and fingerprints. Updating members,
weights, filters, or trusted source state creates or reuses a snapshot;
renaming, describing, activating, or deactivating a pool does not.

The Backend computes every snapshot identity and fingerprint. Browser, DSH,
and MCP callers cannot supply an authoritative snapshot ID or fingerprint.

### 2. Canonical identity and idempotency

Symbols use the canonical `NNNNNN.SH|SZ|BJ` form, are deduplicated, and are
sorted by symbol. Snapshot identity is SHA-256 over canonical JSON containing
`schema_version`, `pool_id`, `pool_type`, normalized definition, normalized
provenance, effective-time fields, and ordered members with canonical decimal
weights. It excludes version number, timestamps, actor, name, description,
and lifecycle status. `membership_fingerprint` separately hashes only the
ordered symbol/weight membership, so equivalent membership can be compared
across pools without making snapshots share ownership.

An identical semantic update is a no-op that returns the existing snapshot.
A changed update requires an idempotency key and
`expected_current_snapshot_id`; stale writers fail with conflict. A new
semantic snapshot receives the next per-pool version number transactionally.

### 3. Weight contract

Weights are canonical decimal fractions, never binary floats in the persisted
or wire contract. A snapshot is either unweighted (all member weights null) or
fully weighted (every member has a weight). Mixed membership is rejected.
Weighted values must be finite, strictly positive, no greater than one, have
at most 12 decimal places, and sum to one within `0.00000001`; the Backend
stores the normalized exact values and the observed sum. Zero-weight members,
unknown symbols, duplicate symbols, ambiguous percent/fraction units, and
silent normalization are rejected.

Trusted index ingestion may convert provider percentages to fractions only
when it records `source_weight_unit`, conversion contract version, provider,
dataset identity, and effective trade date. Product input cannot perform that
conversion or assert provider provenance.

### 4. Typed provenance and writers

- `custom`: owned and edited by the user. It may store a normalized filter
  definition as explanation, but the persisted members are authoritative.
- `index`: produced only by a trusted BYQ domain/data-plane path from validated
  Tushare or proven provider-independent canonical data. It records index
  symbol, provider, dataset ID, effective trade date, source unit, and
  conversion contract. Browser and Product DSH cannot create or mutate it.
- `dynamic`: produced only by an accepted BYQ computation boundary. It records
  producer ID/version, rule fingerprint, evaluation time, and immutable input
  references. Phase 34 defines and renders this provenance but does not create
  a second generic rule engine or authorize browser/DSH production.

`pool_type` is immutable. BaoStock, AKShare, VectorBT, unproven Community data,
and `source: frontend` are invalid provenance.

### 5. Lifecycle and deletion

Lifecycle is `active -> inactive -> active` or `active|inactive -> deleted`.
Only active pools may receive new Paper Trading, research, or backtest
references. Inactive pools remain readable and their snapshots remain valid
for replay; they may be edited and reactivated. Deleted pools are tombstones:
they are hidden from default catalog queries, cannot be edited/reactivated,
and cannot receive new references.

Delete never removes snapshots or breaks existing references. Hard purge is
outside Phase 34 and would require a future retention decision plus an
authoritative, fail-closed live-reference check. Lifecycle changes are
owner-scoped, idempotent, and audited with actor, reason, previous/new state,
and timestamp.

### 6. Cross-domain references freeze snapshots

Paper Trading, research, and backtest records store
`stock_pool_snapshot_id` as their authoritative universe reference and may
also retain `pool_id` for display. They never resolve `current_snapshot_id`
during replay or execution.

- Backtest requests cannot combine a stock-pool snapshot with a separate
  index-universe selector. Requested symbols and every signal symbol must be
  contained by the frozen snapshot. ADR-0008/0017 validation still applies.
- Research inputs record the snapshot in immutable lineage and enforce owner
  equality.
- A Paper account or explicit universe binding freezes a snapshot. Orders are
  authorized against that binding; a pool edit cannot silently change an
  existing account's authorized universe. Rebinding/rebalancing is an
  explicit future or Phase 35 action that records the new snapshot.

Existing references remain resolvable after inactivation or deletion. New
references require owner equality, an active pool, and a current or explicitly
selected permitted snapshot. Index `as_of` resolution chooses the latest
effective snapshot at or before the requested date and never looks ahead.

### 7. Boundaries and product projections

The browser uses Gateway Product API only. Gateway forwards normalized
owner-scoped requests; Backend owns validation, persistence, fingerprinting,
and lifecycle. Agent-to-domain access uses bounded `byq_pool_*` MCP tools;
DSH never accesses PostgreSQL, Tushare, or raw Backend schemas.

The five persisted detail projections are: Overview, Members & Weights,
Definition & Filters, Provenance & References, and Snapshot History. Type-
specific UI may change labels or make trusted-source fields read-only, but it
does not replace those projections with mock or browser-derived data.

Pagination and response bounds apply to catalog, members, history, and
references. Unauthorized ownership is not disclosed. All writes require
durable BYQ user identity or a trusted service identity already permitted by
the relevant domain boundary.

### 8. Migration

Existing BYQ rows are migrated logically and idempotently into `custom`
catalog identities with one immutable snapshot while preserving `pool_id` and
owner. Canonical valid members and unambiguous valid weights are retained.
Invalid symbols, mixed/invalid weights, unproven non-custom type claims, or
ambiguous provenance are quarantined and reported rather than silently
repaired. The old `version = v1` label is migration input, not snapshot
identity.

Community PostgreSQL is not a Stock Pool migration source for this phase.
Community code, schema, and data remain read-only evidence and are not copied.

## Consequences

- Catalog edits and lifecycle actions no longer damage reproducibility.
- Every consumer can replay the precise universe it authorized.
- Index and dynamic pools require trusted producers; the Product UI cannot
  manufacture authoritative market provenance.
- Phase 34 needs additive schema, logical migration/quarantine reporting,
  Product API and MCP contract expansion, and explicit consumer-reference
  upgrades before the legacy mutable columns can be retired.
- Paper Trading must bind to snapshots; full rebalance and settlement depth
  remains Phase 35.

## Rejected alternatives

- Versioning the whole mutable pool row: produces false versions for rename or
  activation and couples replay to presentation metadata.
- Updating members in place: makes backtest, research, and paper authorization
  non-reproducible.
- Content-addressing membership without `pool_id`: risks cross-owner identity
  sharing and ambiguous lifecycle; cross-pool comparison uses the separate
  membership fingerprint instead.
- Hard-deleting the pool while retaining detached versions: loses a stable
  owner-scoped catalog/audit root.
- Letting the browser create index/dynamic pools or provenance: violates
  Product and provider boundaries.
- Copying Community ORM/routes or adding a compatibility layer: conflicts with
  the BYQ PostgreSQL, Product API, MCP, and runtime architecture.

## Rollback

Before any new snapshot is referenced, the additive tables and projections
can be removed and the legacy row contract restored. After references exist,
rollback means stopping new writes while retaining snapshot tables and a
read-only resolver; referenced immutable data must not be deleted. A rollback
must never rewrite consumer records to a mutable current pool.

## Acceptance review (2026-08-21)

Accepted by the repository maintainer through the explicit instruction to
execute the recommended remediation sequence with all required authorizations.
Acceptance followed read-only inspection and classification of Community
Stock Pool UI, models, routes, versioning, universe guard, migrations, and
tests; audit of current BYQ storage, Product API, frontend, and Paper Trading
authorization; and review against ADR-0005/0006/0008/0012/0014/0016/0017.

Acceptance is conditional on the contract tests and browser evidence listed
in `docs/contracts/stock-pool.md`. It authorizes Phase 34 implementation in a
new isolated worktree only after this ADR is merged; it does not mark Phase 34
complete and does not authorize Phase 35.
