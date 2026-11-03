# ACP transport failure and explicit follow-up recovery — 2026-11-03

Scope: maintainer-authorized maintenance, based on fetched `origin/main`
`47a8643a053286b2bf4cff0e212b26dedff983c3`. No Product Phase advancement.
This task authorizes development and necessary verification, not a new push,
merge, image release or operating deployment. The existing page and environments
remain retained.

## Incident and limits

Conversation `conversation_37875f87f9384b06afa5a32b79ea703c` had two completed
roots followed by failed root `1f8f7c785c974e63a37a87984d00a84a` at
2026-11-03 12:38:28 UTC. Backend records the failed root as closed, terminal
sequence 25, with zero unknown claims. Its five public messages remain stored.
The exact native/provider/tool evidence remains on the retained volumes; a
redacted Engineering receipt is retained outside Git at
`~/.local/state/byq-maintenance/acp-conversation-failure-20261103/INCIDENT-RECEIPT.json`.

The native multi-frame session log records `DeepSeek Messages transport failed`
(`TRANSPORT`) before BYQ publishes `AcpTransportError`. Three admitted provider
requests have completed/forwarded HTTP 200 receipts; no fourth admission is
recorded. This does not prove the failing attempt reached the provider or that
DSH consumed every prior response successfully. The last runtime-context message
is an internal snapshot, not a replay of the user's question.

**Original transport trigger: UNRESOLVED.** The pinned official DSH version wraps
non-`LlmError` failures in `TRANSPORT`, retaining the underlying exception only
as a JavaScript cause. That cause and the Adapter exception message were not
persisted by the old path. Network failure, request preparation and secondary
ACP shutdown cannot be distinguished conclusively from the preserved records.
No DSH fork, persistence edit, lock deletion or automatic prompt retry was used.

## Minimal correction

- A failed, exactly acknowledged root may accept a later explicit instruction
  through a **fresh native session and fresh root** after the existing live
  identity, authority, receipt, process-exit, pending-terminal and domain-drain
  checks pass. Disk and memory native-close facts must agree. Native close RPC
  success is not required for this fresh-native fallback, matching the existing
  normal-completion fallback and settled cold-recovery boundary. Native reuse
  remains disabled. The failed input is never replayed.
- Missing cleanup/settlement proof remains blocked. Only the exact deterministic
  Runtime recovery conflict receives the Product code
  `agent_session_recovery_blocked`; unavailable evidence retains its 503.
  The browser preserves the unsent input, explains the need to check business
  state, and stops repeated resume/send attempts for that session.
- New ACP transport failures carry `runtime-transport-failed` and an allowlisted
  diagnostic reason. Raw exception strings, wire data and chained provider
  errors are never copied to the public trace. This improves classification and
  containment; it is not proof that the original transport trigger is fixed.

This uses the fresh-native boundary of Accepted ADR-0093/0096. It does not
broaden native recovery, replay an unknown operation, alter a historical receipt,
or weaken Backend terminal/unknown-claim checks.

## Verification boundary

- Local Runtime lifecycle/ACP compatibility/Product slot contracts: **PASS**,
  134 tests. They include reproduction of the old settled-failure refusal,
  fresh root/native identity, explicit-input-only execution, lost response retry,
  delayed old ACK, and six negative native-close, process-exit, cleanup,
  receipt and domain-drain cases.
- Local Gateway recovery/Product Agent contracts: **PASS**, 79 tests, including
  frozen terminal/unknown-claim protection, safe error mapping and unavailable
  recovery evidence.
- Frontend Agent view/WorkflowTrace tests: **PASS**, 46 tests; TypeScript/Vue
  checking and `git diff --check`: **PASS**.
- Independent Sol review: **PASS_SCOPED** for the recovery correction,
  diagnostics, safe Product errors and UI behavior; Clean Break architecture
  **PASS**. This does not close the original transport trigger.
- Candidate real Product/browser and real-provider acceptance: **NOT_RUN**.
  Browser inventory confirms the original page is still open; tab control
  returns `browser.user is unavailable`. No replacement browser/session harness
  or additional real model request was created.
- Hosted CI, push/PR, merge, image publication and deployment: **NOT_RUN**.

The original incident is not fully closed. A later controlled reproduction must
retain its first failure category and exact receipts before attributing or
claiming a fix for the underlying DSH/provider transport trigger.
