# Paper Trading Contract — Phase 35

本 contract 落实 ADR-0021。关键词 **MUST**、**MUST NOT**、**SHOULD** 和 **MAY** 具有规范性。

## Domain invariants

- Paper Trading 必须仅为 simulation，并与 Backtest/live brokerage 分离。
- 每条 record/mutation 必须 owner scoped；不得泄漏未授权 ownership。
- Account、order、fill、ledger、snapshot 和 bundle IDs 必须由 Backend 生成或 remap；Browser、DSH 和 import payloads 不是 identity authorities。
- Money 必须使用精确 decimal semantics；quantities 为非负整数。
- Mutations 必须 transactional、idempotent；同 key 不同 request reuse 必须 conflict。
- Browser traffic 必须使用 Gateway/Product API；Agent mutations 必须使用有界 MCP 和适用的 ADR-0009 approval reference。

## Account 与 universe binding

Account 暴露 generated identity、name、CNY currency、initial/current cash、equity、realized P&L、status、version、settlement date、frozen Stock Pool snapshot binding 和 timestamps。首个 accepted order 必须绑定 active、owner-equal snapshot，后续 orders 必须使用该 binding。显式 rebind 要求 empty portfolio、expected account version、idempotency key 和 audit record。

用户删除 Account 必须是 owner-scoped、expected-version、idempotent 的 tombstone mutation。
删除后的账户不再出现在 Product catalog，也不能继续读取或交易；Backend 必须保留既有 order、
fill、ledger、snapshot、transfer 与 audit history，并追加 `account_deleted` audit。删除不得物理级联
或改写不可变历史。为允许用户重新使用原账户名，tombstone 可将内部名称改为带 account identity
后缀的不可见保留名。

## Orders、positions 与 fills

Order 必须保留 normalized input、pool/snapshot identity、risk outcome、stable blocked reason、cost/tax result、decision provenance、fill reference 和 immutable events。Phase 35 terminal states 为 `filled` 和 `blocked`；UI 不得暗示 asynchronous/live-broker states。

Positions 必须保留 total、sellable、locked quantities，以及 average cost 和 last mark/provenance。Buys 只锁定 purchased quantity；sells 只消耗 sellable quantity。Tests 必须覆盖 mixed old/same-day holdings。

## Settlement 与 snapshots

Settlement 要求 canonical date、expected account version、idempotency key，以及所有 open positions 的完整、正且有限的 mark set。Dates 严格单调。一个 transaction 提升 eligible locked quantity、持久化 marks、追加一个 immutable daily snapshot 和 settlement audit/ledger entry，并推进 account state。

Snapshot identity 必须包含 canonical account/date/position/mark semantics，排除 mutable timestamps 和 actor display data。Same-date identical replay 幂等；不同 content conflict。Valuation 不得记录为 cash movement。

## Risk controls

持久化 control projection 包含 versioned kill-switch state/reason 和可选 maximum order notional。Updates 要求 optimistic concurrency、idempotency、owner/actor audit 和有界 values。Order detail 记录所评估 control version/result。Phase 35 不暴露 failure circuit breaker。

## Ledger

Ledger 必须 append-only 且由 Backend 生成，记录 initial funding、fill cash changes、zero-cash settlement audit events 和带稳定 references/account summaries 的 import provenance。Pagination/order 确定。Product caller 不能更新或删除持久化 ledger entry。

## Asset bundle

`paper-account-bundle-v1` export 必须 canonical、有界，semantic sections 确定，并含带 SHA-256 digests/counts 的 manifest。必须排除 owner/actor authority、secrets、tokens、DSH raw events、market datasets 和 source code。

Import 写入前必须验证所有 digests、bounds、references、arithmetic、chronology 和 local frozen-universe permissions；原子创建新的 owner-scoped account 并 remap IDs。不得覆盖、不得接受 bundle 中的 owner，也不得部分导入无效数据。

## Product projections

持久化六视图 workspace 为 Overview、Positions、Orders & Fills、Ledger、Snapshots、Risk & Transfer。Order detail、settlement、controls、export/import 都是真实 Product API flows。Collection responses 有界。Browser 不得直接调用 Backend、MCP、DSH、PostgreSQL、Redis 或 data provider。

## Community classification

| Community capability | Decision | BYQ treatment |
|---|---|---|
| Account selector/create 与 order workspace | `REFACTOR` | 保留 UX 意图；使用 durable identity、Product API 和 BYQ state machine。 |
| Overview/positions/orders/ledger/snapshot layout | `PORT_LAYOUT` + `PORT_UX` | 适配六个 BYQ persisted projections 和 responsive shell。 |
| T+1 sellable quantity 与 immutable daily settlement | `PORT_LOGIC` + `PORT_TESTS` | 重新实现精确 quantities、monotonic dates 和 conflict semantics。 |
| Order detail lifecycle | `PORT_UX` | 呈现 BYQ immediate fill/blocked events，不虚构 broker states。 |
| Kill switch 与 max-order notional | `PORT_UX` + `REFACTOR` | 持久化、version、audit，并在 execution rules 前由 BYQ 评估。 |
| Broker failure circuit breaker | `DROP` | Phase 35 不存在 external failure stream。 |
| Account JSON import/export | `REPLACE` | 使用 canonical BYQ bundle、manifest/digests、new ID、owner rebinding 和 atomic validation。 |
| ORM/repository、Agent runtime、broker adapter、old APIs | `REFERENCE_ONLY` | 不复制代码或架构。 |

## 必需 acceptance tests

Phase 35 完成前，automated tests 必须证明：

1. 每个 read、mutation、bundle 和 order detail 的 owner isolation；
2. first-order universe binding、frozen membership、empty-account explicit rebind，以及 pool lifecycle 变化后的 historical resolution；
3. stable order/risk reason codes、idempotency conflicts 和精确 fees/tax；
4. older/same-day holdings 共存时的 partial T+1 availability；
5. monotonic atomic settlement、complete marks、immutable snapshots，以及 identical-replay/different-content conflict；
6. persisted append-only funding/fill/settlement/import ledger entries；
7. versioned kill switch/max-notional enforcement 与 audit；
8. order detail 引用真实 request/risk/fill/event data；
9. deterministic export digests、secret/authority exclusion、tamper rejection、new-ID import、reference remap、owner rebinding、no overwrite 和 atomic rollback；
10. legacy logical migration 可重复，并 quarantine ambiguous rows；
11. Product API 和必需有界 MCP contracts 保留 trusted context；
12. 六个 UI views/actions 均消费真实 Gateway/Product API data。

Chrome MCP evidence 必须覆盖 desktop/mobile workspace states、account create/select、accepted/blocked orders 及 detail、mixed T+1 positions、ledger、settlement/snapshot history、kill switch/max-notional 和 bundle export/import。完成证据必须链接逐功能 Community checklist，并记录 browser 只调用 `/api/product/...` 的 network evidence。
