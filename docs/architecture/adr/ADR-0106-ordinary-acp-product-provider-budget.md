# ADR-0106 — Ordinary ACP Product provider request budget

- Status: **Accepted** (2026-10-07; maintainer: "接受"). The maintainer accepted exactly the
  `/tmp/opencode/adr-draft-ordinary-acp-provider-budget.md` design: a new independent closed profile
  `product-turn.v1`; 16 model requests/attempts; concurrency 1; deadline 180000 ms; per-call input 262144 B /
  output 8192 tokens / tool-payload 131072 B; cumulative 4194304 B / 131072 tokens / 1048576 B. The
  **tool-call count target 16 is a separate minimal proof** and HTTP counting must not be presented as tool
  counting. This ADR is the ordinary-budget design only; it does not accept the lost-runner Draft A, and the
  dedicated research-judgment implementation plan continues to follow ADR-0097/0098.
- Scope: the fixed official `dsh-v0.2.0-rc.2` (`639ed015397290b3745d163aafe02ffee4aa3f84`) ordinary Product
  ACP path (ADR-0100 resource group). It does not change the background-continuation profile (ADR-0105), the
  dedicated judgment path, the DSH version, or any default promotion.

## Problem
The ordinary ACP Product composition routes the DSH child's provider egress directly to
`https://opencode.ai/zen/go/v1` / `/zen/v1` (`plugins/dsh-byq/profiles/acp-0.2.0-rc.2/byq-product.patch.yml`
105-155) with no `retryPolicy`/`maxRetries`/`maxCalls`/`timeout`. The BYQ request gate/proxy
(`ResearchRequestGate`/`RequestGateProxy`, `services/runtime-adapter/app/research_request_gate.py`) is wired
only on the background-continuation path (`services/runtime-adapter/app/runtime.py:1029-1036`,
`if budget is not None`). So an ordinary ACP Product turn has no BYQ-enforced provider request budget. This
ADR adds an ordinary provider budget **policy** and routes the ordinary egress through the existing
gate/proxy. It changes only the ordinary Product provider egress; the ordinary tool/MCP path is unchanged.

## Decision
1. **Profile.** A new closed profile id `product-turn.v1` with an exact execution-profile binding
   (provider/model/route/limits), separate from `task-ready-read.v1`.
2. **Limits (normative).** per-call: `max_input_bytes` 262144, `max_output_tokens` 8192,
   `max_tool_payload_bytes` 131072; cumulative: `max_total_input_bytes` 4194304,
   `max_total_output_tokens` 131072, `max_total_tool_payload_bytes` 1048576; count: `max_provider_calls` 16,
   `max_attempts` 16, `max_tool_calls` 16, `max_concurrent` 1, `deadline_ms` 180000.
3. **Reuse.** Reuse the existing `ResearchRequestGate` / `RequestGateProxy`. No second generic harness; no
   DSH fork.
4. **Root identity.** Bind the gate instance to the exact current ordinary root
   (`root_run_id` / `runtime_boot_id` / `generation` / `session_id` / `trace_id`) — the same fields the
   continuation gate binds. A lost/unknown provider response stops further calls for that root. The
   background reservation and the continuation `ALLOWED_TOOL_NAMES` guard are **not** reused.
5. **Tool authority unchanged.** The ordinary path keeps its existing MCP tool authority (full role catalog).
   The gate bounds provider egress, not tool authority.
6. **Egress route.** The ordinary DSH child's provider `baseURL` is pointed at the gate/proxy (the same
   mechanism the continuation uses via `_continuation_proxy_advertise_host`).

## Model qualification (explicit)
- This ACP candidate qualifies **only** the OpenCode Go / `deepseek-v4.1-flash` route. On the ACP Product
  budget path, any other resolved provider/model is **rejected before any proxy or process start**
  (`ModelCredentialUnavailable`, `NOT_QUALIFIED`) — never an unbudgeted egress and never a silent switch.
- The ordinary SDK path and any not-enabled path keep their existing contract unchanged: this budget
  applies only where the ACP Product provider budget is enabled (`self._acp_product_slots`). Other
  provider/model routes must be disclosed as **NOT_QUALIFIED** before any default promotion.

## Tool-count boundary (explicit)
- The provider proxy proves only the **model HTTP budget**: provider calls/attempts, per-call and cumulative
  input/output bytes/tokens, and the declared tool-**payload** byte bound.
- It does **not** prove the ordinary **tool-call count** or tool permissions. The `max_tool_calls` 16 target
  requires a **separate minimal proof** (an ordinary-path tool-dispatch counter/fence, or a documented
  existing bound). Until that is proven, the ordinary budget is model-HTTP-only and must not be described as
  an enforced tool-count limit.

## Required evidence before real ordinary turns
- Free proof on the **actual ordinary path** that: the cap rejects before any upstream post (`posts=0`); an
  unknown provider outcome fails closed (no further calls, no replay); cleanup and exact root identity hold.
  The isolated test-only proxy run is engineering evidence, not the production default.
- Independent Tester/Reviewer on the exact diff.
- Real ordinary stop/continue/end and multi-turn (same model, same budget) run only after the executed-limit
  proof; each root requires its own exact terminal ACK + cleanup before the next; unknown results are never
  auto-replayed.

## Gates
No push/merge/deploy/tag, no default promotion, no Phase advance, no third context compression. Production
default unchanged until this ADR's implementation and evidence pass the merge/deploy gates.
