# Phase 65 validation evidence

Date: 2026-08-29

## Architecture and contracts

- Accepted decision: `docs/architecture/adr/ADR-0040-plugin-center-deployment-control-plane.md`.
- Public contract: `docs/contracts/plugin-center-api.md` and the versioned Product OpenAPI paths under
  `/api/product/plugins`.
- Authority remains split between the Git registry qualification ceiling, durable PostgreSQL desired
  policy/request/audit, trusted immutable deployment output, and Runtime Adapter active readiness.
- Browser and Product services have no npm, Git, Docker, shell, source-write, arbitrary package or running
  DSH mutation capability. A `202` request is never projected as active.
- Every policy request stores its own immutable `plugin-deployment-policy.v1` snapshot, so a later concurrent
  policy request cannot silently retarget an earlier deployment.

## DSH baseline and registry result

The DSH baseline was **not upgraded**:

- Python SDK: `deepseek-harness-sdk==0.1.1rc1`
- runtime-bin: `deepseek-harness-runtime-bin==0.1.1rc1`
- npm runtime closure: `0.1.1-rc.1`
- upstream latest observed by the registry on 2026-08-28: `0.1.2-alpha.1` (observation only)

| Plugin | Exact upstream package version | Registry state | Default policy | Risk | Allowed Agent ceiling | Reason |
| --- | --- | --- | --- | --- | --- | --- |
| Web Search | `@deepseek-ai/dsh-tool-web@0.1.1-rc.1` closure | QUALIFIED | enabled | MEDIUM | `market_researcher`, constrained root orchestrator seam | Search-only rc.1 is qualified; fetch remains disabled and evidence is research-only. |
| Guard | repeat reminder + timeout policy `0.1.1-rc.1` | QUALIFIED | enabled | LOW | all registered Product research roles | Adds bounded advisory/timeout behavior without authority or tools. |
| Compaction | official compaction closure `0.1.1-rc.1` | QUALIFIED | enabled | LOW | all registered Product research roles | Context maintenance only; never substitutes for a BYQ Artifact or domain state. |
| Spill | official spill closure `0.1.1-rc.1` | BLOCKED | disabled | HIGH | none | rc.1 lacks acceptable session/age cleanup and exposes filesystem locators. |
| Interaction | ask-user/user-questions `0.1.1-rc.1` | BLOCKED | disabled | MEDIUM | root ceiling only | Current SDK/JSON-RPC transport has no qualified Product question/answer lifecycle. |

## Real controlled deployment journey

The isolated `byq-phase65-review` stack completed this non-mocked flow:

1. A durable admin browser session loaded Overview, Catalog and Detail through same-origin Product API.
2. A qualification request was queued and survived a Backend restart.
3. A disable-Web-Search policy request was persisted as
   `plugin_request_7d5b9b601a49490c84bf3f3ea05026c9`, policy version 2.
4. The trusted lane read the exact request snapshot and generated `managed-v2` with Guard + Compaction.
5. The deterministic composition identity was
   `sha256:46a438f452a25fc8ee52924b50028da56fdd489d3dc5a178ba252d1516b9875d`.
6. A new immutable Runtime Adapter image was built and restarted through the normal Compose lifecycle.
7. Runtime readiness reported the same profile, hash and plugin IDs; a keyless session initialized and released
   cleanly before the request transitioned to `active`/`completed`.
8. The UI then showed desired and active identity as consistent. An ordinary durable user received HTTP 403.

This exercise changed only the isolated review stack. The Git registry's default research profile remains the
deployment source for a fresh normal build.

## Automated and browser validation

- Architecture: 46 tests passed; online install/extensions/shell/terminal/source write/direct control/MCP bypass
  and unqualified capability paths remain rejected.
- Backend: full clean-PostgreSQL suite passed, including durable admin policy, audit, qualification, exact-version,
  idempotency, optimistic concurrency and immutable request-snapshot coverage.
- Gateway: 70 tests passed; Plugin Center projection reports credential state only when a real credential is
  configured and marks active only from matching Runtime readiness.
- Runtime Adapter: Node runtime contracts and Python suite passed; real keyless initialize/release and restart
  persistence smoke passed.
- Frontend: locked install, production build, dependency audit, 41 files / 111 tests, 17 mocked browser E2E and
  3 real Product API browser tests passed.
- Existing MCP contracts and the Phase 48 no-mock two-user Product coherence journey passed.
- Chrome MCP: desktop and 390x844 mobile reviewed; both Lighthouse Accessibility and Best Practices scored 100.
  Console had no messages. Network traffic contained only the frontend origin and `/api/*` Product routes, with no
  direct Backend, Runtime Adapter, DSH or MCP request.
- `git diff --check`: passed.

## Browser artifacts

- `plugin-center-desktop.png`
- `plugin-center-mobile.png`
- `lighthouse-desktop/report.json` and `report.html`
- `lighthouse-mobile/report.json` and `report.html`
- `community-classification.md`

## Known limitations

- Qualification execution and deployment remain trusted CI/operator workflows; Phase 65 queues and audits requests
  but deliberately does not turn Product services into a deployment engine.
- Spill and Interaction remain blocked until a future full DSH Upgrade Lane proves the missing lifecycle/security
  semantics. Observation of a newer upstream release does not authorize an upgrade.
- No Marketplace, arbitrary package onboarding, hot install, rollback button, or public Plugin Center exists.
