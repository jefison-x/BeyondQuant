# Independent Reviewer — probe change (child tool-count, next slice)

Read-only. Verdict: **probe-only change OK**; no DSH source, product patch, guard plugin, or
business/permission/recovery contract/default touched.

## Exact change (probe-only) vs the prior NOT_PROVEN probe
- Fake MCP `tools/list` expanded 8 → 15 (added the 7 names the prior run failed on:
  `byq_market_daily`, `byq_market_valuation`, `byq_market_fundamentals`, `byq_experiment_create`,
  `byq_artifact_create`, `byq_web_evidence_create`, `byq_workflow_card_propose`).
- Delegate args made schema-correct: `{description, prompt, run_in_background:false}`.
- Added capture: provider catalogs + bounded messages → persisted `tool_role_messages`,
  `provider_catalogs`, `created_session_headers`, full DSH stderr copy.
- Observer narrowed to identity/parent/tool fields (`hint()`); dropped the raw agent-object snapshot.
- `PRODUCT_PATCH`/`PLUGIN` read-only; writes only to output dir + temp `DSH_HOME`.

## Tool-set check
`delegate-market-research.toolFilter.allow` (patch.yml) has 16 entries; minus DSH-native `web_search`
= 15; the probe advertises exactly those 15. No missing/extra. Corroborated by the child provider
catalog (15 MCP + `web_search`).

## Guard-admit anti-pattern
Avoided: `PROBE_OK` requires a real child id, child `exec.agent` tool events, and `mcp_calls>=1`.

## Overclaim / wording (corrected)
The label "shared 16/17 boundary" was ambiguous. Corrected in `RESULT.md` to: process-global
root-inclusive 16-tool ceiling — 1 root delegate + 15 of 17 requested child MCP calls admitted; the
16th child call blocked with `BYQ_CONTINUATION_TOOL_LIMIT`; the 17th never reached.

## Residual risk
- Keyless/synthetic only (identity plugin disabled, count-only guard); properly disclaimed. Not an
  overall qualification / default upgrade.
- Diagnostic run's source revision not separately retained (fixed by a provenance note in
  `RESULT.md`).
