# Community Market Data Migration

Status: `PLANNED` for Phase 16 design and later controlled execution.

This document defines a logical, read-only-source migration plan. It does not
perform a migration, create a target store, or authorize bulk import. The
Durable Market Data Storage ADR required by Phase 16 must be Accepted before a
formal import.

## Source and target boundary

### Source

- Repository: `/home/jefison/projects/BeyondQuant-community`.
- Reference revision inspected: `58dd99d` on `agent/workspace-community`.
- Database source: Community PostgreSQL configured by the legacy Compose file
  as `beyondquant` on PostgreSQL 15, with the local physical directory at
  `data/postgres`.
- Source policy: read-only. Allowed operations are schema inspection,
  `SELECT`, `COPY OUT`, and data-only logical export. `UPDATE`, `DELETE`,
  `ALTER`, `DROP`, `TRUNCATE`, migration execution, and cache cleanup are
  prohibited.

### Audit limitation at roadmap time

The Community `data/postgres` directory exists but is ignored by Git and was
not readable from this environment (`0700 nobody:nogroup`). No Community
PostgreSQL container was running; the available Docker containers belonged to
BYQ phase worktrees. Therefore table names and columns below are schema-source
evidence from Community Alembic/model files, not live row counts or a claim
that every table currently exists in the cluster. Phase 16 must repeat a
read-only live audit and record the connection/database/table evidence without
including credentials.

### Target

The new BYQ Data Plane is the only authoritative target. It must have a
BYQ-owned schema, migration history, indexes, retention policy, backup/restore
policy, update strategy, provider refresh strategy, and provenance model. The
Community PostgreSQL cluster and physical data directory must not be mounted,
copied, or used by BYQ runtime.

## Schema-source table audit

| Community table | Schema evidence | Provider/provenance gate | Initial migration decision | Target mapping work |
|---|---|---|---|---|
| `market_data_daily` | `symbol`, `trade_date`, `data_source`, `adjust`, `asset_type`, `open`, `high`, `low`, `close`, `volume`, `amount`; key includes symbol/date/source/adjust | Accept only proven `tushare` raw rows or proven provider-independent canonical rows; `adjust` must be understood and normally `none` | `MIGRATE_WHERE_VALID` | Map `volume` to BYQ `vol` only after unit proof; preserve raw OHLC, source, asset type, adjustment and provenance |
| `market_adjustment_factors` | symbol/date/source/asset type/`adj_factor` | Accept only proven Tushare rows with a defined factor convention | `MIGRATE_WHERE_VALID` | Map to BYQ adjustment-factor contract; do not mix with raw bars or invent adjusted prices |
| `market_trading_status` | symbol/date/source, pre-close, up/down limits, suspension flag/timing/type | Accept only rows with source and date semantics; validate limits and suspension meaning | `MIGRATE_WHERE_VALID` | Map to BYQ TradingStatus; preserve stable suspension/limit evidence and coverage |
| `market_corporate_actions` | symbol/end/ex/announcement/record/pay dates, dividend/share ratios, cash amounts, source | Accept only Tushare/proven canonical events with date and unit proof | `MIGRATE_WHERE_VALID` | Map to BYQ CorporateAction; retain point-in-time dates and cash/share units |
| `stock_universe` | symbol/name/industry/market/valuation fields/list date plus source and lifecycle additions | Source must be proven; historical valuation fields need effective/as-of semantics | `MIGRATE_WHERE_VALID` | Map to BYQ Security/universe snapshot; never treat mutable current rows as historical truth |
| `index_master` | index symbol/source/name/market/publisher/category/base/list metadata | Provider/source and index identity must be proven | `MIGRATE_WHERE_VALID` | Map to BYQ index master reference |
| `index_constituent_weights` | index/constituent/date/source/weight with point-in-time key | Accept only rows with effective snapshot semantics and source proof | `MIGRATE_WHERE_VALID` | Map to BYQ point-in-time universe/index membership |
| `security_name_history` | symbol/start/end/source/name/announcement/reason/ST flag | Accept only effective-dated records with source/date proof | `MIGRATE_WHERE_VALID` | Map to BYQ SecurityNameHistory and historical ST coverage |
| `stock_daily_basic` and other Tushare research tables | Schema/model evidence exists for daily valuation and research enhancements | Each dataset needs its own contract, unit, as-of, coverage, and source audit | `DEFER_UNTIL_MAPPED` | Do not include in a market-bar bulk import; add a separate dataset mapping/ADR if needed |
| sync-state tables | Per-source/per-symbol or per-period freshness and error state | Operational history is not automatically canonical market data | `REFERENCE_ONLY` | Rebuild BYQ migration/refresh state; do not treat old sync flags as truth |
| `market_data_ticks` / tick-like legacy caches | Legacy/ambiguous high-frequency data and source labels | No automatic acceptance without a separate high-frequency contract | `DROP_OR_DEFER` | Not part of Phase 16 daily cache migration |
| rows marked `akshare` or `baostock` | Provider-specific legacy rows | Permanently rejected | `DROP` | No adapter, fallback, or compatibility path |

The table list is not a declaration that data exists. Phase 16 live audit must
record discovered/missing tables, row counts, source distribution, date range,
symbol count, schema version, and checksums in a migration manifest.

## Community → BYQ schema mapping

The mapping is semantic, not a column rename. The import pipeline must preserve
the source field, normalized field, units, null semantics, adjustment,
asset-type, symbol/date, and provenance evidence for every accepted dataset.

