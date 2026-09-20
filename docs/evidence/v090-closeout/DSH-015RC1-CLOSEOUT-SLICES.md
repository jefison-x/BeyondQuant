# DSH 0.1.5-rc.1 closeout slices

Status: **plan only — nothing implemented.** Proposed ADR-0082/0083 stay Proposed;
the production selector/default remains `dsh-0.1.2rc1`; `R3_RESUME = NO`.

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

- **Implementation owner:** R6 Full Runtime Continuity Qualification, with an
  out-of-process continuable provider (ADR-0082 option 1) or the isolated
  runtime-adapter stack with a real DSH child process.
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

- **Implementation owner:** R6/composition hookup under Proposed ADR-0082 (option 1 or
  option 2). Requires an accepted ADR before implementation.
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

- **Implementation owner:** R4 TerminalAttachment under Proposed ADR-0083; first a
  candidate-specific, reversible evidence-only layer sufficient to re-run D15-G.
- **Reproduction (current `BLOCKED`):** an adapter abort kills the DSH runtime; native
  terminal sessions are process-local and the committed BYQ tree persists no
  `TerminalAttachment`, so a fresh adapter rejects the old attachment (real rejection
  evidence, no fabricated reattach). Evidence:
  [D15-5 verdict](../d15/d15-5/verdict.v1.json),
  [interface probe](../d15/d15-5/interface-probe.v1.json),
  [adapter-restart scenario](../d15/d15-5/scenarios/adapter-restart.v1.json).
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

- **Implementation owner:** R4 TerminalAttachment under Proposed ADR-0083.
- **Reproduction (current `BLOCKED`):** a restarted DSH runtime is a new process and
  native terminal sessions do not survive it; no BYQ reconnect surface exists, so the old
  attachment must be reported lost. Evidence:
  [D15-5 verdict](../d15/d15-5/verdict.v1.json),
  [dsh-runtime-restart scenario](../d15/d15-5/scenarios/dsh-runtime-restart.v1.json).
- **Acceptance criteria:** the BYQ attachment layer records the transition to
  `lost`/`interrupted` and never claims reattach when native state is gone; orphan
  detection reconciles a surviving PTY with no attachment as lost, never silently reused;
  terminal lifetime never defines conversation or durable-job lifetime.
- **Failure-closure criteria:** without an accepted ADR-0083 the item stays `BLOCKED`; a
  fabricated reattach must fail the observer and force a non-zero verdict.

## Minimal serial slices and gating order

| # | Slice | Depends on | Exit / stop condition |
|---|---|---|---|
| 1 | B1 `subagent-child-crash` | ADR-0082 decision + out-of-process provider/stack | Draft PR; blocker reaches real `PASS` or stays `BLOCKED` |
| 2 | B2 `subagent-byq-adapter-restart` | ADR-0082 decision + B1 provider boundary | Draft PR; real rebind `PASS` or `BLOCKED` |
| 3 | B3 `terminal-adapter-restart` | ADR-0083 decision + candidate-specific attachment layer | Draft PR; real rebind/loss `PASS` or `BLOCKED` |
| 4 | B4 `terminal-dsh-runtime-restart` | ADR-0083 + B3 layer | Draft PR; truthful loss `PASS` or `BLOCKED` |
| 5 | D15-G re-run | slots 1–4 | `GO` only if every required atomic capability derives `PASS` |
| 6 | R3 Thin Runtime Supervisor | slot 5 `GO` | Draft PR; no selector switch |
| 7 | R4 TerminalAttachment productization | slot 6 | Draft PR |
| 8 | R5 DurableJob independence | slot 7 | Draft PR |
| 9 | R6 Full Runtime Continuity Qualification | slot 8 | Draft PR |
| 10 | Independent Production Go/No-Go | slot 9 | **Maintainer decision only** |

Slices 1–4 are serial at the boundary level: B1/B2 share the ADR-0082 child boundary and
B3/B4 share the ADR-0083 attachment boundary, and each boundary plus its persistence must
be coherent before D15-G can be re-run. D15-G must **not** be re-run, and R3 must **not**
resume, while any of B1–B4 is non-`PASS`.

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
