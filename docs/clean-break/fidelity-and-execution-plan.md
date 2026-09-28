# Functional fidelity, risks and Phase 7–17 order

Status: acceptance plan, not completed feature evidence. All scenarios use a fresh BYQ schema and new Workspace. Historic sessions, Jobs and data do not count.

## Target boundary

```mermaid
flowchart TD
  UI --> API[BYQ Gateway / Product API]
  API --> BYQ[BYQ Workspace, ResearchTask, Strategy, Approval]
  API --> AD[Thin DSH adapter]
  AD --> DSH[DSH sole Agent harness]
  DSH --> MCP[BYQ Product MCP / quant tools]
  MCP --> BYQ
  BYQ --> JOB[BYQ Job store]
  JOB --> WORKER[Backtest / Data / ML workers]
  WORKER --> ART[BYQ Artifact]
  ART --> BYQ
  DEV[Codex Sol + Luna / Dev MCP] -. isolated Engineering plane .-> API
```

## Functional fidelity matrix

| Capability | New-state evidence required | Scenario |
|---|---|---|
| Single-turn market analysis; multi-turn research | Product API/DSH conversation, persisted ResearchTask | A |
| Web Search; TuShare | real qualified tool calls, source/provenance, bounded outputs | A |
| Research Artifact; Interaction | stable Artifact ID, user interaction through Product API | A |
| Delegated research | actual DSH subagent and normalized BYQ projection | A |
| Multi-round backtest; long BacktestJob | two real Job IDs, worker completion, persisted results | B |
| Parameter optimization; result comparison | real optimization Job, comparison Artifact | B |
| TrainingJob; GPU Worker; ML checkpoint/restart | worker execution and model Artifact, restart evidence | C |
| Agent interruption; Job continuation/relink | old DSH session ends while Job completes; new authorized session queries the same Job ID without duplicate execution | D |
| Approval AUTO/DECISION/ACTION | allowed read, user choice, exact action gate and audit | A/B/C |
| Audit Event | structured event with request/workspace/resource/job identity | A/B/C |
| Reset Runtime; Reset Workspace | scoped, idempotent cleanup with protected global state intact | E |
| `dev-clean → init → start → seed → test` | clean rebuild from templates on isolated stack | F |

## Golden scenarios

- **A — Market Research:** new Workspace → ResearchTask → TuShare + Web Search → multi-turn interaction and DSH delegated research → Research Artifact; verify provenance, Product API and normalized trace.
- **B — Multi-round Backtest:** Agent starts BacktestJob A → Artifact → strategy change → BacktestJob B → optimization/comparison → comparison Artifact; verify Job IDs and approval boundaries.
- **C — ML:** Agent starts TrainingJob → GPU Worker → worker checkpoint/restart → model and metrics Artifacts; verify Agent does not own GPU process.
- **D — Session interruption:** Agent starts Job → old DSH session ends → Job completes independently → new authorized DSH session uses the same `job_id` to fetch status and result Artifact; verify no duplicate Job, no automatic replay of unknown actions and no claim that the old Agent or child resumed. DSH process restart and in-flight child rebind are outside this 0.10 scenario.
- **E — Workspace Reset:** create research/jobs/artifacts → Reset Runtime → Reset Workspace → verify scoped clean state and preserved account/RBAC/global config → seed → rerun A.
- **F — Full rebuild:** `dev-clean --dry-run` scope review → `dev-clean` → `dev-init` → `dev-start` → `dev-seed` → Golden tests on fresh database.

## Risks and gates

