# ADR-0109 bounded implementation qualification — 2026-10-08

## Scope and baseline

Worktree `dsh-acp-single-version`, branch `codex/dsh-acp-single-version`, HEAD
`2d5810973240c5d7692569319c2b5ab337ae2082`. Pre-existing changes are preserved.
Pre-slice backup: `/tmp/byq-adr0109-baseline-20261008/source-baseline.tar.gz`.
Frozen slice: `/tmp/byq-adr0109-review-20261008/slice.diff`, `manifest.json`.
Fixed official DSH tag/commit unchanged. No Product Phase, deployment, push or merge.

## Implementation

Trusted private authorization checks exact observed request, native AgentRun, current root/boot
and input digest. Only role_tool_not_allowed commits a denial audit plus exact receipt in the
same transaction. Existing ingress settlement gains the receipt-bound denied outcome. MCP
requires HTTP 200, validates exact receipt and waits for the exact negative settlement response.
No refusal proof is exposed to the model. Ordinary audit cannot write reserved acp_control
content. User-policy refusal remains generic 403 without proof. Public authorization API,
dedicated judgment five-tool root and fixed DSH version stay unchanged.

Product root/child instructions now authorize actual MCP names before domain calls, and do
not authorize local DSH delegation as a domain action. Composition identities/hash assertions
are updated together.

## Evidence so far

| Check | Result | Limit |
| --- | --- | --- |
| Backend durable role denial, idempotency, exact negative settlement and terminal digest | PASS | isolated fresh PostgreSQL, 3 focused tests |
| Backend sibling/changed input/unknown and reserved audit detail rejection | PASS | included above |
| Private endpoint identity and user-policy denial/no proof | PASS | focused API test rerun after policy fix |
| MCP build, bridge and ingress wire tests | PASS | synthetic Backend; bridge rerun after strict HTTP 200 fix |
| Composition pin and Product capability catalog | PASS | 11 architecture tests |
| Syntax and focused diff whitespace checks | PASS | source checks only |
| Existing late old-root/close fencing tests | NOT_RUN | reusable earlier evidence; no full rerun |
| Actual Backend + MCP joint probe | PASS normal/fence; FAIL lost settlement ACK | 3 synthetic requests, actual HTTP/bridge; no DSH/Gateway/model |
| Independent final review | FAIL (functional), PASS (architecture) | lost settlement response violates current accepted fence |
| Lost negative-settlement response blocks root under current literal ADR | FAIL | Backend can commit denied/settled before HTTP response is lost |
| New real Product signed-child qualification | NOT_RUN | failed legacy root remains fenced; no retry |
| Publish, default upgrade and production deployment | NOT_RUN | no Root qualification PASS |

## Preserved failure and remaining decision

Root `0a00179537f54edab8cd92a9fc37af03` remains unresolved, with the two historical unknown
rows unchanged. Its final assistant response is not terminal ACK or cleanup proof.

Lost authorization response before settlement and lost response after committed settlement
are distinct. MCP reports the latter call as unknown, while Backend already holds the exact
known denial. Accepted ADR literally fences every lost response, so overall qualification
cannot be marked PASS. The accompanying proposed revision makes the durable exact denial plus
subsequent exact terminal ACK and proven cleanup authoritative for closure; it requires
maintainer acceptance before qualification/promotion of that branch. No receipt-delivery
claim or automatic replay is proposed.

## Rollback

This slice has not replaced candidate containers. Existing candidate runner/Adapter images and
stopped rollback containers remain available as recorded in codex-handoff-20261008. Rolling
back the source/profile requires the pre-slice files and corresponding identity/hash pins;
existing ingress/audit JSON remains durable business evidence and must not be deleted or
rewritten. No incompatible schema migration was added.

## Root conclusion

Architecture boundary PASS; complete functional qualification FAIL under current Accepted
ADR-0109. New Product acceptance, candidate image replacement, push/PR, merge and deployment
remain NOT_RUN. Stop the affected promotion branch pending the proposed precise ADR revision.

Temporary test Backend/PostgreSQL containers and test network were removed by exact name
after evidence preservation. Candidate/rollback containers and persistent volumes were untouched.
