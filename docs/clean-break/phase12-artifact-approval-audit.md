# Phase 12 — Artifact, Approval and Audit

Base: `6c832d7ef8ffe36df0252e279597356a033214a5` (`origin/main` after Phase 11 and CI maintenance).
Status: local Phase 12 gate PASS; repository PR/CI/merge gate remains open.

## Ownership and scope

| Boundary | Existing authority | Phase 12 change |
|---|---|---|
| Persistent result | BYQ `ResearchStore.artifacts`; specialized Job stores hold result Artifact IDs | Expose one bounded Artifact reference with stable ID and workspace; keep producer-specific validated content and Job status in their existing owners. |
| Human decision | BYQ approval rows, typed strategy/ML approval Artifacts and exact ResearchTask action facts | Publish closed `AUTO` / `DECISION` / `ACTION` policy classification. Keep existing stronger grants. Require an exact approved grant for Agent cancellation paths already classified as approval-required. |
| Observation | Module-specific audit rows and logs | Add a structured AuditEvent emitter with a narrow Job completion pilot. The emitter has no business-state authority. |

The existing `operations_audit`, `product_feedback_audit`, paper-account and other named records are **not** deleted by this phase: some participate in idempotency, rate limits or financial facts. Phase 14 owns the new schema baseline and table cleanup after each record's authority is classified.

The existing authenticated Product Artifact full-content route remains for
asset export and research detail flows. Phase 12 binds its GET/list queries to
the exact workspace, including when an Artifact ID is known. The new
`/reference` route is the safe identity projection; it does not imply that the
older full-content contract is content-redacted. Phase 17 should inspect
whether the full-content Product projection can be narrowed without losing
the required export/detail flows.

## Focused acceptance

1. A completed Job's public result reference is the exact validated Artifact ID; the separate Product API Artifact reference excludes stored content and object-store location. Workspace and owner mismatches fail closed. Existing full-content Artifact reads remain available to authorized internal callers.
2. Policy levels are exactly `AUTO`, `DECISION`, `ACTION`. Unknown tools cannot receive an automatic classification. `AUTO` compute still obeys existing exact contextual approval and typed Artifact gates; classification alone never grants execution.
3. Agent backtest-task and ML-training cancellation, and Agent strategy approval, require an approved grant bound to the same actor, owner, workspace, session, action and target resource before changing business state. Missing, rejected, stale or mismatched grants leave it unchanged. A separately authenticated Product user may still cancel their own training or review their own strategy through the existing Gateway route. Existing plan-command and typed Artifact grants retain their authority.
4. A successful Job completion can emit one structured event with exact `job_id` and `artifact_id`; absent transport request identity remains null. A failed/stale attempt emits no success event. Sink failure does not roll back committed business state or expose secrets.
5. Run focused component and contract tests locally, then required exact-head hosted CI. Tester, independent Sol Reviewer and Root must each PASS before Phase 13.

Golden Scenarios A–F, full fresh-schema rebuild and old runtime table deletion remain in their assigned later phases.

## Local gate evidence (2026-09-29)

The Tester ran one scoped disposable PostgreSQL environment. The first focused
Backend batch passed 54 cases; two incorrect test expectations were corrected,
and the affected eight-case rerun passed. Gateway Product API: 4 focused cases
passed. MCP: TypeScript build and five focused suites passed. DSH revision and
retirement: 9 tests passed. Architecture: 73 of 74 passed initially; the
missing OpenAPI entry for the new Artifact reference route was added and that
exact regression passed. `dev-check` and `git diff --check` passed. The current
immutable build manifest `dsh-0.1.5rc1-post-u8.264` checked at
`sha256:c7b234b9e03f11cb7d09e3105a5a515eaef793289c75cf942f415eb6280d3f85`.
The disposable database had no volume; its container and dedicated network,
and the MCP test runner were removed.

Independent Sol Reviewer: Functional **PASS**, Tests **PASS**, Clean Break
Architecture **PASS** after inspecting the final diff and test corrections.
Root accepts **Phase 12 local PASS**. Hosted PR CI and the repository merge
gate are separate and still required before Phase 13. A live MCP contract stack,
full backend suite, fresh full rebuild and Golden Scenarios were not run in this
local slice; the risk-selected hosted CI and later phases own those checks.
