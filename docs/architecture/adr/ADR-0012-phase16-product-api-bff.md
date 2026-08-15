# ADR-0012: Phase 16 Product API / BFF

- Status: Accepted
- Date: 2026-08-16
- Decision scope: Phase 16 browser Product API boundary

## Context

Phases 6-15 established a headless quant core. A browser frontend must consume
a stable BYQ Product API/BFF rather than raw Backend-internal, MCP, DSH, or
WorkflowTrace schemas. The Gateway already owns product bearer authentication
and WorkflowTrace projection, so the Product API belongs there.

## Decision

1. The Gateway owns the browser-facing Product API/BFF under `/api/product`.
2. The BFF uses the existing `BYQ_PRODUCT_TOKEN`/`BYQ_PRODUCT_PRINCIPAL`
   authentication boundary and returns one BYQ product error envelope. It
   never forwards MCP tokens, provider credentials, DSH event schemas, or raw
   Backend storage exceptions.
3. Product resource paths are defined in a versioned OpenAPI source
   (`docs/contracts/product-api.openapi.yaml`). Generated TypeScript client
   types must be derivable from that source.
4. Phase 16 implements only the contract-bearing BFF seams needed to prove
   auth, error, and pagination boundaries plus dashboard/data-status/health.
   Full resource APIs are mapped in OpenAPI and implemented in later
   productization phases.
5. Browser requests always follow
   `Frontend -> Gateway Product API -> Backend or Runtime Adapter -> MCP/DSH`
   behind accepted boundaries. The frontend does not call Backend, MCP, or DSH
   directly.

## Consequences

- Product and Engineering/Agent plane boundaries remain explicit.
- A browser client can consume one typed contract without coupling to DSH.
- Future resource endpoints can be added behind the same auth/error/
  pagination envelope without changing the browser boundary.
