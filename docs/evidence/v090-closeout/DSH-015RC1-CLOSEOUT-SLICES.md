# DSH 0.1.5-rc.1 closeout slices

> **Current gate-scope override (ADR-0084, Accepted 2026-09-21).** This file preserves the
> historical closeout order, observations and verdicts. B1/B2 remain `BLOCKED_EXTERNAL`, but
> are no longer global blockers for 0.9 closeout, candidate compatibility, bounded R3 failure
> containment or unrelated roadmap work. The next current slice is BYQ session failure
> containment and business recovery, followed by a new D15 superseding assessment. Do not
> rewrite the historical D15-G `NO_GO`, claim B1/B2 PASS, implement ADR-0082 Option 2, or infer
> production selector/deployment authorization. Current authority is ADR-0084 and the top table
> in `docs/roadmap/STATUS.md`; later “mandatory for 0.9” wording below is historical.

Status (audit-time snapshot, 2026-09-20): **plan only — nothing implemented.** At audit
time ADR-0082/0083 were Proposed; the production selector/default remains `dsh-0.1.2rc1`;
`R3_RESUME = NO`.

**Historical snapshot — not the current D15/slice state.** Current qualification state
(2026-09-21): ADR-0082/0083 are **Accepted** (without implementing production wiring); B3
`terminal-adapter-restart` is **PASS** at the candidate/qualification layer; B4
`terminal-dsh-runtime-restart` is **BLOCKED / not started**; B1/B2 remain **BLOCKED**;
D15-G is **not re-run and still `NO_GO`** (even if re-run it stays `NO_GO` while B1/B2/B4 are
not PASS). The current authority is `docs/roadmap/STATUS.md` and the `current_state_after_b3`
overlay in `acceptance-matrix.v1.json`; the committed `docs/evidence/d15/d15-5` and
`docs/evidence/d15/d15-g` verdicts are **not rewritten**.

Machine-readable form: [acceptance-matrix.v1.json](acceptance-matrix.v1.json)
`dsh_0_1_5_rc1_closeout_slices`.

## Ground truth

`D15-G` is an honest `NO_GO` derived by a fail-able observer. The verdict is decided
**only** by four atomic required capabilities that are `BLOCKED`
([capability matrix](../d15/d15-g/capability-matrix.v1.json),
[verdict](../d15/d15-g/verdict.v1.json)):

1. `subagent-child-crash`
2. `subagent-byq-adapter-restart`
3. `terminal-adapter-restart`
4. `terminal-dsh-runtime-restart`

`host-reboot-resume` is an **OPTIONAL limitation** (`NOT_RUN`) and never gates GO;
aggregates `subagent-resume` / `terminal-persistence` are display-only.

## The four atomic blockers (owner / reproduction / acceptance / failure-closure)

### B1 `subagent-child-crash` — independent out-of-process continuable child

- **Implementation owner:** D15 remediation / candidate-qualification slice D15-4 (evidence-only
  native harness, or the isolated runtime-adapter stack with a real DSH child process). **Not**
  post-GO R6. If 0.1.5-rc.1 has no independent-process continuable provider, B1 is an
  **external blocker**: an upstream out-of-process provider implementing `prepareContinuable`
  must land and be qualified first (or the maintainer chooses a gate-order adjustment below).
- **Owner node:** `d15-4-child-provider-remediation` (pre-gate).
- **External blocker:** `available_in_0_1_5_rc1 = false`. Until an independent-process
  provider is qualified, `subagent-child-crash` cannot PASS and D15-G stays `NO_GO`; this must
  not be hidden by assigning the blocker to a post-gate R-series phase.
- **Reproduction (current `BLOCKED`):** the composed native spawn provider runs children
  in-process, so a child-only SIGKILL while the parent executor stays alive is not
  reachable; the owning-process SIGKILL is explicitly not a substitute.
  Evidence: [verdict v2](../d15/d15-4/verdict.v2.json),
  [routing probe](../d15/d15-4/routing.v1.json),
  [child-crash scenario](../d15/d15-4/scenarios/child-crash.v2.json).
- **Acceptance criteria:** a real independently killable child exists and is SIGKILLed
  while the parent stays alive; the parent records a truthful failed settlement, keeps
  the durable child id and can natively resume or truthfully mark loss; measured
  exactly-once settlement and no orphan process/session after cleanup.
- **Failure-closure criteria:** without a qualifiable out-of-process provider the item
  stays `BLOCKED` and may not be deleted or downgraded; a `PASS` requires real child PID
  death and a real parent observation, never a reasoned result.

