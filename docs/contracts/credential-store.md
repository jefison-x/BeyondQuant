# Credential Store Contract

ADR-0019 defines the authority boundary. This document fixes the initial
storage, public projection, encryption, resolution, and lifecycle contract.

## Credential identity and scope

A credential has:

- `credential_id`: `cred_` plus 32 lowercase hexadecimal characters;
- `purpose`: `model_api_key` or `tushare_token`;
- `provider`: a reviewed BYQ catalogue key;
- `scope`: `user` or `system`;
- `owner_user_id`: required for `user`, null for `system`;
- `label`: 1–120 display characters;
- `status`: `active`, `disabled`, or `revoked`;
- positive `version`; and
- created/updated timestamps and actor identifiers.

`tushare_token` is system-scoped. Phase 37 model provider/model values come
from the BYQ runtime catalogue; arbitrary base URLs are rejected.

## Public projection

Credential reads and mutation responses contain only:

```json
{
  "credential_id": "cred_0123456789abcdef0123456789abcdef",
  "purpose": "model_api_key",
  "provider": "deepseek",
  "scope": "user",
  "label": "研究模型",
  "status": "active",
  "configured": true,
  "masked": "sk-…cdef",
  "version": 1,
  "created_at": "2026-08-22T00:00:00+00:00",
  "updated_at": "2026-08-22T00:00:00+00:00"
}
```

It never contains fields named `secret`, `api_key`, `token`, `plaintext`,
`ciphertext`, `nonce`, `tag`, `key`, `key_id`, or `envelope`. Empty secret
values are invalid on create/replacement. Secret input is limited to 16 KiB.
The mask exposes at most a reviewed provider prefix and four trailing
characters; values too short for that rule render as `configured`.

## Encryption envelope

The stored envelope is logically:

```text
version = credential-envelope.v1
algorithm = AES-256-GCM
key_id = deployment key identifier
nonce = 12 random bytes
ciphertext_and_tag = AESGCM.encrypt(key, nonce, utf8(secret), aad)
```

AAD is the canonical UTF-8 encoding of:

```text
credential-envelope.v1\n<credential_id>\n<purpose>\n<provider>\n<scope>\n<owner-or-system>
```

The deployment supplies:

- `BYQ_CREDENTIAL_KEYRING`: a JSON object mapping bounded key ids to
  base64url-encoded, unpadded 32-byte keys; and
- `BYQ_CREDENTIAL_ACTIVE_KEY_ID`: the member used for new writes.

Malformed JSON, duplicate/invalid ids, incorrect key length, a missing active
id, unknown envelope version, unknown key id, or authentication failure makes
credential writes/resolution unavailable. It never causes plaintext fallback.

Rotation adds the new key, selects it active, rewraps active credentials in
bounded batches with optimistic version checks, verifies them, and only then
removes an unused old key. Rotation writes audit events but never secret or
envelope material. Key-ring values are not logged or exposed by health APIs.

## Lifecycle and concurrency

- Create requires a secret and an idempotency key.
- Metadata update uses expected `version`; omission of the secret preserves
  the envelope.
- Secret replacement uses expected `version`, a new nonce, and increments the
  version.
- Disable retains the envelope but prevents resolution.
- Revoke atomically disables dependent bindings and clears the envelope.
- Revoked credentials cannot be enabled or resolved.

Audit entries are append-only and record the action, credential id, scope,
owner, actor, request/idempotency identity, prior/new version, outcome, and
timestamp. They contain no submitted secret, mask fragments, model prompt,
provider response, or encryption material.

## Model profile and binding

An owner-scoped model profile references one owner-visible active
`model_api_key`, one provider/model catalogue pair, and bounded generation
options. A binding maps `(owner_user_id, agent_preset_id)` to one profile with
optimistic versioning. Cross-owner references and provider/model/credential
mismatches fail closed.

Gateway may pass owner, Agent preset, selected profile, and session/turn ids to
Runtime Adapter. It never receives resolution output. Runtime Adapter calls
only the dedicated internal resolve operation with its resolver service token.
The response is single-purpose and contains provider/model runtime fields plus
the plaintext key. The adapter must not cache it beyond the owned session or
write it to the durable session record.

`BYQ_CREDENTIAL_RESOLVER_TOKEN` is a distinct high-entropy service secret
injected only into Backend and Runtime Adapter. It is not reused as
`BYQ_MCP_TOKEN`, `BYQ_PRODUCT_TOKEN`, a browser session, or an encryption
key. Missing or invalid resolver authentication returns a normalized denial
without attempting credential lookup.

## Environment fallback

`DEEPSEEK_API_KEY` and `TUSHARE_TOKEN` are system bootstrap fallbacks only.
An active database system credential takes precedence. A user binding never
falls back to an environment or system credential after selection. Environment
values are not auto-imported and their mask is never derived for a public
response.

## Failure and redaction

Secret-bearing request bodies and internal resolution responses must be
redacted before HTTP/log/trace instrumentation. Provider authentication errors
are normalized and contain no provider body or submitted credential. The
following consumers never receive plaintext or envelope data:

- browser and Product API clients;
- Gateway;
- MCP and DSH tools/events;
- WorkflowTrace and business audit projections;
- exception messages, metrics labels, logs, fixtures, and exported assets.
