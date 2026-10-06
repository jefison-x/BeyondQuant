# ADR-0105 — ACP F6 continuation on OpenCode Go / deepseek-v4.1-flash

- Status: **Proposed** (2026-10-06; awaiting maintainer decision). Draft
  amendment to ADR-0090. Not accepted; no behavior change until accepted.
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
4. **Limits (unchanged values, restated).** per-call: `max_input_bytes`
   262144, `max_output_tokens` 8192, `max_tool_payload_bytes` 65536;
   cumulative: `max_total_input_bytes` 4194304, `max_total_output_tokens`
   131072, `max_total_tool_payload_bytes` 1048576; count: `max_provider_calls`
   16, `max_attempts` 16, `max_tool_calls` 16, `max_concurrent` 1,
   `deadline_ms` 180000. Per-call, cumulative and count are enforced
   separately.
5. **Usage / unknown / stop.** Usage is read from the provider stream exactly as
   today; unknown usage stays unknown and blocks settlement as `outcome_unknown`
   (no estimate). No automatic retry and no model switch; an unqualified or
   over-budget request is refused before dispatch.
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
