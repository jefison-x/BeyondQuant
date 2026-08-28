# Phase 63 upstream inspection

Inspection date: 2026-08-28. Source of truth was the official DeepSeek Harness GitHub
repository/releases, npm registry metadata, PyPI JSON metadata and the exact official rc.1 source
archive. No Community repository or database was modified.

## Baseline decision

| Surface | Latest observed | BYQ qualified baseline | Decision |
| --- | --- | --- | --- |
| GitHub release | `dsh-v0.1.2-alpha.1` | `dsh-v0.1.1-rc.1` | no upgrade |
| Python SDK | `0.1.1rc1` | `0.1.1rc1` | unchanged |
| Python runtime-bin | `0.1.1rc1` | `0.1.1rc1` | unchanged |
| npm DSH closure | newer prereleases observable | `0.1.1-rc.1` | exact rc.1 only |

The official rc.1 source archive SHA-256 was
`066bb6245f59ecbec835a45fa5bb84493ca445b121d21b36a55ff030ac4403ee`.
GitHub/npm releases newer than rc.1 cannot enter Product while a matching, fully qualified Python
SDK/runtime-bin pair is absent. Discovery did not authorize an Upgrade Lane.

Official metadata endpoints inspected:

- `https://api.github.com/repos/deepseek-ai/deepseek-harness/releases`
- `https://registry.npmjs.org/@deepseek-ai%2fdsh-*`
- `https://pypi.org/pypi/deepseek-harness-sdk/json`
- `https://pypi.org/pypi/deepseek-harness-runtime-bin/json`
- `https://github.com/deepseek-ai/deepseek-harness/tree/dsh-v0.1.1-rc.1`

## Sample source findings

### Web Search

Official rc.1 packages are `@deepseek-ai/dsh-web`,
`@deepseek-ai/dsh-web-search-deepseek` and `@deepseek-ai/dsh-tool-web`. Package exports and Cordis
requirements were inspected. `dsh-tool-web` independently gates search/fetch, so BYQ sets
`search: true` and `fetch: false`; the DeepSeek provider reads `DEEPSEEK_API_KEY` by reference.
Search results are non-authoritative research context, never deterministic Factor/Strategy/Backtest
input.

### Guard

`@deepseek-ai/dsh-repeat-tool-reminder` observes identical tool+canonical-argument chains and adds
plugin-labelled advisory context without rewriting the tool result or bypassing a downstream block.
`@deepseek-ai/dsh-tool-call-timeout-policy` is cooperative: it applies a declared per-tool deadline,
waits for the tool to honor `exec.signal`, restores the upstream signal and normalizes only its own
expiry as `TOOL_TIMEOUT`.

### Compaction

Inspected `@deepseek-ai/dsh-compaction`, `dsh-compaction-basic`,
`dsh-compaction-tool-result-pruner`, `dsh-token-meter` and command/peer requirements. Automatic
compaction and bounded tool-result pruning are composition-capable on rc.1. Their summaries/pruned
results are Agent context only, not BYQ Artifact, evidence, StrategyVersion or Backtest manifest.
CLI-only `/compact` UX is not exposed as a Product tool.

### Spill

Inspected `@deepseek-ai/dsh-spill`, `dsh-spill-local` and `dsh-spill-policy`. rc.1 spill-local writes
local files and returns a path with read/grep guidance, but does not provide the session/private,
age-bounded cleanup contract BYQ requires. Product DSH also intentionally lacks filesystem-read
tools. The capability is therefore `BLOCKED_BY_SECURITY_BOUNDARY`, not patched or enabled.

### Interaction

Inspected `@deepseek-ai/dsh-user-questions` and `dsh-tool-ask-user`. The packages exist at rc.1, but
the qualified Python SDK/stdio JSON-RPC path has no proven Product request/answer resume lifecycle.
It is `BLOCKED_BY_RUNTIME_VERSION`. Generic user agreement would not replace
`byq_agent_authorize`, owner/workspace policy, idempotency or audit even after a future qualification.

All recorded package versions and npm integrity values are in
`plugins/dsh-byq/registry/plugins.json`; the committed lockfile is the closure evidence.
