# ADR-0097 judgment tool admission: implementation boundary

Status: implementation candidate, **not Product qualification**. The dedicated
judgment MCP rejects every `tools/call` by default. An explicit local admission
flag reaches four bounded read handlers only after Backend ingress proof;
`byq_agent_context` remains denied because its current callback reads generic
notifications and research context outside the admitted frozen stage input.

## Required proof before enabling one read

1. Give the isolated judgment MCP process a **distinct Backend proof bearer**;
   it must not receive the Product ACP proof bearer, Product MCP bearer, legacy
   read-only bearer or runtime-authority bearer. Backend judgment ingress routes
   accept only this bearer. Product ACP ingress routes reject judgment roots,
   including observation abort and settlement, unless the request uses the
   judgment-specific proof path and exact task/call scope.
2. Verify the separately signed judgment MCP bearer on every call. Carry its
   immutable owner/Workspace, task/call, BYQ root, boot, generation and native
   root identity into a judgment-specific Backend observe request. Backend must
   match those claims to the durable `research_judgment_acp_roots` binding,
   current active root and trusted native AgentRun **in the same transaction**
   that reserves the existing ACP ingress sequence and arguments digest.
   `byq_agent_context` is not a pre-registration bootstrap for this process.
3. Check tool arguments against the **admitted stage input**, not merely the
   owner or tool name. The only eligible forms are:

   | Tool | Admitted arguments |
   | --- | --- |
   | `byq_agent_context` | Empty object. |
   | `byq_research_get` | `entity_type=research_task`, `entity_id` equal to the exact admitted task; no watch or idempotency lookup. |
   | `byq_research_stage_input_get` | `task_id` equal to the exact admitted task. |
   | `byq_backtest_task_get` | Direct `backtest_task_id` equal to a `backtest_task` evidence ID frozen in the begin receipt; no task/key recovery lookup. |
   | `byq_backtest_analysis_get` | `job_id` equal to a `backtest_job` evidence ID frozen in the begin receipt; section/page arguments retain their existing bounds. |

   If the relevant evidence ID is absent, deny that call before handler entry.
   Compare structured, validated arguments; do not infer task ownership from a
   same-tenant Backend read. A later plan revision cannot expand the frozen
   call's read set.
4. After a valid observation receipt, invoke the existing read callback with
   a trusted Backend fetcher that carries the signed root and observation ID.
   Settle the exact request as `settled` or `unknown`; if observe response is
   lost before dispatch, write the exact abort tombstone. Unknown/pending rows
   must keep Backend close blocked. A denied call must enter no business handler
   and must not create a successful observation receipt.
5. A valid direct MCP request with an old root, changed task/call, changed
   arguments, forged Product/static bearer or late native request must fail at
   MCP or Backend. Verify the old request remains attributed to the old root
   after a new root starts. Two-user and same-tenant cross-task tests are both
   required. The five-tool catalog and result/close tests alone do not prove
   these properties.

## Current finding

The dedicated proof and Backend admission routes now exist in the isolated
candidate. Focused store/route and synthetic MCP tests pass, but no actual
business read has completed against the real Backend through this path. Keep
the opt-in admission flag unset outside isolated qualification. The context
tool needs a task-bounded callback or a documented denial in the final tool
contract. Late requests, unknown outcomes and exact close/ACK still need
integrated proof before any default ACP promotion.
