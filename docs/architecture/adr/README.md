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
