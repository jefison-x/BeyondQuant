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
17. Do not migrate legacy code by copy unless `legacy-inventory.md` explicitly marks it for migration.
18. The old repository at `/home/jefison/projects/BeyondQuant-community` is a READ-ONLY reference.
19. Never edit `BeyondQuant-community` as part of new project work.
20. Before implementing a legacy feature, inspect the old implementation, identify its domain invariant, implement it cleanly in the new architecture, and do not blindly copy its architecture.

## Change discipline

- Keep Product Plane and Engineering Plane privileges separate.
- Treat strategy code as an auditable domain artifact.
- Preserve framework-neutral BYQ contracts at integration boundaries.
- Record exceptions and boundary changes in `docs/architecture/adr/`.
- Never use the old Community or Legacy repositories as the Git history for this project.

## Single-maintainer human merge gate

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

## Before starting implementation

Read all of the following before selecting or implementing work:

- `docs/roadmap/STATUS.md`
- `docs/roadmap/IMPLEMENTATION_PLAN.md`
- `docs/DEVELOPMENT_WORKFLOW.md`
- every Accepted ADR relevant to the phase

“Continue development” means read `STATUS.md` and execute its `Next phase`
according to the implementation plan. It does not authorize selecting an
unrelated task or skipping the workflow. Codex must still use an isolated
worktree and must not automatically merge `main`.

`STATUS.md` is the repository phase source of truth, not a Git source of truth:
it must not hard-code a main SHA or transient PR state. Derive the clean base
with `git rev-parse origin/main` after synchronizing `main`. An Accepted ADR
and the current phase acceptance criteria are required before moving to the
next phase.
