# Product API / BFF Contract — Phase 16

## Ownership

The Gateway owns the browser-facing Product API. It exposes normalized BYQ
resource projections and does not expose MCP, DSH, raw DSH events, Backend
storage internals, provider credentials, or bearer tokens.

## Authentication and session

Normal browser login uses username/password through `/api/auth/login` and a
durable Gateway `byq_session` HttpOnly cookie (`SameSite=Lax`, `Path=/`). The
Gateway resolves that opaque Backend-owned session to the owner/actor
principal and forwards only trusted BYQ context headers. The legacy
`Authorization: Bearer` product token is internal/bootstrap compatibility
only; it is not normal browser identity and is never forwarded to Backend,
MCP, Runtime Adapter, or WorkflowTrace payloads.

## Error envelope

Every non-success Product response uses:

```json
{"error": {"code": "...", "message": "...", "request_id": "..."}}
```

Messages are safe and bounded; internal exception text and storage paths are
never returned.

## Bounded list policy

Implemented list routes return resource-specific arrays such as `tasks`,
`artifacts`, `backtests`, `pools`, and `accounts`. Backend queries impose their
domain bounds and stable ordering where defined. There is no universal
pagination envelope. Phase 34 Stock Pool catalog/history routes implement
bounded `limit`/`offset` parameters and return `total`, `limit`, and `offset`;
other routes must not advertise pagination until they implement and test it.

## Resource projections

The versioned OpenAPI source is
[`product-api.openapi.yaml`](product-api.openapi.yaml). Architecture tests
require its browser route/method set to match the implemented Gateway surface.
It maps:

- Dashboard
- Agent sessions and WorkflowTrace
- ResearchTask / Experiment / Artifact
- Factor
- Strategy / StrategyVersion / Approval
- Backtest
- Stock Pool catalog, immutable snapshots, typed provenance, references, and
  lifecycle
- Approval Inbox / Audit
- Data status / migration status

Later productization phases implemented the mapped resource behavior. New or
removed browser routes must update the OpenAPI source in the same change.
