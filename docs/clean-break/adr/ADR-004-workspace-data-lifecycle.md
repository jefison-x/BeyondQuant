# ADR-004 — Workspace and data lifecycle

- Status: Accepted under ADR-0088 (2026-09-25)
- Acceptance: maintainer's explicit disposable-runtime, reset and old-DB archive specification, recorded by [ADR-0088](../../architecture/adr/ADR-0088-clean-break-baseline-activation.md).

## Decision

Old BYQ databases receive one verified, checksum-recorded, read-only final archive and are never new-schema migration inputs. New BYQ 0.10 storage starts from a fresh schema baseline and minimal seed. No old session, run, child-run, checkpoint, recovery, backtest/training runtime or trace state is migrated. Proven canonical market data remains a distinct, separately governed domain data decision; this ADR does not authorize copying unverified Community or old DB rows.

`Reset Runtime` is workspace-scoped and idempotently removes disposable Agent references, transient execution state, temporary artifacts, traces and caches, while preserving or explicitly cancelling durable Jobs according to documented state rules. `Reset Workspace` removes user-scoped research, histories, temporary strategies/experiments, generated development Artifacts and associated runtime references, then recreates a minimal default Workspace. It preserves user accounts, authentication, RBAC, system configuration, global credentials and shared datasource configuration. Cross-workspace deletion is forbidden.

## Accepted personal-reset refinement (2026-10-01)

[ADR-0091](../../architecture/adr/ADR-0091-workspace-reset-fact-retention.md) supersedes the research-only Workspace reset scope with complete personal Product data reset, same account/Workspace identity, registration defaults and seven-day read-only archive. Closed personal audit and simulated financial history can expire; unresolved external responsibility, system security facts and minimal reset/idempotency proof remain protected. Shared market data/global credentials and the old final database archive remain outside this operation.

## Acceptance

Isolated tests show reset scope and idempotency; seed after reset works; old archive is readable and checksum-valid but never auto-restored or used by tests.

## Alternative and consequence

Migrating old runtime rows would preserve unwanted architecture and is rejected. The old database remains a verified read-only rollback/reference archive, not a new-schema input. Cleanup cannot precede backup verification.
