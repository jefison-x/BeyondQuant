# Plugin Center Product API Contract

Phase 65 exposes one admin-only, secret-free governance contract through the same-origin Gateway:

- `GET /api/product/plugins` — Overview, Catalog, desired policy, recent request/audit and active identity;
- `GET /api/product/plugins/{plugin_id}` — bounded Detail and evidence IDs;
- `POST /api/product/plugins/changes` — versioned `enable|disable|assign` deployment request;
- `POST /api/product/plugins/qualifications` — exact registered-version qualification request.

All mutations require a durable admin session, `expected_version`, a unique idempotency key and a non-empty
reason. Ordinary/disabled users receive `403`. Unknown fields, plugin/version/Agent IDs, unqualified or dangerous
plugins and assignment escalation fail closed.

## State semantics

```text
desired policy request accepted
  → validated / awaiting_generation
  → trusted CI/operator builder and exact-lock validation
  → immutable image deploy/restart
  → Runtime Adapter readiness hash comparison
  → ACTIVE
```

`202 Accepted`, `validated`, `queued` and `awaiting_generation` never mean active. If runtime readiness is
unavailable the projection is `partial`; it does not infer active state. Qualification does not modify Product
policy or auto-enable a plugin.

## Public-field ceiling

The Catalog may return plugin ID/display name/description, official publisher, exact package name/version,
qualification/compatibility/risk/capability metadata, evidence basename IDs, allowed/denied/desired Agent IDs,
tool names, credential-required/configured booleans and desired/active status. It may return normalized runtime
SDK/runtime-bin/profile/composition hash/plugin IDs.

It must never return package integrity bytes, credential reference/value, environment secret, internal token,
connection string, raw registry/Cordis/lockfile, executable command, internal filesystem path, raw DSH event,
tool arguments/results, hidden reasoning, Docker/Git/source control or arbitrary package input.
