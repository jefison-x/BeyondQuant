# ADR-0019: Encrypted Credential Store and Runtime Resolution Boundary

- Status: Accepted
- Date: 2026-08-22
- Decision scope: Phase 37 model credentials and Phase 39 Tushare credentials
- Related: ADR-0003, ADR-0004, ADR-0005, ADR-0012, ADR-0014, ADR-0016
- Contract: `docs/contracts/credential-store.md`

## Context

Community exposes provider/model credential CRUD, model profiles and Agent
binding through `UserModelSettingsPanel`, and data-source configuration through
`DataSourceConfig`. Those workflows are useful product evidence, but the old
credential APIs, provider catalogue, Agent runtime, and persistence model are
not a safe migration boundary.

BYQ currently receives `DEEPSEEK_API_KEY` and `TUSHARE_TOKEN` from the process
environment. The Gateway's model-settings response is status-only, so a user
cannot create a personal model credential or make an Agent binding effective.
Environment-only configuration also cannot provide audited administrator CRUD
for a Tushare credential. A database-backed store is therefore required, but
putting recoverable secrets in PostgreSQL introduces encryption, key rotation,
authorization, runtime delivery, deletion, and observability decisions that
must be closed before Phase 37 begins.

The browser, Gateway, MCP, DSH event stream, WorkflowTrace, audit records, and
application logs must never receive a stored plaintext secret. At the same
time, an adapter-owned model client and the Backend-owned Tushare provider need
the plaintext briefly to authenticate an outbound provider call.

## Decision

### 1. Backend owns one typed credential store

The Backend owns PostgreSQL records for credential metadata and encrypted
secret envelopes. The initial credential purposes are:

- `model_api_key`, with `user` or `system` scope; and
- `tushare_token`, with `system` scope only.

Every record has a stable BYQ identifier, purpose, provider key, scope,
owner identity when user-scoped, display label, status, version, masked
descriptor, encrypted envelope, and created/updated/revoked audit metadata.
Exact limits and public projections are defined by
`docs/contracts/credential-store.md`.

User-scoped credentials are visible and mutable only to their owning durable
BYQ user. System-scoped credentials require an authenticated `admin` role.
The browser reaches them only through Gateway Product API routes. MCP and DSH
receive no credential CRUD or resolution capability.

### 2. Use a versioned AES-256-GCM envelope

Secret values are encrypted in the Backend application layer with AES-256-GCM.
Each write uses a fresh 96-bit random nonce and the active 256-bit deployment
key. Authenticated additional data binds the ciphertext to the envelope
version, credential id, purpose, provider, scope, and owner, preventing a
ciphertext from being moved to another record or meaning.

Deployment keys are supplied through a versioned environment key ring and are
never stored in PostgreSQL or returned by readiness endpoints. The key ring
identifies one active key for new writes and may retain previous keys for
decrypt-and-rewrap rotation. Unknown key ids, invalid tags, malformed
envelopes, or unavailable keys fail closed. Plaintext is never persisted,
cached to disk, included in an exception, or placed in a queue.

The normative envelope, key-ring variables, rotation procedure, and startup
behavior are part of the credential-store contract. A production credential
write is unavailable until a valid active key exists; env-only bootstrap
operation remains possible without silently weakening encryption.

### 3. Public reads are metadata-only and writes are secret-blind

Public Product API reads return exact allow-listed metadata, `configured`, and
a bounded masked descriptor such as `sk-…abcd`. They never return ciphertext,
nonce, tag, key id, plaintext, environment values, or a reversible derivative.
The descriptor is calculated at write time and cannot be used to reconstruct
the value.

Create and replacement requests accept the secret only in the request body.
Responses use the same metadata-only projection. Updating metadata with the
secret omitted preserves the current encrypted value; replacing a secret
increments the credential version and writes a new nonce/envelope. Identical
idempotency keys may replay the prior metadata response but never replay the
submitted request body.

Delete is an auditable revoke: active bindings are disabled atomically and the
encrypted envelope is removed. It is not possible to read or restore a revoked
secret. All create, replace, enable/disable, bind/unbind, and revoke operations
append an audit event containing actor, owner/scope, credential id, action,
request identity, and timestamp, but no secret or credential-shaped payload.

### 4. Model profiles and Agent bindings are separate from secrets

A model credential authenticates a provider; it is not itself an executable
Agent configuration. BYQ stores owner-scoped model profiles that reference an
active credential and contain only allow-listed provider/model catalogue keys
and bounded generation options. Arbitrary user-supplied provider URLs are not
accepted in Phase 37; this avoids turning the runtime into an SSRF proxy.

An owner-scoped Agent binding maps a BYQ Agent preset id to a model profile.
Only catalogue-compatible, active profiles may be bound. Revoking or disabling
the credential makes dependent profiles unavailable and their bindings
ineffective without falling through to another user's or another system
credential. The Product API may report the effective source and availability,
but never the secret.

### 5. Resolve model secrets through a private Backend-to-Adapter seam

