# Phase 93 Community Feature Checklist

The Community repository was inspected read-only before implementation. It contains Issue templates and prior approval/navigation UX, but no
Cloudflare Worker, D1, Durable Object, Queue, Service Binding or central publisher implementation.

| Feature / invariant | Community evidence | Decision | Phase 93 result |
|---|---|---|---|
| Reproducible public report fields and sensitive-content warning | `.github/ISSUE_TEMPLATE/reproducible_bug.md` and `strategy_plugin.md` | `PORT_TESTS` / `PORT_UX` | Preserve the Phase 92 immutable public snapshot and fail-closed validation; no template source copied. |
| Approval center and source conversation continuity | Existing Community approval/navigation UX | `REFERENCE_ONLY` | Already delivered by Phases 91–92; Browser, Product API, MCP and DSH are unchanged. |
| User leaves the product and submits with a GitHub identity | Issue-template route | `REPLACE` | Central moderation and the isolated fixed-repository publisher keep normal users at zero GitHub configuration. |
| Central serverless intake and publication | No corresponding implementation | `REPLACE` | BYQ-owned Hub Worker, D1/DO transactional state, Queue/DLQ and private GitHub App publisher. |
| Community Agent/API/runtime/storage | Incompatible direct boundaries | `DROP` | No Community runtime, database, credential, PydanticAI, Hermes or direct GitHub path is introduced. |

The Community repository/database/runtime/credentials/Git history remained read-only and were not modified, imported or copied.
