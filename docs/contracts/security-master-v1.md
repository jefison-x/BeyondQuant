# Security Master v1 Contract

ADR-0026 定义 platform-scoped、由 Tushare 支持的 A-share security catalogue。这是 BYQ Data Plane contract，不是 raw `stock_basic` response contract。

## Record

每条 record 只包含：

- canonical `symbol`（`NNNNNN.SH`、`NNNNNN.SZ` 或 `NNNNNN.BJ`）和六位 `local_symbol`；
- `name`，以及可选 `area`、`industry`、`market` display metadata；
- normalized `exchange`（`SSE`、`SZSE` 或 `BSE`）；
- `list_status`（`L`、`P` 或 `D`）、`list_date`、可选 `delist_date` 和 `is_hs`；
- `asset_type=stock`。

Symbol suffix 必须与 exchange 一致。Dates 使用 `YYYYMMDD`；listing date 必填且不能晚于 delisting date。Empty names、duplicate symbols、conflicting statuses、malformed dates 和 non-A-share identities 会拒绝整个 synchronization result。

## Immutable snapshot

完整 sync 请求全部三种 statuses 并原子 commit。Snapshot projection 包含 opaque `snapshot_id`、`provider=tushare`、`endpoint=stock_basic`、content-derived `dataset_id`、normalized `request_fingerprint`、精确 statuses、row count、retrieval time 和 creation time。

Dataset ID 对 canonical ordered records 取 hash，排除 actor/timestamps。相同 dataset 复用 snapshot。即使 current metadata 改变，historical snapshot members 仍可在 Data Plane 内读取。

## Product catalogue

`GET /api/product/data-center/securities` 接受有界 `query`、逗号分隔 `statuses`/`exchanges`、`limit`（1–200）及非负 `offset`。返回 normalized records、精确 total、page information 和拥有该 page 的 snapshot；不返回 database columns、actor identities、credentials、raw provider fields 或 workspace identity。

Security-master sync creation/job reads 仅 admin 可用；catalogue reads 要求 durable authentication。Browser 只调用 Gateway/Product API。

## Daily-bar selection

Daily job 冻结以下一种：

- `explicit`：1–500 个唯一 canonical symbols；
- `selected`：对最新 named catalogue snapshot 验证的 1–500 symbols；
- `security_master`：按 status/exchange/query 过滤的 latest snapshot；
- `stock_pool`：一个 owner-authorized immutable Stock Pool snapshot。

Catalogue/Stock Pool resolution 上限 6,000 symbols。Job 执行前存储 resolved list 和 source snapshot evidence。Public response 暴露 `symbol_count`、最多 100 个 preview symbols、`result_count` 及最多 200 个 per-symbol results。

`incremental` 从每个 symbol 在 requested date bounds 内的 latest persisted bar 之后开始；已最新的 symbol 以 successful no-op 完成。`range` 请求完整 declared interval。二者均保留 `KEEP_NEW` conflict semantics。