### B2 `subagent-byq-adapter-restart` — BYQ rebinds a persisted continuable child

- **Implementation owner:** D15 remediation / candidate-qualification slice D15-4 candidate
  composition hookup under ADR-0082 (candidate profile + BYQ child-resume/rebind surface).
  **Not** post-GO R6. Requires an accepted ADR-0082 option before implementation.
- **Owner node:** `d15-4-candidate-composition-hookup` (pre-gate).
- **Reproduction (current `BLOCKED`):** generation A returns a continuable child and
  persists it; a fresh adapter exposes only root `resume_session`; the 0.1.5 Python SDK
  is byte-identical to 0.1.2 and exposes no child operation; no committed BYQ surface
  rebinds the child. Evidence:
  [continuable verdict](../d15/d15-4/continuable/verdict.v1.json),
  [continuable adapter restart](../d15/d15-4/continuable/continuable-adapter-restart.v1.json),
  [byq-compose-adapter-restart](../d15/d15-4/continuable/scenarios/byq-compose-adapter-restart.v1.json).
- **Acceptance criteria:** after an adapter restart a fresh adapter rebinds the exact
  persisted child and delivers messages to it; exactly-once settlement, original-goal
  linkage, BYQ-owned child-id persistence, epoch/generation fencing and orphan cleanup
  are measured; no unrelated child is created and no second session store is introduced.
- **Failure-closure criteria:** without an accepted ADR-0082 option the item stays
  `BLOCKED`; a stale-epoch or wrong-owner rebind must fail closed and be recorded, never
  fabricated.

### B3 `terminal-adapter-restart` — BYQ TerminalAttachment survives an adapter restart

- **Implementation owner:** D15 remediation / candidate-qualification slice D15-5 candidate
  attachment layer under ADR-0083 (candidate-specific, reversible, evidence-only). R4 later
  productizes the surface; the blocker is **not** owned by post-GO R4.
- **Owner node:** `d15-5-candidate-attachment-layer` (pre-gate).
- **Reproduction (audit-time D15-5 snapshot `BLOCKED`; not rewritten):** an adapter abort kills the DSH runtime; native
  terminal sessions are process-local and the committed BYQ tree persists no
  `TerminalAttachment`, so a fresh adapter rejects the old attachment (real rejection
  evidence, no fabricated reattach). Evidence:
  [D15-5 verdict](../d15/d15-5/verdict.v1.json),
  [interface probe](../d15/d15-5/interface-probe.v1.json),
  [adapter-restart scenario](../d15/d15-5/scenarios/adapter-restart.v1.json).
- **Current state after B3 (2026-09-21): `PASS`** at the candidate/qualification layer — a durable
  BYQ `TerminalAttachment` minimal lifecycle is implemented and verified (fresh adapter rebinds the
  same attachment when native state survives; truthful `lost`/`interrupted` otherwise). Evidence:
  [B3 verdict](../v090-step5-b3-terminal-adapter-restart/verdict.v1.json) /
  [B3 README](../v090-step5-b3-terminal-adapter-restart/README.md).
- **Acceptance criteria:** a BYQ-owned durable attachment record (BYQ-minted id, owner
  principal, runtime generation, executor epoch) is persisted and authorized by BYQ; after
  an adapter restart the same attachment rebinds when native state survives, otherwise the
  status is truthfully `lost`/`interrupted`; foreign-session/unauthorized access is
  rejected; stale generation/epoch is fenced; cleanup leaves no orphan PTY; the browser
  reaches the surface only through Gateway/Product API.
- **Failure-closure criteria:** without an accepted ADR-0083 the item stays `BLOCKED`;
  any `reattached` result must bind a real attachment/session/pid or it must be
  `lost`/`interrupted`.

### B4 `terminal-dsh-runtime-restart` — truthful terminal loss across a DSH restart

- **Implementation owner:** D15 remediation / candidate-qualification slice D15-5 candidate
  attachment layer under ADR-0083 (candidate-specific, reversible, evidence-only). R4 later
  productizes the surface; the blocker is **not** owned by post-GO R4.
- **Owner node:** `d15-5-candidate-attachment-layer` (pre-gate).
- **Reproduction (audit-time D15-5 snapshot `BLOCKED`; not rewritten):** a restarted DSH runtime is a new process and
  native terminal sessions do not survive it; no BYQ reconnect surface exists, so the old
  attachment must be reported lost. Evidence:
  [D15-5 verdict](../d15/d15-5/verdict.v1.json),
  [dsh-runtime-restart scenario](../d15/d15-5/scenarios/dsh-runtime-restart.v1.json).
