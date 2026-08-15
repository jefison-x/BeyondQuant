# DSH Runtime Integration Options

## Status

Decision recorded in [ADR-0003](adr/ADR-0003-gateway-dsh-runtime-integration.md):
**Accepted for Phase 6** after the exit criteria passed. The selected seam
is an independent Python Runtime Adapter using the official Python SDK to
launch an explicit npm rc.6 JSON-RPC runtime composition.

The DSH Web surface remains a bootstrap/verification surface only. It is not
the Gateway transport and no proxy, host networking, `socat`, `nginx`, source
patch, fork, or Web network exposure is part of this decision.

## Common evaluation criteria

Every option was evaluated for stdio/process boundary, lifecycle, notification
streaming, cancellation, persistence ownership, WorkflowTrace translation,
MCP composition, Python Gateway cost, failure isolation, authentication,
observability, horizontal scaling, and DSH upgrade compatibility.

## Option A: Python SDK plus bundled runtime

### Shape

```text
Gateway
  → dedicated Runtime Adapter
  → deepseek-harness-sdk==0.1.0rc6
  → deepseek-harness-runtime-bin==0.1.0rc6 executable
```

### Verification

The official runtime wheel was downloaded, hash-verified, unpacked, and
introspected. Its bundled config includes the stdio JSON-RPC server and the
default agent spine, but also mounts local bash and local filesystem providers.
It does not include `@deepseek-ai/dsh-mcp-client`.

The SDK API allows a custom Cordis path, but a custom composition cannot add a
package that is absent from the single-file runtime closure. Rebuilding the
upstream runtime wheel to add the MCP client would be a fork/rebuild of DSH,
which is prohibited.

### Result

**Rejected for the Product runtime.** Reasons:

1. zero-config composition is coding-capable and violates the BYQ Product
   capability boundary;
2. the bundled closure lacks the required BYQ MCP client;
3. adding it would require rebuilding/forking the official runtime carrier.

The wheel remains useful as an official SDK capability reference and as an
upgrade compatibility input, but `DeepSeekHarness()` zero-config is not used
by the BYQ Runtime Adapter.

## Option B: Python SDK plus explicit npm rc.6 runtime

### Shape

```text
Gateway
  → internal HTTP/SSE BYQ seam
  → Product Plane Runtime Adapter (Python/FastAPI)
  → deepseek-harness-sdk==0.1.0rc6
  → launch_args_override: node + dsh-sdk-jsonrpc-demo/packaged-bin.js
  → exact npm rc.6 JSON-RPC runtime
      ├── @deepseek-ai/dsh-sdk-jsonrpc-server@0.1.0-rc.6
      ├── @deepseek-ai/dsh-agent-spine-demo@0.1.0-rc.6
      ├── @deepseek-ai/dsh-session-persistence-jsonl@0.1.0-rc.6
      └── @deepseek-ai/dsh-mcp-client@0.1.0-rc.6
          ↓
       BeyondQuant MCP
```

The BYQ composition is `plugins/dsh-byq/compositions/byq-product-sdk.cordis.yml`.
It disables `toolBash`, `toolJobs`, skills, workspace context, and goals;
there is no coding executor, source filesystem, Git, or Engineering DSH
plugin in the composition. It mounts the official JSON-RPC server, DSH-owned
JSONL persistence/checkpoint policy, and the exact BYQ MCP client with
`failOnStartupError: true`.

The runtime adapter never calls zero-config `DeepSeekHarness()`. It supplies
`cordis`, `session_root`, and `launch_args_override`, so the SDK's bundled
default injection is bypassed. `runtime_bin` is retained as a documented SDK
option but is not selected for Product operation.

### Prototype result

The installed npm rc.6 artifact was executed with its actual
`packaged-bin.js`; `--help`, `--version`, profile/config introspection, and
JSON-RPC behavior were observed. The initial composition exposed one real
configuration error (`skills: false` instead of the rc.6 schema's
`skills.enabled: false`); after correcting it, the runtime returned a valid
`initialize` response and a clean `shutdown` response without a model key.

The containerized Runtime Adapter then performed:

1. `POST /internal/runtime/sessions`;
2. official Python SDK initialize of an owned explicit npm runtime;
3. rc.6 MCP client startup against the healthy BeyondQuant MCP with
   `failOnStartupError: true`;
4. `POST .../cancel?mode=hard`;
5. clean status `interrupted`, with `process_ownership: dedicated` and
   `persistence: dsh-owned`.

The first exact composition attempt also exposed a real closure issue: the
published JSON-RPC demo does not transitively install the session persistence
and checkpoint packages named by the composition. The adapter's npm manifest
now direct-pins both official rc.6 packages; a rebuilt container passed SDK
initialize, remained alive after 700ms, and hard-cancelled with no stderr load
error. This artifact introspection result is part of the compatibility gate,
not a hidden runtime patch.

This is a keyless startup/handshake smoke. It does not claim a real model turn
or model-generated answer. The `byq_health` MCP contract remains covered by
the MCP contract tests; rc.6 has no stable non-LLM SDK tool invocation API.

### Result

**Selected.** It is the only evaluated option that meets the explicit
composition gate without forking/rebuilding DSH and preserves Python Gateway
integration.

## Option C: TypeScript SDK plus explicit npm runtime

`@deepseek-ai/dsh-sdk-client@0.1.0-rc.6` is an official TypeScript client for
the same stdio JSON-RPC protocol. Its actual rc.6 artifact owns a child
process, exposes `DeepSeekHarness`/`HarnessClient`, fans out notifications,
and performs EOF → SIGTERM → SIGKILL cleanup. It has no separate remote
protocol or cancellation capability; it inherits the same runtime limits.

It would require either a Node Gateway, a Node adapter service, or a second
Node sidecar owned by a Python adapter. All three add a language/process
boundary, dependency alignment work, and another observability/lifecycle
surface. The event and process behavior is not better than the Python SDK for
this Python Gateway. It is therefore **not selected**, but remains a valid
future compatibility option if BYQ adopts a Node Gateway boundary.

## Comparison matrix

| Criterion | A: bundled Python | B: explicit npm + Python | C: explicit npm + TypeScript |
| --- | --- | --- | --- |
| Product MCP closure | Fail: absent | Pass: explicit client | Pass: explicit client |
| Product coding boundary | Fail: bundled bash/filesystem | Pass: composition disables coding | Depends on same composition |
| Gateway language cost | Low | Low | Extra Node adapter/sidecar |
| Notifications/events | SDK available | SDK available + adapter normalization | SDK available + Node normalization |
| Hard cancellation | Close shared runtime is unsafe | Dedicated process close | Dedicated process close |
| Persistence ownership | DSH runtime | DSH runtime | DSH runtime |
| CI/prototype | Bundled launch only | Keyless initialize/MCP startup/cleanup pass | No benefit sufficient to offset seam |

## Shared boundary decisions

- Gateway sees only BYQ-owned health and `WorkflowTraceEvent` envelopes.
- Raw DSH notifications are consumed and normalized in the adapter.
- Product DSH reaches business data only through BeyondQuant MCP.
- DSH Web is not a product transport.
- Gateway stores BYQ session/trace identities only; DSH durable session logs
  remain in the Agent Plane runtime ownership boundary.
