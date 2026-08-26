# Strategy Artifact Contract

Phase 11 将 strategy code/configuration 视为有界 BYQ domain data。它绝非 application source，Product DSH 不能写入或执行。

## StrategyDraft

`POST /v1/research/strategies/validate` 接受 normalized strategy snapshot：

- `strategy_id`、`name`、`category`、description、parameters 和 parameter schema；
- `source_type=python_script`；
- 有界 Python script，只定义一个同步 `CustomStrategy.generate_signals(data, parameters)` 或 `generate_target_weights(data, portfolio_state, parameters)` method。

BYQ 静态拒绝 syntax errors、unsupported/relative imports、unsafe calls/attributes、async output methods、missing method arguments、unsupported categories、credential-bearing keys、historical loop 中的 model fitting、unsupported PortfolioState fields、malformed JSON 和 oversized content。Execution validation 明确留给未来 BYQ-owned worker；本 phase 不在 API process 执行 generated code。

成功 validation evidence 随 lifecycle status 为 `validated` 的 `strategy_draft` Artifact 持久化。Revised draft 是新的 immutable Artifact，不是 in-place source update。

## StrategyVersion

`POST /v1/research/strategies/versions` 将 validated draft 物化为 content-addressed `strategy_version` Artifact。Version ID 是 canonical semantic snapshot/schema identity 的 SHA-256；排除 mutable timestamps、trace IDs、idempotency keys 和 Agent runtime state。Source fingerprint 是 script 的独立 SHA-256。Historical consumers 解析 stored version Artifact，而非 latest draft。

## Export

`GET /v1/research/strategies/versions/{artifact_id}/export` 只返回 deterministic version contract 和 semantic snapshot；不含 credentials、runtime settings、prompts、raw DSH fields 或 application-source paths。

## Approval

`POST /v1/research/strategies/approvals` 创建独立 immutable `strategy_approval` Artifact，链接 validated StrategyVersion，记录 reviewer principal、decision、rationale、trace 和 idempotency evidence。Approved decision 设置 `execution_authorized=true` 与 `execution_outcome=not_started`；approval 授权未来尝试，不表示 execution/business mutation 已成功。

对应 MCP operations 为 `byq_strategy_validate`、`byq_strategy_version_create`、`byq_strategy_approve` 和 `byq_strategy_export`。
