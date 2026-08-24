# Security Master v1 Contract

ADR-0026 defines a platform-scoped, Tushare-backed A-share security catalogue.
This is a BYQ Data Plane contract, not a raw `stock_basic` response contract.

## Record

Every record contains only:

- canonical `symbol` (`NNNNNN.SH`, `NNNNNN.SZ`, or `NNNNNN.BJ`) and six-digit
  `local_symbol`;
- `name`, optional `area`, `industry`, and `market` display metadata;
- normalized `exchange` (`SSE`, `SZSE`, or `BSE`);
- `list_status` (`L`, `P`, or `D`), `list_date`, optional `delist_date`, and
  optional `is_hs`;
- `asset_type=stock`.

The symbol suffix and exchange must agree. Dates use `YYYYMMDD`; listing date
is required and cannot be later than delisting date. Empty names, duplicate
symbols, conflicting statuses, malformed dates, and non-A-share identities
reject the complete synchronization result.

## Immutable snapshot

A complete sync requests all three statuses and commits atomically. The
snapshot projection contains:

- opaque `snapshot_id`;
- `provider=tushare`, `endpoint=stock_basic`;
- content-derived `dataset_id` and normalized `request_fingerprint`;
- exact statuses, row count, retrieval time, and creation time.

The dataset ID hashes canonical ordered records and excludes actor/timestamps.
An identical dataset reuses the snapshot. Historical snapshot members remain
readable inside the Data Plane even after current metadata changes.

## Product catalogue

`GET /api/product/data-center/securities` accepts bounded `query`, comma-
separated `statuses`/`exchanges`, `limit` (1-200), and non-negative `offset`.
It returns normalized records, exact total, page information, and the snapshot
that owns the page. It never returns database columns, actor identities,
credentials, raw provider fields, or workspace identity.

Security-master sync creation and job reads are admin-only. Catalogue reads
require durable authentication. The browser calls Gateway/Product API only.

## Daily-bar selection

A daily job freezes one of:

- `explicit`: 1-500 unique canonical symbols;
- `selected`: 1-500 symbols verified against the latest named catalogue
  snapshot;
- `security_master`: latest snapshot filtered by status/exchange/query;
- `stock_pool`: one owner-authorized immutable Stock Pool snapshot.

Catalogue and Stock Pool resolution are capped at 6,000 symbols. The job stores
the resolved list and source snapshot evidence before execution. Public job
responses expose `symbol_count`, at most 100 preview symbols, `result_count`,
and at most 200 per-symbol results.

`incremental` starts each symbol after its latest persisted bar within the
requested date bounds; already-current symbols finish as a successful no-op.
`range` requests the full declared interval. Both retain `KEEP_NEW` conflict
semantics.
