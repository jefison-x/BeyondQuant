# Phase 95 Community Feature Checklist

The Community repository was inspected read-only before implementation. It has Issue templates and a general Agent approval center, but no
central anonymous-feedback service, Cloudflare operator console or fixed-repository publication moderation UI.

| Feature / invariant | Community evidence | Decision | Phase 95 result |
|---|---|---|---|
| Structured reproducible issue content | `.github/ISSUE_TEMPLATE/reproducible_bug.md` | `PORT_UX` / `PORT_TESTS` | Render only the already validated immutable public candidate: classification, description, steps, expected/actual behavior and opted-in environment fields. |
| Secret/security warning before public publication | Issue template warning and security contact | `PORT_UX` / `PORT_TESTS` | Keep Hub fail-closed validation and add an explicit warning before central acceptance enters the public Issue queue. |
| Human approval interaction | `docs/approval_center.md` | `REFERENCE_ONLY` | Reuse understandable list/detail/status/action UX only; central moderation remains its own D1/DO state machine and does not copy the Community Agent service. |
| Central operator moderation console | No corresponding implementation | `REPLACE` | Hub-hosted Chinese console with bounded status pagination, lazy current-page detail, short HttpOnly session and same-origin mutation guard. |
| Community browser/API/runtime/storage | Incompatible Product/Agent boundaries | `DROP` / `REPLACE` | Console calls only same-origin Hub admin contracts; no Community runtime, database, credential, source or Git history is copied. |

The Community repository and database remained read-only and were not modified, imported or copied.
