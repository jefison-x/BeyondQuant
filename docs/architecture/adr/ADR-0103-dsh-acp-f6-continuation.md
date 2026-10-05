# ADR-0103 — F6 background continuation on the rc.2 ACP family

- Status: **Proposed** (2026-10-05). Requires maintainer acceptance before the
  ACP continuation path is enabled; removing the SDK-only
  `RuntimeAdapter.continuation_qualified` restriction without this contract is
  not acceptance.
- Scope: fixed official `dsh-v0.2.0-rc.2` (`639ed015397290b3745d163aafe02ffee4aa3f84`),
  ordinary Product ACP resource group (ADR-0100). Extends ADR-0090
  (continuation request limits) and reuses ADR-0096 (completed-root native
  session reuse) and ADR-0099 (isolated runner / provider egress) semantics.
  Does not change the dedicated judgment path or authorize default promotion.

## Problem

Today F6 background continuation is enabled only for the `0.1.5rc1` SDK pair:
`RuntimeAdapter.continuation_qualified` requires
`deepseek-harness-sdk == runtime-bin == 0.1.5rc1` and `family == 'dsh-0.1.5'`.
Under rc.2 ACP it always returns false, so a background Job completion cannot
advance the conversation. F6 is a **new root turn triggered by a background
result**, not a surviving atomic Agent, so it can use the ADR-0096 root-reuse
map: new root identity → resume the correct native root session → send only the
new input.

## Decision (proposed)

For a background Job completion that BYQ has authorized and admitted:

1. BYQ verifies the trusted task result, owner/workspace, continuation
   permission, and budget before any model dispatch.
2. The Adapter waits for the old root's exact Backend terminal ACK and cleanup
   proof (or the accepted same-root authority transfer) and never pre-empts an
   unsettled execution.
3. The continuation runs as a **new root** with a new root/generation/root MCP
   identity. It resumes the correct native root session per ADR-0096 and sends
   only the new continuation input; DSH owns context, and BYQ does not re-inject
   history that already exists natively.
4. Provider egress is bounded by the ADR-0090 request limits and routed through
   the ACP provider egress proxy (ADR-0099 semantics for ordinary roots): a
   per-invocation selected route/model/credential from trusted Backend
   admission, declared-output/input/deadline limits, redirect/方案 deny, and a
   lost-provider-response **unknown** stop. An unknown result is not retried and
   the original tool call is not replayed.
5. Event claim, submission, result and terminal are persisted durably;
   duplicate events and revoked permission do not start a second turn; an
   already-submitted or unknown request is reconciled by exact ID, never
   auto-replayed.
6. A restart may resume only after exact Backend reconciliation; an unknown
   outcome stays unknown until reconciled.

## Rejected

- Enabling F6 by only deleting the `0.1.5rc1` check.
- Treating a background continuation as an atomic/surviving Agent.
- SDK/ACP mixed execution or automatic fallback to the old SDK.

## Required evidence before enabling

- Keyless narrow verification: F6 event → new ACP root → native resume → only
  new input; duplicate event, revoked permission, insufficient budget, lost
  model call/receipt, restart, and unknown-result protection.
- ACP provider egress bounded and isolated; no direct static-URL bypass.
- Exact Backend terminal ACK for the background-triggered root.
- Independent Tester/Reviewer (ADR-0101) on the exact final head; exact-head CI;
  merge gate. F6 default promotion remains separately gated.

## Rollback

The SDK `0.1.5rc1` F6 path and images remain the offline rollback set; this ADR
does not authorize a mixed path.
