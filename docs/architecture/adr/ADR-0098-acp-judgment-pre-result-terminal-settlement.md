# ADR-0098 — ACP judgment root pre-result terminal settlement

- Status: **Proposed** (2026-10-04). Maintainer acceptance is required before
  changing the Backend judgment root/call terminal contract.
- Scope: the dedicated Product ACP research-judgment root selected by Accepted
  ADR-0097 at fixed official `dsh-v0.2.0-rc.2`
  (`639ed015397290b3745d163aafe02ffee4aa3f84`). No Product Phase change.
- Amends ADR-0097's result-then-close sequence for a root that cannot produce
  a proven stage result. The successful completed-result path is unchanged.
  ADR-0094's exact MCP ingress and unknown-claim terminal rules remain in force.

## Observed gap

Backend atomically admits a judgment stage call and opens a distinct root
before ACP starts. The current `research_judgment_acp_roots` row permits only
`root_created` or `agent_bound`; `research_judgment_stage_calls` remains
`admitted` until an exact result is committed. Backend
`_require_judgment_root_result_before_close` accepts only a bound Agent,
committed result and `completed` outcome. `acp-root/status` rejects a closed
root without that result. A pre-prompt setup failure, user cancellation,
provider outcome unknown, ACP process fault or Adapter restart therefore has
no exact Backend settlement and can strand an active root and admitted call.
ACP `session/cancel`, process exit and an absent provider receipt do not prove
that the model or a business tool did not run. The MCP
`abort_before_dispatch` contract only concerns one ingress request, not the
judgment root or stage call. The current ACP entry correctly returns 503.

## Decision proposed

Add a **named, one-way pre-result settlement** for the exact admitted
task/call/root. It records one of these distinct facts, without manufacturing
a judgment result:

| Settlement | Required evidence | Backend terminal outcome |
| --- | --- | --- |
| `never_dispatched` | Private journal durably shows no prompt-may-dispatch and no provider-attempt marker; owned ACP/proxy processes are proven stopped; Backend confirms no business ingress or unresolved claim. Missing journal or uncertain cleanup cannot use this state. | `failed`, or `cancelled` only when a durable authenticated user cancellation intent exists. |
| `cancelled_after_dispatch` | Durable authenticated user cancellation intent plus proven ACP/proxy shutdown and frozen ingress/claim readback. The provider may have been charged; the record does not claim otherwise. | `cancelled`. |
| `outcome_unknown` | Prompt/provider dispatch may have happened, a response was lost, cleanup is uncertain, or the prior Adapter boot cannot prove a narrower state. Keep available exact journal and prompt/provider-attempt digests, known usage, and explicit missing-evidence flags. | `interrupted` only after old execution is fenced and the generic root terminal ingress gate can close; otherwise no terminal ACK and remain fail closed. |

`cancelled` means an authenticated Product/Gateway user cancellation command
for the exact owner/task/call/root was durably admitted by Backend. The
Adapter's own timeout, process shutdown or internal cancellation request is
not a user cancellation and must settle as `failed` only if no dispatch is
proved, otherwise `outcome_unknown`. A user cancellation intent does not by
itself change the research task's status or prove provider/business outcomes;
any task-level cancellation remains a separate authorized domain transition.

The settlement request must be internal Runtime Adapter authority only, with
exact task ID, call identity, attempt binding, root ID, Adapter boot and
authority epoch, plus a deterministic **settlement digest** over the exact
Backend admission scope, requested outcome and evidence declaration. This
digest is for idempotency only. Prompt, provider-attempt and local journal
digests are separate evidence fields and may explicitly be `unknown` or
`missing` after crash; Backend must never synthesize them from the settlement
digest. A cancellation outcome also carries the exact Backend cancellation
intent receipt.
Backend must compare the persisted task/plan/root scope and serialize with
root authority, stage result and close operations. One settlement wins;
retries with the same digest read back the same receipt, while a different
settlement or a later result fails closed. A committed result wins over a
late settlement. A late MCP request remains attributed to the old root and
is denied after its authority closes.

All three settlements **consume the admitted stage-call slot permanently**.
They store no proposal, progress identity or successful result receipt, and
must not advance a plan or assert that unknown work did not happen. Move the
current nonterminal research plan to `needs_attention` with the exact
call/root and settlement reason in the same transaction that settles the
call. If a separately authorized task transition has already made the task
terminal, do not write the task **or plan**; store the attention reason only
in the settlement record. In particular, do not call the current
`_apply_stage_needs_attention` helper on a terminal task, because it also
updates task progress/version. The same attempt cannot be
re-admitted or automatically replayed. Any later plan revision or new
judgment attempt requires the existing explicit domain authorization; this
ADR grants no automatic retry. Root close and its terminal ACK occur only
after the atomic call settlement and any applicable nonterminal plan update
are readable by exact status.

The Backend status response must distinguish `admitted`, committed result,
and each pre-result settlement, including its digest and exact root terminal
event. The generic root close guard may accept a non-`completed` outcome for
a judgment root only when the matching settlement is durable and the existing
MCP ingress/unknown-claim terminal proof succeeds. A lost settlement or close
response requires status readback of the exact digest, frozen ingress cursor,
unknown-claim count and terminal event. No local or synthetic response is a
Backend ACK. A root with unresolved business claims or unproven old process
fence remains open/unknown; no next judgment invocation is released.

For Adapter restart, a new boot cannot assert `never_dispatched` from absence
of a local record. It must use the existing same-root authority fence/transfer
rules and reconcile the exact old boot and ingress state. If execution cannot
be fenced, leave the root in unknown state and do not issue a terminal ACK or
new model request.

## Implementation and verification gate

1. Add a closed request/receipt/status schema and additive durable columns or
   table for the terminal settlement. Preserve existing successful result
   receipts and all legacy SDK rows. No data deletion or status rewrite.
2. Under the existing task/root locks, prove settlement/result/close race
   ordering and idempotent lost-response readback. A committed result cannot
   later become cancellation or unknown; a settled call cannot commit a result.
3. Test pre-prompt failure, authenticated user cancellation before and after
   dispatch versus Adapter internal timeout/stop, task cancellation ordering,
   unknown provider response, lost settlement/close replies, old-process
   fencing, Adapter restart with missing journal, late MCP request and two
   users. Verify the stage call remains consumed; a nonterminal task's plan
   enters `needs_attention`, while a terminal task and its plan keep their
   prior values and the settlement stores the attention reason.
4. Integrate the fixed-source ACP path only after this contract, live proxy
   binding, network bypass prevention, dedicated-root budget measurement,
   exact terminal ACK and Product API qualification pass independently.

## Alternatives and rollback

- Retain `result` then `completed` close only: leaves every non-success
  post-admission path without a terminal ACK, so the ACP entry must stay 503.
- Treat process exit or cancellation as no dispatch: could misclassify a
  charged provider request or a late MCP call; rejected.
- Delete the admitted call/root and retry: loses idempotency and unknown
  outcome evidence; rejected.

Until this ADR is Accepted and implemented, keep `/acp-root/run` unconditional
503. The retained DSH `0.1.5rc1` SDK route, image and configuration remain the
exact judgment rollback path. This proposal does not authorize deployment,
default ACP promotion, PR merge or a paid provider request.
