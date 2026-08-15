# DeepSeek Harness SDK rc.6 research

## Evidence and version policy

Research date: 2026-08-15. The sources of truth for this note are the
official npm registry, PyPI artifacts, the installed wheel contents, and the
official `deepseek-ai/deepseek-harness` repository.

| Artifact | Exact version | Evidence |
| --- | --- | --- |
| npm `@deepseek-ai/dsh` | `0.1.0-rc.6` | npm `latest` and `next` both resolve to rc.6; SHA-512 integrity `sha512-brpZfED7ieRa2PQ5tUxMhHrM1pb2CmKFVM/f6yMULBDMicahk+Z2OsHgTwTDnoiZm23Ftu9rQz0NN4pflaoJcg==` |
| PyPI `deepseek-harness-sdk` | `0.1.0rc6` | wheel SHA-256 `8a05421be4298196cf94383e0a3164b020f5f5977a8d30019cc5add64cb208eb` |
| PyPI `deepseek-harness-runtime-bin` Linux x64 | `0.1.0rc6` | wheel SHA-256 `d7261d3bdadfa8d10ab03fd06c6bbc66a182ae27d39892a0eb7c2ce9d63a5448` |

The complete PyPI wheel hash inventory is:

- SDK `deepseek_harness_sdk-0.1.0rc6-py3-none-any.whl`:
  `8a05421be4298196cf94383e0a3164b020f5f5977a8d30019cc5add64cb208eb`.
- Runtime Linux x64:
  `d7261d3bdadfa8d10ab03fd06c6bbc66a182ae27d39892a0eb7c2ce9d63a5448`.
- Runtime Linux arm64:
  `99d0ef334a4e3cb178d7b0302bbdd01c8dde6068ee5fe8b01e074541db5c7747`.
- Runtime macOS arm64:
  `2bbd65edd52dfc340d74f88a890e8031a272a820e58406c2de1f5f5dee51bd9f`.

The npm spelling (`0.1.0-rc.6`) and PEP 440 spelling (`0.1.0rc6`) are
intentionally kept distinct. BYQ keeps the Phase 5 npm baseline and does not
follow a newer release automatically.

Version mapping used by BYQ:

```text
deepseek-harness-sdk==0.1.0rc6
  └── deepseek-harness-runtime-bin==0.1.0rc6
        └── explicit BYQ npm runtime packages @deepseek-ai/*@0.1.0-rc.6
```

Official metadata:

- npm package source: `https://github.com/deepseek-ai/deepseek-harness`,
  directory `apps/cli`.
- PyPI SDK source: `https://github.com/deepseek-ai/deepseek-harness`.
- SDK `Requires-Python`: `>=3.10`.
- SDK dependencies: `deepseek-harness-runtime-bin==0.1.0rc6` and
  `pydantic>=2.12,<3`.
- Runtime wheel `Requires-Python`: `>=3.10`; it has no Python runtime
  dependencies.

The other published rc.6 protocol artifacts used by the prototype are also
exact-pinned: `@deepseek-ai/dsh-sdk-jsonrpc-server@0.1.0-rc.6`,
`@deepseek-ai/dsh-sdk-jsonrpc-demo@0.1.0-rc.6`,
`@deepseek-ai/dsh-sdk-client@0.1.0-rc.6`, and
`@deepseek-ai/dsh-mcp-client@0.1.0-rc.6`. The explicit BYQ composition also
exact-pins `@deepseek-ai/dsh-session-persistence-jsonl@0.1.0-rc.6` and
`@deepseek-ai/dsh-session-checkpoint-policy@0.1.0-rc.6`; their npm integrity
values are `sha512-US9Q4b5CZJPRRqa/M+WESL5VAOLjfYWjdzb3TQ/7zmpR4/+EQWCOFA9CtDSMh4t1oFOQBjz2+YJJcGu59MKHDA==`
and
`sha512-wdWNyS/95wI3QB9SHeeeQ9HDIWeFQKInI54Wqlw35H+bGGjGZE92nx9QiqiiosoxHedQFBdA0TKgON4EIoxCgg==`.

## Installed wheel introspection

The installed SDK wheel contains `deepseek_harness/api.py`,
`deepseek_harness/client.py`, `models.py`, and `errors.py`. The runtime wheel
for Linux x64 contains one executable,
`deepseek_harness_runtime/runtime/dsh-jsonrpc-agent-pkg-linux-x64`, plus the
checked-in default `runtime/cordis.yml`.

The SDK owns a `subprocess.Popen` child with stdin/stdout/stderr pipes. The
reader thread treats stdout as JSON-RPC line transport; stderr is retained as
a bounded diagnostic tail. The SDK never treats stdout as application logs.

The installed `runtime/cordis.yml` contains:

- `@deepseek-ai/dsh-sdk-jsonrpc-server`;
- `@deepseek-ai/dsh-agent-spine-demo`;
- `@deepseek-ai/dsh-llm-deepseek`;
- JSONL session persistence and checkpoint policy;
- local subprocess, local bash, and local filesystem providers.

