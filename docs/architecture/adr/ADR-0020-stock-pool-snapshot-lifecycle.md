# ADR-0020：Stock Pool Identity、Snapshot 与 Lifecycle Contract

- Status: Accepted
- Date: 2026-08-21
- Accepted: 2026-08-21
- Decision scope: Phase 34 Stock Pool depth
- Related: ADR-0005、ADR-0006、ADR-0008、ADR-0012、ADR-0014、ADR-0016、ADR-0017

## 背景

Phase 34 必须将现有 create/list Stock Pool surface 转换为 durable domain capability。
当时 BYQ `stock_pools` row 将 mutable symbol、weight、provenance 和常量 `v1` label 保存
在一起。Paper order 按 submit 时的 current membership 验证，无法 resolve historical
membership；Browser 还可以声称 `index`/`dynamic` provenance，尽管它不是 trusted
producer。

Read-only Community implementation 证明了有用 behavior：canonicalize/deduplicate/sort
symbol、fingerprint membership、复用 identical version、保留 history、无 look-ahead 地
选择 index snapshot，以及防止 requested symbol/signal 越出 frozen universe。其 storage
和 lifecycle 不能复制：Community 将 pool name、description、Strategy、activation 纳入
version hash，删除 pool 后留下 detached version record，混淆 catalog state 与可复现
domain input。

## 决策

### 1. 分离 mutable identity 与 immutable snapshot

`stock_pools` 是 owner-scoped catalog identity，包含 globally generated `pool_id`、
immutable `pool_type`、mutable name/description、lifecycle status 和 current snapshot
pointer。Name/description 不是 reproducibility input。

`stock_pool_snapshots` 与 `stock_pool_snapshot_members` 是 append-only PostgreSQL domain
record。Snapshot 包含 canonical membership、weight、definition、provenance、effective-
time semantics、schema version、monotonic per-pool version number 和 fingerprint。更新
member、weight、filter 或 trusted source state 会 create/reuse snapshot；rename、describe、
activate/deactivate pool 不会。

Backend 计算所有 snapshot identity/fingerprint。Browser、DSH、MCP caller 不能提供
authoritative snapshot ID 或 fingerprint。

### 2. Canonical identity 与 idempotency

Symbol 使用 canonical `NNNNNN.SH|SZ|BJ`，deduplicate 后按 symbol sort。Snapshot identity
是以下 canonical JSON 的 SHA-256：`schema_version`、`pool_id`、`pool_type`、normalized
definition/provenance、effective-time field，以及带 canonical decimal weight 的 ordered
member；排除 version number、timestamp、actor、name、description 和 lifecycle status。
`membership_fingerprint` 单独 hash ordered symbol/weight membership，使不同 pool 可比较
等价 membership，而不共享 ownership。

Identical semantic update 是 no-op，返回现有 snapshot。Changed update 要求 idempotency
key 和 `expected_current_snapshot_id`；stale writer conflict。新 semantic snapshot 在
transaction 中取得下一个 per-pool version number。

### 3. Weight Contract

Weight 是 canonical decimal fraction，persisted/wire Contract 绝不使用 binary float。
Snapshot 要么 unweighted（全部 member weight 为 null），要么 fully weighted（每个 member
都有 weight）；mixed membership 被拒绝。Weighted value 必须 finite、strictly positive、
不大于一、最多 12 位小数，并在 `0.00000001` tolerance 内 sum to one。Backend 保存
normalized exact value 和 observed sum。Zero-weight member、unknown/duplicate symbol、
ambiguous percent/fraction unit 和 silent normalization 均被拒绝。

Trusted index ingestion 只有在记录 `source_weight_unit`、conversion Contract version、
provider、dataset identity 和 effective trade date 时，才可将 provider percentage 转成
fraction。Product input 不能执行该转换或声称 provider provenance。

### 4. Typed provenance 与 writer

- `custom`：由 user 持有和编辑。可保存 normalized filter definition 作为解释，但
  persisted member 具有权威性。
- `index`：只由 trusted BYQ Domain/Data Plane path 从 validated Tushare 或 proven
  provider-independent canonical data 生成。记录 index symbol、provider、dataset ID、
  effective trade date、source unit 和 conversion Contract。Browser/Product DSH 不能
  create/mutate。
- `dynamic`：只由 Accepted BYQ computation boundary 生成。记录 producer ID/version、
  rule fingerprint、evaluation time 和 immutable input reference。Phase 34 定义并显示该
  provenance，但不创建第二套 generic rule engine，也不授权 Browser/DSH production。

`pool_type` immutable。BaoStock、AKShare、VectorBT、unproven Community data 和
`source: frontend` 都是 invalid provenance。

### 5. Lifecycle 与 deletion

Lifecycle 为 `active -> inactive -> active` 或 `active|inactive -> deleted`。只有 active
pool 可接收新的 Paper Trading、research 或 Backtest reference。Inactive pool 可读，
snapshot 对 replay 仍有效，且可编辑/reactivate。Deleted pool 是 tombstone：default
catalog query 不显示，不能 edit/reactivate，也不能接收新 reference。

