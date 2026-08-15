# BeyondQuant Development Workflow

This workflow is mandatory for future Codex phases and Engineering Plane
changes. “Continue development” means: read `docs/roadmap/STATUS.md`, identify
its `Next phase`, and execute that phase's scope in
`docs/roadmap/IMPLEMENTATION_PLAN.md`. It does not mean choosing an unrelated
task from repository history.

## Required sequence

1. Read `AGENTS.md`, `ARCHITECTURE.md`, `docs/roadmap/STATUS.md`,
   `docs/roadmap/IMPLEMENTATION_PLAN.md`, this workflow, and every Accepted
   ADR relevant to the phase.
2. From the repository root, synchronize a clean `main` with
   `origin/main` using fast-forward-only updates. Confirm the expected base
   SHA and record any mismatch.
3. Inspect the phase scope, dependencies, non-goals, architecture constraints,
   acceptance criteria, and stop conditions before editing.
4. Create an isolated worktree under `/home/jefison/projects/.byq-worktrees/`
   and a feature branch. All implementation edits happen there.
5. Implement the smallest contract-first change that satisfies the current
   phase. Do not modify the old Community repository.
6. Run architecture tests.
7. Run unit tests.
8. Run contract tests.
9. Run keyless smoke/integration tests. If a real model key is required,
   record that as a phase boundary and never add a test secret.
10. Run `git diff --check`, inspect the complete diff, and perform a security
    and architecture self-review.
11. Commit intentionally on the feature branch and push only that branch.
12. Open a Draft PR targeting `main`, including scope, evidence, known
    limitations, and any remaining decisions.
13. Let CI run and record the result. Fix failures in the feature branch.
14. Perform a final self-review of files, tests, dependency pins, and boundary
    changes.
15. Stop at the human merge gate. Codex must not merge or push directly to
    `main`.

## Evidence expectations

Architecture changes need an ADR or an update to a relevant Accepted ADR.
Integration boundaries need framework-neutral contracts and translation tests.
Exact external dependencies need metadata/version evidence. Runtime changes
need lifecycle and cleanup evidence. Product/Engineering capability changes
need explicit isolation tests. A green test without architecture evidence is
not sufficient acceptance.

## STOP CONDITIONS

Codex must stop and report evidence, alternatives, and a recommendation when
any of the following occurs:

- an architecture rule conflicts with the requested implementation;
- DSH behavior changes in a breaking or newly undocumented way;
- a security boundary would change;
- a domain invariant is unclear;
- legacy migration classification is unclear;
- a test would require bypassing the architecture;
- the exact dependency baseline is unavailable.

Stopping means no silent workaround, speculative compatibility layer, fork,
protocol patch, or merge. A human must choose the next direction, or an ADR
must be written before implementation resumes.

## Handoff format

Every phase handoff should state the branch, worktree, base and commit SHA,
Draft PR, files changed, architecture decision/status, tests and CI, external
dependency versions, known limitations, blockers, and whether `main` or the
legacy repository was modified. The final line must say whether the next phase
is permitted or the phase is blocked pending review.
