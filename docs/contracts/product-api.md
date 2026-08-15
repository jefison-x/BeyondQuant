# Product API / BFF Contract — Phase 16

## Ownership

The Gateway owns the browser-facing Product API. It exposes normalized BYQ
resource projections and does not expose MCP, DSH, raw DSH events, Backend
storage internals, provider credentials, or bearer tokens.

## Authentication and session

Product endpoints require the Gateway-owned `Authorization: Bearer` token.
The token is mapped to the configured BYQ product principal and is never
forwarded to Backend, MCP, Runtime Adapter, or WorkflowTrace payloads.

## Error envelope

Every non-success Product response uses:

```json
{"error": {"code": "...", "message": "...", "request_id": "..."}}
```

Messages are safe and bounded; internal exception text and storage paths are
never returned.

## Pagination, filtering, and sorting

List endpoints accept `limit` (1-200, default 50), `offset` (>= 0), `sort`
(explicit allowlisted field and direction), and bounded filters. Every list
response includes:

```json
{"items": [], "pagination": {"limit": 50, "offset": 0, "total": 0}}
```

## Resource projections

The versioned OpenAPI source is
[`product-api.openapi.yaml`](product-api.openapi.yaml). It maps:

- Dashboard
- Agent sessions and WorkflowTrace
- ResearchTask / Experiment / Artifact
- Factor
- Strategy / StrategyVersion / Approval
- Backtest
- Approval Inbox / Audit
- Data status / migration status

Full resource behavior is implemented in later productization phases; Phase 16
proves the auth/error/pagination boundary and dashboard/data-status/health
seams.
