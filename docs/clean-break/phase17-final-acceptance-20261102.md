# Phase 17 — Final acceptance reconciliation, 2026-11-02

Status: **PASS — scoped Phase 17 technical acceptance, Tester → independent Sol Reviewer → Root.**
This is the final Phase 17 applicability review, not a new Product phase,
release candidate, image publication or operating-stack deployment.

## Authority and accepted source

The maintainer explicitly authorized: “允许 PR #419 一次性直接 squash 合并，继续完成
Phase 17 的剩余验收和收尾，复用已有证据，保留测试环境和当前页面。”
[PR #419](https://github.com/jefison-x/BeyondQuant/pull/419) was squash-merged
at `b1238aa162b73a1be6711c3856d8725b702fe180`; its tested head was
`3cdd2d0a355392c40e4ec8c09d281d9d496b9125`. The one-time direct-merge exception
belongs only to #419. Server protection, all checks and immediate read-only
contribution/configuration preflight remained enabled. This record does not
authorize release, deployment, old-data cleanup or Phase 18.

The [phase plan](fidelity-and-execution-plan.md), [verification policy](verification-gates.md),
[accepted final Golden mapping](phase17-final-golden-acceptance.md) and
[2026-10-31 closeout](phase17-closeout-20261031.md) remain the evidence basis.
Their dated failures and pre-run OPEN/NOT_RUN statements retain their original
meaning. This document records later acceptance without rewriting those receipts.

## Golden applicability

| Gate | Accepted evidence and applicability | Limit retained |
| --- | --- | --- |
| A — market research | Reuse the real TuShare, multi-turn research, delegated Web query, Artifact and browser evidence in the final Golden mapping; later official ordinary-search qualification is in the October closeout. User-wide execution settings do not change market-data or provenance semantics. | No new market download, real-data qualification or investment-quality claim. F6 synthetic market data is not used to replace A. |
| B — backtest/optimization | Reuse the accepted two BacktestJobs, OptimizationJob and comparison Artifact from Phase 16/17. #419 changes resource selection identity in the existing UI, with focused tests/build; domain computation and immutable result contracts are unchanged. | No new backtest or optimization was executed for this reconciliation. |
| C — CPU ML Worker | Reuse actual independent Worker termination/natural reclaim of the same TrainingJob and validated Feature/Model Artifacts, plus the accepted fresh-schema ML-watch contracts. | Reclaim is not mid-epoch checkpoint recovery; GPU remains N/A under ADR-0089. |
| D — Job independence | Reuse the completed Job and new authorized Agent reading the same exact Job/Artifact. Current ordinary Root/terminal evidence and the separate scoped recovery acceptance are recorded in the October closeout. | No universal Agent crash recovery, old-turn replay or native-child restart claim. The excluded old-conversation sample is preserved, not repaired or replayed. |
| E — personal reset/new research | Reuse the populated reset/seven-day archive and bounded post-reset research/save/browser evidence. ADR-0111's accepted user-options amendment preserves account-wide execution settings across Workspace reset; the affected isolated PostgreSQL retention/isolation test passed in the user-settings slice. | No new reset or archive restore. Old conversation values follow their existing archive behavior; the new user preference is not silently promoted from them. Original FAIL/UNKNOWN receipts remain. |
| F — reconstructibility/source currency | Reuse the accepted scoped dev lifecycle, canonical fresh bootstrap and source/build qualifications. #419 CI rebuilt the affected current images and passed clean-PostgreSQL, isolated Compose, Product browser, restart and two-user checks. | No new complete empty-stack rebuild or restore is claimed; the original bounded F reuse and dependency-build failure are retained. |
| Current ACP real F6 | The [official DeepSeek qualification](../evidence/acp-official-deepseek-f6-20261101.md) closes the formerly missing current-ACP real gate: two foreground inputs, one automatic background input, one SignalJob/validated Artifact, three closed Root authorities, exact terminal receipts, same native context, one settled dispatch, known actual usage and refreshed read-only usage UI. | Real provider and Job lifecycle; explicitly synthetic market fixture. ResearchTask remains planned. Earlier per-Root native close flags are mechanism inference through strict reuse, not individually captured readbacks. |
| User-wide execution options | [Actual Product settings qualification](../evidence/user-agent-execution-options-20261101.md): ordinary durable users, desktop/mobile save/reload, peer isolation, CAS restore, subsequent executions and immutable old snapshots. | Settings tests do not stand in for F6; the independent real F6 evidence above supplies that gate. |

The accepted [ADR-0111](../architecture/adr/ADR-0111-automatic-continuation-execution-parameters.md)
and [ADR-0116](../architecture/adr/ADR-0116-official-deepseek-f6-qualification.md)
replace the old grant/revoke/fixed-budget acceptance for new automatic requests.
The real case keeps user options revision zero, auto_continue=true and null numeric
limits; it does not close out by disabling all of the user's conversations.
The exact one-off Worker stopped with exit zero; the public conversation and page
remain open. Historical grants, reservations and unknown outcomes remain intact.

## CI, remaining failures and final gates

[CI 41356483896](https://github.com/jefison-x/BeyondQuant/actions/runs/41356483896)
passed all 12 jobs on the exact tested #419 head. Backend main shards reported
1,333 passed and two pre-existing skips. Integration passed 15 checks including
the synthetic F6 release fixture and two desktop/mobile browser cases; scoped
cleanup was verified. This is distinct from the real-provider F6 evidence.
The first #419 run `41353802963` remains FAIL; its owner-route fixture and
test-session identity corrections are recorded in the qualification document.

The tested and squash-merged trees are both
`e8c62cc778e161db853a08b157e360b87dc44a11`. The actual eight selected lanes
match the matrix selected by `plan.py --full`, using the same per-lane commands.
Record this as **PR CI all-lanes PASS**, not a newly dispatched Full run on the
squash commit. The phase verification policy requires affected contracts and
final Golden applicability; it adds no separate standalone Phase 17 Full once
these all-lane checks pass. The old Phase 17 PR #381/Full `37087327746` and later
nightly runs remain evidence for their original trees only. A future trusted-main
Release Images qualification cannot stand in for this phase gate.

The two retained Runner failures are old empty-state-directory assertions after
Runner bootstrap. Signed rejection/no-CWD behavior was not the failed assertion.
They remain FAIL with original broad-suite file logs NOT_CAPTURED, and are not
selected Phase 17 gates. Hosted Runtime tests cover native JS and Adapter pytest,
not the separate Runner module, and do not offset these failures. The real F6
case and focused route/guard contracts qualify only their recorded Runner scope.

## Separate maintenance follow-ups

| Item | Current record | Phase boundary |
| --- | --- | --- |
| R3 feedback post-review status polling | Still NOT_RUN in the [designated remediation record](post-release-fix-requirements.md); Hub received and local status-after-moderation are distinct. | Separate post-release remediation, not one of the Phase 17 A–F/F6 scenarios. It remains open; this reconciliation does not claim the full feedback lifecycle passed. |
| Global usage aggregation | The old system-level aggregate does not include this official F6 request; its zero is not factual request usage. | F6 requires exact request accounting and its read-only receipt UI, which passed. Global aggregation/cost monitoring remains unqualified; it is not silently marked fixed or replaced by a zero. |
| Runner test hygiene | Two old bootstrap/empty-directory assertions remain FAIL; historical broad-suite file logs are NOT_CAPTURED. | Separate test maintenance: compare initialized state before/after rejected requests while retaining signed rejection, no-CWD and non-consumption assertions. No claim of a wholly green Runner suite. |
| Trusted image release / operating deployment | NOT_RUN for the #419 application source. | Separate release authorization, trusted-main image qualification and operator deployment gates. Existing successful older releases keep their original scope. |

These classifications follow the existing phase and remediation scopes; they do
not remove an A–F/F6 criterion, suppress a required failure or redefine product
completion. No source/API/schema capability is added in this documentation slice.

## Preservation and verdict

The original test environment, browser tabs, current backtest page, durable admin
identity, historical containers/volumes/data and rollback material are retained.
No model input, business Job, feedback submission, password reset, Workspace
reset, market download, publication or operating-stack replacement was made by
this reconciliation. Existing evidence remains read-only.

Final Tester evidence audit: PASS. Independent Sol Reviewer: Functional PASS,
Tests PASS for the applicable phase gates, Clean Break Architecture PASS. Root
accepts the A–F applicability above, the current real F6 and settings evidence,
the exact-tree all-lanes PR CI and authorized #419 merge: **Phase 17 PASS within
this BYQ 0.10 scope**. No remaining selected functional gate requires a new
model/Job/Golden execution or standalone Full dispatch.

The private handoff directory `.ci-artifacts/phase17-final-acceptance-20261102/`
retains `tester-evidence-audit.md`, `full-gate-audit.md` and
`independent-final-review.md`; the prior F6 and CI/merge receipts remain in their
original directories. Documentation changes still follow their own checks and
repository gate; no permission to bypass those gates follows from this verdict.

Phase 18 remains NOT_STARTED and has no accepted new implementation plan. This
phase acceptance is not universal recovery, real investment performance, global
usage/feedback completion or v1.0 release/parity qualification.
