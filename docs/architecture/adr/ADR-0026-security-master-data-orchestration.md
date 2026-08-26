# ADR-0026：Security Master 与 Bounded Market-Data Orchestration

- Status: Accepted
- Date: 2026-08-24
- Accepted: 2026-08-24
- Decision scope: Beta Data Plane security master、catalogue Product API 和 daily-bar
  synchronization orchestration
- Related: ADR-0005、ADR-0013、ADR-0016、ADR-0019、ADR-0020、ADR-0025

## 背景

Phase 39 交付 durable Tushare daily-bar job，但每个 job 要求 operator 已知 1-20 个
canonical symbol。Coverage projection 只列已有 bar 的 symbol，无法 bootstrap 完整
A-share catalogue。这使 Data Center 内部一致，却不能用于首次 market-data acquisition。

Read-only Community implementation 调用 Tushare `stock_basic` 获取 listed、paused、
delisted security，并保存 mutable stock universe。有用证据是 canonical identity、
lifecycle date、searchable basic metadata 和 security-master-first synchronization
sequence；其 provider registry、ORM、Pandas/Tushare SDK、background thread、broad
multi-dataset runtime 和 frontend-to-internal API coupling 均不兼容 BYQ。

BeyondQuant 保持 Beta，直到维护者明确授权正式 release。该能力只闭合 Beta Product
gap，不授权 release、新 provider 或 arbitrary Tushare access。

## 决策

1. BYQ 持有 framework-neutral `security-master.v1` Contract，定义 canonical A-share
   stock identity。Record 包含 canonical/local symbol、display name、exchange、market/
   board、area、industry、listing status、listing/delisting date、Stock Connect flag、asset
   type 和有界 provenance。只接受 `.SH`、`.SZ`、`.BJ` stock。
2. Backend-owned Tushare Adapter 增加明确 `stock_basic` capability。它以 explicit field
   list 请求 closed status set `L`、`P`、`D`，在 Backend 内转换 raw envelope，拒绝
   duplicate/conflicting identity，绝不暴露 arbitrary endpoint/parameter passthrough。
   Tushare `T` prefix historical alias（如 `T600018.SH`）不是 canonical A-share identity，
   且 normalization 会与另一 six-digit security collision；因此仅将有界且 otherwise
   valid alias persistence 为 quarantine evidence，并排除于 authoritative catalogue。
3. PostgreSQL 持有 platform-scoped current security record 和 immutable content-addressed
   security-master snapshot。每次 successful full sync 都 atomic，并记录 provider、request/
   dataset fingerprint、status coverage、row count、retrieval time、actor 和 snapshot
   member。Later snapshot 缺失的 row 保留为 historical evidence，但不作为 latest catalogue
   member 显示。
4. Security master 依据 ADR-0025 是 platform data，没有 `workspace_id`，也不 export 到
   personal workspace bundle。Synchronization 只允许 administrator；authenticated
   Product user 在 Product workflow 需要时只能获得有界 searchable catalogue。
5. Browser access 保持 same-origin Gateway/Product API。Product response 只含 normalized
   record/job metadata，不暴露 credential、raw Tushare envelope、database schema、MCP
   surface 或 DSH event。
6. Daily-bar job 可从四种有界 source resolve frozen symbol selection：explicit canonical
   symbol、selected catalogue symbol、按 listing status/exchange filter 的 latest security-
   master snapshot，或 authorized immutable Stock Pool snapshot。Execution 前 persistence
   resolved symbol/selection provenance，因此后续 catalogue/pool change 不影响 job。
7. Explicit/selected request 保持有界；catalogue/Stock Pool orchestration 最多 resolve
   6,000 symbol。Public job projection 返回 count 和 bounded preview/result，不返回无界
   symbol array。Provider call 保留 bounded retry 和 durable per-symbol progress。
8. `range` sync 请求 declared inclusive range。`incremental` sync 从每个 symbol latest
   persisted bar 之后开始，并受 requested range 限制；coverage 已到 end 时记录 no-op。
   Existing authoritative bar 继续使用 `KEEP_NEW`，绝不 last-write-wins overwrite。
9. Data Center 提供 basic-data synchronization、status count、searchable/paginated stock
   catalogue、explicit selection、all-listed/exchange filter、Stock Pool selection 和 daily-
   bar job progress；不隐含 live quote、fundamental、ETF/index master 或 complete market
   coverage。

## Security 与 domain invariant

- Tushare plaintext 依据 ADR-0019 保持在 Backend 内。
- Canonical `stock_basic` result 必须匹配 requested status 和 symbol/exchange relation；
  malformed date、empty name、conflict 和 unknown out-of-contract identity 使整个 snapshot
  fail。只有有界、fully validated `T` prefix historical alias 可 quarantine；count/identity
  evidence 随 immutable snapshot 保存，且不进入 `market_securities` 或 daily-bar selection。
- Successful security-master sync 是 atomic；partial provider status result 绝不替换 latest
  catalogue。
- Dataset identity 排除 mutable timestamp/actor metadata。
- Daily job 在 provider execution 前冻结准确 symbol/source snapshot。Client-supplied
  workspace/ownership field 不授予 access。
- Stock Pool resolve 要求 trusted durable workspace/owner context 和 existing immutable
  snapshot；guessed cross-workspace ID 按 not found fail。
- BaoStock/AKShare 保持 `DROP`，不增加 compatibility provider/fallback。

## 后果

- Fresh BYQ deployment 可在要求 operator sync daily bar 前 bootstrap 真实 A-share catalogue。
- Full-market historical refresh 成本高，但明确、有界、observable，并可通过 incremental
  job 在 symbol level resume；受 Tushare account permission/rate limit 约束。
- Security metadata 成为 shared platform dependency。Future ETF、index、calendar、
  valuation 或 corporate-action dataset 需要独立 mapped Contract，不能 piggyback 本
  endpoint。

## 必需证据

- secret-free fixture 的 provider translation/retry/duplicate/status/date test，包括有界
  historical-alias quarantine 和 fail-closed unknown identity；
- PostgreSQL atomic snapshot、idempotency、latest catalogue、search/filter/pagination、
  historical retention test；
- daily selection freezing/bound、incremental semantics、Stock Pool authorization、Product
  API RBAC、response-bounding test；
- frontend component/API test 和真实 Product API desktop/mobile Chrome DevTools review；
- Community classification 和 architecture test，证明无 excluded provider、raw Tushare、
  Backend、MCP、DSH 或 PostgreSQL Browser path。

## 拒绝的替代方案

- 从 distinct daily bar 派生 catalogue：遗漏 suspended、not-yet-traded 和 historical
  lifecycle record，且无法自举。
- Fetch 一次 recent `daily` market snapshot：code 缺少 authoritative basic identity/
  lifecycle，并遗漏 non-trading security。
- 让 Frontend/DSH 调 `stock_basic`：暴露 provider schema/credential，绕过 Product API/MCP。
- 复制 Community stock-universe stack：重引入 incompatible ORM、provider registry、SDK、
  scheduler 和 mutable-current-row assumption。
- 从 Browser submit 数千 symbol：造成 unbounded request/replay payload，并让 client 对
  catalogue identity 具有权威。

## 回滚

禁用新 Product route/security-master job create。Existing daily job 继续接受 legacy
explicit-symbol Contract。Additive platform table/immutable snapshot 可保留为 audit
evidence；不修改 workspace row 或 Community source。Failed schema/data rollout 通过
forward repair 或正常 PostgreSQL backup boundary restore。
