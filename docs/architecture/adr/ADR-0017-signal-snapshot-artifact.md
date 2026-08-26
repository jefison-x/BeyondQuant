# ADR-0017：用于 Backtest Input 的 Strategy Signal Snapshot Artifact

- Status: Accepted
- Date: 2026-08-18
- Accepted: 2026-08-18
- Decision scope: Phase 32 Backtest create-wizard input boundary
- Related: ADR-0003、ADR-0007、ADR-0008、ADR-0016

## 背景

Phase 32 Community-parity Backtest workspace 需要 browser “create backtest” wizard。
现有 Backend submit boundary（`POST /v1/research/backtests`）已经要求 validated
`strategy_version_artifact_id`、validated `approval_artifact_id` 和 frozen input snapshot
（`universe`、`bars`、`signals`、`execution`、`corporate_actions`）。ADR-0008 有意接收
frozen signal snapshot，并且在该 Phase 不执行 Strategy Python source。

因此 wizard 不能直接从 StrategyVersion 产生 Backtest；必须有组件提供 frozen signal
snapshot，而当时架构中不存在这种 producer。本 ADR 决定 wizard 如何引用 signal input，
同时不引入不安全的 Strategy source execution。

## 决策

1. Backtest submission 引用 immutable `signal_snapshot` Artifact。Signal snapshot 是 BYQ
   domain Artifact，不是 application source；它由 BYQ-owned computation boundary 生成，
   而不是 Product DSH。
2. 在现有 Artifact store（依据 ADR-0016 使用 PostgreSQL）中增加
   `signal_snapshot` artifact kind。其 content 是 secret-free、normalized JSON document：
   - `strategy_version_artifact_id`
   - `strategy_version_id`
   - `universe`（frozen symbol）
   - `bars`（每个 `(symbol, trade_date)` 一条 canonical OHLC bar）
   - `signals`（稳定 buy/sell/hold row，含 `symbol`、`trade_date`、`side`、`quantity`）
   - `execution`（next-session-open、T+1、lot size、cost、tax）
   - `corporate_actions`（可选）
   - `source`（provenance：producer、content hash）
3. Phase 32 不实现 signal producer（执行 Strategy code 并派生 signal 的组件）。Producer
   留待后续专用 ADR。在此之前，signal snapshot 只能由以下路径创建：
   - 仅用于 test/demo 的明确 keyless fixture/import path；
   - 在 producer ADR Accepted 后，由未来 BYQ computation worker 创建。
4. Backtest create wizard 选择 validated StrategyVersion、匹配的 `signal_snapshot` 和
   execution parameter，然后通过 Product API submit。它绝不在 browser 或 DSH 中生成
   signal。
5. MCP 增加 read-only `byq_signal_snapshot_get` tool；本 Phase 中 DSH 可以 inspect，但
   不能 create/mutate signal snapshot。
6. Ownership、Approval 和 idempotency semantics 遵循 ADR-0007/ADR-0008。
   `signal_snapshot` 必须引用 validated StrategyVersion，并由同一 principal 持有。

## 后果

- 无需执行 untrusted Strategy source 即可解除 Phase 32 create wizard blocker。
- Snapshot content-addressed 且 immutable，提高 Backtest reproducibility。
- 用户要从新 Strategy 一步进入 Backtest，仍需独立 signal-producer ADR。在此之前，
  wizard 依赖 pre-computed fixture/import snapshot。
- DSH 保持在 computation boundary 外；不扩大 provider credential 或 storage access。

## 拒绝的替代方案

- 在 Backend request 或 Product DSH 中执行 Strategy Python：违反 ADR-0008 和 Product
  source-protection boundary。
- Wizard 上传 raw CSV signal：validation、provenance 和 reproducibility 不足。
- 立即增加 signal worker：时机过早，其 sandbox 和 determinism 需要专用 ADR。

## 回滚

移除 `signal_snapshot` kind 和 MCP read tool；Backtest submission 恢复为要求 caller
inline 传入 frozen input。不需要 Data Plane migration。

## Acceptance review（2026-08-18）

仓库维护者检查本文件的 review material，并与当前 codebase（submit boundary、Artifact
store、MCP tool、Community wizard）对照后接受本 ADR。Review 确认 Context 准确，且
决策与 ADR-0007/ADR-0008/ADR-0016 一致。Acceptance 以以下实现澄清为条件，并约束
所有使用本 ADR 的 Phase 32 wizard 工作：

1. **Phase 32 acceptance boundary**：wizard 必须能以 validated StrategyVersion、匹配
   `signal_snapshot` 和 execution parameter 通过 Product API submit Backtest。它不承诺
   end-to-end Strategy-to-Backtest journey；从 Strategy source 生成 signal 仍延后到
   signal-producer ADR（D-0002）。只要 Phase 明确记录该边界，缺少 producer 不构成
   fake completion。
2. **Matching rule**：只有 `signal_snapshot.strategy_version_artifact_id` 等于所选
   StrategyVersion Artifact id、`owner_principal` 等于 submitting principal，且属于同一
   task（或记录明确 lineage link）时才算 matching。
3. **Approval**：Backtest submission 继续通过现有 `strategy_approval` Artifact 授权；
   `signal_snapshot` 不增加独立 Approval step。
4. **Content schema 与 size**：snapshot content 复用 `normalize_backtest_request` 的现有
   normalization rule（每个 `(symbol, trade_date)` 一条 canonical OHLC bar、finite-value/
   OHLC validation、stable signal ordering），并设置 content size cap，使单条 Artifact
   row 保持有界。

这些澄清必须反映在 Phase 32 wizard implementation 和 contract test 中。