- **Current state after B3 (2026-09-21): `BLOCKED` / not started.** B4 is the next pre-gate
  slice in the G-split strict internal order and has **not** been started.
- **Acceptance criteria:** the BYQ attachment layer records the transition to
  `lost`/`interrupted` and never claims reattach when native state is gone; orphan
  detection reconciles a surviving PTY with no attachment as lost, never silently reused;
  terminal lifetime never defines conversation or durable-job lifetime.
- **Failure-closure criteria:** without an accepted ADR-0083 the item stays `BLOCKED`; a
  fabricated reattach must fail the observer and force a non-zero verdict.

## Minimal serial slices and gating order

| # | Slice | Owner node (pre-gate) | Depends on | Exit / stop condition |
|---|---|---|---|---|
| 1 | B1 `subagent-child-crash` | `d15-4-child-provider-remediation` | ADR-0082 decision; **external blocker** if no out-of-process provider | Draft PR; real `PASS` or stays `BLOCKED`/external |
| 2 | B2 `subagent-byq-adapter-restart` | `d15-4-candidate-composition-hookup` | ADR-0082 decision (+ B1 when option 1 is required) | Draft PR; real rebind `PASS` or `BLOCKED` |
| 3 | B3 `terminal-adapter-restart` | `d15-5-candidate-attachment-layer` | ADR-0083 decision | Draft PR; real rebind/loss `PASS` or `BLOCKED` |
| 4 | B4 `terminal-dsh-runtime-restart` | `d15-5-candidate-attachment-layer` | ADR-0083 decision + B3 layer | Draft PR; truthful loss `PASS` or `BLOCKED` |
| 5 | D15-G re-run | gate `d15-g-rerun` | owner nodes 1–4 | `GO` only if every required atomic capability derives `PASS` |
| 6 | R3 Thin Runtime Supervisor | `r3-thin-supervisor` | slot 5 `GO` | Draft PR; no selector switch |
| 7 | R4 TerminalAttachment productization | `r4-terminal-attachment` | slot 6 | Draft PR |
| 8 | R5 DurableJob independence | `r5-durable-job-independence` | slot 7 | Draft PR |
| 9 | R6 Full Runtime Continuity Qualification | `r6-full-runtime-continuity` | slot 8 | Draft PR |
| 10 | Independent Production Go/No-Go | `production-go-no-go` | slot 9 | **Maintainer decision only** |

## DAG and ownership rule

```
v090-audit
 ├── x09-full-interface-rebaseline
 ├── x09-composite-fault-regression
 ├── adr-0082-decision ──► d15-4-child-provider-remediation (external blocker)
 │                       └► d15-4-candidate-composition-hookup
 └── adr-0083-decision ──► d15-5-candidate-attachment-layer
                                   │
        {d15-4-child-provider-remediation, d15-4-candidate-composition-hookup,
         d15-5-candidate-attachment-layer} ──► d15-g-rerun (GATE)
                                                    └► r3-thin-supervisor
                                                        └► r4-terminal-attachment
                                                            └► r5-durable-job-independence
                                                                └► r6-full-runtime-continuity
                                                                    └► production-go-no-go
```

**Owner rule:** every D15-G atomic blocker owner must be a **pre-gate D15
candidate-qualification node**. Post-gate R-series nodes (`r3/r4/r5/r6`) may **not** own a
blocker. This removes the former `B1 → R6` and `B3/B4 → R4` cycles. The machine-readable DAG
is `acceptance-matrix.v1.json` `dag`, and `tests/test_v090_closeout_governance.py` asserts
acyclicity and owner-before-gate for every blocker.

Slices 1–4 are serial at the boundary level: B1/B2 share the ADR-0082 child boundary and
B3/B4 share the ADR-0083 attachment boundary, and each boundary plus its persistence must
be coherent before D15-G can be re-run. D15-G must **not** be re-run, and R3 must **not**
resume, while any of B1–B4 is non-`PASS`.

## Gate-order options (maintainer decision required)

> **Execution status (2026-09-21).** Slice 1 (B1 `subagent-child-crash`, owner
> `d15-4-child-provider-remediation`) was executed as the first and only step-5
> slice. Real read-only capability discovery against the actual `0.1.5-rc.1`
> candidate confirms no out-of-process `prepareContinuable` provider exists
> (evidence: [v090-d15-child-provider-remediation](../v090-d15-child-provider-remediation/README.md)).
> B1 therefore remains **BLOCKED / external**, and the gate-order decision below is
> now required before any further step-5 slice. No downstream slice, D15-G re-run or
> R3 work was started.