| Community field | BYQ target field/contract | Required rule |
|---|---|---|
| `symbol` | canonical `symbol` / Phase 8 `ts_code` | Uppercase exact `NNNNNN.SH`, `NNNNNN.SZ`, or `NNNNNN.BJ`; reject bare/ambiguous symbols into quarantine rather than guessing an exchange |
| `trade_date` | BYQ `trade_date` | Validate exact `YYYYMMDD` and real calendar date; retain deterministic representation required by the target contract; no silent timezone/date shift |
| `volume` | BYQ `vol` for the daily provider contract, or a target storage volume field | Prove unit. The BYQ Phase 8 contract defines `vol` in lots and `amount` in thousand RMB; a value with unknown or conflicting unit is rejected |
| `amount` | BYQ `amount` | Prove monetary unit and currency; do not infer from magnitude; retain `NULL` semantics and reject negative values |
| `open`, `high`, `low`, `close` | BYQ raw OHLC | Finite numeric values; high ≥ open/close/low and low ≤ open/close; no silent correction |
| `pre_close`, `change`, `pct_chg` where available | BYQ daily-bar extension/provenance | Validate source definition and units; omit only under an explicit target contract, never silently reinterpret |
| `adjust` | BYQ adjustment type | Raw daily canonical cache must be `none` unless a future Accepted ADR defines adjusted data; adjusted rows cannot overwrite raw rows |
| `data_source` | BYQ provider/source provenance | Accept `tushare` or proven provider-independent canonical data only; retain original source and migration evidence |
| `asset_type` | BYQ asset type | Normalize only to supported values such as `stock`/`etf`; unknown values quarantine |
| `created_at`/`updated_at` | migration metadata only | Never use mutable legacy timestamps as market-data effective time or content identity |
| `ann_date`, `ex_date`, `record_date`, `pay_date` | BYQ point-in-time event fields | Validate each date's meaning and ordering; retain announcement visibility for research as-of checks |
| `weight` | BYQ index membership weight | Validate unit/percentage convention and snapshot date; do not treat current membership as historical membership |
| `start_date`/`end_date` in name history | BYQ effective interval | Validate non-overlap/ordering and announcement visibility; preserve open-ended interval semantics explicitly |

The Phase 16 Durable Market Data Storage ADR must resolve any difference
between durable storage names and the existing Phase 8 provider DTO (`ts_code`,
`vol`) or Phase 10/12 domain input shapes. It must not create a misleading
`volume → vol` rename without unit evidence.

## Validation and coverage

Each dataset import performs, at minimum:

1. source/table/schema/version and filter validation;
2. provider/source allowlist validation;
3. canonical symbol and asset-type validation;
4. `YYYYMMDD` date validation and `date_min`/`date_max` calculation;
5. finite numeric, NULL-semantic, OHLC, volume, amount, adjustment, and unit
   validation;
6. duplicate-key detection and deterministic ordering;
7. lifecycle, listing/delisting, trading-calendar, and suspension-aware
   coverage classification;
8. point-in-time/as-of and announcement visibility checks where applicable;
9. quarantine/report generation for every rejected or ambiguous row;
10. accepted-row content/checksum evidence before import.

Coverage states must distinguish `READY`, `PARTIAL`, `MISSING`,
`NOT_APPLICABLE`, `SUSPENDED`, and `NON_TRADING`. A missing bar is not by
itself missing data: pre-listing, post-delisting, non-trading sessions,
suspensions, and dataset boundaries need separate reasons. No synthetic bar or
silent repair is allowed in the canonical cache.

## Manifest contract

Every dry-run, import, retry, and verification emits a secret-free manifest
with:

```text
migration_id
source_repository
source_database
source_table
source_filter
source_row_count
accepted_row_count
rejected_row_count
duplicate_row_count
date_min
date_max
symbol_count
schema_version
target_dataset
started_at
completed_at
content/checksum evidence
```

The manifest is append-only and auditable. It must not contain passwords,
tokens, cookies, connection strings with credentials, or provider secrets.
The same source snapshot/filter/schema and target contract must produce a
stable import identity.

## Import, conflict, and rollback policy

```text
Community PostgreSQL (read-only)
  → logical SELECT/COPY OUT/data-only export
  → source snapshot + schema mapping
  → validation/normalization/quarantine
  → migration manifest
  → BYQ Data Plane staging
  → verification and deterministic conflict resolution
  → BYQ authoritative canonical dataset
```

For an existing BYQ record with the same `(symbol, trade_date, dataset,
source)`:

- `KEEP_NEW` when BYQ has a trusted existing record;
- `VERIFY_EQUAL` when source and target canonical content match;
- `REPORT_MISMATCH` when content differs, with neither side silently
  overwritten.

There is no last-write-wins policy. The import is idempotent, resumable, and
safe to retry. Rollback means removing only newly imported target records by
the migration identity or restoring a tested target backup; it never writes
back to Community. Quarantined data is retained as a report/evidence object,
not admitted as canonical data.

## Execution gates

Before a formal import, Phase 16 must have:

- an Accepted BYQ Durable Market Data Storage ADR;
- a live, read-only Community database audit with no mutation capability;
- source table/column/unit/provenance mapping for every selected dataset;
- a dry-run manifest, rejection/quarantine report, and coverage report;
- target backup and restore evidence;
- deterministic conflict and rollback tests;
- post-import row/count/checksum/coverage verification;
- confirmation that no Community file, database, or physical cluster was
  modified.

If provenance, units, schema, coverage, or data correctness cannot be proven,
the dataset is not migrated. Correctness takes priority over avoiding a
provider redownload. After validation, incremental Tushare refresh is preferred
to discarding a trustworthy historical cache and downloading it again.
