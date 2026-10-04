# Product DSH ACP candidate: current qualification ledger

Date: 2026-10-04. This ledger supersedes the implementation status in
`BASELINE.md` and `FALLBACK-QUALIFICATION.md`; those files preserve the initial
audit and historical probes. The fixed official DSH source remains
`dsh-v0.2.0-rc.2` at `639ed015397290b3745d163aafe02ffee4aa3f84`.
The isolated BYQ branch is `codex/dsh-acp-upgrade`, based on
`origin/main` `5619d6aee53a75ae1d461e7732efa922f89c6e4b`.

## Contract and implementation gates

| Gate | Result | Evidence and limit |
| --- | --- | --- |
| Source identity, isolated base, rollback identity | PASS | See `BASELINE.md`; the existing `0.1.5rc1` image and tracked configuration are retained. No live protected configuration was opened. |
| ADR-0093 same-root Backend authority transfer | PASS, contract | Maintainer accepted. Backend implementation and isolated tests are listed below. |
| ADR-0094 per-Agent MCP and Backend ingress proof | PASS, contract | Maintainer accepted on 2026-10-04. Candidate implementation exists; end-to-end qualification remains open. |
| Backend two-stage ingress, transfer/close fence, frozen terminal cursor | PASS, focused | Independent Tester used a fresh tmpfs PostgreSQL `byq_domain_test`, current Backend source mounted read-only, no host port. The first frozen slice gave 7/7; after adding exact abort/tombstone and outcome-bound cursor, a new isolated run gave 10/10. Containers and network were removed. Independent Reviewer accepted the root/request lock ordering. The first 7-test run had three fixture failures corrected before its PASS; the later 10-test run had environment mounting failures before pytest, then a successful run. |
| Gateway closed-before-Adapter-ACK recovery | PASS, focused | Eleven `test_runtime_recovery.py` and terminal business-root tests passed in the isolated Gateway test image with network disabled. Independent Reviewer accepted the code path at its internal service trust boundary. |
| Adapter ACP transport, secret separation and closed-before-ACK recovery | PASS, focused | The current seven ACP compatibility tests plus one exact recovery test passed together, 8/8 in the retained Adapter dependency image with current app/tests/packages mounted read-only, network disabled and read-only filesystem. The test proves settled reattach without ACP resume or prompt replay and that only the selected model credential enters the child. One existing `0.1.5rc1` private-domain-observation regression test also passed in that image. This does not prove a live ACP Product round. |
| Fixed official ACP keyless process behavior | PASS, limited | Earlier source build and tests, no-key ACP new/close smoke, and mock root/child signed MCP identity probe passed. The final BYQ image and Product flow are not thereby qualified. |
| MCP ingress settlement classification | PASS, focused | The blanket HTTP 4xx rule was removed. Independent Reviewer accepted the narrowed classifier: audited read-only callbacks, exact pre-dispatch 425, and exact Backend terminal 422 for four domain actions may settle; other errors remain unknown. Independent Tester copied the current MCP source/tests into an isolated temporary directory: TypeScript build and focused auth, bridge, ingress and write-outcome tests passed. The loopback ingress fixture required an approved local bind because the default sandbox denied it. These tests use synthetic Backend responses. |
| OpenCode provider route configuration | PASS, static only | The six existing `llm-pi-ai` provider routes were carried into the ACP profile and its composition digest updated and checked. Independent Reviewer matched every route field against the old candidate and the official rc.2 configuration schema. No ACP model request or credential test has run. |
| ACP continuation F6 budget and tool guard | FAIL, partial dynamic proof | Current `RuntimeAdapter.continuation_qualified` accepts only the pinned `0.1.5rc1` SDK/runtime pair, so ACP disables an existing Product continuation path. In a keyless fixed-source probe, root allowed read reached mock MCP with the exact reservation, and a child call after deadline was denied before MCP with the expected guard journal row. Direct forbidden-tool denial and provider proxy bounds are still being checked. |
| ADR-0085 research judgment catalog non-exposure | FAIL, fixed-source role probe | `/tmp/byq-acp-judgment-catalog-probe.mts` created the actual official `tool-subagent`/`spawn` judgment child with the configured five-tool allowlist and per-Agent Product MCP client. The child model catalog contained all 13 fixture tools, including strategy approval, backtest execution and ML training. The probe used `maxDepth: 1` solely to reach that child; the candidate profile has `maxDepth: 0`, which official DSH defines as forbidding delegation. No provider call was made. Proposed ADR-0095 records the decision boundary. |
| Observe-response loss reconciliation | PASS, focused; crash limit open | Backend's exact pre-dispatch abort and tombstone passed an independent 10-test isolated DB run, including both observe/abort orders, late observe rejection and idempotent receipt. Reviewer accepted the request/root lock ordering. Independent MCP snapshot build and bridge/ingress tests passed: a missing observe receipt triggers exact-ID abort before handler entry; wrong native Agent and malformed receipts are rejected. A simulated lost abort response was sent only once and remained unknown. MCP crash before abort or lost abort response still leaves a fail-closed pending/unknown record until exact reconciliation. No automatic expiry or speculative abort is allowed. |
| Complete matching ACP image | PASS, local build only | `byq-runtime-adapter-acp:qualification-20261004` built from the fixed official source/lock and current BYQ app/profile/plugin files. Image ID `sha256:f600f4eb348542b96d9e0c64243edc47ee37c8f8f509200c8099da9d658aa2ba`, size 1,430,951,403 bytes. Offline `--dump-config` in the image passed and exposed all six OpenCode route IDs plus the Product identity and judgment plugins; dump SHA-256 `6a5f7048289dc8adc1d40b7138fd92d7bb1ba14a32bb8c7312940b39117932e0`. The seven ACP compatibility tests passed in that exact image without network. A combined eighth recovery test could not collect there because its historical fixture imports the old `deepseek_harness` SDK, absent by design from the ACP image; the same eight tests passed in the retained dependency image with current code mounted read-only. This image is not a release artifact or Product acceptance. |
| Real Backend held-write race | PASS, focused Backend path | Independent Tester used a fresh tmpfs PostgreSQL and a temporary advisory-lock trigger to hold a real feedback insert. Close rejected pending ingress with 409; after the insert committed (201), exact settle (200) allowed close (200) with the frozen cursor. A response rewritten to 5xx after commit remained unknown and blocked close/transfer. In a separate rotated-boot fixture, transfer rejected pending ingress twice with 409; the held handler returned 503 after lock timeout, made no command row, stale boot settle returned 401, and ingress stayed pending. These direct Backend routes do not yet prove the full MCP→Backend→Adapter/Gateway chain or terminal ACK. |
| Full cross-service terminal ACK and next-root release | NOT_RUN | The Backend and MCP focused tests do not constitute an integrated Product run. |
| Consecutive rounds, stop/continue, end rejection, restart recovery, two-user isolation, identity switch, budget/unknown protection | NOT_RUN | Full BYQ Gateway/Product API acceptance has not run. |
| Real Gateway/Product API browser flow | NOT_RUN | Required because public behavior changes; mock-only tests do not close this gate. |
| Exact head CI, PR, merge, release images, promote, trusted deployment | NOT_RUN | Qualification gate has not passed. There has been no push, PR, merge or deployment. |

