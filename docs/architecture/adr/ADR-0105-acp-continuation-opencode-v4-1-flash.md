# ADR-0105 — ACP F6 continuation on OpenCode Go / deepseek-v4.1-flash

- Status: **Accepted** (2026-10-06; maintainer: "接受ADR-0105当前草案的精确决定").
  Amendment to ADR-0090. The maintainer accepted exactly: F6 uses
  `opencode-go-chat` / `deepseek-v4.1-flash`, the OpenAI-compatible Chat
  protocol, upstream target `https://opencode.ai/zen/go/v1/chat/completions`,
  credential `OPENCODE_API_KEY`; the draft's per-call, cumulative, call-count
  and unknown-usage protections are kept; no other model or route is added.
- §5 revised: **Accepted** (2026-10-07; maintainer: "接受并授权"). The maintainer
  accepted exactly the Root's precise §5 revision
  (`/tmp/byq-adr0105-section5-revision-proposed.md`) that separates token-usage
  unknown from an unprovable business result, execution cleanup or limit
  enforcement; execution closure requires stopped execution, complete request
  and tool guard limit-enforcement evidence, reconciled business calls, and the
  exact Backend terminal ACK, while the closed receipt retains the unknown usage
  and is never called a complete cost settlement; any unprovable outbound
  result, business side effect, cleanup or limit enforcement keeps
  `outcome_unknown` and closes automatic-continuation eligibility. This revision
  is the normative rule; it supersedes the earlier §5 wording, which the
  maintainer replaced rather than merely declaring it erroneous. The same
  authorization covers one further real Gateway/Product API background
  acceptance.
- §5 success semantics clarified: **Accepted** (2026-10-07; maintainer "接受，继续").
  The maintainer accepted exactly the Root's `d1` clarification
  (`/tmp/byq-adr0105-execution-success-clarification-proposed.md`): the execution
  receipt's `completed` denotes only that the model turn completed normally
  (with this turn's normal-completion evidence, the exact Backend terminal ACK,
  all business calls reconciled, and execution-cleanup and limit-enforcement
  evidence); it does not denote ResearchTask/Job/research-plan completion and
  must not auto-complete the business task; any business-completion claim still
  requires the corresponding Job/Artifact/Backend audit facts. This is a precise
  clarification of one sentence; all other accepted §5 conditions are unchanged,
  and the unknown-business-result protection is not relaxed.
- Scope: the ordinary Product ACP resource group F6 background continuation
  (ADR-0090 / ADR-0103). Does not change the dedicated judgment path, does not
  authorize default promotion, and does not exempt budget or qualification
  gates.

## Problem

ADR-0090 fixes the continuation execution profile to `deepseek-official` /
`deepseek-v4-flash` in `packages/contracts/continuation_request.py`
(`ALLOWED_PROVIDER`, `ALLOWED_MODEL`, `_PROFILE`), and the ACP guard plugin
`plugins/dsh-byq/runtime/byq-continuation-budget.js` binds the same
provider/model and closed limits. The accepted contract therefore cannot run F6
on OpenCode Go / `deepseek-v4.1-flash`; changing only a display name does not
change the outbound request. The exact model id `deepseek-v4.1-flash` is
confirmed present in the live OpenCode Go catalog.

## Proposed change (exact fields)

1. **Provider/model.** `ALLOWED_PROVIDER = "opencode-go-chat"`,
   `ALLOWED_MODEL = "deepseek-v4.1-flash"` in the continuation profile. This is
   the OpenAI-compatible chat route at `https://opencode.ai/zen/go/v1`
   (`api: openai-completions`, request target `/chat/completions`), credential
   env `OPENCODE_API_KEY`. No other provider/model is added.
2. **Route/format.** The Adapter continuation proxy and route admission must
   accept exactly this route: `openai-completions`, `stream: true`, one choice,
   the exact selected model, and the `OPENCODE_API_KEY` bearer — matching the
   existing ADR-0097 route-admission rules for the OpenCode chat protocol
   (including SSE terminal/usage parsing).
