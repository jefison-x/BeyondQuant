# Clean Break development verification gates

Status: current execution policy for the development-period BYQ 0.10 Clean Break.
This policy refines the evidence required by the [phase plan](fidelity-and-execution-plan.md)
and [Phase 7 deletion plan](ownership-and-deletion-plan.md). It does not relax the
Tester → independent Sol Reviewer → Root PASS sequence, the human PR/merge gate,
required hosted CI, or BYQ authorization and financial safety invariants.
The [general development gate](../DEVELOPMENT_WORKFLOW.md#通用风险分级验证门禁)
applies as well; this document specifies the Clean Break phase milestones and
old-runtime data policy.

## Recoverable development baseline

Before a destructive **source** slice, record its clean Git base and commit the
finished slice on its isolated branch. Before deleting a database, volume or
container, satisfy the exact-resource and final-archive gate in
[the environment plan](archive-and-environment-plan.md). A committed Git revision
is the source rollback point; keep a second copy of source/config outside the
resource being removed before host-level cleanup. Credentials stay outside Git.

The new environment must be reconstructible from the committed source, pinned
dependencies/images, documented config templates, fresh schema and minimal seed
using the scoped Compose/dev lifecycle. Phase 9 verifies the commands and
available Compose services; the full fresh-schema rebuild is verified after
Phase 14 in Golden Scenario F. Neither is repeated after every code slice.
Restoring old sessions, runs, checkpoints, user history, caches or the archived
old database is not a Clean Break acceptance test. The archive remains readable
and checksum-verified; it is never an input to the new schema.

## Evidence for each slice

1. **Scope:** record the owner, changed public contract, exact deletion set,
   replacement/data fate and affected components. Dead-code or documentation
   deletion needs caller/reference evidence; a live boundary needs a focused
   contract test that fails on the old behavior or otherwise demonstrably
   detects the intended boundary change. Preserve workspace/RBAC, approval,
   idempotency and unknown financial outcome checks where affected.
2. **Local tests:** record the pre-slice Git commit and run
   `python3 scripts/ci/dev-check.py --base <pre-slice-commit>`, `git diff --check`
   and focused tests for the changed behavior. The default `make dev-check`
   compares the entire branch with `origin/main`; report an inherited failure
   separately rather than attributing it to the current slice. Run architecture
   tests for normative architecture or contract changes. Run affected component
   build/tests locally only when the
   focused tests do not cover the integration risk or when diagnosis requires
   them. A passing unrelated full-repository suite is not a substitute for the
   focused contract.
3. **Required CI:** if a PR is opened, the existing risk-selected hosted CI
   remains authoritative for complete affected-component suites and integration
   triggers under [CI policy](../operations/ci-policy.md). A local slice PASS
   without PR CI is explicitly local evidence only; it does not authorize merge.
4. **Review:** Tester reports commands, results and coverage limits. Independent
   Sol Reviewer inspects the actual diff, interfaces/schema, focused tests,
   security and Clean Break ownership. Root accepts or rejects the slice and
   records only evidence needed to explain that decision. Design PASS and slice
   PASS never imply overall Phase PASS or functional fidelity PASS.

## Escalation by changed boundary

| Change | Additional verification |
|---|---|
| Documentation, archived/dead code | Link/reference and caller checks; normative architecture tests when applicable. No Product runtime or frozen historical build matrix by default. |
| Live Product API, MCP or DSH adapter | Public contract and error/authorization tests for the affected path; relevant component integration. Real Product journey when the user-visible flow changes. |
| Shared contract, schema, Job/Worker, approval or financial side effect | Affected component suites, fresh-schema or worker integration, and exact invariant tests. Unknown external/financial outcomes remain fail-closed. |
| Compose, dev lifecycle or resource deletion | Scoped dry run, exact resource identity and archive gate where data is deleted; verify changed Compose services or commands. Complete fresh rebuild follows the Phase 14 schema baseline. |
| Release candidate or Phase 15–16 completion | Required Full CI, full functional fidelity and Golden Scenarios A–F with qualified real dependencies; Golden C uses the independent CPU ML Worker under ADR-0089. |

Do not rerun repository-wide unittest, H4, historical frozen build revisions,
release-input audits, full Compose or Golden scenarios for every slice merely
because an earlier slice ran them. Run one when the diff touches that contract,
the selected CI profile requires it, a failure calls for diagnosis, or the
phase's milestone explicitly requires it. Keep historical evidence immutable;
do not rewrite it to make current code pass.

## Phase milestones

- **Phase 7:** bounded live-path contract and ownership checks per slice. The
  complete phase passes only when its removal scope is satisfied and all slices
  have Tester, Reviewer and Root PASS.
- **Phase 8:** exact-resource cleanup follows the verified final old-DB archive;
  it does not require restoration into the new database.
- **Phase 9:** implement and test the scoped dev commands, Compose configuration,
  `dev-clean` dry run, and the services/seed that can run before the fresh schema
  baseline. Record any command that awaits Phase 14 as NOT_RUN, not PASS.
- **Phases 10–14:** contract and affected-component/schema/worker tests as the
  boundary changes; no automatic full rebuild after each slice.
- **Phases 15–16:** full functional fidelity from an empty schema/workspace and
  Golden Scenarios A–F, including `dev-clean → dev-init → dev-start → dev-seed
  → dev-test` from committed source and templates.
- **Phase 17:** simplification audit and affected contracts; rerun Golden
  Scenarios A–F for final acceptance after the last deletion. During Phase 17
  intermediate slices, rerun only Golden journeys affected by their diff.

Any required test that cannot run is recorded as **NOT_RUN** with its reason and
the resulting gate limit; it is never silently counted as PASS. A failing
selected test must be fixed or the slice remains open. External DSH contract
gaps remain explicit NO-GO for dependent live-path deletion, without blocking
independent slices.

Under [ADR-0089](../architecture/adr/ADR-0089-clean-break-gpu-acceptance-scope.md),
GPU execution and GPU checkpoint/restart are excluded from BYQ 0.10 required
tests and recorded as `N/A`. Historical `NOT_RUN` observations remain unchanged.
The CPU TrainingJob, Agent initiation, real Worker restart/reclaim and Artifact
requirements remain required; GPU exclusion alone does not pass Golden C.