Gateway starts a turn with authenticated owner and Agent/profile references;
it never fetches a secret. Runtime Adapter resolves the effective binding from
a Backend internal endpoint protected by a dedicated resolver service token
that is present only in Backend and Runtime Adapter. The request is bound to
the owner, Agent preset, and session/turn identity. Backend authorizes the
binding and returns one bounded resolution document directly to the adapter.

That internal response is the only API response allowed to contain plaintext.
It is not part of Product API or OpenAPI, is never available to the browser,
Gateway, MCP, or DSH tools, and uses no general credential-list/read endpoint.
Runtime Adapter holds it only in memory and places the model key only in the
environment of the adapter-owned SDK child for that session. It is excluded
from session descriptions, WorkflowTrace, errors, command arguments, logs,
and durable DSH session metadata. Resolution failure fails the requested turn
closed rather than silently using a different user's key.

Phase 37 must prove this seam with secret-boundary, owner-isolation, redaction,
and child-process-environment tests. A future external secret broker or KMS can
replace the internal resolution implementation without changing Product API.

### 6. Tushare resolution stays inside Backend

The Backend-owned Tushare adapter resolves the active system
`tushare_token` directly from the credential store at provider call time. It
does not expose a resolver route to Gateway, MCP, DSH, or Runtime Adapter.
Data-source configuration remains Tushare-only. BaoStock, AKShare, Yahoo, and
other Community providers remain `DROP`.

### 7. Environment credentials are explicit bootstrap fallbacks

`DEEPSEEK_API_KEY` and `TUSHARE_TOKEN` remain bootstrap/system compatibility
fallbacks. A valid active database credential takes precedence for the same
purpose/provider. Environment values are never imported automatically into
PostgreSQL and are represented publicly only as a source/status flag with a
non-revealing descriptor.

There is no environment fallback for a missing, disabled, revoked, corrupt, or
cross-owner user credential. This prevents a personal binding failure from
unexpectedly consuming a system key. Bootstrap fallback use is observable in
secret-free audit/health metadata.

### 8. Phase ownership removes the Phase 37/40 cycle

Phase 37 owns the model credential/profile/binding UI component and API flows
required by its exit criteria, plus asset re-import and Agent policy depth.
Phase 40 may extract or generalize proven shared components later; it is not a
prerequisite for Phase 37. Phase 39 reuses this accepted store for the
Tushare-only data-source workflow and does not add providers.

## Consequences

- Model and Tushare credentials become durable, scoped, masked, auditable, and
  rotatable without exposing secrets to browser-facing contracts.
- The Backend gains credential/profile/binding records and a narrow internal
  resolver; Runtime Adapter gains per-session resolution and in-memory child
  environment injection.
- Deployments must provision and back up the encryption key ring separately
  from PostgreSQL. A database backup alone cannot decrypt credentials.
- Key loss makes affected credentials unrecoverable by design; operators must
  replace them. Invalid encryption state degrades credential-backed operations
  without taking down unrelated Product reads.
- Phase 37 can begin without waiting for Phase 40, while preserving the
  one-phase-per-worktree gate.

## Required implementation evidence

- encryption known-answer/round-trip and tamper/AAD/key-id failure tests;
- key rotation and rewrap tests proving old and active key behavior;
- owner/admin authorization, idempotency, optimistic-version, revoke, cascade,
  and append-only audit tests;
- Product API/OpenAPI tests proving plaintext and envelope fields never occur;
- Runtime Adapter tests proving exact binding resolution, no cross-owner or
  fallback substitution, in-memory-only handling, and complete redaction;
- Tushare precedence/fallback tests without a live secret in fixtures;
- Community feature checklist and real Product API desktop/mobile Chrome MCP
  evidence for Phase 37.

## Rejected alternatives

- Environment-only credentials with a status UI: cannot satisfy durable CRUD,
  personal bindings, rotation, or audit.
- Plaintext or database-extension-only storage: exposes secrets to database
  readers/backups or couples the domain store to an implicit decryption role.
- Hashing provider credentials: outbound provider authentication requires the
  original secret.
- Returning a secret to Gateway and forwarding it to Runtime Adapter: expands
  the browser-facing process trust boundary and creates logging/error hazards.
- A generic secret-read endpoint for MCP or DSH: violates the Agent-to-Domain
  boundary and grants unnecessary secret authority.
- Arbitrary user provider URLs: creates an SSRF/exfiltration surface.
- Automatic fallback from a broken personal binding to a system key: hides
  authorization/configuration failure and can charge the wrong credential.
- Copying Community credential tables, providers, or Agent runtime: preserves
  incompatible trust and provider assumptions.

## Rollback

Disable database-backed resolution and personal bindings, revoke the resolver
service token, and return supported system providers to explicit environment
bootstrap configuration. Revoked records remain audit evidence; encrypted
records may be retained for a bounded rollback window or securely purged after
operator confirmation. Product metadata endpoints continue to omit secrets.
