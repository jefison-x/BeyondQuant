# Phase 50 evidence — personal workspace foundation

> 本文记录该 Phase 的验收与审计证据。中文负责说明和结论；文件名、路径、命令、字段、状态码、测试计数及原始观察值保持英文原样。

## 已交付

- PostgreSQL `workspaces` and `workspace_memberships` with one active personal
  owner workspace per durable user.
- Atomic workspace provisioning in `UserAuthStore.create_user` and idempotent
  startup provisioning for existing users.
- Nullable `workspace_id` plus indexes on all 31 ADR-0025 workspace tables;
  user preferences/credentials/policy, platform data/operations, and
  Engineering Plane tables are unchanged.
- `python -m app.migrate_personal_workspaces` dry-run/execute CLI.
- Exact username → durable user → personal workspace mapping only; unmatched
  or conflicting rows are retained and recorded in migration run/quarantine
  tables rather than guessed.
- Root and inherited child backfill, per-table counts, deterministic manifest
  hash, relationship checks, transactional dry-run rollback, and repeat-run
  idempotency.

## Verification

- `bash scripts/ci/local-ci.sh --only=backend`: PASS against a fresh isolated
  PostgreSQL database.
- Backend tests cover atomic one-per-user provisioning, restart/repeat
  idempotency, dry-run rollback, exact-owner mapping, orphan quarantine,
  research parent/transition propagation, and excluded resource scopes.
- Existing owner-based Product authorization remains active by design. This
  additive phase does not claim the Phase 51 trusted-context cutover.

## Rollback

Before Phase 51, rollback is operationally safe: stop invoking the backfill and
run the prior application version. The new tables, nullable columns, indexes,
and populated workspace IDs are additive and ignored by Phase 48 code. Do not
drop them as a routine rollback; retain migration reports and use forward
repair for quarantined rows.

## Next gate

Phase 51 may start only from this merged phase. It must derive workspace
context from authenticated durable sessions, reject public header/body scope,
cut every workspace-owned repository path to `workspace_id`, and enforce final
constraints only after the migration report is verified.
