# rc.2 keyless child tool-count proof — bounded PASS (2026-10-08, next slice)

Status: **bounded PASS for the child tool-count proof** (keyless, isolated candidate, no external
model, no DSH fork/patch, no business/permission/recovery change). This is **not** an overall
single-version qualification and not a default-upgrade authorization. It does not overwrite the
prior NOT_PROVEN record (`../child-tool-count-20261008/`).

Pinned source commit `639ed015397290b3745d163aafe02ffee4aa3f84`. Image `byq-acpf6-runtime-adapter:latest`
(`sha256:c324ef803409c0a38e9c34b68bcc847942614eb1e907d13ac2b0a30952b1b0b9`). Probe:
`probe_delegate_capture.py`.

## Run 1 — diagnostic (`diagnostic-run/`)
One keyless run captured the REAL `byq_delegate_market_research` tool result (bounded, synthetic) and
the provider catalogs. `delegate_in_catalog=true`; catalog-derived tool name used. The delegate tool
RAN foreground (`run_in_background:false`) but child creation aborted before publishing, tool-role
message at provider request n=2:

```
Error: tools.restrict() names unknown global tools "mcp__byq__byq_market_daily",
"mcp__byq__byq_market_valuation", "mcp__byq__byq_market_fundamentals",
"mcp__byq__byq_experiment_create", "mcp__byq__byq_artifact_create",
"mcp__byq__byq_web_evidence_create", "mcp__byq__byq_workflow_card_propose";
known global tools: <the fake MCP subset + DSH built-ins>
```

Cause (specific): the delegate child `toolFilter.allow` (product patch) names BYQ MCP tools that the
probe's **fake MCP `tools/list` did not advertise**, so the child's scoped `tools.restrict()` failed.
This is a **probe/fake-MCP helper input bug**, not an official DSH behavior gap and not a permission
contract issue. In the same run `mcp_calls=15` (real MCP requests) — confirming that using the ACTUAL
catalog tool name reaches MCP (the earlier `mcp_calls=0` was the guessed-name effect).

## Minimal fix (probe-side only)
Advertise, in the fake MCP `tools/list`, **every** name in the delegate child `toolFilter.allow`
(the 7 missing tools added). No DSH source, no composition semantics, no business/permission change.
Also (already in the probe) the delegate call now matches the official schema: `description`
(REQUIRED) + `prompt` + `run_in_background:false`.

## Run 2 — targeted verification (`raw/`) — PASS
One keyless run after the fix. `PROBE_OK True`. Exact evidence:

| Requirement | Observed |
|---|---|
| real child Agent id | **`0b44497d-89a4-45c9-9833-ea841b0c87d3`** (`agent/created`, distinct from root) |
| parent/root relationship (durable session state) | child session header `origin:"subagent"`, `parentSession:"1855c433-d6f1-4599-9063-555ef8b26db0"` (root), `delegationDepth:1` |
| child `tools/pre-execute` `exec.agent` | **15** child tool events, all `agentId = 0b44497d…` |
| real local MCP requests | `mcp_calls=15`, `mcp_tool_names` = 15 × `byq_research_get` |
| shared process-global 16-tool ceiling (root-inclusive) | 1 root `byq_delegate_market_research` + **15 of 17** requested child `byq_research_get` admitted (journal admitted **16**); the **16th child call** blocked with `BYQ_CONTINUATION_TOOL_LIMIT`; the 17th requested child call never reached |
| observer | `observer.apply` + 2 `agent/created` (root + child) + 16 `tool` |

`provider_requests=2`: request 1 = root delegate, request 2 = child tool turn (real catalog names
`mcp__byq__byq_research_get`). Tool-role delegate error is empty in this run (child created).

Guard-admit is **not** used as success: PASS requires the real child id, the child `exec.agent`
events, and real MCP calls (`mcp_calls>0`).

## Boundaries
- Child tool-count coverage now bounded-PASS for this keyless candidate; not an overall qualification
  and no default/promotion. Single-version default remains the SDK rollback.
- No push/PR/merge/deploy/default/release/tag/Phase; no BYQ paid model; no external model/network in
  the probe; no DSH fork/patch; no business/permission/recovery change.
- Old unknown `task_af01e6ea`/`root41d492` untouched. The two-workspace shared-volume alias remains a
  NOT_RUN isolation boundary, not a two-user file-isolation PASS.
- Persisted observer samples contain only `event/agentId/source/tool/sessionHeader` (no agent memory,
  no runtime prompt, no secrets).

## Runs and provenance
- **Run 1 (diagnostic)** used the probe's initial fake-MCP set (8 MCP tools); its
  `diagnostic-run/probe-result.json` catalog shows exactly those 8, and the delegate error's "known
  global tools" list matches it. The only source change to the persisted `probe_delegate_capture.py`
  is the fake-MCP set 8 → 15 (adding the 7 child-filter tools); the diagnostic run is otherwise the
  same probe. No Run-1 source revision was separately retained (provenance from the captured
  catalog).
- **Run 2 (verification)** used the persisted probe with the 15-tool fake-MCP set.

## Independent verification
- Independent Tester (raw + fixed source): `TESTER.md` — all checks PASS.
- Reviewer of the probe change: `REVIEWER.md` — probe-only change verified; wording correction applied.
