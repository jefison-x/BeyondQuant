# Phase 5–6 runtime ownership audit and deletion plan

Status: review candidate; **no runtime code, schema or migration was removed**. Classification means intended 0.10 disposition after accepted ADR and contract tests. It is not a line-by-line deletion authorization. Sources: `ARCHITECTURE.md`, ADR-0079/0082/0085–0087, `services/runtime-adapter/app`, `services/backend/app`, `services/gateway/app`, `packages/contracts`, `workers` and `plugins/dsh-byq`.

## Ownership audit

| Concept | Current implementation / duplication | Final owner | Disposition |
|---|---|---|---|
| Session | DSH session plus Adapter `RuntimeSession`; BYQ `product_conversations` is user-facing history | DSH Agent session; BYQ Conversation | DELETE generic Adapter session management; KEEP Conversation |
| Run | DSH turn, Adapter `ActiveRun`, Backend `agent_runtime_turns`, `agent_runs` | DSH turn; BYQ authorized business action | DELETE root lifecycle store; REWRITE `agent_runs` to necessary business action/audit semantics |
| ChildRun/Subagent | DSH executes child; Adapter `ChildLease`, `agent_runs.parent_run_id` | DSH lifecycle; BYQ transient process watchdog/correlation | KEEP bounded in-memory watchdog while pinned DSH lacks an effective deadline; DELETE child takeover/recovery; KEEP business parent relation/ID if used |
| Checkpoint | DSH session checkpoint; ResearchTask progress also called checkpoint | DSH context; BYQ ResearchTask/Job progress | DELETE BYQ generic context checkpoint; KEEP business progress |
| Recovery/lease/fencing | Adapter journal/generation/executor fencing, Gateway delivery, Backend continuation receipts | DSH generic recovery; BYQ business idempotency/unknown outcome | DELETE generic path; REWRITE bounded business safety path |
| Workflow | DSH generic orchestration; BYQ `ResearchExecutionPlan` domain state | DSH reasoning; BYQ ResearchTask | KEEP explicit domain transitions; DELETE generic workflow compatibility |
| Agent/role | DSH persona/tool registry; Backend role/capability catalog | DSH runtime; BYQ authorization/MCP | REWRITE duplicate allowlists with Backend/MCP as safety authority |
| Event | `research_continuation_events` stores claim/settle state, more than notification | BYQ pending business command or Job; event notification | REPLACE durable intent with explicit state; event becomes notification |
| Trace | Adapter journal, Gateway `TraceStore`, Backend lifecycle receipt | BYQ user projection/observation | REWRITE one bounded projection; DELETE recovery-by-trace |
| Tool/MCP | DSH MCP client; BYQ Product MCP; multiple profile allowlists | DSH generic tooling; BYQ domain capability | KEEP Product MCP, REWRITE to domain commands only |
| Plugin | DSH registry/profile and BYQ `PluginCenterStore` governance | DSH runtime extension; BYQ minimal enable/policy | REWRITE minimal registry/version/enable/capability; DELETE extra governance |
| Job/Worker | backtest, signal, ML and data jobs in separate stores/workers | BYQ Job; specialized Worker execution | KEEP workers; REWRITE common Job contract and stable ID, avoid forced table merge |
| Artifact | `research.artifacts` with hash/lineage; jobs reference artifacts | BYQ | KEEP and normalize ID/ref/provenance across result kinds |
| Approval | `agent_approvals`, user policy and plugin requests | BYQ | REWRITE to AUTO/DECISION/ACTION with exact resource/action binding |
| Audit | `agent_audit` plus paper/data/plugin/credential records | BYQ structured observation and domain fact stores | REWRITE emitter; KEEP authoritative financial/approval records |
| Workspace | tenancy/membership binds conversations, ResearchTask, Artifact and Jobs | BYQ | KEEP; ADD scoped runtime/workspace reset |

## Concrete code disposition

| Decision | Targets and reason |
|---|---|
| KEEP | BYQ Workspace/RBAC, ResearchTask domain facts, Strategy/Experiment, domain validation, BYQ MCP mediation, business idempotency, exact approval binding, unknown external/financial outcome safety, existing backtest/ML/data workers, Artifact IDs, user-visible Conversation, and the Adapter's transient `ChildLease` process watchdog under ADR-002 while pinned DSH lacks an equivalent bound. |
| DELETE | Generic `RuntimeSession`/`ActiveRun` ownership in `services/runtime-adapter/app/runtime.py`; child takeover/recovery (not the transient watchdog); generation/executor lifecycle state in `generation_ledger.py`/`lifecycle_journal.py`; Gateway recovery-by-delivery; Backend `agent_runtime_turns` and generic run recovery; compatibility-only DSH SDK adapters and candidate Dockerfiles after current DSH API qualification. Exact files/schema must be checked in Phase 7 before deletion. |
| REWRITE | `research_execution_plan.py` to the minimum ResearchTask domain transitions; `research_continuation_ledger.py` from event-as-state to explicit pending business action/Job; `agent_runs` to necessary authorization/audit facts; `workflow_trace.py`/`trace_store.py` as bounded UI notification/projection; Job and Artifact contracts; Approval and Audit. |
| REPLACE | Multiple adapter/gateway/backend runtime receipts with one DSH status boundary plus BYQ business IDs; old schema with fresh baseline, no old runtime migrations; scattered env reads with SystemConfig/WorkspaceConfig/TaskConfig; old Compose/Makefile lifecycle with scoped dev commands. |
| ARCHIVE | Pre-Clean-Break ADRs and P4 evidence as historical only; final old DB dump/config manifest as read-only archive; old runtime migrations and historical CI artifacts as reference where retention requires. Do not use archives as test or migration input. |

### P4 disposition

P4-A/B real-journey evidence remains historical. P4-C1 is in current main despite stale STATUS candidate text. Preserve P4-C2 worktree/branch only as unreviewed reference; do not merge or build Clean Break from it. P4-D is not assumed complete. **Keep semantics**: deterministic domain action, ResearchTask CAS, exact approval/parameters digest, bounded market-data projection, business idempotency, one Job/Artifact identity, explicit unknown financial outcome. **Discard implementation shape**: generic generation ledger, executor lease/fencing/takeover, child-runtime recovery, cross-service session receipt choreography and event-as-state continuation. Do not claim DSH native cross-process continuation merely because P4 safety tests passed.

## Phase 7 entry gate

Before deleting each candidate: identify callers and public contract; state replacement owner and data fate; prove no financial/authorization invariant is lost; inspect schema and deleted component diff; then Tester, Reviewer and Root sign off. Dead or historical-only code uses caller/reference evidence; a live boundary requires a focused contract/architecture test that fails on the old behavior or otherwise detects the intended change. The [development verification gate](verification-gates.md) selects the remaining tests by impact. Phase 7 deletes dead paths first. Any live public path must be cut over in the same bounded Phase 7 slice to a version-qualified DSH API translation or existing BYQ Job/Worker path, with its contract tests passing; a temporary compatibility bridge is forbidden. Phase 10 then completes the broader adapter qualification and contract, while Phase 11 unifies the already-working Job contracts. The proposed ADRs must be accepted and current STATUS/architecture docs superseded. No `DROP TABLE`, volume removal or old DB migration follows from this planning document alone.
