# ADR-0004: Phase 7 Product Agent Authentication and Secret Boundary

- Status: Accepted
- Date: 2026-08-15
- Decision scope: Phase 7 authenticated Product Agent turn
- Supersedes: the unauthenticated Phase 6 internal-only prototype boundary

## Context

Phase 6 established a private Gateway → Runtime Adapter seam. Its endpoints
trusted the private Compose network and deliberately were not user
authentication. Phase 7 needs one authenticated Product Agent turn while
keeping user credentials, model/provider credentials, DSH persistence, and
BYQ WorkflowTrace ownership separate.

No identity provider or user database is in the Phase 7 topology. A larger
identity system would expand the phase beyond the first product turn and would
not be contract-testable in the current repository.

## Decision

1. Product Agent endpoints under `/v1/agent` and `/v1/workflows` require an
   opaque `Authorization: Bearer` token configured as the Gateway-only
   `BYQ_PRODUCT_TOKEN` secret. Comparison is constant-time. The token maps to
   the configured `BYQ_PRODUCT_PRINCIPAL` subject for this phase.
2. Gateway generates session and trace identifiers, records the authenticated
   principal as the session owner, and returns 404 for another principal's
   session. The token is never forwarded to DSH, MCP, the Runtime Adapter, or
   WorkflowTrace payloads.
3. `DEEPSEEK_API_KEY` is configured only on Runtime Adapter. The adapter
   forwards it only to the adapter-owned official SDK child environment. It is
   never included in readiness details, lifecycle responses, exception text,
   logs, or normalized trace events. A Product turn fails closed with a generic
   503 when the provider secret is absent.
4. Phase 6 `/internal/runtime` endpoints remain private compatibility seams.
   They are not a user-facing authentication surface and must not be exposed
   beyond the private service network without the service-identity mechanism
   required by ADR-0003.
5. Gateway owns an append-only normalized WorkflowTrace store. It persists
   only BYQ envelopes, enforces contiguous per-session sequence numbers, and
   supports replay using `Last-Event-ID`. DSH session logs remain Agent Plane
   state and are not copied into the BYQ trace store.

## Consequences

- CI and keyless environments can test authentication, lifecycle, secret
  absence, normalization, ordering, and cleanup without embedding a model
  credential.
- A real model-keyed turn requires an operator-provided `DEEPSEEK_API_KEY`;
  absence is an explicit environment limitation rather than a fake provider.
- The single opaque token is intentionally a Phase 7 bootstrap policy. A
  multi-user identity provider, token rotation, revocation, and cross-instance
  session ownership require a later ADR.
- The Gateway trace store is a Phase 7 append-only filesystem contract. A
  future durable BYQ persistence service may replace its storage while
  retaining the envelope and replay semantics.

## Rejected alternatives

- Passing `DEEPSEEK_API_KEY` through Gateway would widen the secret boundary
  and make Gateway compromise expose the model provider.
- Treating a DSH session token or raw DSH session log as user identity would
  conflate Agent Plane persistence with BYQ authentication.
- Making Product Agent endpoints unauthenticated would not satisfy the Phase 7
  authenticated-turn acceptance criterion.
- Putting the model credential in a WorkflowTrace payload or error would make
  secret leakage observable to product clients.
