# rc.2 keyless child tool-count proof — NOT_PROVEN (2026-10-08)

Status: **NOT_PROVEN.** One corrected narrow keyless probe was executed (no external model, no
network, no DSH fork/patch, no business change). It did **not** produce a real child Agent, so the
required child evidence is absent. This run is **not** counted as a PASS and **not** a business-call
proof. No second probe was run (one-probe boundary this round). Full raw is kept locally isolated
only; only desensitized reduced evidence is in this directory.

## What was run (one corrected narrow probe)
`probe_count_only_child_scope.py` — launches the pinned rc.2 DSH (`639ed015397290b3745d163aafe02ffee4aa3f84`)
via the Runtime Adapter's real ACP stdio client (`app.compat.dsh_acp._AcpProcess`), with the
production `byq-continuation-budget.js` guard in `count-only` mode plus a minimal observer plugin.
Scripted provider emits one `byq_delegate_market_research` call (`run_in_background:false`), then 17
`mcp__byq__byq_research_get` calls.

Harness corrections made before the final run (setup only, no child semantics; each was an
environment/probe defect, not an official DSH limitation):
1. `session/new` -32603 `no adapter registered for provider "deepseek-official"` — caused by
   disabling `llm-deepseek` in the probe overlay; fixed by keeping the default provider adapter and
   pinning the session route to the scripted `opencode-go-chat` afterwards.
2. `byq-acp-mcp-identity` `BYQ_ACP_AGENT_IDENTITY_UNAVAILABLE` standalone — disabled probe-only (no
   signed per-root ACP env in a standalone run); as in the earlier keyless probes.
3. Observer plugin import: an inserted `file://…*.mjs` temp helper failed to import
   (`failed to import`); the **absolute-path `.js`** observer loads (re-confirmed here:
   `observer.apply` recorded). The `file://` temp `.mjs` failure is a **probe-helper** issue and does
   **not** establish that the official rc.2 is unsupported.

## Raw observed result (final run; reduced copy `probe-result-reduced.json`)
- `header_schema = product-turn-tool-guard.v1`, `header_has_reservation = false` (count-only).
- Guard journal: admitted **16** (`tool` rows), blocked **1**
  (`BYQ_CONTINUATION_TOOL_LIMIT`). Admitted names: `byq_delegate_market_research` (call 1) then 15 ×
  `mcp__byq__byq_research_get`.
- `agent_created_count = 1` and `child_agent_ids = []` → **only the root Agent** was created.
- `tool_agent_ids = [<root session>]` → **every** admitted dispatch belonged to the root Agent; no
  child `tools/pre-execute` `exec.agent`.
- `child_tool_event_count = 0`, `child_parent_links = []`, `parent_relation_proven = false`.
- `provider_requests = 2` (root turn 1 with 4 messages + root turn 2 with 7 messages; both 20 tools).
- `mcp_calls = 0` → the admitted `mcp__byq__byq_research_get` names **never reached the MCP**; they
  are guard-level dispatch names only and must **not** be counted as business calls.
- `notification_sessions` shows only the root session; `subagent_header_hits = []`.

Reduced evidence: `observer-reduced.jsonl` (18 lines: `observer.apply`, 1 root `agent/created`, 1
`byq_delegate_market_research` tool, 15 root `byq_research_get` tools). Full raw (`observer.jsonl`,
`probe-result.json`, `probe-stdout.log`, `composition.yml`, `dsh-stderr.log`, `guard-journal.jsonl`,
`home-files.json`, `byq-agent-observer.js`) is kept **only locally** at
`/tmp/opencode/child-tool-count-raw-local-20261008/` and is **not** part of the repo evidence.

## Read-only localization of the delegate failure
Official source (`@deepseek-ai/dsh-tool-subagent`, `lib/index.js`):
- The delegate tool mounts **only** when its provider is registered:
  `const present = runtimeCtx.subagents.getProvider(config.provider); if (present !== void 0) mount(present); else logger.info(\`subagent provider "${config.provider}" not registered yet; the "${config.toolName ?? "subagent"}" tool will register when it appears\`)`.
- Foreground vs background: `resolveDelegationRun` returns
  `runInBackground = request.run_in_background ?? options.continuable`; with `run_in_background:false`
  the tool should call `runtimeCtx.subagents.start("spawn", …)` and wait
  (`settleForegroundRun`).
Official source (`@deepseek-ai/dsh-subagent-spawn-in-process`, `inject:["subagents"]`,
`providerName:"spawn"`; `subagent-in-process-driver`): a child is created via
`parent.ctx.agents.create({sessionId: childId, parentAgent: parent, …, setup})` and is **published**
in the `agents` registry; the docs state each child gets a **new flat scope** and the root-composition
`agent/created` listener sees root and child Agents.

Two candidate causes remain, and this run **cannot** disambiguate them:
- **(a) provider/tool not mounted — UNSUPPORTED by fixed source (corrected):** the independent Tester
  found that the shipped `acp` profile registers the spawn provider: base bundle
  `packages/bundle/base/cordis.patch.yml:352-355` actively registers
  `subagent-spawn-in-process` (`providerName: spawn`), and the shipped `acp` profile includes
  `dsh-base`; the product patch/probe overlay does not disable it, and `dsh-stderr.log`'s
  non-activation list is only typert/typert-loader/typert-gateway/authorization. So cause (a) is
  **downgraded to unsupported**, not a live candidate.
- **(b) foreground child creation failed before publishing:** `agents.create` rejected before the
  child was published (the driver: "rejection means the unpublished creation transaction reached
  quiescence without publishing a child"), or a probe/overlay effect suppressed it.
The tool **result / error** and DSH **info** logs were not captured by the probe, so the exact
failing parameter/official return is **UNKNOWN** from these artifacts.

## Independent Tester (raw + fixed source) — verdict
**NOT_PROVEN confirmed** (not PASS, not FAIL). Guard/journal/child-absence/`mcp_calls=0` claims all
PASS and exact; reduced observer contains no memory/context/prompt snapshot; no secrets in the repo
evidence dir. Fixed source confirms OFFICIAL-BEHAVIOR for (i) delegate-tool mount gating on provider
presence, (ii) `run_in_background = request.run_in_background ?? continuable` and foreground
`subagents.start`, (iii) in-process child via `parent.ctx.agents.create`, and (iv) spawn-provider
membership in the shipped acp profile. The only correction applied was downgrading cause (a) above.

## Classification (explicit)
- **Helper failure (not official):** earlier inserted `file://` temp `.mjs` observer import failure.
- **Official behavior (read from fixed source):** tool-subagent mount gating on provider presence;
  in-process child creation via `agents.create`; `run_in_background` default = `continuable`.
- **UNKNOWN:** why no child was published here (cause (a) vs (b)); why `mcp_calls = 0` (admitted tool
  names did not execute at MCP).

## Minimal next decision (NOT implemented)
Either (i) capture the `byq_delegate_market_research` tool result + DSH info/stderr and the session
header (`origin=subagent`/`parentSession`) in one future probe — the `spawn` provider row is already
confirmed present in the shipped `acp` profile, so the open question is the child-creation outcome,
not provider registration — or (ii) treat child tool-count coverage as an accepted **NOT_PROVEN**
boundary for this candidate. Do not expand implementation now.

## Boundaries
No push/PR/merge/deploy/default/release/tag/Phase. No business/permission/recovery change. No DSH
fork/patch. No external or paid BYQ model. Old unknowns (`task_af01e6ea`/`root41d492`) untouched. The
two-workspace shared-volume alias is a candidate isolation-boundary observation, **not** a two-user
file-isolation PASS.
