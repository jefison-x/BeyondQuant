# Upstream DSH requirement — out-of-process continuable subagent provider (ADR-0082 Option 1)

Status: **monitoring / qualification artifact — no DSH issue or PR is filed by this
repository slice, and no dependency is upgraded.** This document is the
human-reviewable upstream requirements package for the ADR-0082 Option 1 capability.
It is produced by the independent `v090-dsh-provider-qualification` monitoring slice.

- Blocker: `subagent-child-crash` (and, for BYQ, `subagent-byq-adapter-restart`)
- Owner node: `d15-4-child-provider-remediation` (pre-gate D15 candidate qualification)
- ADR: [ADR-0082](../../architecture/adr/ADR-0082-dsh-continuable-child-resume.md)
  (Accepted, modified: Option 1 chosen, Option 2 rejected; **not implemented**)
- Closeout context:
  [DSH-015RC1-CLOSEOUT-SLICES.md](../v090-closeout/DSH-015RC1-CLOSEOUT-SLICES.md)
- Examined releases and verdicts:
  [verdict.rc2.v1.json](verdict.rc2.v1.json), [verdict.alpha2.v1.json](verdict.alpha2.v1.json)
- Machine-readable contract:
  `scripts/d15/provider_qualification/contract.v1.json`

## 1. Why this requirement exists

ADR-0082 Option 1 says that generic child resume / independent child-crash recovery
belongs to **DSH**, not BYQ. BYQ will not build a second session store, a generic
agent harness, or a runtime-adapter child-resume bridge (Option 2 is rejected).

B1 `subagent-child-crash` is an **external blocker**: the composed DSH providers
that implement `SubagentProvider.prepareContinuable` are **in-process** (`spawn`,
`fork`), so a child shares the executor OS process and cannot be independently
SIGKILLed while its parent stays alive. The published out-of-process backends
(`acp`, `codex`, `claude-code`, `dsh-sdk`) do **not** implement
`prepareContinuable`, and both examined releases state that cross-process
continuation needs a **future durable mailbox + cross-process lease protocol**.

Presence of the out-of-process helper module (`out-of-process.d.ts`,
`subprocessRunHandle`, `NO_START_CAPABILITIES`, `settleRunResult`) is **not** the
capability: those helpers build a **one-shot** `SubagentRun`, not a continuable
child. A PASS must come from a real, registerable provider plus a real
end-to-end cross-process continuation observation.

## 2. Current state (monitored 2026-09-21)

| release | npm channel | Python pairing | out-of-process `prepareContinuable` | verdict |
| --- | --- | --- | --- | --- |
| `0.1.5-rc.2` | `next` | **none** (`deepseek-harness-sdk` stops at `0.1.5rc1`) | absent (`acp`/`codex`/`claude-code`/`dsh-sdk` all `UNSUPPORTED_CAPABILITY`) | **BLOCKED** |
| `0.1.6-alpha.2` | `alpha` | **none** (`deepseek-harness-sdk` stops at `0.1.5rc1`) | absent (same) | **BLOCKED** |

Both releases record the same declared limitations, quoting
`@deepseek-ai/dsh-subagent`'s README:

> **Process-local residency** — the Activation inbox and ownership graph do not
> coordinate two harness processes; concurrent access to one persistence store needs
> a durable mailbox and cross-process lease protocol.

> **No durable parent mailbox** — child-to-parent messages require a resident
> continuable child and live direct parent, and provide acceptance identity rather
> than exactly-once delivery.

> **ACP children remain one-shot** … remote providers need an Activation ownership
> contract before they can support continuable children.

**Minimal concrete gap:** DSH has no out-of-process provider that implements the
continuable contract, and no durable mailbox / cross-process lease protocol for the
continuable-child residency graph.

## 3. Minimal interface contract (upstream deliverable)

The smallest upstream surface that unblocks ADR-0082 Option 1. Names are
illustrative; the semantics are required.

### 3.1 Provider capability

```ts
interface SubagentProvider {
  readonly name: string
  readonly capabilities: SubagentCapabilities
  readonly inheritsParentContext: boolean
  // Existing one-shot entry point.
  start(request: ResolvedSubagentStartRequest): Promise<SubagentRun>

  /**
   * NEW / REQUIRED for an out-of-process continuable provider.
   * Must be implemented by a provider whose child runs in an independent OS
   * process. Must return a spec that the runtime can use to create or
   * cold-resume the child across process generations.
   */
  prepareContinuable?(request: ContinuableCreateRequest): Promise<ContinuableCreateSpec>
}
```

Requirements:

1. A real provider (`acp`/`dsh-sdk`/a new backend) MUST advertise and implement
   `prepareContinuable`, not merely export helpers.
2. The gate `SubagentRuntime.prepareContinuable(provider, …)` MUST succeed for
   that provider (today it returns `UNSUPPORTED_CAPABILITY`).
3. The child MUST run in its **own OS process**, addressable by a stable durable
   child id that survives the parent/provider process and is usable by a **new
   generation**.

### 3.2 Durable mailbox

```ts
interface DurableChildMailbox {
  /** Append a message addressed to a durable child id; returns a stable message id. */
  enqueue(childId: string, message: ContinuationMessage, idempotencyKey: string): Promise<MessageReceipt>
  /** Claim pending messages for a child with a lease; at-most-once delivery. */
  claim(childId: string, lease: LeaseRequest): Promise<ClaimedBatch>
  /** Settle a claimed batch exactly once. */
  settle(messageId: string, settlement: SettlementReceipt): Promise<void>
  /** Wake the owning generation for a child, if any. */
  wake(childId: string): Promise<void>
}
```

