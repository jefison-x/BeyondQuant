# ADR-0025: Personal Workspace Tenancy Boundary

- Status: Accepted
- Date: 2026-08-24
- Accepted: 2026-08-24
- Decision scope: Personal workspace identity, resource ownership, trusted
  request context, compatibility migration, and future team extension
- Related: ADR-0003, ADR-0012, ADR-0014, ADR-0016, ADR-0018, ADR-0019,
  ADR-0024

## Context

BeyondQuant currently has durable users and exact-owner isolation. Product
resources are authorized primarily by `owner_principal`, which is derived from
the authenticated user. This is safe for the present two-user Product journey,
but it conflates three different concepts: the user account, the container that
owns research assets, and the actor that created or changed an asset. That
conflation would make a later Cloud or team deployment require broad rekeying
of conversations, strategies, backtests, approvals, and paper accounts.

The maintainer selected a personal-workspace-first product rather than a team
edition. The immediate requirement is therefore one automatically provisioned
private workspace per durable user, with no invitations, sharing, organization
administration, billing, quotas, or workspace switcher. The storage and request
contracts must nevertheless avoid another ownership migration when a future
ADR introduces team workspaces.

The read-only BeyondQuant-Community repository contains useful planning
evidence: create a personal boundary before commercial features; never trust a
client- or model-declared tenant; keep public market data outside user asset
copies; and migrate ownership without silently assigning unverifiable rows.
It does not contain an implemented tenant system that is compatible with the
current BYQ architecture. Its old runtime, ORM, API, and Cloud topology remain
reference-only or replaced.

## Decision

1. A `workspace` is BYQ's current tenancy and authorization boundary. Every
   durable user receives exactly one workspace of kind `personal`. The user is
   its sole `owner` membership. The initial Product does not expose workspace
   creation, invitation, sharing, switching, or team roles.
2. PostgreSQL owns `workspaces` and `workspace_memberships`. Workspace and
   membership identifiers are stable opaque IDs. A personal workspace has
   exactly one owner membership and cannot be transferred or deleted through
   the Phase 49-52 Product API.
3. Workspace-owned domain rows gain a non-null `workspace_id` after an
   expand/backfill/verify/contract migration. `owner_principal` remains as
   immutable creator or historical audit identity during this program; it is
   no longer the final authorization key after cutover.
4. User account data remains user-scoped: profile, appearance, authentication
   sessions, encrypted personal model credentials/profiles/bindings, and
   personal Agent policy. Their actions may operate on workspace resources,
   but membership does not transfer account secrets or personal preferences.
5. Canonical market data, calendars, provider ingestion state, system
   operations, monitoring policy, deployment configuration, and platform
   audit remain platform-scoped. Referencing platform data from a workspace
   does not copy it into that workspace or make it exportable.
6. The Gateway derives an active personal workspace from the authenticated
   durable user. It strips or ignores any browser-supplied workspace/owner
   identity headers and propagates a normalized trusted context on private
   service calls. Backend remains authoritative for user and membership
   validation and fails closed when the workspace or membership is absent,
   disabled, mismatched, or ambiguous.
7. Runtime Adapter, DSH-facing orchestration, and BeyondQuant MCP receive only
   service-derived workspace and actor context. A model, tool argument,
   WorkflowTrace card, imported bundle, or browser body cannot select its
   workspace. DSH does not access PostgreSQL, and all Agent-to-Domain calls
   continue through BeyondQuant MCP.
8. The browser continues to call only same-origin Gateway/Product API. No raw
   DSH event or internal workspace header becomes a frontend contract. The
   Product may expose a bounded personal-workspace summary for orientation,
   but it does not require a selector while only one workspace is valid.
9. Authorization is explicit in repositories and service contracts during
   this program. PostgreSQL row-level security is a possible later
   defense-in-depth layer, not a substitute for Product API, Backend, MCP, and
   cross-resource authorization tests and not part of Phases 49-52.
