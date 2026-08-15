# BeyondQuant

BeyondQuant (BYQ) is an AI-native quantitative research platform. The current
project stage is **Phase 7 / First Product Agent Turn and WorkflowTrace**.

## Project identity

- Agent foundation: DeepSeek Harness (DSH)
- Domain: BeyondQuant Quant Platform

DSH is the general-purpose Agent Harness. BYQ is the specialized quantitative domain platform built around its own domain invariants, contracts, and product experience.

BYQ does not fork DSH. The DSH version is pinned through an explicit dependency policy and compatibility contract. BYQ provides its own product UI, and communication between agents and the quantitative domain goes through BeyondQuant MCP.

The completed Phase 5 spine provides:

- Gateway health and bootstrap readiness
- a thin DSH runtime pinned to `@deepseek-ai/dsh@0.1.0-rc.6`
- the `dsh-byq` configuration bundle
- a BYQ-controlled `byq-product` preset with no source-editing capabilities
- BeyondQuant MCP Streamable HTTP at `/mcp/v1`
- the authenticated `byq_health` MCP tool
- Backend health endpoints
- an isolated Docker topology for `gateway`, `runtime-adapter`, `mcp`, and
  `backend`; the old DSH Web bootstrap is diagnostic-profile only

Phase 6 adds the formal programmatic runtime seam:

- Gateway internal lifecycle/SSE calls to a dedicated Python Runtime Adapter
- official `deepseek-harness-sdk==0.1.0rc6`
- explicit npm `@deepseek-ai/dsh@0.1.0-rc.6` JSON-RPC runtime composition
- one adapter-owned DSH process per active Product session
- BYQ-owned `WorkflowTraceEvent` normalization
- keyless JSON-RPC initialize, MCP startup, and hard-cleanup smoke coverage

Phase 7 adds the first authenticated Product Agent boundary:

- Gateway-only opaque Bearer authentication for `/v1/agent` and
  `/v1/workflows`
- model/provider secret handling confined to the Runtime Adapter
- interrupted-session resume with a new adapter-owned runtime
- BYQ-owned append-only WorkflowTrace persistence and `Last-Event-ID` replay

The base Compose topology requires `BYQ_MCP_TOKEN` and `BYQ_PRODUCT_TOKEN`.
Set `DEEPSEEK_API_KEY` only when intentionally running a real provider-backed
Product turn; keyless CI and smoke tests must not embed that secret. The
authentication and secret boundary is recorded in
[ADR-0004](docs/architecture/adr/ADR-0004-phase7-product-authentication.md).

The DSH Web surface is available only through the diagnostic `dsh-web` Compose
profile, remains bound to container-local `127.0.0.1`, has no host port, and is
not a BYQ product API. The diagnostic Web surface remains outside the Phase 7
Product Agent API.
The programmatic decision is recorded in
[ADR-0003](docs/architecture/adr/ADR-0003-gateway-dsh-runtime-integration.md).

It does not yet implement strategy, factors, backtests, Tushare, a complete
Xiaoba product, multi-agent workflows, or a WorkflowTrace UI. PostgreSQL,
Redis, frontend, data-worker, backtest-worker, and engineering-dsh remain out
of scope for this phase.

See [ADR-0002](docs/architecture/adr/ADR-0002-initial-runtime-topology.md),
[ADR-0003](docs/architecture/adr/ADR-0003-gateway-dsh-runtime-integration.md),
[the DSH integration options](docs/architecture/dsh-runtime-integration-options.md),
the [implementation plan](docs/roadmap/IMPLEMENTATION_PLAN.md), and the
[development workflow](docs/DEVELOPMENT_WORKFLOW.md).

The architectural rules for this project are normative. Read
[ARCHITECTURE.md](ARCHITECTURE.md) and [AGENTS.md](AGENTS.md) before making
changes.
