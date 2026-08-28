# Phase 63 qualification report

Date: 2026-08-28

Profile: `research`

Composition hash: `sha256:1f4e0f6edd42e678f4b73a54076aa33c89a77c0f07d81b0fe5c4d99bbf44a608`

## Results

| Plugin | Version | Qualification | Enabled | Risk | Allowed Agent | Decision evidence |
| --- | --- | --- | --- | --- | --- | --- |
| Web Search | `0.1.1-rc.1` | QUALIFIED | yes | MEDIUM | Quant Orchestrator, Market Research | exact closure; search-only initialize; bounded tool; fetch disabled; keyless registration |
| Guard | `0.1.1-rc.1` | QUALIFIED | yes | LOW | all Product agents | repeat advisory preserves downstream block/result; cooperative timeout normalizes `TOOL_TIMEOUT` |
| Compaction | `0.1.1-rc.1` | QUALIFIED | yes | LOW | all Product agents | exact peers/exports; generated Cordis initialize; context-only semantics |
| Spill | `0.1.1-rc.1` | BLOCKED | no | HIGH | none | local write/path exposure and no adequate rc.1 session/age cleanup |
| Interaction | `0.1.1-rc.1` | BLOCKED_BY_RUNTIME_VERSION | no | MEDIUM | none in Product | no qualified Python SDK/JSON-RPC question-answer lifecycle |

`web_search` is present only in the Market Research subagent `toolFilter.allow` among specialist
agents. Factor Research, Strategy Research and Backtest Analysis do not receive it. The rc.1 root
registry has no separately proven root filter, so Quant Orchestrator access is explicit in the
registry rather than obtained through implicit inheritance.

## Required validation evidence

- Registry/schema negative cases and deterministic generation:
  `tests/test_dsh_plugin_registry.py`.
- Architecture/online-install/MCP/source-write boundary:
  `tests/architecture/test_architecture.py`.
- Exact Python/npm closure and no prerelease mixing: `tests/test_dsh_upgrade.py`, runtime manifest
  and lockfile.
- Official Guard behavior and Compaction/Web exports:
  `services/runtime-adapter/runtime/verify-qualified-plugins.mjs`, executed during image build.
- Public identity/readiness secret filtering:
  `services/runtime-adapter/tests/test_plugin_identity.py`.
- Real keyless composition initialize, health, session lifecycle, MCP path and cleanup:
  `scripts/evidence/phase63-runtime-smoke.py`, executed in a named isolated Compose stack.

The isolated run built the exact lock, initialized the generated composition, created and released
a dedicated DSH session, reported the same profile/hash before and after Runtime Adapter restart,
kept `/app`, `/opt/dsh-runtime` and `/opt/byq` non-writable, and passed the live MCP contract suite.
The named test containers, images, network and volumes were removed after validation.

No credentialed Web Search was run or made required for CI. The optional live smoke must receive a
secret from operator environment, must not log it, and must not use live search content as a golden
fixture.
