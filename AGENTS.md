# AI Coding Agent Rules

These rules apply to Codex, DSH engineering agents, and any other AI coding agent working in this repository.

1. Read `ARCHITECTURE.md` before making architectural changes.
2. Do not reintroduce PydanticAI as the main runtime.
3. Do not reintroduce Hermes as the main runtime.
4. Do not build a second generic agent harness.
5. Do not fork DeepSeek Harness.
6. Do not bypass BeyondQuant MCP for Agent-to-Domain calls.
7. Do not let DSH directly access PostgreSQL business data.
8. Do not couple the frontend to DSH internal event schemas.
9. Do not expose application-source write access to Product DSH.
10. Strategy code is domain data/artifact, not application source.
11. Engineering changes must occur in isolated worktrees.
12. Do not push directly to `main`.
13. Domain invariants belong to BYQ, not DSH.
14. Generic agent capabilities belong to DSH whenever possible.
15. Any exception to architectural rules requires an ADR.
16. Prefer tests and contracts before broad refactors.
17. Do not migrate legacy code by copy unless `docs/migration/COMMUNITY_MIGRATION_INVENTORY.md` explicitly classifies it for migration.
18. The old repository at `/home/jefison/projects/BeyondQuant-community` is a READ-ONLY reference.
19. Never edit `BeyondQuant-community` as part of new project work.
20. Before implementing a legacy feature, inspect the old implementation, identify its domain invariant, implement it cleanly in the new architecture, and do not blindly copy its architecture.

21. Before implementing any Phase 9+ domain capability, Codex MUST inspect the
    corresponding BeyondQuant-Community implementation first.
22. The mandatory migration sequence is: inspect → classify → extract
    invariants/tests → decide reuse/port/refactor/drop → implement. Existing
    Community code is evidence, not an authorization to copy it.
23. BaoStock MUST NOT be reintroduced.
24. AKShare MUST NOT be reintroduced.
25. VectorBT MUST NOT be reintroduced.
26. Community implementations using those technologies are reference-only for
    provider-independent or engine-independent semantics. Do not add a
    compatibility layer for them unless a future Accepted ADR explicitly
    reverses this decision.

27. Productization Phase 17+ frontend work MUST inspect and classify the
    corresponding BeyondQuant-Community frontend page/component before
    implementation. Reuse visual language and UX only after deciding whether
    each asset is `REUSE_AS_IS`, `PORT_COMPONENT`, `PORT_STYLE`, `PORT_LAYOUT`,
    `PORT_UX`, `REFACTOR`, `REFERENCE_ONLY`, `REPLACE`, or `DROP`.
28. Productization frontend code MUST use BYQ Product API and normalized
    WorkflowTrace projections. It MUST NOT call raw Backend-internal APIs,
    MCP, DSH, or raw DSH event schemas.
29. Market-data migration MUST inspect the Community cache and schema first.
    The Community repository and PostgreSQL database are read-only sources;
    they MUST NOT be updated, deleted, altered, truncated, mounted, or used
    as BYQ authoritative storage.
30. Community PostgreSQL market-cache migration MUST be logical and
    repeatable: read-only export → validation/normalization → manifest →
    BYQ Data Plane import → post-import verification. Physical PostgreSQL
    data-directory copying or mounting is prohibited.
31. Do not redownload historical Tushare data when a validated Community
    cached copy is available. Prefer validate → migrate → incremental refresh,
    while treating data correctness, provenance, units, coverage, and
    reproducibility as higher priority than download avoidance.
32. If Community data cannot prove its provider/source, units, schema,
    canonical symbol/date semantics, lifecycle coverage, or integrity, do not
    migrate it; quarantine and report it instead.
33. BaoStock, AKShare, and VectorBT rows, adapters, fallbacks, dependencies,
    and compatibility paths remain DROP. Only validated Tushare or proven
    provider-independent canonical data may be considered for migration.
