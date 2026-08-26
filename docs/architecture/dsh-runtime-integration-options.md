# DSH Runtime Integration Options

## 状态

决策已记录于 [ADR-0003](adr/ADR-0003-gateway-dsh-runtime-integration.md)：exit criteria 通过后，**Accepted for Phase 6**。选定 seam 是独立 Python Runtime Adapter：使用 official Python SDK 启动显式 npm rc.6 JSON-RPC runtime composition。

DSH Web surface 仅用于 bootstrap/verification，不是 Gateway transport。本决策不包含 proxy、host networking、`socat`、`nginx`、source patch、fork 或 Web network exposure。

## 通用评估标准

每个 option 均按 stdio/process boundary、lifecycle、notification streaming、cancellation、persistence ownership、WorkflowTrace translation、MCP composition、Python Gateway cost、failure isolation、authentication、observability、horizontal scaling 和 DSH upgrade compatibility 评估。

## Option A：Python SDK 加 bundled runtime

```text
Gateway
  → dedicated Runtime Adapter
  → deepseek-harness-sdk==0.1.0rc6
  → deepseek-harness-runtime-bin==0.1.0rc6 executable
```

Official runtime wheel 已下载、hash-verified、解包并 introspect。Bundled config 包含 stdio JSON-RPC server/default agent spine，也挂载 local bash/filesystem providers；不含 `@deepseek-ai/dsh-mcp-client`。

SDK API 允许 custom Cordis path，但 custom composition 不能加入 single-file runtime closure 中缺失的 package。为加入 MCP client 重建 upstream runtime wheel 等同 fork/rebuild DSH，属于禁止行为。

结果：**Product runtime 拒绝采用。**

1. Zero-config composition 具备 coding capability，违反 BYQ Product capability boundary；
2. bundled closure 缺少必需 BYQ MCP client；
3. 添加它要求 rebuild/fork official runtime carrier。

Wheel 仍可作为 official SDK capability reference/upgrade compatibility input，但 BYQ Runtime Adapter 不使用 `DeepSeekHarness()` zero-config。

## Option B：Python SDK 加显式 npm rc.6 runtime

```text
Gateway
  → internal HTTP/SSE BYQ seam
  → Product Plane Runtime Adapter (Python/FastAPI)
  → deepseek-harness-sdk==0.1.0rc6
  → launch_args_override: node + dsh-sdk-jsonrpc-demo/lib/bin.js (dsh-jsonrpc-agent)
  → exact npm rc.6 JSON-RPC runtime
      ├── @deepseek-ai/dsh-sdk-jsonrpc-server@0.1.0-rc.6
      ├── @deepseek-ai/dsh-agent-spine-demo@0.1.0-rc.6
      ├── @deepseek-ai/dsh-session-persistence-jsonl@0.1.0-rc.6
      └── @deepseek-ai/dsh-mcp-client@0.1.0-rc.6
          ↓
       BeyondQuant MCP
```

BYQ composition 为 `plugins/dsh-byq/compositions/byq-product-sdk.cordis.yml`。它禁用 `toolBash`、`toolJobs`、skills、workspace context、goals；不含 coding executor、source filesystem、Git 或 Engineering DSH plugin。它挂载 official JSON-RPC server、DSH-owned JSONL persistence/checkpoint policy，以及带 `failOnStartupError: true` 的 exact BYQ MCP client。

Runtime Adapter 从不调用 zero-config `DeepSeekHarness()`。它提供 `cordis`、`session_root`、`launch_args_override`，绕过 SDK bundled default injection。`runtime_bin` 作为 documented SDK option 保留，但不用于 Product operation。

Rc.6 `dsh-jsonrpc-agent` public bin 已针对 exact BYQ composition/healthy MCP 测试并通过 initialize/idle/close。`packaged-bin.js` 也作对比 probe，但不是 selected carrier。二者均为 exact rc.6 artifacts，不承诺未来 DSH compatibility。

### Prototype 结果

Installed npm rc.6 artifact 使用 public `lib/bin.js` 和 exported `packaged-bin.js` 运行，观察了 profile/config introspection 与 JSON-RPC behavior。初始 composition 暴露真实配置错误（`skills: false` 应为 rc.6 schema 的 `skills.enabled: false`）；修正后 runtime 在无 model key 时返回有效 `initialize`/clean `shutdown`。

Containerized Runtime Adapter 随后完成：

1. `POST /internal/runtime/sessions`；
2. official Python SDK initialize owned explicit npm runtime；
3. rc.6 MCP client 以 `failOnStartupError: true` 连接 healthy BeyondQuant MCP；
4. `POST .../cancel?mode=hard`；
5. clean status `interrupted`，且 `process_ownership: dedicated`、`persistence: dsh-owned`。

第一次 exact composition 还发现 closure 问题：published JSON-RPC demo 不会 transitively install composition 指定的 session persistence/checkpoint packages。Adapter npm manifest 现 direct-pin 两个 official rc.6 packages；重建 container 通过 SDK initialize、存活超过 700ms，并在无 stderr load error 下 hard-cancel。该 artifact introspection 属于 compatibility gate，不是隐藏 runtime patch。

这是 keyless startup/handshake smoke，不声称真实 model turn 或 model-generated answer。`byq_health` MCP contract 仍由 MCP contract tests 覆盖；rc.6 没有稳定 non-LLM SDK tool invocation API。

结果：**Selected。** 这是唯一无需 fork/rebuild DSH、满足 explicit composition gate 且保留 Python Gateway integration 的 option。

## Option C：TypeScript SDK 加显式 npm runtime

`@deepseek-ai/dsh-sdk-client@0.1.0-rc.6` 是同一 stdio JSON-RPC protocol 的 official TypeScript client。实际 rc.6 artifact 管理 child process，暴露 `DeepSeekHarness`/`HarnessClient`，分发 notifications，并执行 EOF → SIGTERM → SIGKILL cleanup。没有独立 remote protocol/cancellation capability，继承相同 runtime limits。

它要求 Node Gateway、Node adapter service，或 Python adapter 拥有的第二 Node sidecar；都会增加 language/process boundary、dependency alignment 和 observability/lifecycle surface，且 event/process behavior 对当前 Python Gateway 并无优势。因此 **not selected**；若未来 BYQ 采用 Node Gateway boundary，可作为 compatibility option。

## 比较矩阵

| Criterion | A: bundled Python | B: explicit npm + Python | C: explicit npm + TypeScript |
| --- | --- | --- | --- |
| Product MCP closure | Fail: absent | Pass: explicit client | Pass: explicit client |
| Product coding boundary | Fail: bundled bash/filesystem | Pass: composition disables coding | Depends on same composition |
| Gateway language cost | Low | Low | Extra Node adapter/sidecar |
| Notifications/events | SDK available | SDK available + adapter normalization | SDK available + Node normalization |
| Hard cancellation | Close shared runtime is unsafe | Dedicated process close | Dedicated process close |
| Persistence ownership | DSH runtime | DSH runtime | DSH runtime |
| CI/prototype | Bundled launch only | Keyless initialize/MCP startup/cleanup pass | No sufficient seam benefit |

## 共享 boundary decisions

- Gateway 只看到 BYQ-owned health 和 `WorkflowTraceEvent` envelopes。
- Raw DSH notifications 在 adapter 中消费并规范化。
- Product DSH 只经 BeyondQuant MCP 访问 business data。
- DSH Web 不是 product transport。
- Gateway 只存 BYQ session/trace identities；DSH durable session logs 留在 Agent Plane runtime ownership boundary。