10. A future Accepted ADR may add workspace kinds and membership roles or put
    an organization above workspaces. Existing domain rows remain keyed by
    `workspace_id`, so that extension adds memberships and active-workspace
    selection instead of reassigning every asset.

The normative context shape and resource classification are recorded in
[`personal-workspace.v1`](../../contracts/personal-workspace.md).

## Security and domain invariants

- The authenticated user is the actor; the workspace is the resource boundary.
- Platform administrator status does not implicitly grant membership or
  ordinary Product access to another user's workspace.
- Workspace-owned parent and child records must have the same `workspace_id`.
- Idempotency and uniqueness keys for workspace resources include the
  workspace boundary.
- Cross-workspace lookup, mutation, approval, import, replay, object retrieval,
  and lineage traversal fail closed without revealing the target resource.
- Object storage paths are never treated as ownership evidence. Authoritative
  PostgreSQL metadata grants access before object retrieval.
- Imported assets receive the destination workspace from trusted request
  context. A manifest-supplied workspace or owner is evidence only and cannot
  grant access.
- Actor and workspace context are recorded separately in audit and
  WorkflowTrace correlation. Public projections remain bounded and secret-free.

## Migration and compatibility

The migration is deliberately staged:

1. Expand with workspace tables and idempotently provision one personal
   workspace and owner membership for every durable user.
2. Add nullable `workspace_id` columns and workspace-aware indexes to the
   classified domain tables without changing current reads.
3. Backfill only where an exact unique durable-user mapping from the historical
   owner principal can be proved. Produce counts and a manifest; quarantine or
   report orphaned, ambiguous, service-token, and otherwise unverifiable rows.
4. Verify row counts, parent-child equality, reference integrity, uniqueness,
   and owner-to-workspace mappings before making any column mandatory.
5. Cut writes and reads to trusted `WorkspaceContext`, retaining
   `owner_principal` for creator/audit compatibility. Only then add non-null,
   foreign-key, and uniqueness constraints for verified tables.
6. Remove compatibility read paths only after the two-user browser and Product
   API golden journey proves restart persistence, import/export, approvals,
   lineage, and cross-workspace denial.

No migration assigns all legacy rows to the first user or to an administrator.
Before the contract step, rollback disables workspace-aware reads/writes while
leaving additive tables and columns in place. After constraints are enforced,
rollback is a forward repair or restore from the phase backup; it is never a
silent return to mixed owner/workspace authorization. `owner_principal` is not
dropped in Phases 49-52.

## Consequences

- The personal product gains an explicit, auditable tenancy boundary with no
  team-management complexity in its UI.
- Most domain tables and service methods require a controlled migration, even
  though the visible Product change is small.
- User secrets and preferences stay correctly bound to a human account while
  shareable research artifacts are structurally ready for a later team model.
- Existing owner isolation provides a safe compatibility source, but it must
  not be mistaken for completed workspace isolation until Phase 52 closes the
  migration and golden journey.

## Rejected alternatives

- Treat `user_id` as the permanent tenant key: simplest now, but forces broad
  asset rekeying when team workspaces arrive and keeps actor and owner
  semantics conflated.
- Implement full organizations and teams now: adds invitations, role policy,
  switching, sharing, billing, and operator support before the personal
  Product needs them.
- Trust a client-supplied workspace ID: permits confused-deputy and horizontal
  privilege-escalation failures.
- Reuse the Community tenant design or runtime code: it is a planning draft
  coupled to obsolete runtime and storage assumptions, not a compatible
  implementation.
- Make all data workspace-owned: duplicates canonical market data and confuses
  access to shared platform datasets with ownership of user artifacts.
- Enable RLS first and rely on it alone: leaves service, MCP, object, lineage,
  import, and audit boundaries unspecified and increases migration risk.

## Acceptance record

The maintainer selected the personal-workspace tenancy option on 2026-08-24.
This acceptance authorizes Phases 49-52 below. It does not authorize team
features, raw DSH browser contracts, DSH database access, Community code
copying, or silent ownership assignment.
