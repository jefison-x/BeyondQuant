# Strategy Artifact Contract

Phase 11 treats strategy code and configuration as bounded BYQ domain data.
It is never application source, and Product DSH cannot write or execute it.

## StrategyDraft

`POST /v1/research/strategies/validate` accepts a normalized strategy snapshot:

- `strategy_id`, `name`, `category`, description, parameters, and parameter
  schema;
- `source_type=python_script`; and
- a bounded Python script defining exactly one synchronous
  `CustomStrategy.generate_signals(data, parameters)` or
  `generate_target_weights(data, portfolio_state, parameters)` method.

BYQ statically rejects syntax errors, unsupported imports, relative imports,
unsafe calls/attributes, async output methods, missing method arguments,
unsupported categories, credential-bearing keys, model fitting inside a
historical loop, unsupported PortfolioState fields, malformed JSON, and
oversized content. Execution validation is explicitly deferred to a future
BYQ-owned worker; this phase does not execute generated code in the API
process.

The successful validation evidence is persisted with a `strategy_draft`
Artifact whose lifecycle status is `validated`. A revised draft is a new
immutable Artifact and is not an in-place source update.

## StrategyVersion

`POST /v1/research/strategies/versions` materializes a validated draft as a
content-addressed `strategy_version` Artifact. Its version ID is the SHA-256
of a canonical semantic snapshot and schema identity; mutable timestamps,
trace IDs, idempotency keys, and Agent runtime state are excluded. The source
fingerprint is a separate SHA-256 of the script. Historical consumers resolve
the stored version Artifact rather than the latest draft.

## Export

`GET /v1/research/strategies/versions/{artifact_id}/export` returns only the
deterministic version contract and semantic snapshot. It contains no
credentials, runtime settings, prompts, raw DSH fields, or application-source
paths.

## Approval

`POST /v1/research/strategies/approvals` creates a separate immutable
`strategy_approval` Artifact linked to a validated StrategyVersion. It records
the reviewer principal, decision, rationale, trace, and idempotency evidence.
An approved decision sets `execution_authorized=true` and
`execution_outcome=not_started`; approval authorizes a future attempt and does
not claim that execution or a business mutation succeeded.

The corresponding MCP operations are `byq_strategy_validate`,
`byq_strategy_version_create`, `byq_strategy_approve`, and
`byq_strategy_export`.
