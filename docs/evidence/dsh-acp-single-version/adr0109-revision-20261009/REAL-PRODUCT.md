# Actual isolated Product delegated read — 2026-10-09

Independent Tester: PASS. Independent Reviewer: Functional/Tests/Clean Break Architecture PASS.
Root: **PASS for this normal-completion, real read-only delegation slice only**.
One actual Gateway Product turn, fresh scope `byq-dev-c89ff732f2`; durable cookie user
with fresh personal workspace. Fixed official DSH rc.2, OpenCode Go
`deepseek-v4.1-flash`, actual BYQ MCP and Backend, no mock MCP.
Old failed root/unknowns remain in old `byq-acpf6`, unchanged.

## Observed actual evidence

- New root: `dc5a6601b7594965b73a63cdbe8404a6`.
- Native root: `9b167d2e-3fb1-4997-b77d-3768fd9f1abd`.
- Native child: `01de151a-1e24-4f78-8ba7-215facba33db`, origin subagent, depth 1,
  native parent exactly native root. Distinct own AgentRun and parent AgentRun.
- Child `byq_agent_authorize`, `byq_research_get`, `byq_agent_audit`:
  signed Backend ingress sequences 1–3, all settled, all own native child/AgentRun.
- Backend root completed/closed; exact terminal sequence 11 and event hash;
  frozen final ingress sequence 3 and digest; unknown claims 0. No forced close.
- Runner real persisted cleanup receipt: exact same root/session/trace/workspace,
  HMAC verified inside runner without exporting secret; cleanup proven/code 0.
  Transport reason `cancelled` reflects process close after normal completion,
  **not user cancellation acceptance**. Post-turn UID10002 process count 0.
- Model provider journal: 9 admitted/completed attempts, all HTTP200, all within
  ADR-0106 closed request budget. Actual input tokens 272579 (cache-read 205440),
  output 5432. No inference retry, second turn or model switch by the operator.
  Gate role label `root` is a shared-budget label, not proof of native-agent
  attribution; attribution comes from signed Backend native registrations/ingress.

## Boundaries

Read-only tool proof is the actual signed ingress and settlement, plus native binding.
`agent_acp_domain_call_observations` is empty here: this read-only callback does not
exercise a mutating domain command; do not invent write-operation acceptance.
No negative role denial or lost-response fault was induced in this paid run.
The accepted loss contract relies on reused narrow local fault/terminal tests.

Normal completed root: actual bounded evidence observed.
User cancellation/continue, unknown-result recovery, process-fault recovery, cross-root
late calls, background task continuation, dedicated judgment task execution, browser
flow, full/default/release/promotion/production: NOT_RUN in this attempt. Earlier
evidence remains independently scoped; do not erase FAIL/unknown or imply revalidation.

The synthetic seed task is a clearly labeled development fixture; the Gateway/model/
DSH/MCP/Backend chain is real. This is isolated Product integration acceptance of
one read-only delegation, not production acceptance or whole ACP project completion.
All evidence files and SHA hashes are in `real-evidence-manifest.json`.
