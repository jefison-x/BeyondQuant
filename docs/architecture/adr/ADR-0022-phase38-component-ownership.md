# ADR-0022: Phase 38 Operations Component Ownership

- Status: Accepted
- Date: 2026-08-22
- Decision scope: Phase 38 operations workbenches and the Phase 40 shared-component gate
- Related: ADR-0012, ADR-0015, ADR-0016, ADR-0018, ADR-0019

## Context

The Community full-parity plan originally described Phase 40 shared components
as a prerequisite for Phase 38. Phase 40 is also the final parity-closure phase
and is sequenced after Phases 38 and 39. That creates a circular delivery gate:
Phase 38 cannot start before Phase 40, while Phase 40 cannot perform final
closure until Phase 38 is complete.

Phases 36 and 37 already resolved the same ownership problem safely. Each phase
owned the specific component required for its acceptance criteria, and Phase 40
retained responsibility only for extracting or generalizing proven reusable
components. Phase 38 needs the same explicit rule before implementation begins.

ADR-0019 is Accepted. The remaining Phase 38 prerequisites are therefore
Backend projections, Product API authorization, audit contracts, Community
inspection/classification, and real browser evidence rather than a generic
component extraction performed by a later phase.

## Decision

1. Phase 38 owns the operations-specific views and components required to
   replace its placeholders and satisfy its acceptance criteria.
2. Phase 40 is not a prerequisite for Phase 38. Phase 40 may extract,
   consolidate, or generalize components proven by Phase 38, but it must not
   change the Product API or security boundaries merely to make components
   generic.
3. Phase 38 must reuse existing BYQ base components where they fit. It must not
   create a speculative generic component library or copy Community component
   architecture.
4. Every operations browser request remains Gateway/Product API only.
   Read-only projections must be real and bounded. Every write action must be
   explicitly RBAC-protected, audited, idempotent where applicable, and fail
   closed.
5. Community Redis assumptions are replaced by PostgreSQL market-data cache
   status. Product DSH receives no database, runtime-control, credential-read,
   application-source, or deployment authority.
6. Data-source credential CRUD and data-sync execution remain Phase 39 scope.
   Phase 38 may show bounded configuration/readiness status but must not absorb
   Phase 39 or expose secrets.
7. DSH model-call budget projections must use normalized BYQ accounting. Raw
   DSH event schemas, hidden reasoning, tool arguments, and provider secrets
   must not cross the Runtime Adapter/Gateway boundary.

## Consequences

- The circular Phase 38/40 dependency is removed without weakening Phase 38
  acceptance criteria.
- Phase 38 can begin after ADR-0019 using phase-owned operations components.
- Phase 40 remains the final shared-component and parity-closure phase and can
  generalize only implementations already proven in product flows.
- Phase 38 remains large and must be delivered in one isolated phase worktree
  and PR, with contract-first slices and no placeholder completion.

## Required implementation evidence

- Community operations pages/components inspected and classified before code;
- admin/role denial, audit, secret-redaction, and bounded-projection tests;
- Backend and Product API contract tests for each operations projection/action;
- no direct browser calls to Backend, DSH, MCP, PostgreSQL, Redis, or providers;
- real Product API desktop/mobile Chrome MCP review and feature checklist;
- standard architecture, unit, contract, integration, and local CI checks.

## Rejected alternatives

- Run Phase 40 before Phase 38: breaks the ordered phase source of truth and
  asks final closure to generalize components that do not yet exist.
- Keep Phase 38 blocked until Phase 40: preserves a circular dependency.
- Waive the shared-component concern without an ADR: contradicts the explicit
  blocker in `STATUS.md` and the development workflow.
- Copy Community workbenches: imports obsolete topology, Redis assumptions,
  unsafe direct control APIs, and incompatible authorization semantics.

## Rollback

If phase-owned components prove unsuitable, stop Phase 38 and restore the gate
through a superseding Accepted ADR. Do not silently move operations authority
into the browser, DSH, or a generic component abstraction.
