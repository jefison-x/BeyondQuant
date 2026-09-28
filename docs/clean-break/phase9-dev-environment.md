# Phase 9 — isolated developer environment

Status: Phase 9 local PASS; hosted CI and human PR/merge gates remain separate. This document describes the
Phase 9 command contract; the fresh 0.10 schema, Workspace reset, minimal domain
seed and Golden rebuild belong to Phases 13–16.

Run commands from this isolated source worktree:

| Command | Phase 9 behavior |
|---|---|
| `make dev-init` | Create ignored, mode-0600 `.env.dev` from `.env.example` with a worktree-specific Compose project and random local secrets; validate the explicit Compose files. Existing project config is checked, never overwritten. |
| `make dev-start DEV_PROFILE=core` | Start Postgres, Backend, Product MCP, Runtime Adapter and Gateway for this worktree. |
| `make dev-start DEV_PROFILE=research` | Core plus data worker. |
| `make dev-start DEV_PROFILE=backtest` | Core plus signal sandbox and signal worker; existing Backend backtest capability remains in Backend until the business Job phase. |
| `make dev-start DEV_PROFILE=ml` | Core plus current ML worker; GPU qualification belongs to later phases. |
| `make dev-start DEV_PROFILE=full` | Core, research, backtest, ML and frontend. Feedback publishing remains an opt-in production integration. |
| `make dev-stop` | Stop this worktree's containers without deleting volumes or credentials. |
| `make dev-clean` | Read-only preview of exactly this worktree's containers, networks and named volumes. |
| `make dev-clean DEV_CLEAN_APPLY=1` | Remove only verified resources owned by this worktree; preserve `.env.dev`, source, images, caches outside this Compose project and all other Docker projects. |
| `make dev-reset` | Explicit `NOT_RUN` until Phase 13 implements scoped Workspace/Runtime reset. |
| `make dev-seed` | Explicit `NOT_RUN` until Phase 14 provides the fresh schema and minimal domain seed. |
| `make dev-test` | Current offline developer/config checks; full fresh-stack and Golden Scenarios are Phase 15–16 gates. |

Docker Compose 2.24.4 or newer is required for the `!override` port rule in
`compose.dev.yml`; Phase 9 was validated with Compose 2.40.3.

The CLI always names `compose.yml` and `compose.dev.yml` explicitly, so
`compose.override.yml` and historical candidate configurations are not loaded
implicitly. The generated project name is derived from the absolute worktree
path; its PostgreSQL, domain, DSH-session, trace and ML volumes are separate
from any existing stack. Loopback ports are assigned dynamically to avoid a
fixed-port collision between worktrees. `BYQ_DATABASE_URL` and PostgreSQL
credentials come from the generated local file. The file contains secrets and
is ignored by Git; do not copy production `.env` or log its values.

Domain objects and Product DSH data are intentionally disposable in this dev
project. The independent final old-database archive is never mounted, restored
or used by tests. Phase 9 qualification must show config validation, scoped
preview and command behavior. A complete `clean → init → start → seed → test`
from a new schema is a Phase 15–16 milestone, after Phase 14's schema baseline.
