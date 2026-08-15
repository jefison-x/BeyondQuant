# ADR-0013: Phase 16 Durable Market Data Storage and Logical Migration

- Status: Accepted
- Date: 2026-08-16
- Decision scope: Phase 16 Data Plane durable market-data target

## Context

Phase 8 provides a process-local Tushare daily-bar contract. Community has a
historical PostgreSQL market cache, but that cluster is read-only evidence and
must not become BYQ authoritative storage. Phase 16 needs a durable BYQ Data
Plane target and a safe, logical migration boundary before any bulk import.

## Decision

1. BYQ owns a new durable market-data target with BYQ-owned schema, migration
   history, indexes, retention, backup/restore, refresh, and provenance.
   Community PostgreSQL is never mounted, copied, or used as authoritative
   storage.
2. Migration is logical and repeatable:
   read-only `SELECT`/`COPY OUT` -> validation/normalization -> manifest ->
   staging -> BYQ import -> post-import verification.
3. Only proven `tushare` rows or proven provider-independent canonical rows
   are eligible. BaoStock and AKShare rows are permanently `DROP`.
4. The migration dry-run is a pure BYQ contract module. It accepts a bounded
   read-only audit snapshot, validates canonical symbols/dates/units/OHLC/
   coverage/provenance, and emits a secret-free manifest plus quarantine
   report without connecting to Community PostgreSQL.
5. Existing BYQ records are never overwritten by last-write-wins. Conflict
   policy is `KEEP_NEW`, `VERIFY_EQUAL`, and `REPORT_MISMATCH`.
6. Formal bulk import requires a live read-only Community audit, a dry-run
   manifest/quarantine report, and tested target backup/restore evidence.

## Consequences

- Historical cache can be reused only after provenance, unit, schema, and
  quality validation.
- No Community file, database, or physical data directory is modified.
- CI can test manifest/quarantine and conflict behavior without PostgreSQL or
  provider credentials.
