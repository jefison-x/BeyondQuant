# ADR-0013：Phase 16 Durable Market Data Storage 与 Logical Migration

- Status: Accepted
- Date: 2026-08-16
- Decision scope: Phase 16 Data Plane durable market-data target

## 背景

Phase 8 提供 process-local Tushare daily-bar Contract。Community 有历史 PostgreSQL
market cache，但该 cluster 是 read-only evidence，不能成为 BYQ authoritative storage。
任何 bulk import 之前，Phase 16 需要 durable BYQ Data Plane target 和安全的 logical
migration boundary。

## 决策

1. BYQ 持有新的 durable market-data target，以及 BYQ-owned schema、migration history、
   index、retention、backup/restore、refresh 和 provenance。Community PostgreSQL 绝不
   mount、copy 或作为 authoritative storage 使用。
2. Migration 必须 logical 且 repeatable：read-only `SELECT`/`COPY OUT` → validation/
   normalization → manifest → staging → BYQ import → post-import verification。
3. 只有 proven `tushare` row 或 proven provider-independent canonical row 有资格迁移。
   BaoStock 和 AKShare row 永久为 `DROP`。
4. Migration dry-run 是纯 BYQ Contract module。它接受有界 read-only audit snapshot，
   验证 canonical symbol/date/unit/OHLC/coverage/provenance，并产出 secret-free manifest
   和 quarantine report，不连接 Community PostgreSQL。
5. 现有 BYQ record 绝不采用 last-write-wins 覆盖。Conflict policy 为 `KEEP_NEW`、
   `VERIFY_EQUAL` 和 `REPORT_MISMATCH`。
6. 正式 bulk import 要求 live read-only Community audit、dry-run manifest/quarantine
   report 和经过测试的 target backup/restore evidence。

## 后果

- Historical cache 只有在 provenance、unit、schema 和 quality 验证后才能复用。
- 不修改任何 Community file、database 或 physical data directory。
- CI 无需 PostgreSQL 或 provider credential 即可测试 manifest/quarantine 和 conflict
  behavior。
