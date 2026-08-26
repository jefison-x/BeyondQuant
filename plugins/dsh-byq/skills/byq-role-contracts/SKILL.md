---
name: byq-role-contracts
description: BYQ quant research role, authorization, approval, and audit contract.
user-invocable: false
disable-model-invocation: false
---

# BYQ role contract

Use the specialized DSH delegation tools for focused work. Start a BYQ agent
run before domain work, then call `byq_agent_authorize` before a domain action
and `byq_agent_audit` with the bounded outcome afterward.

The authorization `action` is always the exact MCP tool name you will call;
never invent aliases such as `market_daily.read`. Audit every distinct authorized
domain action separately with its actual success or failure. Authorization is not a
successful domain result, and one later audit must not be described as covering
several unaudited calls.

Role boundaries are enforced by BYQ, not by this instruction. A delegated
role must report a denied capability instead of retrying or asking for a wider
tool scope. Research evidence remains a BYQ Artifact; DSH workflow state and
raw DSH events are not business evidence.

Market research returns frozen stock candidates to the coordinator; it never
creates or mutates a Stock Pool. When the user explicitly asks to save those
candidates, only the `quant_orchestrator` may authorize and call the bounded
`byq_pool_list`, `byq_pool_get`, or `byq_pool_create` tools. Use the trusted
owner/workspace context, never invent or request an internal owner identifier,
never expand the candidate set silently, and audit the actual domain result.
Pool snapshot, lifecycle, delete, index, and dynamic-pool mutations are not
Agent capabilities.

Public progress and answers use product language only. Say that data is being
read, a pool is being saved, or a strategy is being checked. Never narrate role
IDs, skill loading, policy/contract mechanics, MCP tool names, validator
versions, workers/runtimes, or internal Artifact IDs unless the user explicitly
requests diagnostic detail. Internal execution remains visible in normalized
activity, not in the investment answer.

Consequential actions return `approval_required`. Create a pending approval and
wait for a trusted human decision. Approval is not execution success: record
the later domain outcome separately, including failures.

When a user-facing result is naturally a strategy draft, stock-candidate
list, or optimization proposal, call `byq_workflow_card_propose` once with a
bounded summary after the supporting domain work. The card is presentation
only: never put credentials, source code, tool arguments, URLs, approval
claims, execution claims, or raw results in it. Do not call the tool merely to
decorate ordinary prose.

After a BYQ domain validation failure, use the returned safe validation summary
for at most one corrected call with the same user intent. A second failure is a
stop condition; report it instead of guessing task states, roles, identifiers,
or alternative payload shapes.
