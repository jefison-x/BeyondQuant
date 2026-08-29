# Stock Pool Producer Contract — Phase 66

本 contract 落实 ADR-0041；Phase 66 只冻结契约，不声称 runtime 已实现。

## `stock-pool-producer.v1`

### Definition

每个定义必须包含 `definition_id`、`pool_id`、trusted `workspace_id`、`producer_kind`（`index` 或
`dynamic`）、`schema_version`、`version`、normalized `definition`、`schedule`、`status`（`draft`、
`active`、`paused`）、`definition_fingerprint` 和 audit metadata。Pool type 必须与 producer kind 相同；
一个 pool 只有一个当前定义 identity，修改生成单调 version。

Index definition 仅接受 canonical index symbol、closed dataset contract、refresh policy 和 weight mode。
Dynamic definition 仅接受 ADR-0041 allowlist 的 base universe、fields/operators、missing policy、rank、
top-N、weight method 和 cadence。未知字段/操作符、arbitrary expression/code/SQL/URL 必须拒绝。

### Materialization run

Run 必须包含 `run_id`、`definition_id`/version、`pool_id`、`workspace_id`、`requested_as_of`、可选
`effective_trade_date`、`producer_id`/version、`input_manifest`/hash、status/attempt/lease、bounded
counts/error、`snapshot_id` 和 timestamps。Browser projection 不暴露 lease token、raw provider payload、
SQL、credential 或 internal path。

稳定幂等 identity 为 definition/version + requested as-of + trigger identity；同 key不同输入冲突。
成功后 snapshot ID 必填；非成功状态不得声称新 snapshot。`waiting_for_data` 可在 completeness event
后安全重排队；过期 running lease 可恢复，超过 attempt ceiling 转 failed。

### Atomic promotion

Worker 必须先完整 canonicalize、validate、hash 所有成员和 provenance，再在单 transaction 内创建或
复用 immutable snapshot、更新 run、按 effective date/definition version 规则推进 current pointer 并写
audit。任一步失败全部回滚。旧 snapshot 永远不修改或删除。

## Product API boundary

Browser request 只能提交 definition intent、expected version、as-of 和 idempotency key。Browser 不得
提交 workspace/owner、producer identity/version、input manifest/hash、trusted provenance、snapshot
fingerprint、job status 或 provider operation。Gateway/Product API 只返回 normalized catalog、definition、
preview、run/history、readiness、snapshot/diff projection。

Preview 是非权威结果，不得被 Research/Backtest/Paper 引用。Agent-to-Domain 仍经 BYQ MCP；Phase 66
不增加 Agent write capability。

## Acceptance contract for implementation phases

- owner/workspace isolation，ordinary Browser 无 trusted writer path；
- definition validation/version conflict/idempotency/audit；
- exact index weight normalization、completeness/quarantine、no-look-ahead/out-of-order protection；
- dynamic deterministic ordering/missing policy/announcement visibility/calendar cadence/max members；
- lease/retry/restart、no partial promotion、same-input reuse、previous snapshot retention；
- frozen Research/Backtest/Paper references and replay stability；
- Product API/OpenAPI/typed client parity、secret/internal-schema negative tests；
- real PostgreSQL two-user journey、desktop/mobile Chrome review、same-origin Network evidence。
