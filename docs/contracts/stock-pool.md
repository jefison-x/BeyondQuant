# Stock Pool Contract — Phase 34

本 contract 落实 ADR-0020。关键词 **MUST**、**MUST NOT**、**SHOULD** 和 **MAY** 具有规范性。

## Domain records

### Pool identity

Pool identity 必须暴露 `pool_id`、`owner_principal`、`name`、可选 `description`；immutable `pool_type`（`custom`、`index` 或 `dynamic`）；`status`（`active`、`inactive` 或 `deleted`）；`current_snapshot_id`、`current_version_number`、`created_at`、`updated_at` 和 lifecycle audit metadata。

`pool_id` 必须由 Backend 全局生成。Catalog reads 必须 owner scoped。Deleted identities 默认排除，除非授权显式有界 `include_deleted` operator/domain query。

### Immutable snapshot

Snapshot 必须暴露：

- `snapshot_id`、`pool_id`、`schema_version` 和 per-pool `version_number`；
- `membership_fingerprint`、`snapshot_fingerprint`；
- `pool_type`、normalized `definition`、normalized `provenance`；
- 按类型可选 `effective_at`/`effective_trade_date`；
- `member_count`、`weight_mode`、`weight_sum`、immutable `created_at`；
- paginated member projection 和 owner-safe reference summary。

Snapshot identity 使用 sorted object keys、无无意义空白的 canonical UTF-8 JSON。Decimal weights 为 canonical strings，members 按 canonical symbol 排序。Mutable timestamps、actor、pool name、description、status 和 `version_number` 不得进入 hash。

### Members 与 weights

每个 member 含 `symbol`、可选 `weight` 和有界 type-specific display metadata。Display name、industry、live quote data 是 joins，不属于 snapshot identity，除非未来 Accepted ADR 明确冻结。

Backend 必须拒绝 empty membership；non-canonical/duplicate/out-of-contract symbols；混合 weighted/unweighted members；zero、negative、non-finite、over-one 或 over-precision weights；不在 `1 ± 0.00000001` 内的 weighted sums；non-members 的 weights；以及未标记的 percent-to-fraction conversion。

## Write behavior

### Create

User Product API create 仅限 `custom`。Backend 原子生成 pool 和 first snapshot。Trusted index/dynamic creation 使用独立 service capability，并校验 ADR-0020 要求的 provenance。

### Metadata update

Name/description updates 需要 owner scope 和 optimistic identity version checking；不得创建 membership snapshot。

### Snapshot update

Member、weight、definition 或 trusted provenance updates 要求 `expected_current_snapshot_id`、`idempotency_key`、完整 desired semantic snapshot（非模糊 partial JSON merge），以及与 `pool_type` 相符的 owner/trusted-writer authorization。

Backend 在一个 transaction 内 canonicalize/hash。相同 semantic content 返回 existing snapshot，不递增 version。Stale expectation 或同 idempotency key 搭配不同 content 返回 conflict。任何 update 都不修改 existing snapshot。

### Lifecycle

Activation、deactivation、delete 需要 idempotency key 和有界 reason。重复相同 target state 成功且不重复 audit records。`deleted` 为 terminal；deleted pool 不能接受 metadata/snapshot writes。Replay 所需 snapshot/history/reference reads 仍可经 owner/domain-authorized routes 使用。

## Provenance

`custom` provenance 记录 `source=custom`、由 audit 记录 creator/last editor，以及可选 normalized filter definition。Filter results 在持久化为 snapshot members 前不具权威性。

`index` provenance 必须含 `source=index`、canonical index symbol、provider、provider dataset ID、effective trade date、original weight unit、normalization contract version 和 ingestion manifest/reference。除非验证通过 provider-independent canonical data，否则 configured provider 为 Tushare。禁止 BaoStock 和 AKShare。

`dynamic` provenance 必须含 `source=dynamic`、producer ID/version、rule fingerprint、evaluation time 和 immutable input references。Phase 34 不得创建 generic rules runtime，也不得让 Product DSH 执行评估。

## Consumer rules

- 新 consumer 必须绑定 `stock_pool_snapshot_id`、验证 owner equality，并拒绝 inactive/deleted pools。
- Replays 必须直接解析 stored snapshot，不得 dereference current pool pointer。
- Backtest requested symbols/signals 必须是 snapshot 子集，且不得与另一 index-universe selector 组合。
- Research artifacts 必须记录 snapshot lineage。
- Paper authorization 必须使用 account/universe snapshot binding；pool edits 不得改变 existing binding。
- Index `as_of` 选择 effective date 不晚于 requested date 的最新 snapshot。

## Product API 与 MCP surface

Phase 34 Product API 必须提供 owner-scoped、有界的 catalog list、pool create/detail、metadata update、current members/weights、complete snapshot update、definition/filter、provenance/reference、snapshot history/detail、lifecycle/tombstone delete 和 trusted index constituent/as-of reads。精确 paths 随实现加入 `product-api.openapi.yaml`。Browser 只能调用 `/api/product/...`，不得提交 authoritative fingerprints、snapshot IDs、trusted provenance 或 provider operations。

Phase 34 还必须增加有界 normalized `byq_pool_*` capabilities，覆盖 catalog、detail、snapshot/history inspection、允许的 custom-pool writes 和 lifecycle actions。Results 不得暴露 storage schemas/provider credentials。DSH 不得访问 PostgreSQL/raw Backend endpoints。Mutating tools 必须保留 trusted owner/actor context、idempotency 和 optimistic concurrency。

## Migration contract

当前 BYQ `stock_pools` migration 必须 logical、repeatable 且 transaction-safe：

1. inspect/classify 每行；
2. normalize/validate owner、type、symbols、weights 和 provenance；
3. 保留 `pool_id`，创建 identity 与一个 immutable snapshot；
4. 记录 migration manifest 和 deterministic counts/checksums；
5. 以 reason codes quarantine invalid/ambiguous rows；
6. rerun 不重复 identities/snapshots；
7. import 后验证 current pointers/fingerprints。

缺少 trusted provenance 的 non-custom type claims 必须 quarantine，或仅经 reviewed operator mapping 显式降级，不得静默接受。本 migration 不导入 Community data。

## 必需 acceptance tests

Automated tests 必须证明 owner isolation/non-disclosing responses；canonical ordering、deterministic fingerprints、duplicate rejection；精确 weight/unit/decimal validation；no-op reuse、monotonic versions、idempotency/optimistic conflicts；rename/lifecycle 不创建 snapshots；inactive/deleted reference rules 与 historical resolution；tombstone 不孤立/删除 snapshots；index as-of 无 look-ahead 且 provenance 可信；backtest/research/paper 冻结并强制 membership；migration 幂等且 quarantine invalid rows；Product API 与 `byq_pool_*` parity；五个 UI detail projections 使用真实持久化 Product API data。

Chrome MCP evidence 必须覆盖 desktop/mobile catalog/detail、custom pool create/edit、weight validation、snapshot history、lifecycle actions 和至少一个 read-only index/as-of flow。Completion report 必须链接 Community feature checklist 和 Phase 34 visual reference evidence。
