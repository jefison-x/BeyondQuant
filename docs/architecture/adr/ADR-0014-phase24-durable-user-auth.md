# ADR-0014: Phase 24 Durable User Identity and Session Authentication

- Status: Accepted
- Date: 2026-08-16
- Decision scope: Phase 24 Product user identity and browser session boundary

## Context

Phases 16-23 used an opaque `BYQ_PRODUCT_TOKEN` for browser login. Product
completion requires durable users, password authentication, owner isolation,
and a session boundary that does not place a long-lived bearer token in
browser storage.

## Decision

1. BYQ Backend owns a durable `users` table and `auth_sessions` table.
2. Passwords are hashed with Python `hashlib.scrypt` using a per-user random
   salt. Plaintext, SHA-256 password, MD5, and home-grown crypto are forbidden.
3. Gateway issues an HTTP-only `byq_session` cookie with `SameSite=Lax` and
   `Path=/`. The cookie value is a Backend-owned opaque session id. Product API
   resolves the cookie to a BYQ principal by calling Backend.
4. The old `BYQ_PRODUCT_TOKEN` remains a bootstrap/internal compatibility seam
   only and is not the normal browser login path.
5. Users have `admin` or `user` roles. Admin can create/list/disable users and
   revoke sessions. Owner-scoped domain state binds to the resolved principal.

## Consequences

- Browser clients no longer store a product token in localStorage for login.
- Session expiration/revocation is Backend-owned and auditable.
- Product API owner isolation can be enforced per authenticated principal.
