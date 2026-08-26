# Community Market Data Migration

Status: Phase 16 design 及后续 controlled execution 的 `PLANNED` 文档。

本文定义 logical、read-only-source migration plan；不执行 migration、不创建
target store，也不授权 bulk import。Phase 16 要求的 Durable Market Data
Storage ADR 必须先 Accepted。

## Source 与 target boundary

Source repository 为
`/home/jefison/projects/BeyondQuant-community`，检查 revision `58dd99d`
（`agent/workspace-community`）。Legacy Compose 配置的 database 是
PostgreSQL 15 上的 `beyondquant`，physical directory 为 `data/postgres`。
只允许 schema inspection、`SELECT`、`COPY OUT`、data-only logical export；
禁止 `UPDATE`、`DELETE`、`ALTER`、`DROP`、`TRUNCATE`、migration execution
和 cache cleanup。

Roadmap audit 时 `data/postgres` 为 ignored、`0700 nobody:nogroup`，本环境
不可读且无 Community PG container。下述 tables/columns 仅来自 Community
Alembic/model schema-source evidence，不代表 live row count 或 table 一定存在。
Phase 16 必须重新做 read-only live audit，记录 connection/database/table
evidence，但不记录 credentials。

唯一 authoritative target 是新 BYQ Data Plane，必须具 BYQ-owned schema、
migration history、indexes、retention、backup/restore、update/provider refresh
strategy 和 provenance。Community cluster/physical directory 不得 mount/copy/
供 BYQ runtime 使用。

## Schema-source audit

| Community table | Gate 与 decision | BYQ mapping |
|---|---|---|
| `market_data_daily` | 仅 proven `tushare` raw 或 provider-independent canonical；理解 `adjust`；`MIGRATE_WHERE_VALID` | 单位证明后 `volume→vol`；保留 raw OHLC/source/asset/adjust/provenance |
| `market_adjustment_factors` | 仅 proven Tushare 且 factor convention 明确；`MIGRATE_WHERE_VALID` | 独立 adjustment-factor contract，不与 raw bars 混合 |
| `market_trading_status` | source/date/limits/suspension semantics 必须证明 | BYQ TradingStatus，保留 limit/suspension/coverage evidence |
| `market_corporate_actions` | Tushare/proven canonical、dates/units 证明 | BYQ CorporateAction，保留 PIT dates/cash/share units |
| `stock_universe` | source/lifecycle/as-of 证明 | Security/universe snapshot；mutable current row 不作 historical truth |
| `index_master` | provider/index identity 证明 | BYQ index master reference |
| `index_constituent_weights` | effective snapshot/source 证明 | Point-in-time membership |
| `security_name_history` | effective dates/source 证明 | SecurityNameHistory/ST coverage |
| `stock_daily_basic` 等 | 每 dataset 需独立 contract/unit/as-of/coverage/source audit | `DEFER_UNTIL_MAPPED`，不混入 daily-bar bulk import |
| sync-state tables | operational history 非 canonical data | `REFERENCE_ONLY`，重建 BYQ state |
| tick-like caches | high-frequency semantics/source 模糊 | `DROP_OR_DEFER` |
| `akshare` / `baostock` rows | permanently rejected | `DROP`，无 adapter/fallback/compatibility |

Live audit manifest 必须记录 discovered/missing tables、row counts、source
distribution、date range、symbol count、schema version 和 checksums；上表不声称
数据存在。

## Community → BYQ semantic mapping

Mapping 不是简单 rename；每个 accepted dataset 都保留 source field、
normalized field、units、null semantics、adjustment、asset type、symbol/date
和 provenance evidence。

| Community field | BYQ target/rule |
|---|---|
| `symbol` | canonical `NNNNNN.SH`/`SZ`/`BJ`；bare/ambiguous quarantine，不猜 exchange |
| `trade_date` | 精确有效 `YYYYMMDD`，不 silent timezone/date shift |
| `volume` | BYQ `vol` 前必须证明 unit；Phase 8 为 lots |
| `amount` | 证明 currency/unit，不按 magnitude 推断；保留 NULL，拒绝 negative |
| `open/high/low/close` | finite 且满足 OHLC envelope；不 silent correction |
| `pre_close/change/pct_chg` | 校验 definition/unit；只按显式 contract omit |
| `adjust` | raw cache 必须 `none`，除非未来 Accepted ADR；adjusted 不覆盖 raw |
| `data_source` | 只接受 `tushare` 或 proven provider-independent，并保留 source |
| `asset_type` | 只 normalize supported values；unknown quarantine |
| `created_at/updated_at` | 仅 migration metadata，不作 effective time/content identity |
| event dates | 验证 meaning/order，保留 announcement visibility |
| `weight` | 验证 unit/snapshot date，不将 current membership 当 history |
| name-history interval | 验证 order/non-overlap/announcement/open-end semantics |

Durable Storage ADR 必须协调 storage names 与 Phase 8 DTO
（`ts_code`、`vol`）和 Phase 10/12 shapes；无 unit evidence 时不得伪装
`volume→vol`。

## Validation、coverage 与 manifest

每 dataset 至少验证 source/table/schema/version/filter、provider allowlist、
canonical symbol/asset、`YYYYMMDD`/date bounds、finite/NULL/OHLC/volume/
amount/adjustment/units、duplicates/order、lifecycle/calendar/suspension
coverage、PIT/as-of/announcement visibility，并为每个 rejected/ambiguous row
生成 quarantine/report；import 前生成 accepted content/checksum evidence。

Coverage 区分 `READY`、`PARTIAL`、`MISSING`、`NOT_APPLICABLE`、
`SUSPENDED`、`NON_TRADING`。Missing bar 不等于 missing data；pre-listing、
post-delisting、non-trading、suspension 和 dataset boundary 要有独立 reason。
Canonical cache 不允许 synthetic bar/silent repair。

每个 dry-run/import/retry/verification 生成 append-only、secret-free manifest：

```text
migration_id, source_repository, source_database, source_table, source_filter,
source_row_count, accepted_row_count, rejected_row_count, duplicate_row_count,
date_min, date_max, symbol_count, schema_version, target_dataset,
started_at, completed_at, content/checksum evidence
```

不得包含 passwords、tokens、cookies、credential-bearing connection strings 或
provider secrets。同一 source snapshot/filter/schema/target contract 必须产生
stable import identity。

## Import、conflict 与 rollback

```text
Community PostgreSQL (read-only)
  → logical SELECT/COPY OUT/data-only export
  → snapshot + schema mapping
  → validation/normalization/quarantine
  → manifest → BYQ staging
  → verification + deterministic conflict resolution
  → BYQ authoritative dataset
```

相同 `(symbol, trade_date, dataset, source)` 使用 `KEEP_NEW`、
`VERIFY_EQUAL`、`REPORT_MISMATCH`；绝不 last-write-wins。Import 必须
idempotent、resumable、retry-safe。Rollback 只按 migration identity 删除新
target rows，或恢复已测试 target backup；绝不写回 Community。Quarantine 作为
evidence object 保留，不进入 canonical data。

## Execution gates

Formal import 前必须：Accepted Durable Storage ADR；无 mutation capability 的
live read-only audit；每 selected dataset 的 schema/unit/provenance mapping；
dry-run manifest/quarantine/coverage；target backup/restore evidence；
deterministic conflict/rollback tests；post-import counts/checksum/coverage；
确认 Community file/database/cluster 未修改。

无法证明 provenance、units、schema、coverage 或 correctness 时不得迁移；
correctness 高于避免 redownload。验证后优先 incremental Tushare refresh，而非
丢弃可信 historical cache 重新下载。
