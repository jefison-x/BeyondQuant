# ADR-0102 — DSH ACP post-interruption business continuation (new child Agent)

- Status: **Accepted** (2026-10-05). The maintainer explicitly accepted option
  (a) for D1 as recorded below. This decides the interrupted-business
  continuation contract only; it is not "atomic Agent recovery" and does not
  change the DSH version or any other gate.
- Scope: BYQ DSH ACP special project, fixed official `dsh-v0.2.0-rc.2` at
  `639ed015397290b3745d163aafe02ffee4aa3f84`. Does not change the DSH version,
  does not fork DSH, does not modify official persistence, does not delete
  locks, does not reintroduce the old SDK, and does not authorize automatic
  version changes.

## Problem and official limit

After an interruption, BYQ cannot resume the original child (subagent)
instance on the pinned official version. `packages/acp/acp/lib/index.js:1216`
(`resumeSession`) refuses any persisted session whose
`origin === "subagent"` or whose `parentSession !== undefined`, returning
`invalidParams("session is not resumable: ...")`. Prior ACP reuse work
(ADR-0096) covers only a completed **root** native session.

Restoring the original child instance is therefore **not supported by the
pinned official version**. Fabricating it (fork, persistence edit, lock
deletion, or history replay) is prohibited.

## Decision

Interrupted business continuation uses: **restore the parent conversation
context → verify the existing business Job and its business-call outcome →
create a new child Agent to continue the work.** The original child instance
is not restored. The acceptance name is **"中断后业务接续（新子Agent）"**
(post-interruption business continuation via a new child Agent); it MUST NOT be
reported as "atomic Agent recovery PASS".

Required properties:

1. The old root's exact Backend terminal closure and cleanup proof must be
   obtained first, or handled under the already-Accepted same-root authority
   transfer contract; creating a new child Agent never bypasses this.
2. The original Job, its idempotency key and any persisted result are checked;
   an already-submitted task is never restarted.
3. An unknown business result stays `unknown` until reconciled by exact
   business ID; it is never treated as "did not happen" and the original tool
   call is never automatically replayed.
4. The new root and new child Agent use correct new identities; a late request
   from the old root still belongs to the old root.
5. Only necessary business state is supplied; the parent conversation's
   existing history is not replayed.
6. The user interface clearly distinguishes "business continuation" from
   "restoring the original Agent instance".

## Boundaries

- No DSH version change, no fork, no official-persistence mutation, no lock
  deletion, no old-SDK reintroduction, no automatic version switch.
- This ADR does not itself authorize push, PR, merge, release or deployment.
- The dedicated judgment path and F6 remain governed by their own Accepted
  ADRs; this ADR does not qualify them.

## Required evidence

- Keyless fixed-source verification that rc.2 refuses child resume (exact
  source line) and that the chosen continuation builds a **new** child Agent
  with new identities while the old root stays attributed to itself.
- Business proof: existing Job/idempotency/result reconciliation, no
  re-submission, unknown stays unknown.
- Exact Backend terminal ACK and cleanup proof for the old root before
  continuation.
- Independent Tester and Reviewer (ADR-0101 exception) on the exact final
  head, plus an explicit UI distinction between business continuation and
  original-instance restoration.

## Acceptance reference

Maintainer instruction in the DSH ACP single-version session, 2026-10-05:
"选择D1方案a，接受以下合同调整：中断后的业务接续采用"恢复父会话上下文→核对既有
Job及业务调用结果→新建子Agent继续处理"，不要求恢复原来的子Agent实例。……验收名称
改为"中断后业务接续（新子Agent）"，不得称为"原子Agent恢复PASS"。"
