# BeyondQuant

BeyondQuant (BYQ) is an AI-native quantitative research platform. The current
completed project stage is **Phase 35**; the next phase is
**Phase 36 — Agent workbench depth**, enabled by Accepted ADR-0018. The v1.0
release-candidate gate is not yet satisfied. See
[`docs/roadmap/STATUS.md`](docs/roadmap/STATUS.md) for the
authoritative current state.

## Project identity

- Agent foundation: DeepSeek Harness (DSH)
- Domain: BeyondQuant Quant Platform

DSH is the general-purpose Agent Harness. BYQ is the specialized quantitative domain platform built around its own domain invariants, contracts, and product experience.

BYQ does not fork DSH. The DSH version is pinned through an explicit dependency policy and compatibility contract. BYQ provides its own product UI, and communication between agents and the quantitative domain goes through BeyondQuant MCP.

## Current capabilities

- Browser Product Plane with durable username/password sessions and
  owner-scoped Product API access.
- Gateway → Runtime Adapter → pinned DSH JSON-RPC runtime integration with
  BYQ-owned normalized WorkflowTrace projections.
- BeyondQuant MCP as the only Agent-to-Domain capability boundary.
- PostgreSQL as the single BYQ domain store; logical migration and
  backup/restore tooling are present.
- ResearchTask, Experiment, Artifact, Approval, factor research, strategy
  draft/version, deterministic signal-snapshot backtests, Stock Pool, and
  simulation-only Paper Trading domains.
- Vue product workspaces for research, strategy, backtest, Stock Pool, Paper
  Trading, assets/settings, Data Center, and protected operations surfaces.

## Current limitations

- A BYQ-owned strategy-source → `signal_snapshot` producer is not yet defined;
  the browser cannot complete a newly authored strategy-to-backtest journey.
- Agent, My Space, Operations, Data Center, and shared-component depth remain
  in Phases 36–40.
- ADR-0019 remains Proposed and blocks its dependent phases; ADR-0018 is
  Accepted and Phase 36 is ready for implementation.
- The project is not yet eligible for the BeyondQuant Next v1.0 RC gate.

The base Compose topology requires internal service secrets such as
`BYQ_MCP_TOKEN` and bootstrap compatibility configuration. Provider secrets
remain Backend/Runtime-Adapter owned and must never be exposed to DSH, MCP,
Gateway responses, or frontend code. Keyless CI and smoke tests must not embed
real credentials.

See [ADR-0002](docs/architecture/adr/ADR-0002-initial-runtime-topology.md),
[ADR-0003](docs/architecture/adr/ADR-0003-gateway-dsh-runtime-integration.md),
[the DSH integration options](docs/architecture/dsh-runtime-integration-options.md),
the [implementation plan](docs/roadmap/IMPLEMENTATION_PLAN.md), and the
[development workflow](docs/DEVELOPMENT_WORKFLOW.md).

The architectural rules for this project are normative. Read
[ARCHITECTURE.md](ARCHITECTURE.md) and [AGENTS.md](AGENTS.md) before making
changes.
