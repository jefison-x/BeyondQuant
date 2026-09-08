# Post-U8 recovery / watchdog / public lifecycle slice

2026-09-07. Status: COMPONENT_AND_SCRIPTED_INTEGRATION_VERIFIED_BUILD_GATE_PENDING.
Worktree: `post-u8-conversation-recovery`; Product Phase97 unchanged. No production deployment.

## Implemented boundary

- R2: bounded unanswered request and closed failure facts in a separate recovery section;
  same-text deduplication, explicit current instruction priority, ambiguous short continuation
  rejected before starting a run. Current durable message ID reused on lost-adapter retry.
- R3: each associated child owns inactivity180s and hard600s accounting; root remains900s.
  Only advancing official child event sequence renews that child's lease. Unknown lineage,
  duplicate/out-of-order sequences, finished child and unrelated parent activity cannot renew it.
- R5: at most one waiting notice per60s while running; closed run identity and elapsed/quiet
  seconds only. Notices do not modify last activity or hard deadlines and stop at termination.
- R4/F3 public slice: unknown submit is not completed; cancellation/failure/result close orphaned
  public steps. Domain jobs are untouched. Tool activity identity is scoped to the public turn;
  same tool call ID in another turn cannot overwrite the earlier activity.

Official fixed-version source and a real synthetic wire probe confirm `session.event.event.seq`;
`subagent.started` exposes parent/child identities but no tool-call identity. Therefore the current
development profile uses the official `agent-loop.config.maxParallelToolCalls=1`, not a BYQ scheduler.
Source: [official Agent loop](https://github.com/deepseek-ai/DeepSeek-Harness/blob/dsh-v0.1.2-rc.1/packages/core/agent-loop/src/index.ts).
Current generated profile/identity changed together; historical U7.3 build manifests/reports remain immutable.

## Checks

- Gateway full suite103 passed (one dependency deprecation warning).
- Runtime default suite86 passed,5 skipped (three dependency deprecation warnings).
- Real DSH0.1.2rc1 + live BYQ MCP + local scripted provider:11 passed in17.58s.
  Includes three recovery inputs, five role journeys, MCP auth rejection and product roster,
  and a model step requesting two delegations: both get their own call-linked leases,
  maximum simultaneous associated children is1. No paid/model-provider requests.
- Frontend51 files/152 tests passed; typecheck and production build passed.
- Mocked Playwright20 passed (1.2min); an existing ResizeObserver warning appeared
  in the unrelated Backtest workspace journey, as in the earlier R1 run. It is retained,
  not described as a clean console result for that mocked suite.
- WorkflowTrace contract7 tests passed; candidate profile generator check passed.
- Architecture203 tests:5 failures/12 errors. Build/release checks still compare modified source
  to historical certification; dependent negative assertions are preempted by drift checks.
  This is NOT CI-green. An earlier read-only invocation additionally failed temporary-directory
  creation; only the subsequent writable-fixture run is used for the counts above.

## Browser evidence

Isolated Compose `byq-ci-r2-recovery-20260907`, frontend18261, Gateway18262; independent PostgreSQL,
trace/session volumes and network. Synthetic credential values only; no training/data workers.
Real Chrome context `byq-post-u8-r35`, no browser API mocking. Product login200 and persisted
synthetic conversation through the real catalog; normalized waiting/unknown/terminal fixtures
through TraceStore. Fixtures prove projection, not a60-second model execution or a domain submission.

Desktop displays the waiting explanation and “结果待核实”; fetch/XHR origins only localhost18261.
390×844 mobile: no horizontal overflow. After terminal fixture and reload, waiting disappears,
unknown business result stays visible in the activity drawer; inspected console has no errors/warnings.
Setup corrections retained: wrong login route404 then correct `/api/auth/login`200; a hardcoded
terminal sequence conflicted with runtime-restoration ready event and was rejected, then appended
at the actual next sequence. No record was overwritten.

## Not complete

R2 paid-model semantic acceptance, durable AgentRun closure, domain receipts/reconciliation,
authorized background continuation, index pool S1–S3 and full interface audit remain open.
No overall R/S/F completion, release qualification, push/merge or production acceptance is claimed.
The expanded synthetic model evaluation request is separate from historical fixed G1–G6 authority.
