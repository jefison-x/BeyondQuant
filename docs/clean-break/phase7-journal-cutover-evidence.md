# Phase 7 Adapter journal cutover evidence (2026-09-28)

## Accepted boundary

The maintainer explicitly accepted removal of Adapter persistence safeguards and
abandonment of Adapter cross-process recovery. A new Adapter boot has a new
identity and new private DSH sessions. Old Product roots and AgentRuns lose
business-call authority when Backend observes that boot. In-flight external
effects with unconfirmed results remain `outcome_unknown`; they are not replayed.
This slice does not delete any existing database, account, volume, or backup.

## Change

- Removed the live Adapter `LifecycleJournal`, stale executor lease and disk
  recovery paths, plus `/recover-evidence`. Removed the inert containment
  endpoint.
- Kept exact terminal and domain receipt reconciliation within one Adapter boot.
  A bounded 512-entry memory tombstone allows an exact ACK response-loss retry
  after a released private session is reaped. A missing receipt stays unknown.
- Gateway public status requires a live in-memory session binding and verified
  Adapter/Backend boot. A prior bound boot shows interrupted after rotation;
  absent or unverifiable authority shows unknown.
- Selected build `.237` pins the modified Adapter image and DSH 0.1.5rc1.
  Frozen `.236` remains unchanged.

## Verification

- Adapter suite: 241 passed, 50 skipped. Gateway suite: 285 passed.
- Architecture suite: 198 passed. Build/retirement unittest: 12 passed.
  `dev-check.py --base 1d71bdb0`, `git diff --check`, and selected build
  revision check passed.
- Disposable Compose project `byq-p7-root-f07cb6db72`: Gateway-only restart
  retained the active root and AgentRun, rejected a competing prompt with 409,
  and made no new provider call. Adapter PID-1 kill rotated the boot, revoked
  old root and AgentRun authority, and showed interrupted to Product API.
- Disposable Compose project `byq-p7-unknown-e64f4525c6`: four Product MCP
  calls executed once. An external-action claim remained `executing` with
  `outcome_unknown=true`, `retryable=false`, zero artifacts and zero replay
  after Adapter loss and boot rotation.
- Disposable Compose project `byq-p7-term-b523654350`: test proxy dropped
  the first Backend close response. Backend closed the exact root and AgentRun;
  Adapter blocked a new same-session prompt with 409. Gateway retried the
  identical close after release and received the same receipt. Backend saw
  two forwarded close requests and the provider made two requests total,
  with no duplicate model call. The current probe checks these observable
  contracts; it does not claim to inspect a removed journal or private ACK
  state.

All three named Compose projects used isolated databases and project-scoped
resources. Their containers, volumes, networks, temporary credentials and
project images were removed. Existing Product DB volume
`byq-postgres-clean-20260904` and final logical backup at
`/home/jefison/backups/byq-clean-break-final-20260927T234310Z/byq-domain.dump`
were not changed.

## Scope of acceptance

This evidence qualifies the journal-removal and same-boot authority slice.
Adapter cross-process session recovery is deliberately unsupported. It does
not establish Phase 7 overall completion or authorize Phase 8. The image still
contains disconnected `app/containment.py` and `app/executor_identity.py`;
historical operator/qualification scripts and unused settlement persistence
helpers still refer to old disk mechanisms. They require a separate Phase 7
deletion review before the overall gate can pass.
