# BYQ 0.10 Clean Break ADR baseline

All six ADRs here are **Accepted under [ADR-0088](../../architecture/adr/ADR-0088-clean-break-baseline-activation.md)** as the sole current BYQ 0.10 product architecture baseline. Pre-Clean-Break product ADRs are historical-only architecture records at their original paths so evidence links and path-based tests remain readable. ADR-0015/0059/0068/0070/0080 continue only in their non-product governance/security scope; they do not compete with the Product Core baseline. `ARCHITECTURE.md` states the current boundary. This acceptance authorizes bounded Phase 7 implementation after its own tests and review; it does not authorize database or Docker deletion, production deployment, direct `main` push or merge.

| Decision | Scope |
|---|---|
| [ADR-001](ADR-001-core-ownership.md) | Core entities and single owner |
| [ADR-002](ADR-002-dsh-boundary.md) | Sole harness and thin adapter |
| [ADR-003](ADR-003-business-jobs.md) | Long compute and worker ownership |
| [ADR-004](ADR-004-workspace-data-lifecycle.md) | Fresh DB, reset and archive |
| [ADR-005](ADR-005-artifact-approval-audit.md) | Persistent result, policy and audit |
| [ADR-006](ADR-006-extension-model.md) | Tool/Job/Artifact/Adapter extension |

The supersession covers old runtime-continuity, continuation, workflow, approval and migration architecture requirements. Independent product safety invariants remain: MCP mediation, workspace/RBAC, exact authorization, business idempotency, financial unknown-outcome handling, browser Product API boundary, read-only Community sources and forbidden BaoStock/AKShare/VectorBT paths.
