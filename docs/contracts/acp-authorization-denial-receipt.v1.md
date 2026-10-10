# ACP authorization denial receipt v1 (ADR-0109)

Internal control contract; not a Gateway/Product API or a model-selectable route.

## Authorization query

POST `/internal/acp/agent-authorize` uses the existing authenticated MCP proof boundary and
full private BYQ scope plus native Agent identity headers. JSON body has exactly:
`schema_version: byq-acp-agent-authorize.v1`, `mcp_request_id`, `arguments`.
The arguments must be identical to the already observed byq_agent_authorize request.
arguments.run_id must equal the AgentRun bound to that exact native Agent ingress; a same-root
sibling AgentRun is not interchangeable.
No caller-supplied root/boot/native identity in the body substitutes for authenticated scope.

- Allowed query: HTTP 200 `{status: ok, authorization: <existing authorization result>}`.
- Exact role_tool_not_allowed query: HTTP 200 `{status: denied, authorization:
  {authorized: false, decision: denied, run_id, role_id, action}, refusal_receipt}`.
- Missing/mismatched request, native/scope/AgentRun/arguments, generic errors, inactive root,
  or previously unknown ingress: no denial proof.

## Negative proof

Closed refusal_receipt keys:
`schema_version` (byq-acp-authorization-denial-receipt.v1), `mcp_request_id`, `root_run_id`,
`runtime_boot_id`, `native_agent_session_id`, `agent_run_id`, `tool_name` (byq_agent_authorize),
`arguments_sha256`, `event_sha256`, `reason` (role_tool_not_allowed), `outcome` (denied),
`audit_id`, `receipt_sha256`.

receipt_sha256 is the canonical JSON SHA-256 of the complete receipt excluding that field.
The proof and denial audit must commit together in existing durable storage.
The acp_control audit detail field is reserved for trusted Backend control writes; ordinary
agent audit requests must reject it, so caller-supplied audit content cannot create denial proof. The receipt never
asserts success of a business action. Models cannot supply it, choose their own scope or receive
it as permission. MCP validates every binding against the currently observed tool ingress.

## Exact negative settlement

The existing internal ACP settlement request gains only an outcome=denied branch, requiring
refusal_receipt. Backend must match it to its own durable audit proof, current scope and exact
observed request before accepting the negative settlement. Database dispatch status is settled;
the settlement JSON outcome remains denied and its digest binds the refusal proof hash.
Existing settled/unknown forms remain unchanged. MCP waits for the exact Backend negative
settlement receipt. A missing/lost/mismatched response remains unknown to MCP: do not replay
or grant permission. If Backend has already durably validated and committed the exact denied
settlement, its subsequent exact root terminal ACK binding the same final ingress digest may
be authoritative for closure, together with proven runner cleanup and no other unresolved
outcomes. A lost authorization proof before settlement remains pending/unknown and blocks
closure. Existing persisted unknown rows must never be rewritten. This exception is specific
to the trusted role-denial control result and does not broaden business outcome classification.

## Fences

Do not broaden generic 403/4xx classification or add authorize to read-only tools. Never rewrite
an existing unknown row or infer legacy refusal proof from model text or log counts. No root can
advance without exact terminal ACK plus proven process cleanup. Dedicated judgment's five tools,
DSH version, public permissions and rollback behavior remain unchanged.
