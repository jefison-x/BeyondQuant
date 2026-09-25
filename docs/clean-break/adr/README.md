# Proposed BYQ 0.10 ADR baseline

All ADRs in this directory are **Proposed**, pending maintainer acceptance and integration into the canonical ADR index. They define the replacement baseline as a set and do not yet supersede Accepted ADR-0001–0087 or authorize Phase 7 deletion. On acceptance, archive old ADRs under `docs/archive/adr-pre-clean-break/` with an explicit historical-only notice, update `ARCHITECTURE.md`, `AGENTS.md`, `STATUS.md`, and cross-references, and make this directory the sole current product architecture baseline. Preserve historical evidence without treating it as new architecture authority.

| Decision | Scope |
|---|---|
| [ADR-001](ADR-001-core-ownership.md) | Core entities and single owner |
| [ADR-002](ADR-002-dsh-boundary.md) | Sole harness and thin adapter |
| [ADR-003](ADR-003-business-jobs.md) | Long compute and worker ownership |
| [ADR-004](ADR-004-workspace-data-lifecycle.md) | Fresh DB, reset and archive |
| [ADR-005](ADR-005-artifact-approval-audit.md) | Persistent result, policy and audit |
| [ADR-006](ADR-006-extension-model.md) | Tool/Job/Artifact/Adapter extension |

Acceptance must name the supersession of current runtime-continuity, continuation, workflow, approval and migration ADR requirements explicitly. It must also preserve independent product safety invariants: MCP mediation, workspace/RBAC, exact authorization, business idempotency, financial unknown-outcome handling, browser Product API boundary, read-only Community sources and forbidden BaoStock/AKShare/VectorBT paths.
