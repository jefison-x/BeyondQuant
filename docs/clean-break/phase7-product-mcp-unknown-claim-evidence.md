# Phase 7 — Product MCP unknown claim across Adapter loss

Status: bounded local PASS; Phase 7 overall OPEN.

## Scope

On 2026-09-27, an isolated Compose project `byq-p7-unknown-ffa887ae1f`
ran PostgreSQL, Backend, Product MCP, an independent MCP observer, Adapter
with DSH `0.1.5rc1`, and Gateway. Generated credentials and project-only
volumes/networks were used. No host ports were published. The Backend and
Adapter used test-only launchers mounted from `tests`; the Product API, DSH,
MCP and domain admission code remained the real implementations.

The scripted model requested the real Product MCP tools in order:
`byq_agent_context`, `byq_agent_run_start`, `byq_research_task_create`, and
`byq_strategy_validate`. The Backend launcher held the validation operation
callback after the claim became durably `executing`, then raised a synthetic
exception without creating an artifact. The transaction was released before
Adapter boot rotation to avoid an authority-lock deadlock. Product MCP returned
`outcome_unknown` with `retryable=false`; the provider then held its next
response until Adapter PID 1 was killed.

## Observed result

The independent observer saw exactly one successful transport call for each
of the four Product MCP tools. Before Adapter death, there was one active
business root, one active AgentRun, one `executing` strategy-validation claim,
and zero task artifacts. SIGKILL of Adapter PID 1 exited with code 137;
both recorded Adapter/DSH host processes disappeared and Gateway Agent
readiness returned 503. Backend, MCP, observer, PostgreSQL and Gateway stayed
running. No further Product MCP request appeared during the dead interval.

Manually recreating only Adapter established a new boot. Gateway became ready;
Backend retained the old boot binding and marked both old root and AgentRun
`authority_revoked_unconfirmed`. The same sole claim remained `executing`,
artifact count stayed zero, and the observer saw zero automatic MCP replay.

The first probe reached the new-boot check but failed because the host runner
queried Adapter before its HTTP endpoint was ready. Its disposable database
already showed one `executing` claim and one revoked root/run each. The runner
was corrected to await Gateway Agent readiness first. After a full disposable
reset, the complete probe passed:

```json
{"result":"PASS","outcome_unknown":true,"retryable":false,"claim_count":1,"claim_status":"executing","artifact_count":0,"adapter_exit_code":137,"old_dsh_processes_gone":2,"boot_rotated":true,"old_root_authority":"authority_revoked_unconfirmed","old_run_authority":"authority_revoked_unconfirmed","mcp_replay_count":0}
```

`docker compose down --volumes --remove-orphans` removed the exact test stack.
Filtered post-cleanup checks found zero project containers, volumes, networks
and images; the temporary credential directory was removed. The final selected
BYQ build is immutable `.231`; `.230` is frozen. The live probe used `.230`
with the current mounted test fixtures; `.231` changes the embedded source
manifest and Dockerfile selection, not Product runtime logic. A separate
network-isolated `.231` image build passed and its embedded manifest reported
the exact `.231` build ID, DSH `0.1.5rc1` release and revision-specific
Dockerfile; that test image was removed.

## Limit

This proves the qualified Compose topology for an in-flight BYQ artifact
mutation claim and Adapter PID-1 loss. The injected Backend exception models
an unknown result after durable claim admission. It does not prove arbitrary
host power loss, external financial side-effect rollback, or same-session DSH
reattachment. The live Adapter journal, Gateway lifecycle delivery and Backend
root/claim fences remain required until a separately reviewed replacement
vertical path passes. Phase 8 remains CLOSED.
