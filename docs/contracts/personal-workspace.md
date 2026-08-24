# Personal Workspace Contract (`personal-workspace.v1`)

This contract fixes the tenancy boundary accepted by ADR-0025. It is a BYQ
Product and domain contract, not a raw browser header or DSH event schema.
The browser continues to use only same-origin Gateway/Product API routes.

## Trusted context

After authenticating a normal browser request, Gateway and Backend resolve one
normalized context:

```json
{
  "contract": "personal-workspace.v1",
  "workspace_id": "workspace_<opaque-id>",
  "workspace_kind": "personal",
  "membership_role": "owner",
  "owner_user_id": "user_<opaque-id>",
  "actor_user_id": "user_<opaque-id>",
  "actor_principal": "durable-auth-subject",
  "request_id": "request-correlation-id"
}
```

The values are resolved from durable authentication and authoritative
membership records. Browser bodies, query parameters, imported manifests,
model output, MCP arguments, and raw runtime events cannot override them.
Private service propagation may use deployment-trusted headers or a later
signed service token, but every ingress strips corresponding public headers
and Backend validates the membership rather than trusting identity text alone.

The initial closed values are:

- `workspace_kind`: `personal`
- `membership_role`: `owner`
- one active personal workspace per durable user

Adding team/member roles or multiple active workspaces requires a later ADR
and a new compatible contract version or explicitly additive fields.

## Resource scope matrix

| Scope | Resources | Authorization source |
|---|---|---|
| User | user profile, authentication sessions, UI appearance, personal model credentials/profiles/bindings, personal Agent policy | authenticated durable `user_id` |
| Workspace | Product conversations/messages; research tasks, experiments, artifacts and transitions; Agent runs, approvals and domain audit; stock pools, immutable snapshots and references; strategies and versions represented by artifacts; signal-producer jobs; backtest jobs/results/references; paper accounts, positions, orders, fills, controls, ledger, snapshots and transfers; learning-loop resources; portable workspace bundles | trusted `workspace_id` plus valid membership |
| Platform | canonical securities, calendars and market bars; data-source ingestion and coverage state; platform credentials/fallback model configuration; operations budgets, monitoring, access administration and deployment audit | explicit platform RBAC/service policy |
| Engineering | engineering tasks, source-changing engineering runs and Engineering Plane audit | Engineering Plane identity and ADR-0011; never Product workspace membership |

Audit rows that describe a workspace operation carry both `workspace_id` and
actor identity. Platform/Engineering audit rows do not acquire a fake personal
workspace merely because a user initiated an authorized administrative action.

## Relationship rules

- Every workspace-owned root row has `workspace_id NOT NULL` after contract
  migration.
- Child rows either carry the same `workspace_id` explicitly for bounded
  queries/audits or inherit it through an enforced parent foreign-key path;
  they may never cross workspaces.
- Workspace uniqueness and idempotency are at least `(workspace_id, key)`.
- Domain references validate source and target workspace equality before
  creation and again when dereferenced.
- Platform dataset references remain platform references; they do not change
  resource scope.
- Creator/actor fields are audit facts, not authorization substitutes.

## Public projection

The browser may receive only a bounded orientation projection:

```json
{
  "contract": "personal-workspace.v1",
  "workspace_id": "workspace_<opaque-id>",
  "kind": "personal",
  "display_name": "个人工作区",
  "role": "owner"
}
```

It contains no membership-management action, internal trust header, database
identifier for another user, raw DSH state, entitlement, billing, or secret.
The server still resolves authorization independently on every request.

## Failure semantics

- Missing or invalid login remains `401`.
- Authenticated requests without a valid personal membership fail closed.
- A resource outside the resolved workspace is returned as not found unless a
  narrower accepted contract explicitly requires a non-enumerating denial.
- Workspace mismatch in a write, lineage edge, approval, bundle, or
  idempotency replay is a conflict or validation failure and never falls back
  to `owner_principal`.
