# Harness / compound-research continuation audit — 2026-09-22

## Scope

- Baseline: `origin/main` at `e2b440b18d04a82f857a6d67a4d13a540db5460a`
- Deployed DSH selector: `0.1.5-rc.1`
- Incident: one Product conversation attempting a three-round momentum/dual-MA/Kelly backtest research task
- Method: read-only inspection of persisted Product/Research state, Runtime Adapter lifecycle/budget evidence, DSH v3 JSONL session events, and current Backend/Gateway/MCP/Adapter contracts
- Raw DSH session files are not committed because they contain private conversation/tool payloads. This record contains only bounded operational facts and aggregates.

## Executive finding

The failure is architectural orchestration debt, not a transient provider failure and not primarily a context-window shortage.

BYQ persists business objects safely, but it does not persist a machine-executable next action for a compound research task. Data-ready and approval continuations launch broad natural-language DSH turns and expect the model to rediscover the exact object, original idempotency key and action order. Three separate mechanisms—approval continuation, task/data-ready continuation and normal user turns—can each start a general model loop without sharing one authoritative plan state.

The incident exhausted its eight-call guard before executing round-one backtest. Raising the guard or revising the prompt would preserve the same failure mode.

## Incident facts

The durable research task remained `running`, version 4, stage `backtest`. Its free-text next action said to execute round one after the frozen signal snapshot became ready. Its linked objects contained two artifacts and one experiment, but did not contain the backtest task identity.

The data-ready event did contain:

- `signal_producer_job`: `signaljob_9a8fb396e6bb42eaba0719eb7c5242c5`
- validated `signal_snapshot`: `artifact_c688cd94aa9e4e1faec2abe918347bea`

Current BYQ code deterministically maps this job to:

- `backtest_task_id`: `backtesttask_9a8fb396e6bb42eaba0719eb7c5242c5`
- phase after a completed signal job: `ready_to_execute`
- next action: `execute`

The continuation prompt did not carry that derived identity or a structured action. It asked the model to re-read and reconcile the task.

### Eight model calls

The single continuation consumed exactly the guard limit:

| Scope | Model calls | Tool calls | Outcome |
|---|---:|---:|---|
| Root | 5 | 11 | aborted by `byq-continuation-budget` |
| Read-only child | 3 | 5 | completed without locating the task |
| Total | 8 | 16 | no round-one backtest execution |

The root loaded two skills; read the research task; started an Agent run; fetched the signal snapshot; read linked artifacts and experiment; reconstructed and called `backtest_task_prepare`; delegated a child to locate the task; then attempted authorization. The child repeated task/artifact/experiment reads and another prepare attempt. Both paths lacked the original backtest task identity even though it was derivable from the event.

Provider-reported per-call usage from the persisted events totals approximately 233,442 tokens including cache-read and output tokens. The continuation ledger charged 8,454,144 because the guard reserves `1,048,576 + 8,192` for each of eight calls. The larger number is a conservative reserved ceiling, not actual provider token consumption.

### Oversized tool payload

`byq_signal_snapshot_get` returned a 15,916,651-character JSON payload. The bounded structural audit found:

- 806 signal rows;
- 300 universe symbols;
- 739 benchmark OHLCV rows;
- 739 dates;
- 220,803 date-index entries;
- 220,803 symbol-index entries;
- ten dense bars/research columns;
- 1,147 corporate-action rows.

DSH recorded a compaction prune of approximately 3,979,175 estimated tokens for this tool result. The following provider call reported a much smaller input, so the full payload was pruned before that inference request. It nevertheless entered the harness event/session pipeline, generated avoidable serialization and compaction load, and provided the agent an execution-grade object it did not need.

The correct statement is therefore:

- BYQ did not intentionally ask the model to judge three years of raw daily bars;
- the Product Agent MCP did fetch the full frozen execution snapshot into the harness;
- DSH pruned that payload before the next recorded provider call;
- a bounded metadata/analysis projection should have been the only Agent-visible form.

## Code-path findings

