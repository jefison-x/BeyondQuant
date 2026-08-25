# Architecture Decision Records

Architecture Decision Records (ADRs) capture decisions that change or clarify durable system boundaries. An ADR is required for changes to:

- DSH boundary
- MCP boundary
- Database boundary
- WorkflowTrace
- Authentication
- Engineering Plane
- Container topology
- Strategy runtime
- Data-provider abstraction
- Artifact / Approval semantics

Each ADR should describe context, the decision, consequences, alternatives when relevant, and migration or rollback considerations. An exception to `ARCHITECTURE.md` MUST have an ADR before implementation.

Current phase-specific accepted decisions are also listed in
`docs/roadmap/STATUS.md`. ADR-0020 defines the Stock Pool identity, immutable
snapshot, lifecycle, and cross-domain reference boundary for Phase 34.
ADR-0021 defines the Paper Trading account, settlement, risk, ledger, and
portable bundle boundary for Phase 35.
ADR-0018 defines the structured WorkflowTrace card, public activity,
normalization, authority, replay, and fixed Product-action boundary for Phase
36.
ADR-0019 defines encrypted credential storage, key rotation, public masking,
model binding/runtime resolution, Tushare resolution, audit, and bootstrap
fallback boundaries for Phases 37 and 39.
ADR-0024 defines the conversation-first Product shell, durable BYQ conversation
catalog versus DSH Session boundary, route-backed settings consolidation, and
durable semantic appearance/theme contract for Phases 42-48.
ADR-0025 defines the personal workspace as BYQ's tenancy/authorization
boundary, separates resource ownership from actor identity, fixes trusted
context propagation and the verified compatibility migration, and deliberately
defers team-product capabilities to a later ADR.
ADR-0026 defines the Beta security-master snapshot, bounded catalogue Product
API, frozen daily-bar selection, and true incremental synchronization boundary.
ADR-0027 defines calendar-driven full-market daily automation and the trusted
Data Worker boundary. ADR-0028 defines lifecycle-aware readiness, bounded
repair and immutable ready inputs. ADR-0029 defines adjusted research views,
raw execution prices and implemented corporate-action settlement semantics.
ADR-0030 defines frozen benchmark performance, point-in-time index membership,
and closed strategy-declared valuation/fundamental research inputs.
