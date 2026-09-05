# DSH 0.1.2rc1 U0 carrier decision evidence

Date: 2026-09-06

Accepted by the maintainer under ADR-0058: **Option A**, the matching official PyPI
runtime wheel's bundled executable, launched through the Python SDK's public profile/patch/home
configuration. Option B (exact official npm `@deepseek-ai/dsh` CLI) is a viable fallback but is not
selected or retained as an implicit second runtime.

## Reproducible U0 spike

The downloaded Linux x86-64 SDK/runtime wheels identified in `UPSTREAM.md` were extracted into a
new temporary directory. The executable was invoked with the equivalent public command:

```text
DSH_HOME=<isolated-home> DSH_TELEMETRY_MODE=OFF \
  <wheel>/deepseek-harness-sdk-runtime-linux-x64 \
  --profile sdk --patch <isolated-safe.patch.yml>
```

The spike used only loopback scripted model/MCP servers, a synthetic key, a synthetic skill, the
actual BYQ trusted-time plugin and the exact released executable. It did not access a paid model,
production MCP, production credentials, default home, source write path or running service.
`--version`, `--help`, `--dump-default-config` and resolved `--dump-config` all succeeded.

The safe patch explicitly:

- disabled telemetry, approval/permission UI, bash/pwsh/jobs, filesystem/search, editor, plan,
  workflow/todo/goal/ralph, default subagent tools and web tool;
- limited skills to one explicit directory with default discovery and watch disabled;
- placed JSONL sessions below the explicit isolated home;
- loaded the actual BYQ dynamic Asia/Shanghai time-context plugin;
- loaded `dsh-mcp-client` with `failOnStartupError:true` against a loopback read-only fixture;
- added one one-shot, depth-one BYQ child whose allowlist contained only that MCP tool.

## Observed runtime result

- initialize returned server `deepseek-harness-sdk-runtime`;
- direct root MCP run produced a prompt receipt, `tool/call`, `tool/result` and terminal idle;
- delegated run produced `subagent.started`, child MCP execution, `subagent.finished`, root result and
  terminal idle;
- root model-visible roster was exactly `byq_delegate_probe`,
  `mcp__byq__readonly_status`, `skill`;
- child model-visible roster was exactly `mcp__byq__readonly_status`;
- forbidden shell/editor/jobs/filesystem/web-fetch/plan tools were absent;
- each model assembly received refreshed UTC/Asia-Shanghai/local-date context plus the explicit
  warning that wall time is not trading-session truth;
- protocol `shutdown` returned `{}` and the process exited `0`; loopback servers were stopped.

The DSH file-policy context still described the synthetic workspace as `workspace-write`, but the
effective roster contained no shell or file executor. The production U4 descriptor should also set
`DSH_PERMISSION_MODE=read-only` as defense in depth and prove a forbidden invocation cannot execute.
This is follow-up qualification, not permission to expose a file tool.

The only stderr finding was Node's module-type warning when the BYQ time plugin was loaded by an
absolute `.js` path without package `type: module`. It did not affect the hook and does not require
a private API; U4 should package the plugin with explicit module metadata so production is quiet.

## Why Option A passes U0

Option A has an exact official SDK/runtime pair and host-platform artifact, needs no system Node,
uses only documented launcher/SDK fields, supports explicit home and ordered safe patches, loads the
required BYQ plugin/MCP/skill/subagent seams, exposes an observable actual tool roster, and shuts
down under public protocol control. It avoids the old demo entry point and does not create a second
Agent harness.

Selection at U0 is a feasibility/architecture decision only. U1 must make release identity and
closure reproducible; U3/U4 must implement the compatibility adapter and generated production-safe
profile; U5/U6 must perform full qualification and rollback. Production remains on 0.1.1rc1.

## Rejected alternatives and stop conditions

- Do not use unpatched `sdk`, `sdk-minimal`, a coding profile or danger-full-access.
- Do not keep both wheel and npm carriers as runtime fallback.
- Do not call the removed `dsh-sdk-jsonrpc-demo`/`dsh-agent-spine-demo` paths.
- Do not use `_launch_args`, `_proc`, forced npm resolution, a DSH fork or another generic harness.
- Stop and return to 0.1.1rc1 if U1 cannot bind the bundled executable to auditable build metadata,
  or U4 cannot reproduce the exact safe roster, contained home and lifecycle without private APIs.
