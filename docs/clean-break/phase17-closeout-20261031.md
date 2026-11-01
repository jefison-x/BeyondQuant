# Phase 17 closeout reconciliation — 2026-10-31

The [2026-11-02 final Phase 17 acceptance](phase17-final-acceptance-20261102.md)
supersedes this checkpoint's pending phase verdict. The ordinary/recovery evidence,
original failures and preservation boundaries below remain unchanged.

This is a development and evidence closeout. It does not advance the Product
phase, authorize a formal release, or authorize another pre-release deployment.
Engineering uses Codex under the current maintainer instruction; OpenCode is
not required.

## Applicable evidence

| Gate | Existing result | Acceptance boundary |
| --- | --- | --- |
| Phases 11–16 | PASS and merged, as recorded in [STATUS](../roadmap/STATUS.md) | Existing Job, Artifact, approval, reset, schema and Golden evidence; not a new full-suite execution. |
| Phase 17 Golden mapping | Scoped local PASS; [original evidence](phase17-final-golden-acceptance.md) retained | Final phase documentation/acceptance remains open; old observer failures are not erased. |
| ACP continuation/recovery maintenance | PASS for the [2026-10-27 checkpoint](../evidence/dsh-acp-upgrade/CURRENT-QUALIFICATION.md); PR #413 merged | Retained-browser and exact-Root gates have their original scope; not universal crash recovery. |
| Maintenance PR CI / trusted release | PASS: runs [40686561816](https://github.com/jefison-x/BeyondQuant/actions/runs/40686561816) and [40689715700](https://github.com/jefison-x/BeyondQuant/actions/runs/40689715700) | Source `4724aa6e48dd76336acafc97959739b0e685a03c`; pre-release deployment/basic browser PASS, fault injection NOT_RUN. |
| Official DeepSeek search fix | PR #417 merged; PR CI [40780268134](https://github.com/jefison-x/BeyondQuant/actions/runs/40780268134) and trusted Full/image release [40783104095](https://github.com/jefison-x/BeyondQuant/actions/runs/40783104095) PASS | Source `0fc8fcb7260b7073451f76d46cf9f5a234f85392`, [ADR-0115](../architecture/adr/ADR-0115-official-ordinary-search-credential.md); ordinary first/subsequent search and reload persistence passed. |

The search-fix application updated only the three ACP roles to image digest
`6056e773d24b0ebb2345659496476d4345f07c64755426bf0a30c7cdd2eec8f5`.
The other 13 application containers, PostgreSQL, protected credential/profile
digests and mounts were preserved. The receipt is
`PRODUCTION-SEARCHFIX-RECEIPT.json`, SHA-256
`b2ede81da673b46c1c5dc4185a08fbf2837532e6bb232da79e1d2a765f1a0e52`,
under the existing maintenance worktree's
`.ci-artifacts/maintenance-release-20261029-searchfix/` directory.
The historical filename says "production"; the maintainer subsequently
clarified this is a pre-release operating environment, without a formal v1.0
tag or delivery.

The search browser evidence proves two successful ordinary turns and persisted
public search steps. Per-turn internal Root identities, model-call accounting
and terminal/cleanup receipts were NOT_PROVEN in that record. They are not
inferred from the successful answers or from the later idle-session readback.

## Maintainer clarification and exclusions

The later clarification in that directory's `RESULT.md` supersedes the earlier
PR summary's unresolved-item wording. Preserve the observed recovery mismatch
for `conversation_1bc1768d65af43afa9c612a64d841e1a`; it is not a blocker for the
completed search release and does not authorize compatibility work. The sample
was created after #413; its origin in a legacy architecture has not been
established. It cannot alone establish overall recovery failure or success.
The final phase gate must determine applicability using current-version
behavior and keep the original failure unchanged.

Do not repeat completed Full/release/search tests to improve historical labels.
Do not replay unknown business inputs, reset test identities, or delete retained
containers, volumes, data or browser pages.

## Current-version forward cursor correction

A new regression reproduces a defect independently of the excluded historical
conversation: complete and acknowledge a Root, release, recover and acknowledge
the recovery boundary, then release again without a new prompt. The second
release emitted a real `session.closed`, but the binding retained the previous
boundary's cursor and rejected the next recovery.

The correction advances the existing durable cursor when the boundary is
acknowledged and when the real release occurs. A later recovery requires that
exact durable tail and creates a new pending boundary. Pending-boundary
release, wrong event hashes, foreign boots and arbitrary higher tails remain
rejected. Original Root authority and settlement fields are preserved; no new
storage/schema, legacy event repair, prompt replay or native-child resume is
introduced.

The new regression failed on the original source. The corrected focused module
passed 15 Runtime tests and 12 Gateway tests, with independent regression checks,
and independent source review passed. Runtime source SHA-256:
`26d9382dccbae240cecba2a59f8048ac96a42aa187801a5f5c51da8be8b05398`;
test source SHA-256:
`b285ecf02f33590c185cdc3ce4ea223a67f8f3a09f92769c9c8266b775082550`.
Architecture tests passed 73 cases. Logs are retained under
`.ci-artifacts/phase17-closeout-20261031/`. The first test collection failure
was a missing repository root in `PYTHONPATH`, corrected before the real red
test. One intermediate implementation run had 11 PASS / 2 FAIL; its artifact
was overwritten and is not reconstructed or presented as retained evidence.

## Retained test environment after reboot

The maintainer chose a new ordinary current-release test instance while
preserving historical experiment containers and data. The old special A
Runner and Runtime are stopped with automatic restart disabled. The new A
Runner has separate sessions/state/control volumes; only the A slot is routed
to it. B/C/D slot configuration and mounts are retained; no test inputs were
submitted for those Workspaces. A's 35 prior registered AgentRuns were read
back as authority `closed` before testing and their complete row digests were
unchanged afterward. These are AgentRun rows, not the complete Root inventory.
The first live batch's separate `agent_runtime_turns` readback found 68 Roots,
all authority `closed`, including its new completed Root. Runtime
held/awaiting-ACK/awaiting-cleanup counts were zero before the test.

The local Runtime image uses the qualified search-fix release as its base and
copies only the corrected Runtime source. Running-source readback matches the
reviewed SHA. This is an isolated local image, not a new trusted release image
or a deployment to the `beyondquant` operating stack. The test page remains at
`http://127.0.0.1:32790/` using the original durable user identity.

### First live batch — retained FAIL

One new ordinary no-tools browser turn succeeded in conversation
`conversation_f3c32849e1ba48a9ab7e19348e232cfd`, Runtime session
`byq-session-ff13eb32a4ac4f40a8bc1a81fa2caee2`.
Root `4a7dd4fa0bf5471484cf8cb0351a4424` completed and received exact Backend
terminal ACK at sequence 7, event digest
`02bd45ef2fb67ace3f10e2bba98c663d94b45973c93b842c1747e2a0b36afe43`.
Normal idle release and the first reattachment returned HTTP 200, followed by
another normal release. Attempting the later user input exposed Gateway's
remaining old cursor equality check: `runtime recovery boundary changed`.
The sending batch stopped; its screenshot and native service logs are retained.
Runtime active-prompt and held/awaiting counts were zero. This first batch
remains FAIL; its successful first reply is not overall browser acceptance.

The Gateway binding validator and its append/ACK boundary handoff must use
the same cursor contract as Runtime. Their complete offline path must be
qualified before any further real input; no real model input is used to debug
one validation branch at a time.

## Final source and bounded live recovery

Ordinary replacement now captures its exact predecessor under the existing lock
and uses a hash CAS to write the new Root/generation/cwd before execution. The
previous ACK boundary is retired. Qualified and native-reuse paths retain their
strict native-close requirement; ordinary fresh-native retains its established
confirmed-process-exit fallback after a failed close RPC. No new store, schema,
compatibility path, prompt replay or native-child recovery is introduced.
Gateway's validator and append/ACK handoff use the same exact cursor contract;
when a new boundary replaces an ACKed one, it rereads the trusted Runtime binding
and checks unchanged scope, receipt and prior authority before appending.
Gateway source SHA: `717e03d9267f6fb3dba7f765a137f91937b25998498b88c58126c89eb4e40c78`.

After the Gateway correction, the second reply arrived but its terminal ACK
failed because ordinary prestart retained R1's boundary. This second live batch
also remains FAIL. Gateway was frozen; no further input was sent during diagnosis.
Root `177476df4de544f394584561e8395a70` was Backend completed/closed at terminal19,
digest `595cc3a8e9eca13d2b1ca79db619a5e6167994519f9448d4e8cc2e2c8ed87321`.
Independent design review admitted exact recovery of this ordinary v1 sample:
R1 and R2 shared boot `b78c5786a7ef7ac42fd7b8f2d4359aab` / epoch36 and domain0/0.
Complete original SHA `795ebb0e69a2ee72eda791748b32fa784b04a1be3e3b3fe2aa85ded8026998f3`
was backed up. A locked exact-byte CAS removed only the stale R1 boundary.
The original terminal-receipt operation then returned HTTP200 with the exact
R2 receipt and actually completed native cleanup. Runtime's resulting original
SHA `c16549cf8a4842a2cdf312110a4466581275c3da06daea2abf1922d4f41e4d7f` was separately
backed up; another locked CAS removed only that same stale field rewritten by
old in-memory code. No sequence, authority, Root, receipt or business value was
manually edited. Native-close/process-exit became true, cleanup uncertainty false
and held/awaiting slots0. The old Runtime was then stopped, PID0/restart=no.
Independent review verified both original hashes and both single-field changes.
This is a one-sample incident recovery; both earlier live FAILs remain unchanged.
The first helper invocation failed at import before any lock/write and is retained.

The final test stack uses qualified current Backend/MCP/Frontend/Runner images
plus reviewed local Runtime/Gateway source overlays. All old experiments and data
are retained. A worker inspection accidentally printed three test internal tokens
to tool output; no provider key or Git file was involved. These tokens were not
shared with the operating stack. They were rotated across current test API
consumers after an encrypted database backup. Credential/profile counts and full
row digests are unchanged. No operating-stack service was replaced.

One final explicit no-tools input in the same public conversation created Root
`b96e0add383a447db824faa426ae4497`, generation
`generation-e4b014f7414241df9400a86706a87726`, native session
`8b0baa61-7b66-4e7d-adc4-2a7fa9e28dbc`, boot
`470507ed6f4c5390f6cd262a74510b36` / epoch37. Final source naturally wrote the new
binding without the stale boundary. Gateway observed exact Backend ACK at26,
digest `b6ad5f929791b3129a2e8dda9ac7a8c3fd4da05f8358a3db46bcd8a81b1ae6df`.
Native close/process exit are true, cleanup uncertainty false, domain0/0 and
held/awaiting-ACK/awaiting-cleanup0. Final binding SHA:
`99e325a4a3f8691c6fb3f31a46766ce9012a0acba015049bbb90123f0b0e397d`.
The three public inputs do not establish exact provider-call or cost accounting.
No new Job/business tool input was made. The encrypted backup was not restored;
no restore qualification is claimed. Secrets remain outside Git. Scope is final
normal fresh-Root/terminal acceptance plus the separate bounded R2 recovery;
not universal recovery and not a relabeling of either original failed batch.

## Remaining phase gate

Phase 17 remains **OPEN**. This reconciliation corrects stale release and
old-conversation blocker descriptions; it does not replace the final
Tester → independent Reviewer → Root phase acceptance. Applicable current
contracts and retained Golden evidence must be reconciled before that decision.
Phase 18 remains **NOT_STARTED**.
