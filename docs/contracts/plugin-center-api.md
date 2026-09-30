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

## Engineering-only handoff

The internal `GET /internal/plugin-center/requests/{request_id}` and
`POST /internal/plugin-center/requests/{request_id}/result` endpoints require
the trusted `x-byq-plugin-deployment-token` header. They are an Engineering
handoff and bounded result-reporting seam, not Product or Agent capabilities.

For policy-change requests, the input returns only the immutable desired-policy
snapshot recorded with that request. Its `plugin-deployment-policy.v1` schema,
policy version, and canonical desired-policy hash must match the persisted
request; a missing or corrupt fact returns `503`. The service never substitutes
the current Product policy. The bounded plugin and Agent identities are also
checked against the current registry; if a later registry change invalidates
those facts, the handoff fails with `503` for review rather than retargeting the
request. Qualification requests return the same `plugin-deployment-input.v1`
envelope with `policy: null`, the exact public request projection, and the
runtime baseline.

These endpoints do not execute qualification, build or install packages, mutate
the registry or application source, restart a runtime, or independently prove a
real deployment. A `succeeded` qualification or `active` deployment value is
only a bounded report recorded from the trusted Engineering lane; it is not a
qualification-gate PASS or independent deployment verification.

## Public-field ceiling

The Catalog may return plugin ID/display name/description, official publisher, exact package name/version,
qualification/compatibility/risk/capability metadata, evidence basename IDs, allowed/denied/desired Agent IDs,
tool names, credential-required/configured booleans and desired/active status. It may return normalized runtime
SDK/runtime-bin/profile/composition hash/plugin IDs.

It must never return package integrity bytes, credential reference/value, environment secret, internal token,
connection string, raw registry/Cordis/lockfile, executable command, internal filesystem path, raw DSH event,
tool arguments/results, hidden reasoning, Docker/Git/source control or arbitrary package input.
