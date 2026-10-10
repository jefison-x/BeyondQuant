# Actual cancellation and new-child business continuation — 2026-10-09

Scope: local Gateway/Product API → fixed official DSH ACP rc.2 → own child MCP identity → Backend. This is local real-provider acceptance, not production acceptance. No DSH fork or new generic harness. Existing original Signal Job and idempotency key were reused read-only; no business execution replay or new Job.

| Gate | Result | Actual evidence and limits |
| --- | --- | --- |
| Stop current foreground child | PASS | One input and one soft cancellation; child read settled before cancellation. Old root f45256820c1f4d82826ec4a538e9fd70 cancelled/authority closed; exact ACK41 and runner-signed cleanup match. Adapter private binding remains publicly continuable (`closed=false`), process exit confirmed. |
| New explicit input after cancellation | PASS | One new input; new root 00bbcb5eaf7f46e291e4346f5e62fb44 completed with exact ACK56 and signed cleanup. New native root 59e1fe3f-d0e5-4502-aee4-f4a8432a79c4 and depth-1 child d38295fe-f422-4a3b-ad81-982c0951d94b differ from the canceled instances. |
| Child ownership / exact tool evidence | PASS | Seven ingress entries settled; child own authorize/read/audit and parent authorize/read/audit identities are separately registered and attributable. All calls are read-only; domain writes/execution calls 0. |
| Original business Job unchanged | PASS | Original Job completed, attempt_count=1, same idempotency key/input/result artifact and same-task-key row count=1 before and after both trials. |
| Context and no canceled-input replay | PASS | Fresh native fallback contains one new user source/input, zero canceled input, one completed-history marker and one occurrence of first completed input. This qualifies accepted fresh-native/completed-public-history fallback after cancellation, not same child-instance resume. |
| Provider budget | PASS, bounded | New root 11 admitted / 11 completed HTTP200, within cap16, no blocked request. Canceled root 7 admitted/completed, one unknown provider outcome/usage retained. Business unknown-claim count0 does not mean all provider charges are known. No retry of that unknown provider call. |
| Entire new root reads original object only once | FAIL | Child read once and parent read once: two separately authorized reads of the same object. Assistant claimed only one read. No business write, execution, or original canceled request was replayed. This strict trial condition failed and remains recorded; no paid replay to improve the record. |
| Desktop/mobile explanation of new child versus old instance | PASS | One normalized cancellation-history text change. Actual durable-user desktop/mobile Gateway browser shows new-child/non-restoration/non-replay distinction and exact new persisted reply; original Job still completed/attempt1. 82 GET requests, zero writes/foreign/page errors/model actions. See BROWSER.md. |
| Exact original child-instance resume after interruption | NOT_SUPPORTED / NOT_RUN | Accepted ADR-0102 promises new-child business continuation. Official original child-session restore is not established by this trial. |
| Lost execution process without trusted cleanup | PAUSED | Unaccepted ADR-0104 recovery remains outside implementation; ordinary successful cancellation must not be used to infer this case. |
| Default promotion / trusted-main release / deployment | NOT_RUN | Remaining single-version and release gates stay closed. |

Independent Tester and Reviewer inspected actual Backend/Adapter/runner/native/provider evidence and gave bounded core functional, test and architecture PASS. Root accepts only those listed core gates. Independent real-browser Tester and Reviewer passed the bounded UI distinction; Root accepts that gate. The strict one-read FAIL is not changed to PASS.

## Preserved failures and observer boundaries

The original observer query used a wrong schema field and failed before model execution. The first paid-trial observer stopped at an unattached public runtime status, with zero submissions; GET transcript does not attach. A reviewed read-only events GET then reattached the exact session before the one v2 submission. A source-hash fence stopped an earlier attempt before execution. The new-child read-only ACK collector initially omitted workspace payload and failed; corrected read-only collection did not submit another model input. Original private receipts and hashes are retained; no failed trial was overwritten.

Private full transcripts, credentials, provider headers and raw native histories are not exported. Committed receipts contain immutable object identities, hashes and selected read-only proof. All evidence is test-only. No Product Phase advance or production deployment.
