# Local background-result continuation qualification — 2026-10-09

**Overall: FAIL.** Preserve the completed real execution and repair native reuse before qualification. This is a local Gateway/Product API candidate, not hosted CI, release qualification or production acceptance. Product Phase is unchanged.

| Gate | Result | Evidence |
|---|---|---|
| Prior normal root, exact ACK and signed cleanup | PASS | Native bfee9e74-40ef-410a-b2e1-d74ce86bdd79; private preflight receipts |
| One real single-stock Signal Job, validated result | PASS | signaljob_05a050310e624ccc929274a79127e360 |
| Automatic completion dispatch and public answer | PASS | One reservation, one dispatch, one new root; five assistant messages in exact root interval 40–54 |
| Known budget and durable settlement hash | PASS | Five provider attempts, seven guard tool calls; no limit violations; Backend receipt hash independently recomputed |
| Exact Backend terminal ACK, closed root, zero unknown claims | PASS | Sequence 54 and exact event hash in manifest |
| Signed process cleanup, workers stopped, grant revoked | PASS | Read-only reconciliation; no additional model or Job execution |
| ADR-0103 same-native resume, new identity, no history reinjection | FAIL | Background native ed0cc020-f9c6-4516-9fcb-48bfad5f885f differs from previous native |
| Real browser automatic-answer view | PASS, render only | Current frontend, real Chromium at 1440/390px, exact task/Job answer visible, known settlement and revoked grant readback; zero model/Job writes |
| Public next-turn availability after internal idle release | FAIL | Browser screenshot and Product GET show false closed state from session.closed reason=released at sequence55; Gateway contract repair required |
| Cancellation, process-loss continuation, new interrupted child business | NOT_RUN | Normal completion proves none of these |

## Retained observer failures

The initial observer queried internal roots by public conversation ID and failed before grant, Job or model dispatch. Its correction completed the real Job and automatic reply but invoked `python` instead of the runner's `python3` during cleanup proof collection. The original FAIL record remains unchanged. Later read-only collection verified signed cleanup and exact terminal ACK and read the durable Backend budget receipt, without repeating paid execution.

A further read-only observer expected `request_usage` in a late Adapter response, but the response was `outcome_unknown`. The matching durable Backend receipt was already settled and its canonical hash verified; do not replay it or relabel its known result as unknown. The Adapter allows completed records to be reaped after Gateway idle release. The late in-memory response is not a durable settlement receipt. The evidence exporter also initially assumed one assistant message; inspection found five persisted outputs in this single root interval and corrected the count.

## Required repair

`RuntimeAdapter.submit_prompt` excludes budgeted turns from native reuse; completed-root cleanup also excludes budgeted generations from reuse readiness. Deleting the condition alone is unsafe because overlays and journals collide in the shared native working directory. Isolate each root's budget journals and rotate overlays only after exact ACK and proven old process exit, then verify normal → background → next ordinary/background reuse and refreshed MCP identity. This restores Accepted ADR-0103 without changing its decision. Default promotion stays closed.

Private receipts are retained at `/tmp/byq-adr0109-qual-20261009-c89ff732f2`; sanitized checks and hashes are in `manifest.json`.

## Browser follow-up

Real desktop/mobile read-only browser observation rendered the exact completed background answer with the expected authenticated user, no foreign requests, no unexpected writes, no page errors and closed browser processes. Scrolling was corrected to ensure the target answer actually intersects the viewport. Visual inspection then found the erroneous ended-session banner; the observer had checked rendering but had not checked continued-input availability. Preserve its scoped render PASS and classify the broader public continuation contract FAIL. No user ended this conversation. The Gateway currently treats the internal released event as public hard end; a bounded repair is in progress. Screenshots and original/corrected observer files remain private in the raw evidence directory.
