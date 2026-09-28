# Phase 9 developer environment qualification — 2026-09-28

Original implementation base: `495d1e7b` (Phase 8 local PASS). PR base after Phase 8 merge: `e2edc9f2`. Branch/worktree: `clean-break/dev-environment` under `/home/jefison/projects/.byq-worktrees/clean-break-dev-environment`.

## Implemented

- Worktree-scoped `.env.dev` from `.env.example`, mode `0600`, with generated local credentials, matching internal PostgreSQL URL and dynamic loopback ports. The CLI rejects a foreign worktree scope, external/shared Docker resource overrides, public/fixed binds, and an external database URL. No secret values are logged or committed.
- Explicit `compose.yml` + `compose.dev.yml` selection excludes the historical implicit `compose.override.yml`. `core`, `research`, `backtest`, `ml`, and `full` select explicit services. `dev-stop` preserves volumes; `dev-clean` defaults to a read-only exact-resource preview, with a separate explicit apply mode. It checks Compose ownership before removal and never prunes images or unrelated resources.
- `dev-reset` and `dev-seed` are present as explicit `NOT_RUN` commands until the Phase 13 Workspace reset and Phase 14 fresh schema/minimal seed contracts are available. `dev-test` currently runs offline lifecycle and governance checks; Golden Scenario F remains a Phase 15–16 gate.

## Executed evidence

| Check | Result |
|---|---|
| Isolated worktree verification | PASS |
| Compose config with generated `.env.dev` and two explicit files | PASS |
| Effective Compose Runtime Adapter Dockerfile after Phase 8 merge | PASS; `make dev-init` validates the selected `.251` build, rejecting a stale Dockerfile |
| `make dev-init` fresh and repeated | PASS; local config created/verified, mode `0600` |
| `make dev-test` | PASS; Clean Break governance 2/2 and lifecycle safety 6/6 |
| `make dev-clean` before startup | PASS; empty exact preview |
| Start isolated PostgreSQL alone | PASS; healthy, exact project resources created |
| `make dev-clean` preview/apply after PostgreSQL | PASS; one container, one volume, one network removed; postcheck empty |
| `make dev-start DEV_PROFILE=core` from source/templates | PASS; Postgres, Backend, Product MCP, Runtime Adapter and Gateway healthy |
| Gateway loopback `/readyz` | PASS; HTTP 200 on a dynamic port |
| `make dev-stop` | PASS; five containers stopped, volumes retained |
| `make dev-clean` preview/apply after core run | PASS; exactly five project containers, four volumes and one network removed; postcheck empty |
| `dev-reset`, `dev-seed`, new 0.10 schema rebuild, Golden Scenarios | NOT_RUN; assigned to Phases 13–16 |
| Product deployment, existing BYQ stack, backup restoration, push/merge | NOT_RUN; outside this phase |

No legacy data was restored or migrated. A generated local `.env.dev` remains ignored in this worktree for subsequent development; the isolated Compose project has no containers, volumes or networks after qualification.

Independent Tester: lifecycle 6/6, governance 2/2, Compose configuration and diff PASS; its Docker socket was unavailable. Root performed the recorded live Docker checks, including a second PostgreSQL cleanup after final scope checks. Independent Sol Reviewer: Functional PASS / Tests PASS / Clean Break Architecture PASS on the actual diff and phase boundary. Root accepts Phase 9 local PASS. Hosted CI and human PR/merge gates remain separate.
