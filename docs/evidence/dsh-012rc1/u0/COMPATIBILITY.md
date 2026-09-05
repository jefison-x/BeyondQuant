# DSH 0.1.2rc1 compatibility inventory

Date: 2026-09-06

## Current observed baseline

The running Runtime Adapter was queried read-only. It remained healthy on image
`sha256:301bcd5ac3e7d26a6b61f4f5646ad44409e50f2cd3ab058a37b2bb5605a980ea`
(`beyondquant-runtime-adapter:6168fde`) with:

- `deepseek-harness-sdk==0.1.1rc1` and `deepseek-harness-runtime-bin==0.1.1rc1`;
- explicit old entry point `/opt/dsh-runtime/node_modules/@deepseek-ai/dsh-sdk-jsonrpc-demo/lib/bin.js`;
- profile `research`, composition hash
  `sha256:b8530afdc5b28ee18a132dd1616d841eaa6d803d975e7110e556183b29a214bf`;
- qualified/enabled registry capabilities `compaction`, `guard`, `web-search`; `interaction` and
  `spill` remain blocked and disabled;
- one owned DSH process per active session, with zero active sessions/model calls at observation;
- lifecycle defaults 900 seconds whole-run, 180 seconds child and 120 seconds no-progress;
- MCP backtest analysis page-call limit 6. The normal bounded-exhaustion behavior remains part of
  the existing contract.

No secret value, complete environment or production conversation was collected.

## Public SDK and launcher mapping

| 0.1.1rc1 BYQ surface | 0.1.2rc1 public replacement | U0 decision |
|---|---|---|
| `cordis` | `profile` plus ordered `patches` | MIGRATE; generate a BYQ safe patch over official `sdk` |
| `session_root` | explicit `dsh_home` and patch `dshHomePath('sessions')` | MIGRATE; one contained home per release/generation |
| `launch_args_override` | `dsh_bin`, `profile`, `patches`, `dsh_home`, `cwd`, `runtime_cwd` | MIGRATE; no private argv mutation |
| old demo binary path | bundled official `dsh` executable | REMOVED; never retain the old demo path |
| private `_launch_args` / `_proc` access | public config, notifications, receipt and `close()`/protocol shutdown | no production private dependency accepted |

The public CLI grammar is `dsh --profile <name> [--patch <path> ...]`. Resolution order is bundled
profile, profile patch, explicit home patch, then argv patches. BYQ must always pass an explicit
`DSH_HOME`/SDK `dsh_home`; it must not discover or mutate implicit `~/.dsh`. The U0 spike proved
initialize, prompt receipt, notification subscription, root/child events and protocol shutdown.
The SDK client tracks `subagent.started` parent/child relationships. Final answer and finish reason
are public high-level result fields; raw activity normalization remains Adapter-internal.

## Loaded plugin migration map

`SAME` means the exact package/export and needed public hook exist. It does not copy the old
qualification status. `MIGRATE` means a public replacement exists but config/placement must change.

| Current loaded row/package | 0.1.2rc1 mapping | Class | Required follow-up |
|---|---|---|---|
| `dsh-sdk-jsonrpc-server` | same package in `dsh-sdk-app` profile | SAME | exercise SDK contract in U4 |
| `dsh-agent-spine-demo` | official `dsh-base` bundle + `dsh-sdk-app` | REMOVED/MIGRATE | delete one-to-one demo assumption; patch official host |
| local `byq-runtime-time-context.js` | same public `systemPrompt.context` hook | SAME | package as explicit read-only BYQ plugin; fix ESM metadata warning |
| `dsh-llm-pi-ai` | same package | SAME | preserve fixed provider/model allowlists and credential references |
| `dsh-skill`, `dsh-skill-filesystem`, `dsh-tool-skill` | same packages | SAME | `includeDefaultRoots:false`, fixed custom directory, `watch:false` |
| `dsh-subagent`, `dsh-subagent-spawn-in-process` | same host packages | SAME | keep host registry/provider outside per-agent presets |
| `dsh-tool-subagent` role rows | same package; `backgroundMode` is explicit | MIGRATE | use `backgroundMode:one-shot` and `enableRunInBackground:false`; contract-test foreground/maxDepth/tool filter |
| compaction basic/pruner/token meter | same packages | SAME | requalify exact new package/config behavior |
| repeat reminder/timeout policy | same packages | SAME | requalify; preserve BYQ watchdogs independently |
| `dsh-tool-web`, `dsh-web-search-deepseek`, `dsh-web` | same packages | SAME | keep search-only, fetch disabled, bounded queries; requalify |
| JSONL persistence/checkpoint | same packages | MIGRATE | root derives from explicit release/generation home; no old log migration |
| `dsh-mcp-client` | same public package/config | SAME | retain `failOnStartupError:true`, headers and 60-second initialization policy |

There are no unresolved `UNKNOWN` items blocking the carrier decision. U4 still owns full role-by-role
roster and behavior qualification. `interaction` and `spill` remain disabled; 0.1.2rc1 package
availability alone does not authorize them. External Agent providers, shell, editor, filesystem,
jobs, web fetch, workflow/todo/goal/ralph and plan-mode tools remain outside Product scope.

## Installed versus enabled

The bundled closure includes many packages not enabled by the effective BYQ patch, including shell,
editor, filesystem, job, ACP, workflow, telemetry and web-fetch capabilities. The unpatched `sdk`
profile is therefore unsafe as a Product profile. The official `sdk-minimal` profile is also not
acceptable because its intended tool set includes persistent shell/editor and danger-full-access.
U4 must fail closed if the generated safe patch is absent or if actual runtime roster differs from
the release descriptor; installed package inventory is never used as the capability decision.

## Provenance and rolling compatibility

The trusted evidence producer identity must come from a deployment-controlled release descriptor,
its built-image receipt/attestation, Runtime Adapter installed metadata and active composition/policy
hash—not a model argument or arbitrary `runtime_version` field. MCP/Backend may accept only the
explicitly enabled compatibility-family members. U2 must demonstrate old-runtime/new-policy rolling
write compatibility, exact candidate binding, forged/unknown producer rejection, and continued read
of historical valid artifacts. Candidate qualification does not change the production default.
