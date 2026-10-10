# Real signed Product child acceptance — FAIL (child ingress unavailable) (2026-10-08)

Status: **FAIL.** One real Product read-only delegation turn was run on the existing `byq-acpf6`
candidate. The root created a real child Agent on the pinned Go route, but the child's authorized
read was rejected (`acp_ingress_observation_unavailable` / Backend
`POST /internal/acp/tool-ingress-observe -> 409 Conflict`), so **no child AgentRun / signed child
identity / MCP ingress attribution was obtained**. No retry, no second turn, no fake ACK.
Not an overall qualification and not a merge PASS.

## Preconditions (read-only, PASS)
- Durable clean user **`admin`**, workspace `workspace_c1b071171522479ca18b25b153e43ab8`;
  Backend workspace Agent admission `can_start=true` (no unsettled roots).
- Adapter ready: `provider=opencode-go-chat`, `model=deepseek-v4.1-flash`,
  `model_credentials=configured`, `release_identity=matched`, `release_id=dsh-v0.2.0-rc.2`;
  `enabled_plugin_ids` includes `byq-acp-mcp-identity` and the `delegate-*` tools (real, not fake).
- Budget profile `product-turn.v1` = `max_provider_calls/attempts/max_tool_calls 16`,
  `max_concurrent 1`, `deadline_ms 180000`, pinned provider/model `opencode-go-chat`/`deepseek-v4.1-flash`.
- Route pinned: adapter env `BYQ_DSH_PROVIDER=opencode-go-chat`, `BYQ_DSH_MODEL=deepseek-v4.1-flash`;
  no fallback to `deepseek-official` / no model switch.

## Real run (single turn)
- Conversation `conversation_57cfa3ce48c1406aab1bb8fed1a2d8a9`, trace
  `byq-trace-90c75563e0c4434c999b5724ee938822`, runtime session
  `byq-session-2103ad5bea074f37893d00b6eb49ecbc`; submitted ONE turn (run
  `b73898d6e5cd42d596da6b71845513a8`), no follow-up turn.
- Provider gate: **8 provider calls**, all `within_request_budget`, HTTP 200,
  `usage_source=provider_response` (budget 16 respected; single Go route). Root and child request
  headers both show `provider=opencode-go-chat, model=deepseek-v4.1-flash, maxTokens=8192`.

### Root (real, completed)
- Backend AgentRun `agent_run_31e1ec4620654b648ecc232752e958e6`, role `quant_orchestrator`,
  parent none, owner `admin`, workspace `workspace_c1b07117…`, status `completed`.
- Native registration: `origin=root`, `depth=0`, native root session `deb02e05-969f-4c49-bca6-1a3daa3d0ef5`.
- Root ingress (3, all root): `byq_agent_authorize` -> `byq_research_get` -> `byq_agent_audit`.
- `agent_runtime_turns` root `b73898d6…`: **completed / closed**, `terminal_sequence=14`,
  `terminal_event_sha256=06fd4ad37433f9946304ae94db30b1021521238efd22050ed657f06444b072f1`,
  `terminal_acp_ingress_sequence=3`, `terminal_unknown_claim_count=0`.
- Signed cleanup receipt: `byq-acp-product-runner-cleanup.v1`, `cleanup:"proven"`, `code:0`,
  root `b73898d6…`.

### Child (real Agent created; business read FAILED)
- Root native log `subagent/catalog`: `childId=6f46d7a0-15d7-4a85-a7e1-42d55513c998`, `mode=one-shot`,
  label `只读核查任务状态`.
- Child native session `6f46d7a0-15d7-4a85-a7e1-42d55513c998`: `subagent/descriptor provider=spawn`,
  `mode=one-shot`; request header `provider=opencode-go-chat, model=deepseek-v4.1-flash`.
- Child tool call: `mcp__byq__byq_research_get` with
  `{"entity_type":"research_task","entity_id":"task_bf9e9a042ff241b19b7266cbf3d6def2"}`.
- Child tool result: `Error: {"service":"beyondquant-mcp", ...}` -> the child's own reasoning names
  the error **`acp_ingress_observation_unavailable`**; Backend logged
  `POST /internal/acp/tool-ingress-observe -> 409 Conflict`.
- **No child AgentRun / native registration / ingress observation was persisted** in Backend
  (only the root run and the 3 root ingress rows exist for the trace).
- The model then fell back to a **root** read of the task (root ingress `byq_research_get`, settled)
  and returned the task status. No create/submit/execute, no business write.

### Why (read-only)
The delegated child's first BYQ business tool was `byq_research_get` **without first binding its own
native AgentRun** (`byq_agent_run_start`). ADR-0094/0097 require a bound native AgentRun for ACP
business tool ingress; without it the observation channel returns `acp_ingress_observation_unavailable`
and the Backend refuses (`409`). The child used the correct pinned route and was created, but its
ingress was rejected, so the required signed-child identity/attribution evidence was not produced.

## Outcome
- **Signed child acceptance: FAIL** (child created; child business read rejected; no child run/ingress).
- Root result: **completed/closed**, exact terminal ACK; the delivered task status came from the
  **root** fallback read, not the child.
- No writes/Jobs executed; no old unknown replayed (`task_af01e6ea`/`root41d492` untouched); no retry.
- Desensitized: only ids/hashes/parsed non-secret fields; no Authorization/signed headers/tokens stored.

## Boundaries
No push/PR/merge/deploy/default/release/tag/Phase. No DSH/business/permission change. No fake MCP.
This run is the one authorized business acceptance; no further turn was sent and none is auto-triggered.
