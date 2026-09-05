# Phase 96 Community Feature Checklist

Phase 96 reuses the read-only Phase 95 inspection of Community issue templates, approval documentation and system-management entry points.
Community has no central Cloudflare Hub, single-maintainer authentication or persistent login throttle.

| Feature / invariant | Community evidence | Decision | Phase 96 result |
|---|---|---|---|
| Password form semantics | Community durable login label/name/autocomplete | `REUSE_AS_IS` / `PORT_UX` | Clear administrator-password label and `current-password`; authentication remains Hub-owned. |
| Central moderation list/detail/actions | No central implementation; generic approval UX only | `REFERENCE_ONLY` | Preserve Phase 95 console and Hub state machine; change only authentication and abuse protection. |
| Direct central administrator login | No corresponding implementation | `REPLACE` | Existing encrypted secret becomes the direct password without adding username, user table or recovery lifecycle. |
| Restart-safe brute-force protection | No corresponding implementation | `REPLACE` | HMAC source key → per-source SQLite Durable Object with expiry alarm; raw IP and password are not persisted. |
| Product/Agent/API/runtime/storage | Incompatible with central operator boundary | `DROP` / `REPLACE` | No Product identity, Community Agent runtime, database, credential, source or Git history is copied. |

Community remained read-only and no Community source, database, cache, credential or Git history was modified, imported or copied.
