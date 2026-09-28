# Phase 7 live-state classification

Status: bounded ownership inventory for the Phase 7 exit review. This is not
Phase 7 acceptance or final 0.10 architecture acceptance. Classification is by
behavior, not by class/table name. The old runtime database is archive only;
its rows are not migration or admission inputs for the new environment.

| Remaining state | Behavior and owner | Disposition |
|---|---|---|
| Adapter `RuntimeSession`/`ActiveRun` and `RuntimeGeneration` | In-memory session/run status, prompt admission, cancel/terminal decisions and generation transitions in `services/runtime-adapter/app/runtime.py`; these still make BYQ an Agent lifecycle owner. | **Phase 10 blocker:** replace with DSH-owned lifecycle and bounded transport correlation; qualify the Gateway `/resume` boundary. Phase 7 does not certify this as final architecture. |
| Adapter `pending_conversation_context`/`pending_conversation_recovery` | Carries previous conversation context into a later DSH turn; live Gateway recovery payload feeds it. | **Phase 10 blocker:** remove BYQ generic context/recovery ownership while retaining supported new-session user interaction. |
| Adapter `ChildLease` and process bound | In-memory correlation and watchdog for the owned foreground DSH process, without child resume/rebind or persistence. | **KEEP** under the narrow ADR-002 exception until an equivalent qualified bound exists. |
| Adapter evidence/terminal ACK and Backend boot/root authority | Exact call evidence, boot revocation, root terminal receipt and unknown external outcome constrain BYQ domain actions; they do not restart DSH. | **KEEP** as business safety. Phase 10 qualifies the Adapter/Gateway boundary; Phase 14 normalizes storage without losing the safety fact. |
| Backend `agent_runtime_turns` and `agent_runs` | Generic Agent status/registration shares rows and foreign keys with BYQ action authorization, approvals and audit. | **Phase 10/14 blocker:** separate generic lifecycle decisions from BYQ business authority before removing old runtime fields/tables. Do not drop the tables in Phase 7. |
| Gateway domain-proof `LifecycleDelivery` | Durable private evidence/ACK delivery for BYQ authorization, not Agent execution replay. | **KEEP** for now; qualify exact close and evidence delivery in Phase 10, simplify residual delivery in Phase 17. |
| Gateway live-session restore and `/resume` | Reattaches only a still-live Adapter session or asks Adapter to create a new DSH generation; cannot restore a lost Adapter process. | **Phase 10 blocker:** thin DSH session/status translation and Product API behavior. |

The Phase 7 residual legacy cleanup is narrower: the Backend scan of old
`ResearchTask.continuation_budget.recovery_attempts` at domain-call admission
and the unwired Gateway `LifecycleDelivery.recover` callback are removed in the
accompanying slice. Neither is the exact boot revocation, root close, domain
claim or `outcome_unknown` path. The targeted Tester/Reviewer gate for that
slice and the Phase 7 exit gate are recorded separately in `phase-gates.md`.

Evidence: `runtime.py` session/run/generation definitions and prompt/resume
decisions (lines 120–218, 619–677, 798–863, 1248–1349); Gateway session
restore/resume (`services/gateway/app/main.py` lines 1302–1343, 1844–1867);
Backend runtime/authority records (`services/backend/app/agent_research.py`
lines 430–484, 733–849); business claims
(`services/backend/app/domain_call_admission.py`); Gateway exact close and
private evidence delivery (`services/gateway/app/main.py` lines 495–616).