| Risk | Gate / evidence |
|---|---|
| Current STATUS/Accepted ADRs still authorize 0.9 P4 and freeze 0.10 | New ADR acceptance, STATUS/ARCHITECTURE/AGENTS supersession before Phase 7 |
| Unknown actual DB/backup/volume and unrelated running test containers | identify owner, final verified archive manifest before any DB/container cleanup |
| DSH 0.1.5-rc.1 lacks same-session/child restart continuity | do not claim restart recovery; qualify live child completion, timeout, cancel and interruption on the pinned API; do not rebuild generic recovery |
| P4 safety logic mixed with generic runtime | preserve business CAS/approval/unknown-outcome tests before removing generic components |
| Event ledger currently carries durable commands | move pending command to business state/Job before event deletion |
| Audit tables may contain authoritative financial facts | classify table by table; keep facts, move only observation to emitter |
| Job table unification may become a new workflow abstraction | common contract and IDs first; keep specialized worker stores if simpler |
| GPU/real Tushare/browser credentials and hardware unavailable in ordinary CI | separate keyless contract gate from qualified real Golden evidence; do not mark full fidelity PASS without real flow |
| 144 worktrees / four dirty and rollback images | exact ownership checks; never broad prune or touch P4 branch |

## Implementation sequence after planning gate

Each phase uses one isolated branch/worktree and required human PR gate unless a newly accepted ADR changes it. Each step ends Tester → independent Sol Reviewer → Root PASS before the next begins. The [development verification gate](verification-gates.md) defines risk-selected slice evidence, Phase 9 command/service qualification, and Phase 15–16 full rebuild and Golden milestones; historical-data restoration and repeated full-suite runs are not per-slice gates.

Phase 7 retires identified legacy Agent recovery and compatibility paths. Its
exit gate is a finite classification of the remaining live Adapter, Gateway
and Backend state: record each state item, its actual owner and caller, whether
it decides Agent session/run/generation/child lifecycle or recovers/replays an
Agent, and its later disposition. A name such as `RuntimeSession` or
`agent_runtime_turns` alone is not a failure, but an in-memory object is not
automatically mere transport correlation. Transient DSH transport correlation
and the exact BYQ business-call authorization/close receipt may remain. Do not
remove a live business safety fence merely to make the Phase 7 deletion list
empty. Record any generic Agent lifecycle owner not removed in Phase 7 as an
explicit unresolved Phase 10 blocker; never call it Clean Break complete.
Do not turn Phase 7 into a full Backend/Adapter/Gateway rewrite.
The final thin Adapter contract belongs to Phase 10, and the fresh schema and
old runtime table cleanup belong to Phase 14. Jobs, Artifacts, Approval/Audit,
Workspace reset, dev environment rebuild, full fidelity and Golden scenarios
retain their assigned later phases.

7. Remove identified duplicate Agent/session/child recovery and compatibility paths in bounded slices. Classify remaining live state by actual Agent lifecycle ownership against ADR-002, preserve tested business authority and unknown-outcome behavior, and publish finite Phase 10/14/17 handoffs for unresolved owners. Any live path actually removed needs a same-slice replacement and targeted public contract test. Do not leave a broken public path or add a compatibility bridge.
8. Archive verified old DB, then clean only classified old BYQ containers/volumes/networks/images in inventory order.
9. Build scoped dev lifecycle, templates, profiles and minimal seed; prove `dev-clean` dry run.
10. Qualify current DSH API and implement thin adapter with contract/error/cancel tests; check the Gateway/Adapter terminal-receipt boundary and identify durable delivery that is still needed solely for BYQ business authorization.
11. Establish common Job ID/state contract and worker-backed backtest, training, optimization, factor and data-import paths.
12. Normalize Artifact IDs, three-level Approval and structured Audit; retain domain fact records.
13. Implement scoped, idempotent Reset Runtime and Reset Workspace.
14. Establish fresh schema baseline and seed; old DB remains archive only.
15. Verify full functional fidelity from empty schema/workspace via real Product API and browser where UI applies.
16. Run Golden Scenarios A–F, including GPU/credential-qualified paths and ML worker restart evidence; DSH process restart is outside the 0.10 acceptance scope.
17. Search and delete residual duplicate owner, unnecessary Gateway delivery indirection, compatibility, generic workflow, event-as-state, Agent-owned compute and dev-tool leakage; rerun contract and Golden gates.

No Phase 7 destructive refactor begins before Phase 0–6 gate and accepted ADR. Full 0.10 completion requires the real functionality evidence above; this planning package makes no such claim.
