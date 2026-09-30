# Phase 16 — Golden Scenarios A–F acceptance

Status: **local evidence reconciliation PASS; overall OPEN** for required
exact-head Full CI and repository gates. This phase makes no Product runtime, schema, provider or Worker change.

## Entry, baseline and authorization

The maintainer instructed continuation of Phase 16 after reviewing its scope.
Development and bounded evidence review were authorized first. After reviewing
local commit `80fcb185`, the maintainer explicitly instructed “推送合并”. This
authorizes Phase 16 push/PR, required exact-head Full CI and ADR-0015/0059
squash auto-merge only after all local, hosted and live repository gates pass.
Phase 15's narrower authorization is not used as the Phase 16 grant. Deployment,
release/tag, Phase 17 implementation, existing databases and backups are outside
this task. No new external model/provider calls or destructive stack operations
are proposed; the Phase 15 three-turn CPU-training budget was exhausted.

The clean local `main` was fast-forwarded and the new worktree created from
fetched `origin/main`. Audit baseline: `1a3b3c7016b913926563122aced1f8615391bc0a`,
worktree `/home/jefison/projects/.byq-worktrees/clean-break-phase16`, branch
`codex/clean-break-phase16`. This receipt is an observed base, not a hard-coded
future main requirement. `verify-worktree.py` passed.

## Phase 15 repository completion receipts

