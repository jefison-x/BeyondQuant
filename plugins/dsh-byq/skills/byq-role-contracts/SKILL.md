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

Role boundaries are enforced by BYQ, not by this instruction. A delegated
role must report a denied capability instead of retrying or asking for a wider
tool scope. Research evidence remains a BYQ Artifact; DSH workflow state and
raw DSH events are not business evidence.

Consequential actions return `approval_required`. Create a pending approval and
wait for a trusted human decision. Approval is not execution success: record
the later domain outcome separately, including failures.

When a user-facing result is naturally a strategy draft, stock-candidate
list, or optimization proposal, call `byq_workflow_card_propose` once with a
bounded summary after the supporting domain work. The card is presentation
only: never put credentials, source code, tool arguments, URLs, approval
claims, execution claims, or raw results in it. Do not call the tool merely to
decorate ordinary prose.
