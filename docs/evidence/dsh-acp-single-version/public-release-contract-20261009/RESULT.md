# Public conversation versus runtime teardown — 2026-10-09

## Actual failure

The completed real background answer rendered in desktop/mobile Chromium, but a later Product GET exposed `conversation.status=closed` solely from private event sequence55, `session.closed` / `reason=released`. The mobile screenshot showed the ended-conversation banner. No user ended that conversation. The old R1 requirement/evidence had incorrectly classified idle resource release as conversation end.

## Accepted contract and bounded repair

ADR-0093 says ACP close alone does not close the BYQ conversation; ADR-0096 retains old-root exact terminal ACK/close/drain before the next root. The Gateway now projects public lifecycle from the owner-scoped catalog and exact-owned normalized hard cancellation. Active/archived history and SSE hide all session.closed events; release and Adapter shutdown are runtime lifecycle only. Wrong session/trace/raw-source hard-cancel events are filtered before they can cause the browser to end a conversation. A durable catalog close preserves exact-owned close events. No unknown result is replayed or inferred not to have happened. Backend currently stores active/archived; DELETE removes the conversation, whereas hard cancel remains a terminal event. This slice adds no storage migration or new durable closed state.

Implementation is limited to Gateway main.py and focused tests. Original R1 and 2026-10-08 projection evidence are retained with an explicit correction. This restores the accepted contract and does not change Product Phase.

## Gates

- Worker focused tests: PASS, 8 cases in existing offline Gateway candidate, source mounted read-only; no models/services.
- Independent Reviewer: PASS for Functional, Tests and Clean Break architecture after finding and fixing Adapter shutdown and unowned terminal-event gaps.
- Independent Tester: PASS, seven actual collected cases from the specified frozen node subset; the requested count eight was incorrect (parameter expansion totals seven). No extra test was added to inflate the count. Original intermediate results retained.
- Root: PASS bounded implementation after independent tests and review. Real Product/browser retest remains pending. Do not report the public-next-turn gate PASS until actual current-candidate revalidation.

## Current-candidate actual retest

Gateway candidate `sha256:a71262e4ea785d58a6fad89e07cbab1903f588079a6902395daaba1307b992fd` and Adapter candidate `sha256:935a71872e0ed2931f45ce011dcff1c147cc19b271e3641bd1488f5118930bd5` replaced only those two isolated test services after read-only checks proved zero open roots, unknown claims, unsettled continuations, live grants and active Signal Jobs. Both are healthy. Exact previous image/config pins remain protected. These are local derived candidates, not Release Images qualification.

Real Gateway/frontend Chromium at widths 1440 and 390: existing exact completed Job/task answer rendered; internal runtime close events hidden; erroneous ended banner absent; input present. Read-only browser scope PASS, no model calls/new Jobs/writes/foreign requests/page errors. This does not prove input succeeds.

A single next-input request was rejected with HTTP409 before a new model root was accepted; no automatic retry. Read-only stream recovery returned the same409, `runtime adapter evidence is unavailable`. Source investigation found Runtime release marks the persisted binding `closed`, then recovery rejects it as an ended BYQ session. The public-next-turn gate therefore remains **FAIL** pending a bounded Runtime teardown/closure distinction and actual requalification. Old binding/failure records are retained, not rewritten to manufacture recovery.