### 1. Free-text continuation controls deterministic work

`services/backend/app/research_continuation.py` scans terminal events and creates a natural-language instruction. For grantless data-ready events it reserves eight full model calls and asks DSH to rediscover task state. The event has the signal job identity but the instruction omits the derived backtest task identity and exact command.

### 2. Research progress is descriptive, not executable

`research-progress.v1` stores a free string for `stage`, `next_action` and `blocked_reason`. It validates references but does not enforce a legal transition graph, exact action enum, plan version, parameter hash, approval binding or expected postcondition.

### 3. BYQ already owns the deterministic projection

`services/backend/app/backtest_task.py` derives `backtesttask_<hex>` from `signaljob_<hex>`, projects completed signal production to `ready_to_execute`, and returns `next_action=execute`. `services/backend/app/main.py` executes the exact task with a server-derived idempotency key. A model is unnecessary for this transition.

### 4. Continuation scope is too broad

The task-bound allowlist includes task reads/transitions, experiment/artifact creation, ML work, backtest prepare/create/execute/analysis, workflow cards and other tools. It checks owner/task scope but not the current exact plan stage. The model can investigate or attempt valid-in-scope actions that do not advance the task.

### 5. Approval is a second general continuation engine

Gateway approval handling starts another general DSH root with a natural-language “re-read and execute” prompt. `submitted` proves prompt admission, not that the exact business action completed. This is separate from the task continuation ledger and can reconstruct action order differently.

### 6. Compound-task permission is absent from the chat journey

A continuation permission panel exists in the Research page, but task creation in Product chat does not establish or request the task-bound grant needed for backtest-completed events to wake later rounds. Grantless ADR-0077 handling wakes only for completed signal preparation. Therefore a promised three-round asynchronous task cannot complete unattended under the current Product chat journey.

### 7. Budget is used as a progress detector

The runtime guard correctly fails closed, but the workflow has no durable-progress fence after a model response. It therefore permits repeated rediscovery until all eight reserved calls are consumed. The UI exposes token values whose minimum can fund only one conservative call while a normal tool loop needs at least two.

### 8. Terminal state does not converge

On continuation `needs_attention`, Backend updates only continuation-block fields. It does not atomically update ResearchTask progress/stage or the Product projection. Runtime sets the session failed, but `_run_prompt` does not immediately retire/end the current RuntimeGeneration ledger; the generation can remain `starting` with no `ended_at` until replacement/restart reconciliation.

### 9. Tests prove mechanics, not the business journey

Existing tests prove event reservation, budget enforcement, ownership, restart handling and synthetic tool-loop behavior. The 0.9 composite regression explicitly left real data-ready continuation/runtime tool-boundary rows blocked or relied on scripted/keyless fixtures. No test drives the full real Product journey across strategy approval, data ready, backtest approval/completion, three analysis/revision rounds and simulated-account creation while asserting bounded calls and coherent terminal state.

## Root-cause hierarchy

1. **Primary**: no authoritative machine-executable research next-action plan.
2. **Primary**: deterministic domain transitions are delegated to a free-form LLM loop.
3. **Primary**: approval and async completion paths do not share one task/plan state machine.
4. **Amplifier**: full execution snapshots are exposed through Product Agent MCP.
5. **Amplifier**: broad stage-insensitive tool surface permits rediscovery and delegation.
6. **Amplifier**: conservative budget ceiling is reported/treated like usage and doubles as the only progress bound.
7. **Visibility defect**: task, continuation, session and generation terminal states do not converge.
8. **Process defect**: acceptance tests validate components and labels without executing the promised compound journey.

## Recommended correction

Adopt Proposed ADR-0085. The core change is to let BYQ persist and reduce exact domain actions while keeping DSH responsible for generic Agent Loop and for genuinely interpretive research stages. Do not fork DSH and do not build a second generic harness.

Implementation should be delivered as P0–P4 maintenance slices. The old broad automatic model continuation should remain disabled/notification-only until the exact plan path passes the real three-round journey and fault matrix.