Delete 不移除 snapshot，也不破坏 existing reference。Hard purge 不属于 Phase 34，需要
未来 retention decision 和 authoritative fail-closed live-reference check。Lifecycle change
按 owner 隔离、idempotent，并 audit actor、reason、previous/new state 和 timestamp。

### 6. Cross-domain reference 冻结 snapshot

Paper Trading、research 和 Backtest record 将 `stock_pool_snapshot_id` 保存为
authoritative universe reference，也可保留 `pool_id` 用于 display；replay/execution 时绝不
resolve `current_snapshot_id`。

- Backtest request 不能将 Stock Pool snapshot 与独立 index-universe selector 组合；
  requested symbol 和所有 signal symbol 必须包含在 frozen snapshot 中。ADR-0008/0017
  validation 继续适用。
- Research input 在 immutable lineage 中记录 snapshot，并强制 owner equality。
- Paper account 或明确 universe binding 冻结 snapshot。Order 按 binding 授权；pool edit
  不能静默改变 existing account authorized universe。Rebinding/rebalancing 是未来或
  Phase 35 明确 action，并记录新 snapshot。

Inactivation/deletion 后 existing reference 仍可 resolve。New reference 要求 owner
equality、active pool 和 current 或明确选择的 permitted snapshot。Index `as_of` resolve
requested date 当日或之前最新 effective snapshot，绝不 look ahead。

### 7. Boundary 与 Product projection

Browser 只使用 Gateway Product API。Gateway 转发 normalized owner-scoped request；
Backend 持有 validation、persistence、fingerprinting 和 lifecycle。Agent-to-Domain access
使用有界 `byq_pool_*` MCP tool；DSH 绝不访问 PostgreSQL、Tushare 或 raw Backend schema。

五种 persisted detail projection 为：Overview、Members & Weights、Definition & Filters、
Provenance & References、Snapshot History。Type-specific UI 可改变 label 或让 trusted-
source field read-only，但不能用 mock/browser-derived data 替代这些 projection。

Catalog、member、history、reference 均应用 pagination/response bound。不得泄露 unauthorized
ownership。所有 write 要求 durable BYQ user identity 或相关 domain boundary 已允许的
trusted service identity。

### 8. Migration

Existing BYQ row 以 logical/idempotent 方式迁移为 `custom` catalog identity 和一个
immutable snapshot，保留 `pool_id` 与 owner。Canonical valid member 和 unambiguous valid
weight 保留。Invalid symbol、mixed/invalid weight、unproven non-custom type claim 或
ambiguous provenance 被 quarantine/report，而非静默修复。旧 `version = v1` label 是
migration input，不是 snapshot identity。

Community PostgreSQL 不是本 Phase Stock Pool migration source；Community code、schema、
data 保持 read-only evidence，不复制。

## 后果

- Catalog edit/lifecycle action 不再破坏 reproducibility。
- 每个 consumer 可 replay 准确 authorized universe。
- Index/dynamic pool 要求 trusted producer；Product UI 不能制造 authoritative market
  provenance。
- Phase 34 在退役 legacy mutable column 前，需要 additive schema、logical migration/
  quarantine report、Product API/MCP Contract 扩展和明确 consumer-reference upgrade。
- Paper Trading 必须绑定 snapshot；完整 rebalance/settlement depth 留到 Phase 35。

## 拒绝的替代方案

- Version 整个 mutable pool row：rename/activation 产生 false version，并将 replay 耦合
  presentation metadata。
- In-place 更新 member：使 Backtest、research、Paper authorization 不可复现。
- 不含 `pool_id` 的 content-addressed membership：可能共享 cross-owner identity 并使
  lifecycle ambiguous；cross-pool comparison 应使用独立 membership fingerprint。
- Hard-delete pool 但保留 detached version：失去稳定 owner-scoped catalog/audit root。
- 允许 Browser 创建 index/dynamic pool 或 provenance：违反 Product/provider boundary。
- 复制 Community ORM/route 或增加 compatibility layer：与 BYQ PostgreSQL、Product API、
  MCP 和 runtime 架构冲突。

## 回滚

在任何新 snapshot 被 reference 前，可移除 additive table/projection 并恢复 legacy row
Contract。Reference 已存在后，rollback 表示停止新 write，同时保留 snapshot table 和
read-only resolver；不得删除 referenced immutable data，也绝不能将 consumer record
重写到 mutable current pool。

## Acceptance review（2026-08-21）

维护者明确授权执行 recommended remediation sequence 后接受本 ADR。Acceptance 建立在
对 Community Stock Pool UI、model、route、versioning、universe guard、migration 和 test
的 read-only inspection/classification，对当前 BYQ storage、Product API、frontend、Paper
Trading authorization 的 audit，以及对 ADR-0005/0006/0008/0012/0014/0016/0017 的 review
之上。

Acceptance 以 `docs/contracts/stock-pool.md` 所列 contract test 和 browser evidence 为
条件。它只在本 ADR merge 后授权在新 isolated worktree 中实现 Phase 34；不表示
Phase 34 已完成，也不授权 Phase 35。