The earlier authorized OpenCode paid API call was for the old SDK route. No
new paid provider call has been made for this ACP candidate. No local, mock or
synthetic result in this ledger is production acceptance.

## Exact local candidate inputs

| Input | SHA-256 |
| --- | --- |
| ACP candidate Dockerfile | `d2d02bfdaa1167980d76a57d7583da40d354b76a4035ade8f4bcb43861bfb41c` |
| Adapter ACP Python lock | `53592f4ad247cff51dd7deff6f8ca1b6230257848a5b1917db2cab9e34d49f3e` |
| ACP Product profile | `8bd56a0d3120e10c74e0d51eb95adb392232f1535e0aabc61228a72f372a964d` |
| Profile identity JSON | `3c809e4d387d7fd2918ba7ba86b79518b4d88c25d458b4078e3bd0e68b06d7be` |
| Fixed release identity JSON | `e8af0d1cabf1cb85db9b57da85ba246e5c9691e77f9428664e6e36a3aea7ec67` |

The fixed Dockerfile checks official commit
`639ed015397290b3745d163aafe02ffee4aa3f84` and official
`pnpm-lock.yaml` SHA-256
`80fe05eae33582ae26839afd05f1965f9b0e4be11034ddf9797af6085d5ba9b1`
before building. The official isolated source checkout was clean at the exact
tag when rechecked. The candidate image has not been pushed or deployed.
