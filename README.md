# BeyondQuant

BeyondQuant (BYQ) is an AI-native quantitative research platform. The current
completed project stage is **Phase 57** — frozen benchmark performance,
point-in-time index membership and declared valuation/fundamental research data
under Accepted ADR-0030.
See
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
- Owner-scoped encrypted model credentials, profiles and Product Agent
  binding; canonical workspace asset transfer; and effective personal Agent
  Policy presets/rules under platform approval precedence.
- Nine responsive administrator operations workbenches backed by bounded
  Product API projections, normalized DSH runtime/usage accounting, and
  audited monitoring thresholds.
- Tushare-only Data Center with encrypted write-only credentials, immutable
  `L/P/D` stock-master snapshots, catalogue/Stock Pool-driven durable daily
  sync jobs, true incremental refresh, honest PostgreSQL coverage audit, and
  a trusted calendar-driven full-market daily synchronization worker.
- Isolated, credential-free Pandas signal execution that freezes canonical
  bars and produces immutable normalized `signal_snapshot` artifacts for
  approved strategy versions and backtests.
- Content-addressed forward-adjusted research inputs with raw execution bars,
  durable adjustment factors, and implemented dividend/share actions settled
  on their declared dates.
- Closed benchmark, historical index-membership, daily valuation and financial
  indicator inputs with point-in-time/no-look-ahead readiness and pre-run repair.

## Current limitations

- The DSH Upgrade Lane is scheduled as a post-Phase 40 maintenance initiative;
  it does not change the currently qualified runtime pin.
- The conversation-first frontend, personal-workspace and Beta Data Center
  programs are complete through Phase 57. The project remains Beta: CI-green
  phase PR auto-merge is authorized by ADR-0015, but no
  release-candidate review, tag, deployment or formal release is authorized
  until the maintainer gives an explicit formal release task. Team workspaces,
  invitations, sharing and commercial control-plane capabilities remain out
  of scope.

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
