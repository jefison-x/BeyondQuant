# ADR-0109 — Exact negative receipt for ACP authorization queries

- Status: **Accepted** (2026-10-08; maintainer: "同意草案。继续。"). Implementation and qualification remain separate.
- Date: 2026-10-08.
- Narrow loss revision accepted: 2026-10-09; maintainer: "接受" (the linked loss revision).
- Scope: ordinary Product ACP `byq_agent_authorize` only, fixed official rc.2.
- Related: ADR-0094 exact ingress and terminal proof, ADR-0100 one workspace/root slot.
- Evidence: `docs/evidence/dsh-acp-single-version/signed-child-acceptance-fixed-20261008/RESULT.md`.

## Observed problem

A real signed child now registers its own AgentRun and its `byq_research_get` is settled under
its own identity. The root and child authorization queries each received Backend HTTP 403.
MCP classified these two tool outcomes as unknown because authorize is not in the read-only
catalog and a generic non-read-only 4xx is not precise proof. Backend refuses terminal close
while ingress is unknown. Root `0a00179537f54edab8cd92a9fc37af03` has no terminal ACK.

An authorization query checks business permission; it does not execute the requested action.
Its audit write and transactional rejection nevertheless need a definite result. HTTP status
alone, model prose or a later successful read is insufficient to retrofit unknown settlement.
Do not add authorize to the generic read-only list or treat all 403/4xx as known no-effect.

## Accepted narrow decision

1. For this one trusted Backend authorization endpoint, return a closed, exact negative
   control receipt only when `role_tool_not_allowed` has been proved before any business dispatch.
   User-policy refusal (`policy_denied`) has no proof in this slice and remains generic refusal/unknown.
   Bind the negative receipt to the authenticated root/boot/native AgentRun and actual MCP
   ingress request/input digest; the model cannot supply the authority or receipt.
2. Make the denial audit/receipt durable and the transaction result explicit. Prefer the
   existing ACP ingress/settlement ledgers; no incompatible storage migration or new harness.
   A committed denial proves only that the authorization query was denied. It does not prove
   that a separate business action had no effect, and never grants or substitutes permission.
3. MCP settles that exact ingress as a known negative result only after validating the precise
   receipt against the current observed request. Missing/mismatched authorization proof,
   timeouts, 5xx and generic 4xx remain pending/unknown and block new roots. If Backend has
   already durably committed the exact validated denial settlement but its settlement response
   is lost, MCP reports this call as unknown and must not replay it or grant permission.
   Root closure may rely on Backend's subsequent exact terminal ACK binding the same final
   ingress cursor/digest, including that denial settlement, provided all other ingress and
   business outcomes are resolved and runner cleanup is proven. Backend persisted unknown
   rows remain immutable and block root reuse. Root/child/sibling mismatch and old-root late
   requests must still fail closed. This does not claim MCP received the earlier response.
4. Exact Backend terminal ACK and runner cleanup stay mandatory. No unknown row is rewritten
   from HTTP counts or model text. Existing unresolved trials require their own trusted
   reconciliation evidence; acceptance of this ADR cannot itself close the current trial.
5. Gateway/Product permission and session contracts remain unchanged. Judgment's five-tool
   dedicated root remains unchanged. Production/default/version/release/Phase remain unchanged.

## Qualification (minimal)

- Exact matching denial receipt allows negative settlement and terminal ACK without executing
  a domain action; check root and child attribution.
- Missing, forged, sibling, changed-input, late-root and lost authorization proof remain unknown.
- Lost response after exact durable negative settlement: MCP still reports unknown; verify the
  final ingress digest, exact terminal ACK and cleanup gate, with no replay or permission grant.
- Policy denial is still enforced; no approval or business command is issued by receipt handling.
- One local candidate integration against the trusted Backend + MCP, then only the necessary
  real Product acceptance after independent Tester/Reviewer/Root review.
- Preserve this real failure and distinguish known negative closure from research progress.

## Gain and cost

Known permission refusals can finish a conversation without weakening the unknown-result fence.
The cost is one bounded control receipt path and its targeted failure checks. Generic response
classification and business outcome reconciliation are not broadened.

## Execution boundary

Acceptance authorizes the bounded receipt implementation and qualification above. The existing
unresolved workspace stays fenced until separately proven reconciliation; no replay/new root,
fake ACK or destructive cleanup is authorized by this acceptance.

## Accepted revision evidence

The independent Backend HTTP/MCP bridge probe distinguished lost authorization response
(unknown ledger, blocks closure) from lost response after committed negative settlement
(settled/denied ledger, terminal predicate allows). Historical strict-contract FAIL remains
recorded in `docs/evidence/dsh-acp-single-version/adr0109-20261008/`. The narrow revision is
accepted in `ADR-0109-LOSS-REVISION-PROPOSED.md` there; acceptance does not itself prove
terminal ACK, cleanup or real Product qualification.
