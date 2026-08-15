# BeyondQuant

BeyondQuant (BYQ) is an AI-native quantitative research platform. The current
project stage is **Bootstrap / Architecture Spine**.

## Project identity

- Agent foundation: DeepSeek Harness (DSH)
- Domain: BeyondQuant Quant Platform

DSH is the general-purpose Agent Harness. BYQ is the specialized quantitative domain platform built around its own domain invariants, contracts, and product experience.

BYQ does not fork DSH. The DSH version is pinned through an explicit dependency policy and compatibility contract. BYQ provides its own product UI, and communication between agents and the quantitative domain goes through BeyondQuant MCP.

The Phase 5 spine currently implements only:

- Gateway health and bootstrap readiness only
- a thin DSH runtime pinned to `@deepseek-ai/dsh@0.1.0-rc.6`
- the `dsh-byq` configuration bundle
- a BYQ-controlled `byq-product` preset with no source-editing capabilities
- BeyondQuant MCP Streamable HTTP at `/mcp/v1`
- the authenticated `byq_health` MCP tool
- Backend health endpoints
- an isolated Docker topology for `gateway`, `dsh`, `mcp`, and `backend`

The DSH Web surface is bound only to container-local `127.0.0.1` for runtime
bootstrap and verification. It has no host port and is not a BYQ product API.
Gateway-to-DSH runtime integration is **planned for Phase 6** and remains
`NO DECISION YET`; Phase 5 does not provide a chat or session API.

It does not yet implement strategy, factors, backtests, Tushare, a complete
Xiaoba product, multi-agent workflows, or a WorkflowTrace UI. PostgreSQL,
Redis, frontend, data-worker, backtest-worker, and engineering-dsh remain out
of scope for this phase.

See [ADR-0002](docs/architecture/adr/ADR-0002-initial-runtime-topology.md) and
[the DSH integration options](docs/architecture/dsh-runtime-integration-options.md).

The architectural rules for this project are normative. Read
[ARCHITECTURE.md](ARCHITECTURE.md) and [AGENTS.md](AGENTS.md) before making
changes.