- [PR #378](https://github.com/jefison-x/BeyondQuant/pull/378): MERGED at
  2026-09-30 09:54:11 +08, squash commit
  `1a3b3c7016b913926563122aced1f8615391bc0a`.
- Tested head: `a19fc32e365120fa1424346b4119b3f13cf52a19`.
- [Full CI 36655977569](https://github.com/jefison-x/BeyondQuant/actions/runs/36655977569)
  and [automatic PR CI 36655977256](https://github.com/jefison-x/BeyondQuant/actions/runs/36655977256)
  completed successfully on that exact head. All seven components, integration,
  browser-enabled lanes, run-scoped cleanup, plan/contribution and aggregate
  `local-ci`/`ci-gate` passed. The automatic PR scan covers base through HEAD.
- Tester → independent Sol Reviewer → Root and immediate ADR-0015/0059 platform
  preflight passed before the authorized ready/squash auto-merge. Remote main
  was fetched and confirmed to contain the actual merge; no deployment occurred.

Earlier failed CI, observation and permission attempts remain in
[Phase 15 gates](phase-gates.md) and [functional evidence](phase15-functional-fidelity.md).
They are not retrospectively relabelled PASS.

## Evidence basis and reuse decision

[The phase plan](fidelity-and-execution-plan.md) requires Golden A–F.
[Verification policy](verification-gates.md) requires a fresh-schema milestone,
qualified real dependencies and Full CI, while avoiding mechanical reruns for
unaffected slices. The accepted Phase 15 flows already follow a clean isolated
rebuild, not old runtime restoration. Phase 16 reviews their actual chronology,
identities, affected code and limits before accepting reuse. It does not claim
new executions at the Phase 16 Git head. Recorded commits below are evidence
and reconciliation chronology anchors: the per-flow runtime source tree SHA
was not pinned in the recorded documents or private manifests. They must not
be represented as proven execution-source SHAs. Required Phase 16 exact-head hosted CI
remains separate from Phase 15's successful CI.

| Golden | Post-rebuild evidence and identity | Acceptance limit |
|---|---|---|
| A — Market research | Connected E reran real TuShare and delegated two-turn Web research; conversation `conversation_e5caa88750754edba4b3473355e26982`, trace `byq-trace-f1780ef62b87449ab6cc50a72fbdd6c4`, Web Artifact `artifact_b7e03959f1f442e487977612d12b199f`; real-browser replay and asset listing, normalized activities and durable MCP audit corroboration. | Ordinary Product follow-up qualifies interaction. Separate DSH Interaction plugin is unqualified; Web evidence remains research-only, not authoritative market data. |
| B — Backtest/optimization | Agent conversation `conversation_d7784e11d12f4c9ea166ac22693e7157` read A analysis, revised threshold 9.20→9.22, started Jobs `backtest_a2d9739696bf4c6c902949b125b00c0a` and `backtest_a0dda018f9bc4e44b1442fcad54b5e34`; OptimizationJob `optimizationjob_f75745c4ff184028847c87c104816dc9` and comparison Artifact `artifact_59a9fe87714245c3a7025cbf0bb06c54`; exact Artifact ranking reopened in browser. | Existing entity JSON detail is the comparison Artifact view; no formatted ranking UI is claimed. |
| C — CPU training/reclaim | Agent conversation `conversation_3a58869e9d514aadbf9d7e196bd192d1`, exact approval `agent_approval_f2e77aa5ae9948318cf7e34bc4aad98d`, Job `mlrun_bcd447d93afd46f48db7dcaf881c19ab`; real Worker kill on attempt 1, new container reclaimed after natural lease expiry and completed attempt 2; Feature `artifact_4ca1c68fa5614668b61ee226528bea36`, Model `artifact_9552a32103e848ce9c41502cd7e39380`. | CPU durable reclaim/re-execution, not mid-epoch checkpoint recovery. Feature legitimately reused; one unique Model. Trace arguments are not public; trusted preview, persisted audit and Product Job cross-check submission. GPU N/A under ADR-0089. |
| D — Session loss/Job survival | Old Agent conversation `conversation_11dcaa622f1b49c2b325195ddba6a123` submitted `backtest_ebe7f6dad7cf4caf9e3fff3661c62380`; after deletion same Job completed once; new Agent conversation `conversation_37cf684f534749bd9f529e4732193765` read the Job and Artifact `artifact_2169ba2cdfbc48058662c604798e8145`. | No old Agent resume, DSH process restart or in-flight child rebind claim. Public trace omits exact call arguments/results; Product provenance and exact answer cross-check identity. |
| E — Reset/reseed/research | Browser Runtime reset retained Task; Workspace reset removed exact populated Task/Jobs/Artifacts, preserved identity, roles and representative shared config; seed/fresh task and connected A succeeded. Later bounded Product reset fix retained two successful Web audit facts and deleted disposable Artifacts. | Protected-config observation covers a representative shared configuration, not every SystemConfig key. Repeated-reset fix has focused DB and real Product evidence; no new browser rerun is claimed. |
| F — Clean rebuild | Commit `2987d3c1`: dry run and exact cleanup of 12 containers/4 volumes/2 networks, init/core start/seed/test/login on empty storage, then connected E/A (`80662e2`), D (`a3114ab`), B (`476e823`), comparison browser (`2b41763`), baseline CPU (`3f2ec78`) and final Agent/Worker C. | Uses isolated development state and templates; no archived old DB/session/cache restoration. Later flows after clean rebuild supply the connected journeys. |

### Rebuild currency and subsequent fixes

Golden F is the accepted Phase 15 rebuild baseline at evidence commit
`2987d3c1`, not a rebuild performed at the merged or Phase 16 source head.
Later CI correction commits `74f378c1` and `de30eac2` updated Compose selectors,
`environment.py`, build selection and immutable manifests `.271/.272`. Their
exact-head Full CI and bounded selected/frozen identity gates passed, but no
subsequent destructive developer-stack rebuild is recorded. The Phase 15
Reviewer/Root accepted F's post-rebuild chronology. This reconciliation changes
no dev lifecycle, Compose or build input; it accepts that bounded baseline
rather than mechanically rerunning it. Any later lifecycle/build change or a
claim of a rebuild at a new source head requires its own scoped validation.

The final Golden C evidence commit `9671f435` also includes the Gateway
pre-prompt session-restoration failure correction. Two focused regressions
and the read-only live observation recovery passed; the Phase 15 independent
Reviewer/Root explicitly accepted current C and existing A/B/D/E plus F
chronology. This does not prove that every old flow executed every later source
change. No Phase 16 diff touches these behaviors.

Detailed commands, failed attempts, scopes, Artifact provenance and observation
limits remain at the linked Phase 15 evidence rather than duplicated raw logs.
The existing cached window has 98 trading sessions (2024-01-02–2024-05-31);
no new download, provider call, model call, Job submission, Worker restart or
Workspace reset is performed in this Phase 16 reconciliation.

## Independent local verification

Tester **PASS** on 2026-09-30:

- `dev-check.py --base 1a3b3c70`: syntax PASS, one changed Python file;
  component suites NOT_RUN locally and remote CI remains required.
- `check-docs.py --base 1a3b3c70`: five changed Markdown documents PASS.
- Three named Clean Break governance tests PASS; current README/STATUS phase
  16 agrees, historical phase 97 marker retained.
- `pytest -q -p no:cacheprovider tests/architecture`: 198 tests and 92 subtests PASS.
- Selected `.272` identity check PASS, unchanged manifest hash
  `sha256:a4ea957ef6123d1b8c80882172c89b5b0857bdb4ab163028382d89b7291e3414`.
- `git diff --check` PASS; evidence refs and limits checked independently.

Independent evidence Explorer confirmed A–F mapping and unaffected-behavior
reuse, and required the runtime-source and F currency qualifications now
recorded above. No new Golden execution or stack/data operation occurred.
Independent Sol Reviewer: **Functional PASS / Tests PASS / Clean Break
Architecture PASS** for the actual docs-only diff and accepted-baseline reuse.
Root: **PASS for local Phase 16 evidence reconciliation**. No missing in-scope
Golden evidence requires a new Product execution in this unchanged-behavior
slice. This is not new-head live execution or an overall repository PASS.

## Remaining gate

The independent evidence audit, local normative/document checks and Tester →
independent Sol Reviewer → Root gate are PASS. Remaining: authorized Phase 16
push/PR, exact-head required Full CI and repository gate.

Phase 16 overall is OPEN; Phase 17 remains closed. A local evidence PASS does
not mean hosted CI, merge, deployment or final BYQ 0.10 completion.