The installed wheel listing contains no `@deepseek-ai/dsh-mcp-client`. The
upstream `python/sdk-runtime/package.json` inspected at the same time also
contains no MCP client entry. The installed artifact is authoritative for BYQ
compatibility, so the bundled closure is recorded as **MCP client absent**.

## Public Python SDK capability inventory

### High-level API

- `DeepSeekHarness` owns a reusable runtime subprocess and starts it lazily.
- `DeepSeekHarnessConfig` supports provider, model, token cap, cwd,
  `session_root`, custom Cordis config, environment, `runtime_bin`,
  `launch_args_override`, request timeout, shutdown timeout, base URL, and
  API key.
- `HarnessClient` is the lower-level stdio JSON-RPC client.
- `Session.run()` sends a prompt and waits until the next whole-agent idle
  notification.
- `session_prompt()` returns immediately with a `MessageId` enqueue receipt.

### Notifications and session events

The SDK exposes `Notification(method, payload)`, subscriptions, callback
delivery, and `next_notification()`. It recognizes at least:

- `session.status`, including `idle`;
- `session.event`, with the nested runtime event;
- `subagent.started` and `subagent.finished`.

The high-level API retains descendant ancestry and delivers root and known
descendant notifications in wire order. `RunResult.events` contains only root
session events. This is useful input to the adapter, but it is not a BYQ
public contract.

### Persistence, diagnostics, and lifecycle

- `session_root` is passed as `DSH_SESSION_ROOT`; persistence remains inside
  the DSH runtime.
- `request_timeout_seconds` limits a JSON-RPC request wait and includes a
  runtime diagnostics/stderr tail on timeout. It does not cancel the runtime
  work already queued or running.
- `close()` requests protocol `shutdown`, closes stdin, sends terminate if the
  child remains alive, then kills after the configured shutdown timeout and
  reaps the process.
- `runtime_bin` selects one executable; `launch_args_override` selects an
  explicit argv tuple such as `(node, packaged-bin.js)`.
- `bridge_bin` exists on the low-level client, but no BYQ bridge is selected.
- `cordis` and `DSH_CORDIS_CONFIG` select runtime composition. Explicit
  `launch_args_override` disables bundled zero-config injection.

### JSON-RPC direction and stdout ownership

The protocol is bidirectional JSON-RPC over stdio. The runtime sends
notifications and may send server requests; the SDK exposes `next_request()`,
`respond()`, and `respond_error()` for that direction. The server/client
request capability is a future approval-flow seam, not a complete rc.6 BYQ
approval implementation. All runtime stdout is reserved for protocol frames.

## rc.6 limitations that affect BYQ

The following are current limitations, not planned features presented as
available behavior:

- no prompt cancellation method;
- no per-session close method;
- no protocol version negotiation;
- `session/prompt` returns only a `MessageId` enqueue receipt;
- `Session.run()` owns the interval from durable inbox receipt to the next
  whole-agent idle, so a returned result is not causally assigned to one
  prompt when other queued work or steering contributes;
- request timeout does not stop a running prompt;
- runtime results and notifications are subprocess-owned and must be
  translated before Gateway use;
- stdout cannot carry diagnostics or logs;
- server/client request capabilities for future approval flow are incomplete.

These limitations are why Phase 6 chooses one runtime process per active BYQ
session for the initial lifecycle model. Hard cancellation is process close or
termination of that adapter-owned runtime; it is not a fabricated prompt
cancel acknowledgment.

## Official TypeScript client comparison input

`@deepseek-ai/dsh-sdk-client@0.1.0-rc.6` is the TypeScript counterpart. Its
published package describes the same `DeepSeekHarness` and `HarnessClient`
over stdio JSON-RPC and includes an EOF -> SIGTERM -> SIGKILL process disposal
ladder. It has no executable of its own and requires the same protocol/runtime
composition. Its npm integrity is
`sha512-7y8+dsTljsvHpyZeENeTcUNyxComHlawF8txGdCXxp0VsDt38aKYai8tqdOIrltKAZthmsmj80XuNtmQZxWRlw==`.

The TS client is technically viable, but a Python Gateway would need a Node
adapter/sidecar or a Node Gateway boundary. That adds an extra process/service
and a second application-language seam without improving the rc.6 protocol.

## Official source links

- Python SDK metadata: `https://pypi.org/pypi/deepseek-harness-sdk/0.1.0rc6/json`
- Runtime metadata: `https://pypi.org/pypi/deepseek-harness-runtime-bin/0.1.0rc6/json`
- Python SDK source: `https://github.com/deepseek-ai/deepseek-harness/tree/master/python/sdk`
- Runtime composition source: `https://github.com/deepseek-ai/deepseek-harness/blob/master/python/sdk-runtime/package.json`
- JSON-RPC server package: `https://www.npmjs.com/package/@deepseek-ai/dsh-sdk-jsonrpc-server`
- TypeScript client package: `https://www.npmjs.com/package/@deepseek-ai/dsh-sdk-client`