34. Phases 24-30 are Product Completion phases. Implement exactly one phase
    per isolated worktree/branch/Draft PR and stop at the human merge gate.
    Do not start the next phase until the current phase is merged.
35. Product Completion is not satisfied by Vue file, page, endpoint, or
    placeholder existence. Required features must work through Product API,
    real browser flows, persistence where required, and feature checklist
    evidence.
36. Product phases affecting UI require a Chrome MCP browser review and a
    Community feature checklist before the phase may be marked complete.
37. Community frontend remains READ ONLY and is the Product reference
    baseline. Inspect feature-by-feature before port/redesign/rewrite; do not
    copy the Community repository.
38. Browser requests must use Gateway/Product API only. The frontend MUST NOT
    call Backend, MCP, DSH, PostgreSQL, Redis, or Tushare directly.
39. Product Token is bootstrap/internal/service compatibility only. Normal
    browser login for Phase 24+ must use durable BYQ user identity.
40. No fake completion: placeholder, mock page, static fake dataset, fake
    login, local-only profile persistence, hardcoded user, empty tabs, or
    disabled UI without a documented backend blocker are not phase
    completion.

## Change discipline

- Keep Product Plane and Engineering Plane privileges separate.
- Treat strategy code as an auditable domain artifact.
- Preserve framework-neutral BYQ contracts at integration boundaries.
- Record exceptions and boundary changes in `docs/architecture/adr/`.
- Never use the old Community or Legacy repositories as the Git history for this project.
- Productization is not complete at Phase 15. Phase 16–23 are future roadmap
  constraints until the current STATUS phase permits implementation.

## Single-maintainer human merge gate

The default gate below is subject only to the explicit pre-release exception and
ADR-0059 authorization/preflight rules. Historical Phase text does not independently
grant or revoke merge/deployment authority. Default behavior remains Draft PR.

For a repository with a single human maintainer:

- CI and all required status checks must pass.
- Codex must stop at a Draft PR and must not push directly to `main`.
- The human repository owner must manually review the PR and should leave a
  GitHub review or comment as an audit record.
- A GitHub `APPROVED` state is not required when the PR author and sole
  repository maintainer are the same person and GitHub therefore disallows
  self-approval.
- Codex must not merge or mark the PR ready for review.
- Only the human maintainer may mark the PR ready and merge it.
- If repository rules later require independent approvals, those approvals
  must be satisfied.

Exception (pre-release only): until the official BeyondQuant Next v1.0 release,
[ADR-0015](docs/architecture/adr/ADR-0015-phase-release-automerge.md)
allows Codex to mark PRs ready and enable CI-green auto-merge. This exception
expires at the v1.0 release boundary, after which the single-maintainer gate
above is restored and auto-merge must be disabled.

## Before starting implementation

Read all of the following before selecting or implementing work:

- `docs/roadmap/STATUS.md`
- `docs/roadmap/IMPLEMENTATION_PLAN.md`
- `docs/DEVELOPMENT_WORKFLOW.md`
- every Accepted ADR relevant to the phase

“Continue development” means read `STATUS.md` and execute its `Next phase`
according to the implementation plan. It does not authorize selecting an
unrelated task or skipping the workflow. Codex must still use an isolated
worktree and must not automatically merge `main` outside the explicit ADR-0015/0059 gate.

Explicitly requested maintenance, bugfix, dependency qualification, documentation and
operations tasks use the task routing in `docs/DEVELOPMENT_WORKFLOW.md`; they do not
advance the Product Phase. Development, push/PR, merge and deployment authorization
are separate; a maintainer may explicitly grant them together. Never infer production
deployment from development authorization or give Product DSH Engineering privileges.

`STATUS.md` is the repository phase source of truth, not a Git source of truth:
it must not hard-code a main SHA or transient PR state. Derive the clean base
with `git rev-parse origin/main` after synchronizing `main`. An Accepted ADR
and the current phase acceptance criteria are required before moving to the
next phase.
