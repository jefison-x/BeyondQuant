# Agent stream recovery validation

Date: 2026-08-28 (Asia/Shanghai)

## Incident and invariant

The affected conversation had no active runtime prompt, while its durable trace ended with an
error result and the frontend still retained a local in-progress state. The workflow SSE path was
also eligible for reverse-proxy buffering. The required invariant is now: a run failure is a public
terminal event, every earlier open activity is terminally projected, input is unlocked, and a retry
uses a fresh private runtime identity while retaining the stable BYQ conversation identity.

## Fix coverage

- Runtime Adapter emits `session.failed` for model-run errors and allows failed/interrupted sessions
  to resume in a fresh contained DSH session.
- Private resumed runtime IDs are normalized back to the stable BYQ session ID and never leak into
  public WorkflowTrace.
- Gateway and Nginx disable caching/buffering for the workflow SSE route.
- The frontend flushes a final SSE frame, reconnects from the last sequence, and independently
  reconciles durable replay while a local run is active.
- A terminal failure closes orphan progress rows, removes the thinking/stop state, renders a useful
  failure message, and resumes the runtime before a subsequent send.

## Verification

- Runtime Adapter tests: 43 passed.
- Gateway tests: 61 passed.
- Frontend unit tests: 38 files / 99 tests passed.
- Frontend TypeScript and production build: passed.
- Architecture tests: 42 passed.
- Mocked Chromium regression: 17 passed. The recovery journey verifies failure visibility, unlocked composer, ordered
  `resume -> turn`, and restored stop state after retry.

The browser uses only Gateway/Product API contracts and normalized WorkflowTrace projections.
