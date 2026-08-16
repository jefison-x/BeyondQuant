# ADR-0015: Pre-Release CI Auto-Merge Exception to the Single-Maintainer Gate

- Status: Accepted
- Date: 2026-08-17
- Decision scope: Engineering Plane pull-request merge gate during BeyondQuant
  Next pre-release product-depth work

## Context

The repository operates under a single-maintainer human merge gate: Codex must
stop at a Draft PR, must not mark it ready, and must not merge. The human
maintainer merges after CI passes. Product-depth phases (Backtest, Strategy,
Stock Pool, Paper Trading, Agent, My Space, Operations) each produce one PR,
so the manual merge step repeats many times before the v1.0 release.

The maintainer has explicitly asked to relax this gate until the official
BeyondQuant Next v1.0 release, with CI-green auto-merge, and to be reminded to
disable auto-merge again after release.

## Decision

1. Until the BeyondQuant Next v1.0 release is officially tagged/delivered,
   Codex Engineering Plane MAY create non-draft pull requests, mark them ready,
   and enable GitHub auto-merge with `squash` when all required CI checks pass.
2. Auto-merge applies only when the PR is mergeable and all required checks are
   green. Codex must still inspect and fix CI failures, never push directly to
   `main`, and never force-push.
3. This exception expires automatically at the v1.0 release boundary. After
   release, the single-maintainer human merge gate in `AGENTS.md` and
   `docs/DEVELOPMENT_WORKFLOW.md` is restored without further code changes.
4. The maintainer must disable GitHub auto-merge at release and confirm to
   Codex that the gate is closed. `docs/roadmap/STATUS.md` tracks this reminder
   as a release-blocking checklist item.

## Consequences

- PRs merged during pre-release go through CI and the same diff/architecture
  review evidence, but the human-per-PR merge click is removed.
- The release boundary is the hard stop: auto-merge must not continue past
  the official v1.0 release.
- Direct `main` writes, production deploys, and merging PRs with failing checks
  remain prohibited.

## Rejected alternatives

- Keeping the per-PR human merge gate: slows the product-depth sequence the
  maintainer wants to accelerate.
- Permanent auto-merge: conflicts with the single-maintainer audit model and is
  explicitly out of scope; this exception is pre-release only.
