# DeepSeek Harness SDK rc.6 Research

## 证据与版本 policy

Research date: 2026-08-15。本文 source of truth 为 official npm registry、PyPI artifacts、installed wheel contents 和 official `deepseek-ai/deepseek-harness` repository。

| Artifact | Exact version | Evidence |
| --- | --- | --- |
| npm `@deepseek-ai/dsh` | `0.1.0-rc.6` | npm `latest`/`next` 均解析为 rc.6；SHA-512 `sha512-brpZfED7ieRa2PQ5tUxMhHrM1pb2CmKFVM/f6yMULBDMicahk+Z2OsHgTwTDnoiZm23Ftu9rQz0NN4pflaoJcg==` |
| PyPI `deepseek-harness-sdk` | `0.1.0rc6` | wheel SHA-256 `8a05421be4298196cf94383e0a3164b020f5f5977a8d30019cc5add64cb208eb` |
| PyPI `deepseek-harness-runtime-bin` Linux x64 | `0.1.0rc6` | wheel SHA-256 `d7261d3bdadfa8d10ab03fd06c6bbc66a182ae27d39892a0eb7c2ce9d63a5448` |

完整 PyPI wheel hashes：

- SDK `deepseek_harness_sdk-0.1.0rc6-py3-none-any.whl`：`8a05421be4298196cf94383e0a3164b020f5f5977a8d30019cc5add64cb208eb`；
- Linux x64：`d7261d3bdadfa8d10ab03fd06c6bbc66a182ae27d39892a0eb7c2ce9d63a5448`；
- Linux arm64：`99d0ef334a4e3cb178d7b0302bbdd01c8dde6068ee5fe8b01e074541db5c7747`；
- macOS arm64：`2bbd65edd52dfc340d74f88a890e8031a272a820e58406c2de1f5f5dee51bd9f`。

npm spelling `0.1.0-rc.6` 与 PEP 440 `0.1.0rc6` 有意保持不同。BYQ 保留 Phase 5 npm baseline，不自动跟随新 release。

```text
deepseek-harness-sdk==0.1.0rc6
  └── deepseek-harness-runtime-bin==0.1.0rc6
        └── explicit BYQ npm runtime packages @deepseek-ai/*@0.1.0-rc.6
```

Official metadata：npm package source 为 `https://github.com/deepseek-ai/deepseek-harness` 的 `apps/cli`；PyPI SDK 同源；SDK/runtime wheel `Requires-Python >=3.10`；SDK dependencies 为 `deepseek-harness-runtime-bin==0.1.0rc6` 和 `pydantic>=2.12,<3`，runtime wheel 无 Python runtime dependencies。

Prototype 使用的其他 rc.6 protocol artifacts 均 exact-pin：`@deepseek-ai/dsh-sdk-jsonrpc-server@0.1.0-rc.6`、`@deepseek-ai/dsh-sdk-jsonrpc-demo@0.1.0-rc.6`、`@deepseek-ai/dsh-sdk-client@0.1.0-rc.6`、`@deepseek-ai/dsh-mcp-client@0.1.0-rc.6`。Explicit composition 还 pin `@deepseek-ai/dsh-session-persistence-jsonl@0.1.0-rc.6` 和 `@deepseek-ai/dsh-session-checkpoint-policy@0.1.0-rc.6`；integrity 分别为 `sha512-US9Q4b5CZJPRRqa/M+WESL5VAOLjfYWjdzb3TQ/7zmpR4/+EQWCOFA9CtDSMh4t1oFOQBjz2+YJJcGu59MKHDA==`、`sha512-wdWNyS/95wI3QB9SHeeeQ9HDIWeFQKInI54Wqlw35H+bGGjGZE92nx9QiqiiosoxHedQFBdA0TKgON4EIoxCgg==`。

## Installed wheel introspection

SDK wheel 含 `deepseek_harness/api.py`、`client.py`、`models.py`、`errors.py`。Linux x64 runtime wheel 含一个 executable `deepseek_harness_runtime/runtime/dsh-jsonrpc-agent-pkg-linux-x64` 和 checked-in `runtime/cordis.yml`。

SDK 管理带 stdin/stdout/stderr pipes 的 `subprocess.Popen` child。Reader thread 将 stdout 作为 JSON-RPC line transport；stderr 只保留有界 diagnostic tail。SDK 不把 stdout 当 application logs。

Installed `runtime/cordis.yml` 含 JSON-RPC server、agent spine demo、DeepSeek LLM、JSONL persistence/checkpoint policy 和 local subprocess/bash/filesystem providers，但 wheel/package manifest 不含 `@deepseek-ai/dsh-mcp-client`。Installed artifact 对 BYQ compatibility 具有权威性，故 bundled closure 记录为 **MCP client absent**。

## rc.6 JSON-RPC carrier verification

2026-08-15 重新查询 official npm metadata；`@deepseek-ai/dsh` 的 `latest`/`next` 仍是 `0.1.0-rc.6`。`@deepseek-ai/dsh-sdk-jsonrpc-demo@0.1.0-rc.6` public metadata 声明：

```text
bin: dsh-jsonrpc-agent -> lib/bin.js
exports: ./bin -> ./lib/bin.js
exports: ./packaged-bin -> ./lib/packaged-bin.js
```

