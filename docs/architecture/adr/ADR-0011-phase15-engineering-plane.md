# ADR-0011: Phase 15 Engineering Plane Task Boundary

- Status: Accepted
- Date: 2026-08-16
- Decision scope: Phase 15 Engineering Plane task and evidence contract

## Context

The Product Plane must never gain source-editing, Git, or merge authority.
Phase 15 needs a controlled EngineeringTask record that lets an Engineering
DSH/Codex subagent work in an isolated worktree and produce a tested Draft PR
without weakening that boundary. The Community repository has no equivalent
EngineeringTask implementation, so this is a new BYQ-owned contract rather
than a migration.

## Decision

1. BYQ owns an `EngineeringTask` state machine in the Backend:
   `proposed -> approved -> in_progress -> review_required ->
   completed|rejected|cancelled`. Terminal states are immutable.
2. A task records its owner, initiating actor, trace, description, scope,
   worktree path, branch name, draft PR number, CI status, self-review
   boolean, bounded architecture evidence, and human merge status.
3. `in_progress` requires an approved task. `review_required` requires an
   isolated worktree path and a non-main branch. `completed` requires a draft
   PR number, `ci_status == success`, `self_review == true`, non-empty
   architecture evidence, and `merge_status == not_merged`.
4. The Backend never pushes, merges, or marks a PR ready. A separate
   `record_human_merge` operation only records an explicit human decision
   (`merged` or `rejected`) after the task is completed; it does not perform
   the Git/GitHub mutation.
5. EngineeringTask endpoints are Engineering Plane only. They are not exposed
   through the Product BeyondQuant MCP surface and are not present in any
   Product quant role allowlist.

## Consequences

- Engineering work has an auditable, bounded, evidence-gated contract.
- Product DSH still cannot reach EngineeringTask endpoints or mutate source.
- CI can test state transitions, evidence gates, human merge recording, and
  Product/MCP separation without GitHub or Git credentials.
