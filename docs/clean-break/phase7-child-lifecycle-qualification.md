# Phase 7 next-slice qualification — delegated child lifecycle

Status: **KEEP the transient `child_lease.py` process watchdog with the qualified DSH 0.1.5rc1 Python SDK** under ADR-002. This is not approval for a BYQ child Agent lifecycle or restart bridge. Phase 7 can remove generic child recovery without deleting this live safety guard.

[Phase 7 slice 10](phase7-live-child-process.md) now exercises the locked
foreground child in a real pinned DSH process: normal finish, dedicated
timeout, hard cancel, owned process close and late-result rejection pass.
This qualifies the live guard for those cases; it does not establish
process-restart rebind or multi-child progress cadence.

## 0.10 interruption scope decision (2026-09-27)

The maintainer narrowed functional fidelity: after an Agent interruption, a
new DSH session retrieves a durable BYQ Job by `job_id`; 0.10 does not require
reattaching the old Agent or rebinding an in-flight child after DSH process
restart. The old item 4 restart/rebind gate is therefore removed from the
0.10 cutover contract. An operation against a lost old session reports
`agent_session_interrupted` and does not replay the original turn. If the
turn's outcome cannot be proven, BYQ leaves it unknown instead of inventing
a terminal trace event. The Product conversation catalog may still show the
historical conversation as `active`; that field describes the conversation's
archive state, not proof of a running Agent. This removes the restart-continuity
dependency from the acceptance plan. It does **not** by itself authorize
deleting `child_lease.py`: the live child still needs bounded timeout, root
cancellation, unambiguous failure and a normalized Product projection. Until
that replacement passes a focused contract on the pinned runtime, direct
deletion remains NO-GO. No BYQ child recovery bridge is permitted. A timeout
may be reported as a failure when that is the actual observed terminal;
`interrupted` requires evidence of interruption and must not be inferred from
an ordinary `session.failed` event.

The pinned DSH 0.1.5rc1 `timeout-policy` reads an optional tool `timeoutMs`.
BYQ's `tool-subagent` has no such deadline, and the policy's cancellation is
cooperative even when a tool declares one. DSH therefore does not replace
BYQ's current foreground-child bound. A future lease removal may instead use
a bounded root-turn deadline and close the dedicated root DSH process, if a
focused contract proves child completion, timeout, cancellation, late-result
discard and Product terminal projection. Compose's fallback root hard cap is
disabled (`0`), while `.env.example` sets `900s`; the effective bound depends
on the developer's environment. With the Compose fallback, simply removing
the child timer would permit an unbounded wait.
An absolute root deadline would also cut off a healthy delegated research turn
that continues reporting progress. Refreshing one root deadline from any child
would let a healthy sibling mask a stuck one. The current small, transient
per-child watchdog is therefore retained; it owns no child execution state.
This conclusion follows the pinned [timeout policy](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.1.5-rc.1/packages/guard/timeout-policy/src/index.ts),
[foreground subagent tool](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.1.5-rc.1/packages/subagent/tool-subagent/src/index.ts),
and [Python SDK API](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.1.5-rc.1/python/sdk/src/deepseek_harness/api.py).

## Current boundary

DSH owns child Agent execution. The BYQ Adapter currently correlates child notifications with the parent delegation and uses `ChildLease` for per-child activity and timeout. Its expiry closes the active harness and emits a failure; Gateway projects that failure to Product clients. Deleting only the lease would make the ordinary root no-progress timeout apply to healthy long child turns, while dropping the timeout would leave stuck turns without bounded cleanup. Business idempotency and unknown external outcomes remain BYQ domain safety regardless of child runtime ownership.

The current Clean Break ADR-002 assigns generic Agent and subagent lifecycle to DSH. Historical ADR-0082 recorded DSH's proposed out-of-process `SubagentProvider.prepareContinuable` path, its absence in rc1, and rejection of a BYQ child-resume bridge. That historical record is evidence, not a current architecture constraint. A BYQ generic child-resume bridge or direct session-file access would violate the current DSH ownership boundary.

The locked Python SDK and runtime-bin are 0.1.5rc1 (`config/dsh/releases/dsh-0.1.5rc1.python.lock`, `services/runtime-adapter/requirements.dsh-0.1.5rc1-candidate.lock`). The recorded 0.1.5 SDK public Python surface is byte-identical to 0.1.2 (`docs/evidence/d15/upgrade-recon.v1.json`); `dsh_015.py` inherits `Dsh012Compatibility`. Its BYQ seam covers starting/running a root session and closing it, but has no child status, child-targeted cancellation, or persisted-child rebind method. The real candidate restart record (`docs/evidence/d15/d15-4/continuable/continuable-adapter-restart.v1.json`) reports `sdk_child_surfaces=[]` and no successful BYQ child rebind. Native Node DSH continuable APIs are a separate surface and do not establish a qualified Python Adapter contract.

An official upstream release check on 2026-09-27 found v0.1.7-rc.2 as the newest published release. Its [Python SDK API](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.1.7-rc.2/python/sdk/src/deepseek_harness/api.py) and [SDK protocol](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.1.7-rc.2/packages/sdk/protocol/README.md) still lack public attach/resume/cancel/status-query requests; status is a pushed notification. The tagged [out-of-process subagent provider](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.1.7-rc.2/packages/subagent/subagent-dsh-sdk/README.md) documents a fresh runtime per delegated run, without a released durable child rebind/status/cancel contract. This is a qualification finding for that tag, not a claim about future releases. Upgrading BYQ from 0.1.5rc1 to that tag solely for this deletion would not satisfy the cutover contract.

## Required cutover contract

Before replacing this live BYQ lease, test one bounded design against the
qualified DSH release. Either use a public DSH child handle/progress contract,
or use a root-turn deadline that closes the dedicated DSH process. Both paths
must prove:

1. Duplicate, foreign, late and out-of-order child observations cannot complete the wrong delegation.
2. Every foreground delegation has a bounded timeout; healthy child work is not cut off by the shorter root no-progress timer, and an unresponsive child cannot wait forever.
3. Cancellation has terminal confirmation or a proven root-close fallback; late results cannot be committed.
4. Gateway Product projection remains framework-neutral; no raw DSH event schema reaches the frontend. Same-child lookup/rebind after DSH process restart is outside 0.10 scope.

Use the real qualified runtime and replacement contract tests if this guard is
ever removed. Do not add a BYQ generic child manager, compatibility bridge, or
private DSH SDK dependency. Keep `child_lease.py` and its safety tests under
the current pin. No DB, Docker or workspace cleanup follows from this note.
