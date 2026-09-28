# ADR-006 — Extension and configuration model

- Status: Accepted under ADR-0088 (2026-09-25)
- Acceptance: maintainer's explicit Tool/Job/Artifact/Adapter extension specification, recorded by [ADR-0088](../../architecture/adr/ADR-0088-clean-break-baseline-activation.md).

## Decision

New capability enters as a Tool, Job, Artifact or thin Adapter. A data provider is a Tool, a backtest engine a Job adapter, an ML backend a Worker, a model provider DSH/config, and a new output an Artifact. Plugin handling is limited to registry, version, enable/disable, basic qualification and minimal capability declaration; no marketplace, dependency solver or enterprise lifecycle platform is part of core. Configuration has SystemConfig, WorkspaceConfig and TaskConfig; environment variables construct SystemConfig and are not read throughout business modules.

Before adding an abstraction, document its concrete problem, owner, why existing components cannot solve it and whether DSH already does. A stateless two-component coordinator should normally be a function/helper or thin adapter. Development tooling and MCP stay outside Product dependencies.

## Acceptance

Architecture review finds no new generic WorkflowEngine, SessionManager, recovery service or source-writing Product Agent capability. A DSH or developer-agent upgrade does not require a new BYQ core concept.

## Alternative and consequence

A plugin marketplace, dependency solver or generic workflow platform would expand Core without a proven domain need and is rejected. New capabilities must show owner and bounded contract first.