B1 (`subagent-child-crash`) is an **external blocker** in DSH 0.1.5-rc.1: no out-of-process
continuable provider exists. A strict serial order therefore cannot be both honest and
executable for that item. The maintainer must choose one of:
| Option | Meaning | Requires |
|---|---|---|
| `G-keep` | Keep the strict D15-G gate; D15-G stays `NO_GO` until an upstream provider exists | upstream out-of-process provider |
| `G-split` | Split the gate (e.g. runtime/session/subagent-adapter vs terminal, or required-atomic vs external-dependency) so B1 does not deadlock unrelated continuity | maintainer decision; ADR-0081/D15 contract revision |
| `G-reorder` | Qualify B2/B3/B4 first; schedule B1 after an upstream provider exists | maintainer decision |
| `G-reclassify` | Reclassify `child-crash` as an optional limitation | explicit maintainer Accepted ADR revision (not a silent downgrade) |

This audit did not choose an option; it recorded them. A strict serial order was claimed
**only** for the items that are internally ownable; an external blocker is named as such.

### Maintainer decision (2026-09-21): `G-split`

The maintainer chose **`G-split`** on 2026-09-21:

- **B1 `subagent-child-crash` remains a MANDATORY external blocker** for 0.9 / D15-G.
  It is **not** downgraded, **not** deleted and **not** made optional; `G-reclassify`
  is not chosen. The D15-G required-atomic condition is unchanged.
- **G-split** separates the external B1 from the independently executable **internal**
  pre-gate fixes, allowing the following **strict internal order**:
  **B2 `subagent-byq-adapter-restart` → `terminal-adapter-restart` →
  `terminal-dsh-runtime-restart`**.
- **D15-G stays `NO_GO` until B1 truly PASSes.** A B2/B3/B4 `PASS` does not turn D15-G
  into `GO` while B1 is `BLOCKED`; the gate re-runs only when every required atomic
  capability derives `PASS`.
- **`R3_RESUME = NO`**; D15/R3 stay frozen; **0.9 is not closed**.
- **Next sole task after this decision slice:** B2 `subagent-byq-adapter-restart`,
  owner node `d15-4-candidate-composition-hookup` (pre-gate; never post-GO R6). It is
  **not started** by this decision slice.

Machine-readable record: [gsplit-decision.v1.json](gsplit-decision.v1.json).

### Execution status (2026-09-21): B2 executed and BLOCKED (external/dependency)

The maintainer-authorized G-split internal order has begun. B2
`subagent-byq-adapter-restart` (owner `d15-4-candidate-composition-hookup`) was executed
as the **first internal item** and stays **BLOCKED**:

- A **real isolated composition/restart probe** in the committed candidate image
  (`byq-d15-4-continuable-candidate:local`, `--network none`, keyless scripted provider,
  real `RuntimeAdapter` + real bundled 0.1.5-rc.1 runtime + candidate continuable
  composition) showed generation A really reaches `startContinuable` and persists
  exactly one child linked to the original delegation/goal, but a genuinely fresh OS
  process/container has **no committed BYQ composition surface** to rebind, message or
  cold-resume that child (only root `resume_session`; the 0.1.5 Python SDK has no child
  operation; the composition itself forbids `subagent`/`send_message`/`list_agents`).
- **No Option-2 bridge, no second session store and no DSH fork/patch** were added; the
  fail-able observer verdict is `all_pass=false`, `external_blocked=true`, exit 1.
- Evidence: [v090-step5-b2-adapter-restart](../v090-step5-b2-adapter-restart/README.md).
- **Next sole task in the strict internal order:** `terminal-adapter-restart`
  (owner node `d15-5-candidate-attachment-layer`, pre-gate; never post-GO R4). It is
  **not started** by this B2 slice.
- D15-G stays `NO_GO` until B1 truly PASSes; `R3_RESUME = NO`; 0.9 is **not** closed.

### Execution status (2026-09-21): B3 executed and PASS (candidate/qualification layer)

The G-split strict internal order continued with B3 `terminal-adapter-restart`
(owner `d15-5-candidate-attachment-layer`, pre-gate):