3. **Guard/profile binding.** The guard plugin's `PROFILE_LIMITS` and the
   `executionProfile` binding update only `profile_id`/`profile_sha256` as
   needed for the new provider/model; the closed limits are unchanged unless a
   separate decision changes them. The guard remains tightening-only.
4. **Limits (values; amended 2026-10-07).** per-call: `max_input_bytes`
   262144, `max_output_tokens` 8192, `max_tool_payload_bytes` 131072;
   cumulative: `max_total_input_bytes` 4194304, `max_total_output_tokens`
   131072, `max_total_tool_payload_bytes` 1048576; count: `max_provider_calls`
   16, `max_attempts` 16, `max_tool_calls` 16, `max_concurrent` 1,
   `deadline_ms` 180000. Per-call, cumulative and count are enforced
   separately. **Amendment (maintainer-accepted 2026-10-07):** only
   `max_tool_payload_bytes` changed 65536 -> 131072 (128 KiB). The field bounds
   the per-request tool-related payload (tool catalog **and** tool messages), not
   only schemas. All other limits and the provider/model/route/auth/unknown/exact
   ACK rules are unchanged. ADR-0095 model visibility and call-time authorization
   are retained: no `tools/list` filter is added and visibility is not execution
   authority. New admissions use the new `profile_sha256`; existing reservations,
   receipts, unknown usage and #1-#5 evidence are not rewritten, zeroed or
   reinterpreted, and no compatibility replay layer is added.
5. **Usage / unknown / stop.** Usage is read from the provider response stream.
   Token usage that cannot be proven stays `unknown`: it is never recorded as 0,
   never replaced by the budget ceiling as actual consumption, and no request is
   resent to fill in usage. An already-dispatched request continues to count
   against the call count, and an unknown-usage record must not be deleted or
   reset.
   Token-usage unknown is recorded separately from an unprovable business
   result, execution cleanup, or limit enforcement. The execution receipt may be
   closed only when execution has stopped, the request and tool guard limit
   enforcement evidence is complete, every business call has been reconciled,
   and the exact Backend terminal ACK has been obtained; the closed receipt still
   retains the unknown usage and its incompleteness and is never called a
   complete cost settlement. The execution receipt's `completed` means only that
   this model turn completed normally: it requires this turn's normal-completion
   evidence, the exact Backend terminal ACK, all business calls reconciled, and
   execution-cleanup and limit-enforcement evidence. It does NOT mean the
   ResearchTask, Job, or research plan is complete, and it must not automatically
   complete the business task; any business-completion claim must be separately
   proven by the corresponding Job, Artifact, or Backend audit facts. A failed
   turn records `needs_attention`, and execution closure never advances the
   business by itself.
   If any of the outbound result, a business side effect, process cleanup, or
   limit enforcement cannot be proven, the request stays `outcome_unknown` and
   automatic-continuation eligibility is closed: no automatic replay, no release
   of the unresolved liability, and no fabricated terminal ACK. The exact-ACK and
   prior-root business-permission-isolation requirements are preserved.
   No automatic retry and no model switch; an unqualified or over-budget request
   is refused before dispatch.
6. **Budget accounting.** Every model request in the root — initial, tool
   follow-ups and any compaction/other model request — is charged against the
   same per-call/cumulative/count limits; the guard's tool journal and the
   request gate are the authoritative fences.
7. **Egress.** The single-route private proxy and its bypass protections
   (redirect denial, environment-proxy denial, exact path/model/credential)
   remain; only the selected route/credential change. The OpenCode credential is
   sent only to the OpenCode Go endpoint and never as `DEEPSEEK_API_KEY`.

## Compatibility and evidence

- Old `deepseek-official`/`deepseek-v4-flash` evidence is retained and labelled
  with its provider/model; it is not rewritten as V4.1 acceptance.
- Until accepted, isolated implementation drafts and free verification may
  proceed; formal qualification remains gated.
- This ADR is scoped only to the named OpenCode Go route and model; it does not
  create a general provider/model bypass.
