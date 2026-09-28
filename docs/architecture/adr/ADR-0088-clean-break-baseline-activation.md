# ADR-0088 — BYQ 0.10 Clean Break baseline activation

- Status: Accepted
- Date: 2026-09-25
- Decision owner: BeyondQuant maintainer
- Acceptance evidence: maintainer's explicit Clean Break instruction in the 2026-09-25 development session, followed by the direction to proceed with the work instead of waiting; exact intended ownership, data policy, phase gates and first-round deliverables were specified in that instruction.
- Scope: development-period BYQ 0.10 architecture and its Engineering Plane. No production deployment, old database deletion, automatic merge or Product DSH privilege expansion.
- Supersedes: pre-Clean-Break product architecture decisions in ADR-0001 through ADR-0087 as **current product architecture authority**, including runtime continuity, P4 continuation, compatibility and old schema/migration requirements. Historical product facts and evidence remain records. Non-product governance/security decisions ADR-0015, ADR-0059, ADR-0068, ADR-0070 and ADR-0080 retain their exact existing scope unless a newer explicit rule supersedes them; they do not define BYQ 0.10 Product Core. `AGENTS.md`, `docs/DEVELOPMENT_WORKFLOW.md`, `docs/operations/ci-policy.md`, `ARCHITECTURE.md` and the repository license also remain current policy sources.

## Context

BYQ 0.9 accumulated BYQ-owned Agent session, generation, child lease, recovery, trace and continuation mechanisms alongside DSH's harness. Its 87 earlier ADRs describe successive development phases and leave conflicting runtime ownership instructions. The maintainer has authorized a development-period Clean Break with zero compatibility requirement for old runtime state. The Phase 0–6 inventory, archive plan, ownership audit, deletion plan and independent review are recorded in [`docs/clean-break/`](../../clean-break/README.md).

## Decision

Activate the six Clean Break ADRs as one 0.10 product architecture baseline. DSH alone owns generic Agent runtime; BYQ owns quant business identities, Workspace, ResearchTask, Job, Artifact, Approval and authoritative domain facts; specialized workers execute long deterministic computation. The adapter translates only. Old runtime schema/session/run/child/checkpoint/trace data are disposable and not migration inputs. Old product ADRs remain at their original paths as historical-only architecture records until references and tests can be retired safely; their former `Accepted` labels describe historical product decisions, not current Product Core authority. Five governance/security ADRs remain operative only for their non-product scope as listed below.

Phase 7 removal is permitted only in bounded slices with a version-qualified DSH API or existing BYQ Job/Worker replacement for every live public path, passing contract tests and Tester → independent Sol Reviewer → Root PASS. Phase 8 data/environment deletion additionally requires a verified final old-DB archive and exact resource classification. This decision does not itself claim those gates passed.

### Retained rules and their current owners

| Rule retained | Current authority |
|---|---|
| Human PR review/merge, exact GitHub preflight, CI run identity and fail-closed checks, no direct `main` push, independent deployment authorization | ADR-0059, ADR-0070, `AGENTS.md`, `docs/DEVELOPMENT_WORKFLOW.md`, `docs/operations/ci-policy.md` |
| Product/Engineering privilege isolation, source protection, BYQ MCP, browser Product API | `AGENTS.md` and current `ARCHITECTURE.md` |
| Community original-implementation inspection exemption, read-only repository/database handling and forbidden BaoStock/AKShare/VectorBT | ADR-0068, `AGENTS.md` and current `docs/DEVELOPMENT_WORKFLOW.md` |
| Workspace/RBAC, exact approval, business idempotency, unknown financial outcome and authoritative financial facts | Clean Break ADR-001, ADR-003 and ADR-005; current `ARCHITECTURE.md` |
| Credential secrecy/encryption and protected release-time injection; no plaintext secret in Git/logs/release artifacts/backups | ADR-0080, current `ARCHITECTURE.md`, `AGENTS.md` |
| No live trading | Repository license and current `ARCHITECTURE.md` |

ADR-0015's pre-release auto-merge exception remains a general governance record, but this Clean Break program uses the stricter **Draft PR and human merge gate**. It does not invoke that exception. Merge and deployment still require their own authorization.

## Consequences and alternatives

Keeping old ADRs normative would make mutually incompatible 0.9 and 0.10 runtime rules current simultaneously. Moving all historical files immediately would break dozens of documentation links and path-based tests without improving runtime ownership; a documented historical-only archive at existing paths preserves evidence while allowing the new baseline to be authoritative. A future mechanical move to `docs/archive/adr-pre-clean-break/` may occur after links/tests are updated, without reviving their authority. No compatibility bridge is introduced.

Rollback of an unmerged Clean Break branch is branch abandonment. Once a new 0.10 database is created, old data stays in its read-only archive and is not automatically restored into the new schema.