- The candidate/qualification-layer **minimal BYQ `TerminalAttachment` lifecycle** was
  implemented and verified over the real native DSH 0.1.5-rc.1 persistent terminal
  (BYQ-minted durable attachment id, owner principal/authorization, runtime generation,
  executor epoch, state, audit linkage; DSH keeps PTY/shell/process/IO; no BYQ PTY runtime,
  no DSH fork/patch, no second harness/store, no persisted/faked PTY).
- A fresh adapter generation B reloads the same durable attachment and rebinds when native
  state survives, and deterministically reports `lost`/`interrupted` (rejecting a fake
  reattach) when it does not. The fail-able observer distinguishes a correct honest loss
  from a not-implemented/label-only PASS. Verdict `all_pass=true`, exit 0.
- Evidence: [v090-step5-b3-terminal-adapter-restart](../v090-step5-b3-terminal-adapter-restart/README.md).
- **Current state after B3:** `terminal-adapter-restart = PASS`; B4
  `terminal-dsh-runtime-restart` = **BLOCKED / not started**; B1/B2 remain **BLOCKED**;
  ADR-0083 implemented only at the candidate/qualification layer (R4/production wiring
  **NOT** implemented); D15-G **not re-run**, still `NO_GO`; `R3_RESUME = NO`; 0.9 is
  **not** closed.
- **Next sole task in the strict internal order:** `terminal-dsh-runtime-restart` (B4;
  owner `d15-5-candidate-attachment-layer`). It is **not started** by this B3 slice.

### Execution status (2026-09-21): B4 executed and PASS (candidate/qualification layer)

The G-split strict internal order was completed with B4 `terminal-dsh-runtime-restart`
(owner `d15-5-candidate-attachment-layer`, pre-gate):

- The B4 probe **reuses the committed B3 native runtime role** and the minimal
  `TerminalAttachment` store schema, and **truly terminates and restarts the DSH runtime
  OS process** (SIGKILL, then a genuinely fresh OS process as runtime generation B).
- A fresh adapter generation B reloads the same durable attachment, authorizes and
  generation/epoch-validates it, and truthfully records `lost`/`interrupted` — never a
  fabricated reattach. A **surviving PTY with no attachment** is reconciled as `lost` and
  **never silently reused or adopted**. Terminal lifetime does **not** define conversation
  or durable-job lifetime (both stay `active`). The fail-able observer (48 controls, 45
  defect-targeting) rejects fake reattach, label-only PASS, no-real-restart,
  terminal-driven conversation/job termination and orphan reuse. Verdict `all_pass=true`,
  exit 0.
- Evidence: [v090-step5-b4-terminal-dsh-runtime-restart](../v090-step5-b4-terminal-dsh-runtime-restart/README.md),
  with [current-overlay.v1.json](../v090-step5-b4-terminal-dsh-runtime-restart/current-overlay.v1.json)
  distinguishing the un-rewritten historical D15-5/D15-G committed snapshot from the B4
  current overlay.
- **Current state after B4:** `terminal-adapter-restart = PASS` and
  `terminal-dsh-runtime-restart = PASS` at the candidate/qualification layer; B1
  `subagent-child-crash` and B2 `subagent-byq-adapter-restart` remain **BLOCKED**; ADR-0083
  implemented only at the candidate/qualification layer (R4/production wiring **NOT**
  implemented); D15-G **not re-run**, still `NO_GO` (it must not be re-run while B1 is
  BLOCKED); `R3_RESUME = NO`; 0.9 is **not** closed.
- **G-split strict internal order (B2/B3/B4) is complete.** No further step-5 slice is
  authorized; D15-G awaits the upstream out-of-process continuable provider (ADR-0082
  Option 1) for B1.

## Dependency upgrade is not a production default switch

- "BYQ compatible with DSH 0.1.5-rc.1" and "production default = DSH 0.1.5-rc.1" are
  independent decisions (ADR-0081 §6).
- A `GO` at D15-G, and even R6 completion, do **not** imply a production cutover.
- Only the independent production Go/No-Go (slot 10) with an explicit maintainer decision
  may switch the default. Until then the selector stays `dsh-0.1.2rc1`.

## Sequencing tension to resolve in the ADRs

The terminal blockers (B3/B4) gate D15-G **before** R3, but productization of the
attachment layer is R4 **after** R3. The ADRs must therefore state that acceptance
authorizes a **candidate-specific, reversible evidence-only** attachment layer sufficient
to re-run D15-G, with R4 doing the production surface. See
[ADR-0082-0083-SUFFICIENCY.md](ADR-0082-0083-SUFFICIENCY.md).
