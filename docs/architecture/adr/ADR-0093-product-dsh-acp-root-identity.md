# ADR-0093 — Product DSH ACP root identity and recovery

- Status: Proposed; maintainer acceptance required before ACP Runtime Adapter implementation or promotion.
- Date: 2026-10-04
- Scope: the standalone Product DSH ACP upgrade, not a Product Phase change.
- Candidate: official `dsh-v0.2.0-rc.2` at `639ed015397290b3745d163aafe02ffee4aa3f84`; no floating tag.

## Decision needed

The current Adapter starts a separate DSH process for each root turn. Its MCP client headers include an exact `BYQ_ROOT_RUN_ID` and runtime boot identity. A new turn gets a new process and new headers; Backend closes the previous root and returns an exact terminal acknowledgement before another turn is admitted. Completed public messages can then be supplied to the fresh DSH root as ordinary input.

The candidate ACP implementation accepts MCP servers and their HTTP headers at `session/new` or `session/resume`. `session/prompt` has no supported per-prompt MCP header update. Reusing one native ACP session across BYQ root turns would therefore send later tool calls under the previous root identity. It could also duplicate context if BYQ appended completed public history to a session with native history. This is an authorization failure, not a transport detail.

## Proposed mapping

| Identity or lifecycle | Proposed ownership and rule |
| --- | --- |
| Product conversation ID | Stable user-visible Gateway/Product API identity, scoped to owner and Workspace. Never expose native ACP IDs. |
| BYQ Runtime Adapter session ID | Gateway's private `byq-session-*` binding for that conversation; stable across healthy root turns, distinct from Product conversation and ACP IDs. |
| Root run ID | New BYQ authority identity for each admitted input. Backend exact terminal ACK and domain-call evidence drain gate the next input. |
| Native ACP session ID | Fresh DSH-owned ID for each root run, mapped only to that run. Do not append a new root prompt to an earlier native session. |
| Working directory | Dedicated contained directory for that native session; persist the canonical path only if same-root restart reattachment is accepted and qualified. |
| MCP headers | Mount the exact root identity at native `session/new`; on same-root `session/resume`, remount it only after an accepted Backend authority-transfer contract has proved the new boot owns that root. Never rebind an old native session to a new root. |

The Adapter remains a thin ACP transport and event translator. It must not add a generic Agent session manager, replay queue or private history store. For each fresh root it may provide only the bounded, completed public conversation rows already authorized by the current Clean Break contract. It must not provide those rows again on native resume. Native logs remain DSH-owned. The Backend domain records, not ACP events, decide whether a business command happened.

## Lifecycle proposal

1. **New reply:** acquire the BYQ session and Backend root admission, wait for the prior exact terminal ACK and domain evidence drain, create a fresh native ACP session with new root-scoped MCP headers, then send one prompt. Preserve current Product API IDs and normalized events.
2. **Stop current reply:** request ACP cancellation for the active prompt; continue to fence the exact old root and settle its known or unknown business outcome. A late tool request remains bound to the old root and must be rejected after its authority closes. The user may give a new input only after the old root's terminal acknowledgement. No cancelled prompt is replayed.
3. **End session:** close the active native ACP session and persist BYQ's closed state so later Product inputs are rejected. ACP close leaves its native session resumable; it does not end a BYQ session or close Backend authority by itself. Exact terminal ACK remains required.
4. **Process restart:** do not automatically resend an interrupted prompt. Official ACP resume restores the native log without replaying the prompt and accepts a fresh MCP declaration for the same canonical working directory. However, current BYQ Backend revokes active root authority when the Adapter boot identity changes and records `authority_revoked_unconfirmed`. A new boot cannot simply reuse the old root or obtain its exact terminal ACK. Consequently, native ACP resume is **not yet an authorized Product recovery path**, even if the native session can be reopened. Block tool-enabled continuation and new input until the Backend root's business outcome and authority are reconciled. A completed, acknowledged root needs no native continuation; the next reply creates a fresh native session.

## Acceptance questions

The per-root ACP mapping fits current Clean Break ADR-002. Maintainer acceptance is needed for **cross-process Product recovery** and any durable minimal root-to-native binding. ADR-002 makes reattachment optional and forbids a BYQ recovery coordinator. Current Backend rejects the direct mapping: it revokes the old root on Adapter boot rotation, does not let the new boot re-register it, and requires an exact terminal receipt before closure. A decision must therefore choose one of these explicit paths:

1. Accept restart loss for the interrupted Agent root. Preserve the public conversation and BYQ Jobs/Artifacts, reconcile unknown business results, and admit a fresh root only through a newly defined exact Backend closure path. This narrows the requested restart-resume acceptance and requires the maintainer to change that requirement.
2. Add a narrowly scoped, accepted Backend authority-transfer contract for the **same** root. It must atomically fence the old boot, prove old execution cannot issue new calls, preserve unknown business outcomes and call receipts, authorize the new boot only after those checks, then permit ACP `session/resume` with the same native ID, canonical cwd and root-scoped MCP identity. No prompt replay and no inferred business success are allowed. This changes the root authorization contract and needs its own tests and ADR acceptance before implementation.

The current proposal does not choose or implement either path. Native DSH repair marks unfinished tool results unknown; BYQ must still reconcile exact business IDs and obtain its own authority proof. Qualification must verify ACP resume, MCP remount and close behavior against the fixed candidate. If a safe Backend transfer cannot be proven, report restart loss truthfully; do not add a speculative compatibility layer.

No existing native `0.1.5rc1` session files are migrated. A cutover must drain or explicitly interrupt current roots with exact Backend acknowledgement; existing public BYQ history remains governed by its completed-row contract. Preserve the old image, tracked composition and protected deploy-time configuration as an exact rollback set. Rollback cannot reinterpret an ACP-native session as a Python SDK session.

## Required qualification before promotion

From the fixed official source build, verify multi-turn public behavior, stop and next input, end and refusal, idle and interrupted restart, two-user isolation, per-root MCP identity, late calls, exact terminal ACK, normalized tool/event evidence, credential isolation, budget enforcement, connection loss and process cleanup. Test the actual Gateway/Product API browser flow if user-visible behavior changes. Record PASS, FAIL and NOT_RUN separately. Tester, independent Reviewer and Root must inspect the exact change. A failed or unverified gate blocks push/PR promotion, auto-merge and deployment under this proposal.

## Alternatives rejected for this candidate

- Reusing one native ACP session with unchanged MCP headers across roots: violates root-scoped business authority.
- Injecting hidden per-prompt ACP parameters or editing DSH to mutate MCP clients: unsupported by the pinned official interface and conflicts with the no-fork boundary.
- Appending BYQ public history to native resume or replaying an interrupted input: risks duplicate context, calls and financial outcomes.

This proposal records a design and a stop boundary; it grants no implementation, merge or deployment authority by itself.
