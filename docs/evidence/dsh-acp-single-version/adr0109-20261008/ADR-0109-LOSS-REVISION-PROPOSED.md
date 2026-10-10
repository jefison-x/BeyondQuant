# ADR-0109 narrow revision proposal: lost negative-settlement response

- Status: Accepted revision (2026-10-09; maintainer: "接受"). Qualification and promotion gates remain separate.
- Date: 2026-10-08.
- Scope: only the `byq_agent_authorize` exact role-denial receipt path.
- Parent: `docs/architecture/adr/ADR-0109-acp-authorization-denial-receipt.md`.

## Evidence and historical failed gate

Independent review found that Backend commits `status=settled`, settlement outcome `denied`
before sending its HTTP response. If that response is lost, MCP returns
`acp_ingress_settlement_unknown`. Backend nevertheless has a durable exact denial proof and
no unresolved ingress for that request. Its existing terminal guard can allow closure.
Parent ACP events do not prove receipt delivery for child agents.

This fails the Accepted ADR's literal requirement that every lost receipt remains unknown
and blocks a new root. It does not prove that a denied business action executed, and does
not authorize rewriting a previously unknown ingress. At the initial review, the implementation had NOT passed the original strict qualification
gate. This historical FAIL is retained; revised qualification must prove exact terminal ACK
and cleanup rather than changing the old evidence.

## Recommended narrow amendment

Replace the loss clause in decision 3 with the following:

> A missing or invalid authorization-denial proof remains pending/unknown and blocks root
> closure. If Backend has already durably committed the exact validated denial settlement
> but its settlement response is lost, MCP reports this call as unknown and must not replay
> it or grant permission. Root closure may rely on Backend's subsequent exact terminal ACK
> binding the same final ingress cursor/digest, including that denial settlement, provided
> all other ingress and business outcomes are resolved and runner cleanup is proven.
> Backend persisted `unknown` rows remain immutable and block root reuse.

The MCP tool response and Backend's durable control result are separate observations.
This amendment makes the trusted Backend ledger plus exact terminal ACK authoritative for
closure; it does not claim that MCP received the earlier settlement response.
No new generic acknowledgement protocol, DSH fork, harness or storage migration is proposed.

## Retained fences

The only new negative-proof class remains `role_tool_not_allowed`. User-policy denials
(`policy_denied`) have no receipt in this slice and must remain generic refusal/unknown;
public user-policy authorization semantics are unchanged. This proposal does not expand the
receipt to every policy refusal.

- Lost authorization response before a validated negative settlement: no proof-based closure.
- Generic 403/4xx, timeout, malformed receipt, changed arguments, sibling identity or old boot:
  no known-negative classification.
- A business action with unknown result: remain unknown; no automatic replay.
- Old failed real trial `0a00179537f54edab8cd92a9fc37af03`: remain fenced. This amendment
  supplies no historical denial proof and authorizes no retrospective settlement.
- Root terminal ACK and cleanup remain required. A model response alone is insufficient.

## Alternative and cost

Keep the literal current contract and add a separate durable acknowledgement of MCP receipt.
This adds states, requests and response-loss cases, and is outside the accepted bounded
implementation. It needs its own design and qualification; the current candidate remains
blocked meanwhile. The recommendation avoids that expansion for a permission query whose
exact negative result is already durably proven at the trusted business authority.

## Qualification before promotion if accepted

Demonstrate separately: denial response lost (blocks); negative settlement response lost
(MCP unknown, Backend exact denial remains durable); exact final ingress cursor/hash and
terminal ACK; cleanup fence; no replay or permission grant. Reuse existing normal-path and
identity tests. None of this is Product or production acceptance until the corresponding
real Gateway/Product API flow is completed.