Installed rc.6 artifact 通过两个 entrypoints 使用 BYQ composition/healthy MCP 运行，均完成 SDK initialize、通过 keyless idle probe 并 clean close。Selected carrier 是 public `dsh-jsonrpc-agent`（`lib/bin.js`），因为它在无 packaged-runtime base override 下加载 exact BYQ composition 并保留 public package contract。`packaged-bin.js` 只作 rc.6 compatibility probe。

Public bin 仍 exact-pin rc.6 并由 runtime launch/initialize smoke 保护。未来 DSH release 改变 carrier behavior 时需要独立 compatibility decision；BYQ 不把 public bin 当永久 production guarantee。

## Public Python SDK capability inventory

### High-level API

- `DeepSeekHarness` 管理可复用 runtime subprocess 并 lazy start。
- `DeepSeekHarnessConfig` 支持 provider、model、token cap、cwd、`session_root`、custom Cordis、environment、`runtime_bin`、`launch_args_override`、request/shutdown timeout、base URL、API key。
- `HarnessClient` 是 lower-level stdio JSON-RPC client。
- `Session.run()` 发送 prompt，等待下一次 whole-agent idle notification。
- `session_prompt()` 立即返回 `MessageId` enqueue receipt。

### Notifications 与 session events

SDK 暴露 `Notification(method, payload)`、subscriptions、callback delivery、`next_notification()`，至少识别 `session.status`（含 `idle`）、`session.event`、`subagent.started`、`subagent.finished`。High-level API 保留 descendant ancestry，并按 wire order 交付 root/known descendants notifications。`RunResult.events` 只含 root session events；这是 adapter input，不是 BYQ public contract。

### Persistence、diagnostics 与 lifecycle

- `session_root` 作为 `DSH_SESSION_ROOT` 传入；persistence 留在 DSH runtime。
- `request_timeout_seconds` 限制 JSON-RPC wait，并在 timeout 附 runtime diagnostics/stderr tail；不取消已 queued/running work。
- `close()` 请求 protocol `shutdown`、关闭 stdin；child 存活则 terminate，超过 shutdown timeout 后 kill/reap。
- `runtime_bin` 选择 executable；`launch_args_override` 选择显式 argv，例如 `(node, packaged-bin.js)`。
- Low-level client 有 `bridge_bin`，但 BYQ 未选择 bridge。
- `cordis`/`DSH_CORDIS_CONFIG` 选择 runtime composition；显式 `launch_args_override` 禁用 bundled zero-config injection。

### JSON-RPC direction 与 stdout ownership

Protocol 是基于 stdio 的双向 JSON-RPC。Runtime 发送 notifications，也可发送 server requests；SDK 为反向调用暴露 `next_request()`、`respond()`、`respond_error()`。Server/client request capability 是未来 approval-flow seam，不是完整 rc.6 BYQ approval implementation。全部 runtime stdout 保留给 protocol frames。

## 影响 BYQ 的 rc.6 limitations

- 无 prompt cancellation method；
- 无 per-session close method；
- 无 protocol version negotiation；
- `session/prompt` 仅返回 `MessageId` enqueue receipt；
- `Session.run()` 覆盖 durable inbox receipt 到下一 whole-agent idle；当 queued work/steering 参与时，result 无法因果归属单个 prompt；
- request timeout 不停止 running prompt；
- runtime results/notifications 归 subprocess 所有，Gateway 使用前必须转换；
- stdout 不能承载 diagnostics/logs；
- future approval flow 的 server/client request capabilities 不完整。

因此 Phase 6 初始 lifecycle 采用每个 active BYQ session 一个 runtime process。Hard cancellation 是关闭/终止 adapter-owned process，不虚构 prompt cancel acknowledgment。

## Official TypeScript client 对比

`@deepseek-ai/dsh-sdk-client@0.1.0-rc.6` 是 TypeScript counterpart，使用相同 `DeepSeekHarness`/`HarnessClient` stdio JSON-RPC，并有 EOF → SIGTERM → SIGKILL disposal ladder。它没有 executable，要求相同 protocol/runtime composition；integrity 为 `sha512-7y8+dsTljsvHpyZeENeTcUNyxComHlawF8txGdCXxp0VsDt38aKYai8tqdOIrltKAZthmsmj80XuNtmQZxWRlw==`。

TS client 技术可行，但 Python Gateway 需要 Node adapter/sidecar 或 Node Gateway boundary，增加 process/service 与第二 application-language seam，却不改善 rc.6 protocol。

## Official source links

- Python SDK metadata: `https://pypi.org/pypi/deepseek-harness-sdk/0.1.0rc6/json`
- Runtime metadata: `https://pypi.org/pypi/deepseek-harness-runtime-bin/0.1.0rc6/json`
- Python SDK source: `https://github.com/deepseek-ai/deepseek-harness/tree/master/python/sdk`
- Runtime composition source: `https://github.com/deepseek-ai/deepseek-harness/blob/master/python/sdk-runtime/package.json`
- JSON-RPC server package: `https://www.npmjs.com/package/@deepseek-ai/dsh-sdk-jsonrpc-server`
- TypeScript client package: `https://www.npmjs.com/package/@deepseek-ai/dsh-sdk-client`
