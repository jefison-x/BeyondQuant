# Personal Workspace Tenancy Plan

- Status: Phases 49-50 complete; Phases 51-52 pending
- Decision: [ADR-0025](../architecture/adr/ADR-0025-personal-workspace-tenancy.md)
- Contract: [`personal-workspace.v1`](../contracts/personal-workspace.md)

## Outcome

Move BYQ from principal-keyed personal data to an explicit personal workspace
boundary without adding team-product complexity. At completion, every durable
user has one private workspace, every classified domain asset is authorized by
trusted workspace context, and the current Product journeys remain usable and
isolated across restart, import/export, Agent actions, and browser navigation.

Each phase uses one isolated worktree, branch, and PR. It stops at its own
acceptance gate. Under the pre-release ADR-0015 exception, CI-green auto-merge
may be enabled; after merge, the latest `main` services and frontend must be
started on `0.0.0.0:80` for maintainer validation.

## Fixed scope and non-goals

Included:

- automatic one-per-user personal workspace provisioning;
- workspace membership and trusted request context;
- additive schema, deterministic backfill, quarantine/report, verification,
  contract migration, and rollback evidence;
- workspace authorization for Product, Backend, MCP, Agent orchestration,
  object references, bundles, lineage, approvals, and idempotency;
- a bounded personal-workspace identity in the Product shell;
- two-user no-crossover and recovery evidence.

Excluded:

- organizations, invitations, sharing, member administration, role editor;
- multiple workspace creation or switching;
- billing, subscriptions, entitlements, quotas, commercial data products;
- tenant-specific copies of canonical market data;
- PostgreSQL RLS or service-role redesign;
- changes to DSH's generic runtime or direct DSH database access.

## Phase 49 — Boundary decision and migration classification (`COMPLETE`)

### Deliverables

- Accept ADR-0025 and `personal-workspace.v1`.
- Classify every current resource as user, workspace, platform, or Engineering
  scope.
- Inspect and classify Community tenant/context/ownership evidence under the
  mandatory migration sequence.
- Fix the expand/backfill/verify/contract order, ambiguous-row quarantine,
  compatibility window, rollback rules, and future team seam.

### Acceptance

- No runtime or schema behavior changes are claimed.
- Actor identity and authorization boundary are distinct.
- Team features and platform data are explicitly excluded.
- Phase 50 has exact prerequisites and fail-closed migration rules.

## Phase 50 — Workspace foundation and verified backfill (`COMPLETE`)

### Scope

- Add `workspaces` and `workspace_memberships` through the repository's
  idempotent PostgreSQL bootstrap/migration pattern.
- Provision exactly one personal workspace and owner membership for every
  durable user, including newly created users, in one transaction.
- Add nullable workspace keys and indexes to the workspace-resource roots and
  required child/audit tables.
- Implement an idempotent owner-to-user-to-workspace backfill command with a
  versioned manifest, table counts, mismatch details, and quarantine/report.
- Verify parent-child workspace equality, references, uniqueness, and restart
  idempotency. Do not enforce non-null on an unverified table.

### Acceptance

- Re-running provisioning and backfill creates no duplicate workspace or
  membership and changes no already-verified mapping.
- Exact unique owner mappings are filled; ambiguous/orphan/service identities
  are reported and remain unassigned.
- Backup and rollback drill prove additive changes do not break the Phase 48
  Product path.
- No API treats nullable `workspace_id` as new authorization yet.

### Stop conditions

Stop rather than contract if a resource lacks a provable owner, a parent/child
pair resolves to different workspaces, or counts/references differ from the
manifest.

## Phase 51 — Trusted context and domain authorization cutover

### Scope

- Extend durable session resolution with the authoritative personal workspace
  and membership.
- Make Gateway construct and propagate normalized trusted context while
  stripping browser-supplied identity/workspace headers.
- Change Backend repositories and Product routes to authorize workspace-owned
  resources by `workspace_id`; keep actor/creator fields for audit.
- Propagate workspace context through Runtime Adapter and MCP without changing
  raw DSH event schemas or allowing model-selected scope.
- Make idempotency, lineage, approval, object retrieval, signal production,
  backtest, paper trading, and bundle import/export workspace-aware.
- After verification, enforce foreign-key/non-null/uniqueness constraints for
  migrated workspace tables.

### Acceptance

- Contract tests prove public headers/body cannot impersonate a workspace.
- Two users cannot list, retrieve, mutate, approve, replay, import over, or
  dereference each other's assets, including guessed IDs.
- Platform admin status grants no automatic access to another personal
  workspace.
- Browser remains Gateway/Product API only; DSH remains database-free; all
  Agent domain calls still use MCP.
- Existing Phase 48 golden behavior passes with workspace authorization.

### Stop conditions

Stop the contract migration if any root remains authorized only by
`owner_principal`, any child/reference can cross workspaces, or any runtime or
MCP path accepts model/client-selected scope.

## Phase 52 — Product orientation, recovery, and isolation closure

### Scope

- Expose the bounded current personal-workspace projection in the user shell
  and session bootstrap; do not add a switcher or membership management.
- Update user-facing asset export/import language and diagnostics to identify
  the personal workspace without exposing internal trust data.
- Run fresh database provisioning, legacy-compatible migration, backup/
  restore, service restart, and downgrade/forward-repair drills.
- Extend the no-mock Product journey to two personal workspaces across
  conversation, pool, strategy, approval, signal, backtest, paper trading,
  models, preferences, bundle transfer, and administrator settings.
- Perform real Chrome desktop/mobile review and record the Community checklist
  and network evidence.

### Acceptance

- A new user receives one usable personal workspace automatically.
- Workspace identity persists across logout/login, restart, backup/restore,
  and bundle round-trip.
- Cross-workspace Product API and browser attempts fail closed with no metadata
  leakage; normal personal workflows remain complete.
- UI is explicit about personal scope but contains no fake team affordance.
- The final report lists any quarantined legacy rows and confirms that no
  compatibility read fallback remains an authorization path.

## Later team extension

A later Accepted ADR may introduce team workspaces, multiple memberships,
roles, invitations, an active-workspace selector, and commercial control-plane
policy. It must retain workspace-keyed domain assets and separately evaluate
credential sharing, Agent policy precedence, market-data entitlements, audit
impersonation, and RLS. None of those decisions is implied by this plan.
