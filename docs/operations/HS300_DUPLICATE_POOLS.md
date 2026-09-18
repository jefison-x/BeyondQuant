# Duplicate HS300 Stock Pools: Read-Only Inventory and Consolidation Path

Read-only inventory of the production `byq_domain` database (2026-09-19).
No pool was created, renamed, merged, inactivated or deleted to produce this
report, and no ops script may perform the consolidation below.

## What "duplicate" means here

Four owner-scoped index pools (`owner_principal = admin`, workspace
`workspace_a064d2b76d774b4abc1a80b93671716b`) currently point at the **same
HS300 membership**: identical `stock_pool_snapshots.membership_fingerprint`
`7a7511881bded4dee10ad0bf01ebf2e12d16b809e62a9cea1efddca6632600b8` at
`effective_trade_date = 20230831`, 300 members. Only their names, creation
timestamps and requested `frozen_as_of` differ.

| pool_id | name | created (UTC) | snapshot | refs (signal / data-demand / domain) |
| --- | --- | --- | --- | --- |
| `stock_pool_70625654ef8c4b0a8887cfdcad4213c0` | 沪深300 基准快照 2023-08-31 | 2026-09-18 03:58 | `stock_pool_snapshot_e646ceb98b3b8e6d64310e0b4e782234ab67cd5afb2b50f9777e8511e9e32d94` | 3 / 0 / 4 |
| `stock_pool_7d2a4c5bf3b54391b438d6ce3f6e3f8e` | 沪深300 双均线凯利仓位研究池 | 2026-09-18 00:01 | `stock_pool_snapshot_529439a4711f581dcedbca250d97b8801c070916b9b16caf96c6c0510e96806b` | 1 / 0 / 1 |
| `stock_pool_d1edc22c2c8842189e0da41482e5d837` | 沪深300动量双均线回测池（2023-08-31成分） | 2026-09-17 03:10 | `stock_pool_snapshot_9755eb125dbaa390d97c19889bba42634991a3a94fc74600f543d9e4d98d1dd0` | 1 / 1 / 1 |
| `stock_pool_5c32872939294f20b18d81a9b7e5a402` | 沪深300历史成分快照-20230831 | 2026-09-12 03:57 | `stock_pool_snapshot_add816688e312acf5606d6c1108c4b3bbf431e948c545e71f1359a5a1773c342` | 0 / 0 / 0 |

`stock_pool_70625654…` is the one that owns the completed round-1 HS300
momentum+Kelly production evidence: `signaljob_fa70e3aa…` →
`artifact_300b1f7fc30e4fc1813a8148c0c1c829`, consumed by backtest
`backtest_83cab36af0ec486d98b0a002c671b5da` (`artifact_c62ab34ffd61405d85bac30ea3ca08ed`).
The other three hold either no references or earlier, superseded signal attempts
for the same membership.

## Not duplicates (distinct HS300 snapshots or owners)

These are also `index` HS300 pools but resolve to different membership evidence
or belong to another owner, so they must not be folded into the group above:

| pool_id | name | owner | effective date / fingerprint |
| --- | --- | --- | --- |
| `stock_pool_bcc8479e65394cde8dcffaae7a7b3e02` | 沪深300 | admin | `20260731` / `531b26e4…` |
| `stock_pool_490b110627364dd48625471d98e6887f` | 沪深300动量双均线策略池 | admin | `20230731` / `336687c5…` |
| `stock_pool_2b87e52d511646b2b974c5a29ef8fd8d` | 沪深300股票池（动量双均线周频策略） | admin | `20260831` / `f32878f6…` |
| `stock_pool_752c5d406543497696b478dc5c1cb53a` | 沪深300增强 | chromeuser | no snapshot (frontend provenance, no producer definition) |

## Recommended consolidation path (proposal only; requires domain authorization)

1. **Keep** `stock_pool_70625654ef8c4b0a8887cfdcad4213c0` as the canonical
   2023-08-31 HS300 research pool because it owns the authoritative completed
   round-1 backtest evidence and the most references.
2. **Set the three redundant pools to `inactive`** (reversible) — not `deleted`:
   * `stock_pool_7d2a4c5bf3b54391b438d6ce3f6e3f8e`
   * `stock_pool_d1edc22c2c8842189e0da41482e5d837`
   * `stock_pool_5c32872939294f20b18d81a9b7e5a402`
3. **Use the normal domain path**, never raw SQL: the owner (`admin`) requests
   `status: inactive` through the Product stock-pool management API /
   `byq_pool_lifecycle` (Backend `PaperTradingStore.set_pool_lifecycle`,
   ADR-0020/ADR-0050). Each request needs a trusted owner/actor, an idempotency
   key, a reason and produces a `stock_pool_lifecycle_audit` row. `inactive` is
   the safe, reversible target; it does not touch any snapshot or reference.
4. **Do not tombstone (`deleted`).** `deleted` is irreversible
   (`stock_pools.deleted_at` is set and the pool cannot be reactivated) and is
   unnecessary for consolidation. Only the owner may ask for it, and only after
   confirming no workflow still depends on the pool.
5. **Preserve evidence.** Closing `current_snapshot_id` pointers or editing
   snapshots is out of scope and prohibited; every snapshot, member row, signal
   job, data demand and domain reference stays immutable and readable after a
   pool becomes `inactive`.
6. **Leave the distinct-date pools and `chromeuser`'s `沪深300增强` untouched.**
   They are not duplicates; any cleanup is a decision for their own owner.

The actual mutation is an owner-authorized **domain/agent action**. No
operations script, including `scripts/ops/archive_terminal_signal_jobs.py`, may
merge, delete or re-status these pools.