### 3.3 Single-active lease / epoch fencing

```ts
interface CrossProcessLease {
  /** Acquire or take over the exclusive active lease for a child. */
  acquire(childId: string, owner: GenerationIdentity): Promise<LeaseToken> // { epoch: number }
  /** Renew; fails closed when the epoch is stale. */
  renew(token: LeaseToken): Promise<LeaseToken>
  /** Release on clean shutdown. */
  release(token: LeaseToken): Promise<void>
}
```

Requirements:

- At most **one** active lease per durable child id at any time.
- Epoch is **monotonic**; a takeover increments it and fences every stale writer.
- A stale-epoch write/rebind/settle MUST fail closed, never be silently accepted.

### 3.4 Lifecycle and discovery

- A new generation MUST discover an existing durable child by the **same durable
  child id** without loading a second session store.
- Original **goal** and **delegation** lineage MUST be preserved across the
  generation transition.
- Authorization and tool filtering MUST be re-enforced from the durable
  descriptor, not inferred from a live in-process parent.
- Cleanup MUST leave **zero** orphan child processes/sessions.

## 4. Lifecycle & security invariants (must hold)

1. **Process independence** — the child has its own OS process id, distinct from
   the parent/provider process; killing the provider/parent process does not kill
   the child.
2. **Crash recovery** — after the parent/provider process is SIGKILLed, a wholly
   new generation can rediscover the same durable child and continue it.
3. **At-most-once settlement** — one accepted child turn settles exactly once
   (`settlement_count == 1`); duplicate settlement is a failure.
4. **Single-active lease** — never two concurrent active leases; concurrency is
   serialized by the lease, not by an in-process mutex.
5. **Epoch fencing** — lease takeover advances the epoch; stale-epoch operations
   fail closed.
6. **Durable mailbox** — messages are durable across the process boundary and are
   delivered/wake exactly once; a missing owner does not silently drop work.
7. **Lineage** — original goal and delegation call id are retained and verifiable.
8. **Authorization** — owner/principal checks and the delegation tool filter are
   enforced on every continuation, not only at first start.
9. **No orphan** — cleanup after loss/settlement leaves zero orphan process/session.
10. **Coherent release** — the npm release must have a matching Python SDK/runtime
    pairing before BYQ could adopt it (ADR-0081 §6 independent production decision).

## 5. Reproducible B1 / B2 scenarios

Both scenarios are currently **BLOCKED** and must be run against the future provider.

### B1 `subagent-child-crash`

1. Generation A delegates to an out-of-process continuable provider; record the
   durable child id and the child OS process id.
2. SIGKILL **only the child** process while the parent executor stays alive.
3. Assert the parent observes a truthful failed settlement (no fabricated success),
   retains the durable child id, and can natively resume the child or truthfully
   mark loss.
4. Assert exactly-once settlement and zero orphan process/session after cleanup.

### B2 `subagent-byq-adapter-restart`

1. Generation A (BYQ runtime-adapter OS process) reaches `startContinuable`,
   persists exactly one child linked to the delegation call and original goal.
2. SIGKILL the generation-A provider/adapter process; start generation B as a
   wholly new OS process sharing the same durable store.
3. Assert generation B discovers the **same durable child id**, takes over the
   lease (epoch advances), delivers a message and wakes the child.
4. Assert exactly-once settlement, preserved goal/delegation lineage, enforced
   authorization/tool filter, fenced stale epoch, and zero orphan.

The current probe's `capability-inventory.<version>.v1.json` records the real
native gate rejection for every published release; the qualification becomes
runnable the moment an out-of-process `prepareContinuable` provider is published.

## 6. Upstream acceptance checklist

A release may be treated as unblocking ADR-0082 Option 1 only when **all** of:

- [ ] An out-of-process provider registers and `SubagentRuntime.prepareContinuable`
      returns a spec (no `UNSUPPORTED_CAPABILITY`).
- [ ] B1 child-only SIGKILL: real child pid death, live parent, truthful failed
      settlement, retained child id, native resume or truthful loss, zero orphans.
- [ ] B2 provider/adapter SIGKILL + new generation: same durable child id found,
      lease takeover with monotonic epoch, message delivered and child woken.
- [ ] Durable mailbox API is public and documented.
- [ ] Single-active lease with stale-epoch fail-closed behavior is public and
      documented.
- [ ] At-most-once settlement is demonstrated (no duplicate settlement).
- [ ] Original goal and delegation lineage are preserved across the transition.
- [ ] Authorization and tool filtering are enforced on continuation.
- [ ] Orphan cleanup leaves zero process/session.
- [ ] A matching Python SDK / bundled runtime pairing is published (coherent
      pairing), and a separate production Go/No-Go decision is made — qualifying a
      provider is **not** a production default switch.

## 7. Non-actions of this slice

- No DSH fork or patch; no upstream issue or PR is filed.
- No BYQ provider, child-resume bridge, second session store or generic harness.
- No production selector/default upgrade; `dsh-0.1.2rc1` remains the default.
- No dependency upgrade, deployment, tag or release.
- No D15-G re-run, no R3 unfreeze (`R3_RESUME = NO`), no Phase 100 / `#338` work.
