# ADR-0003: Gateway to DSH Runtime Integration

- Status: Accepted
- Date: 2026-08-15
- Decision scope: Phase 6 Product Plane / Agent Plane runtime seam
- Supersedes: the Phase 5 `NO DECISION YET` Gateway integration placeholder

## Context

Phase 5 deliberately stopped at a container-local DSH Web bootstrap. That Web
surface is not a product API: it remains bound to DSH's loopback interface,
has no host publication, and must not be proxied or otherwise worked around.

Phase 6 needs a programmatic seam for the following path:

```text
BYQ Gateway
  ↓ internal BYQ API
DSH Runtime Adapter
  ↓ official SDK over stdio JSON-RPC
explicit DSH rc.6 runtime composition
  ↓ official MCP client
BeyondQuant MCP
```

The seam must preserve the existing boundaries:

- Product DSH has no coding, source filesystem, Git mutation, or Engineering
  Plane capability.
- Agent-to-Domain calls use BeyondQuant MCP only.
- Gateway does not import the DSH SDK or parse raw DSH notification types.
- DSH session persistence remains Agent Plane state; Gateway retains only BYQ
  session and trace identities.
- DSH remains an external, exact-pinned dependency and is not forked or
  rebuilt for BYQ.

The official rc.6 artifacts were inspected rather than inferred. The npm
notation is `0.1.0-rc.6`; the Python/PyPI notation is `0.1.0rc6`. The Python
SDK owns a subprocess and stdio JSON-RPC client, but rc.6 has no prompt cancel
or per-session close operation. `session/prompt` returns an enqueue receipt,
not a completed result. These limitations make process ownership part of the
architecture decision.

## Options evaluated

### Option A: Python SDK plus bundled runtime

Rejected for the Product runtime. The official runtime-bin wheel's default
composition includes local bash and filesystem providers and does not include
`@deepseek-ai/dsh-mcp-client`. Adding the missing MCP closure would require
rebuilding or forking the upstream runtime carrier. `DeepSeekHarness()`
zero-config is therefore not an acceptable Product runtime.

### Option B: Python SDK plus explicit npm DSH runtime

Selected. The Python SDK is used as the application-facing client, while a
BYQ-controlled exact-pinned npm runtime is launched through the SDK's official
`launch_args_override` and custom Cordis configuration. The composition mounts
the official JSON-RPC server, a non-coding agent spine, DSH-owned persistence,
and `@deepseek-ai/dsh-mcp-client` connected to BeyondQuant MCP.

The Phase 6 prototype verified actual rc.6 `packaged-bin.js` behavior,
JSON-RPC initialize/shutdown, MCP startup with `failOnStartupError: true`,
Gateway-to-adapter session creation, and hard cancellation without a model
key.

### Option C: TypeScript SDK plus explicit npm DSH runtime

Not selected. The official TypeScript client uses the same stdio JSON-RPC
protocol and has the same rc.6 lifecycle limitations. A Python Gateway would
need a Node Gateway or an additional Node adapter/sidecar. That adds a
language/process boundary without improving event, cancellation, or runtime
ownership semantics for this Python Gateway.

## Decision

BYQ adopts Option B with a dedicated Python Runtime Adapter as the only
Gateway-facing DSH runtime owner. The adapter uses FastAPI for its internal
HTTP/SSE prototype API and `deepseek-harness-sdk==0.1.0rc6` to launch one
explicit `@deepseek-ai/dsh-sdk-jsonrpc-demo@0.1.0-rc.6` runtime process per
active BYQ session.

The adapter is an Agent Plane runtime boundary. It is not an Engineering DSH,
not a generic agent harness, and not a public chat API.

## Runtime topology

```text
Gateway (Python)
  ├─ internal HTTP: health/session lifecycle
  └─ internal SSE: BYQ WorkflowTraceEvent only
       ↓
Runtime Adapter (Python/FastAPI)
  ├─ one DeepSeekHarness per active BYQ session
  ├─ official stdio JSON-RPC client
  └─ one owned node packaged-bin.js process per session
       ↓
byq-product-sdk.cordis.yml
  ├─ @deepseek-ai/dsh-sdk-jsonrpc-server
  ├─ @deepseek-ai/dsh-agent-spine-demo (coding flags disabled)
  ├─ DSH JSONL persistence/checkpoint policy
  └─ @deepseek-ai/dsh-mcp-client
       ↓
BeyondQuant MCP (`/mcp/v1`)
```

The DSH Web container remains container-local and is not in this request path.

## Process ownership

The initial rc.6 lifecycle model is one DSH runtime process per active BYQ
session. The adapter owns startup, stdin/stdout/stderr pipes through the
official SDK, shutdown, termination, and cleanup. The Gateway web worker does
not own a subprocess.

A single shared runtime with multiple `sessionId` values was evaluated. It
would lower aggregate cold-start and idle overhead, but it makes hard
single-session cancellation unsafe, increases crash blast radius, and shares
the rc.6 result ownership interval across queued work. It is not selected
until DSH exposes reliable prompt cancellation and per-session close.

The final local prototype measured a fresh Gateway-to-adapter initialize at
`0.355827s` and hard cancel at `0.039565s` on 2026-08-15. At idle after
initialize, `docker stats` reported `101.3MiB` for the Runtime Adapter
container and `docker top` reported `121112KiB` RSS for the owned Node DSH
child. These are baseline measurements, not capacity guarantees; Phase 7
must repeat them under the target CI/production limits.

## Session lifecycle

1. Gateway submits a BYQ `session_id` and `trace_id` to the adapter.
2. The adapter creates the DSH-owned session root, starts the explicit
   runtime, and completes official JSON-RPC `initialize`.
3. Prompt submission is asynchronous in this prototype; SDK notifications are
   consumed by the adapter.
4. The adapter translates selected notifications to BYQ
   `WorkflowTraceEvent` values and exposes them through internal SSE.
5. Session results are retained by the DSH runtime's persistence policy. The
   Gateway never stores DSH internal session state.
6. A normal next run resumes through the DSH session identity while the
   adapter owns the process for the active lifecycle. A hard-interrupted
   process is not silently resumed as if its prompt completed.

## Streaming

The Phase 6 internal prototype selects SSE from Runtime Adapter to Gateway.
SSE maps directly to the adapter's ordered notification queue, is supported by
the Python stack, and is sufficient for a one-way internal event stream. An
internal streaming HTTP transport remains a valid future optimization if
backpressure or bidirectional control requires it.

SSE carries only serialized BYQ `WorkflowTraceEvent` envelopes. Gateway code
does not parse `session.event`, DSH event types, or DSH payload schemas.

## Event normalization

The framework-neutral minimum envelope is defined in
`packages/contracts/workflow_trace.py`:

```text
trace_id, session_id, sequence, timestamp, kind, source, payload
```

The adapter currently demonstrates translation for `session.status` and
selected `session.event` categories. Unknown DSH event types become a bounded
`session.progress` event with an event-kind label; raw DSH payloads never cross
the Gateway boundary. This is an internal prototype contract, not the final
WorkflowTrace domain schema.

## Cancellation

### Soft cancel

Soft cancel is a BYQ adapter state transition to `cancelling`. The adapter
emits a BYQ cancellation event, allows the rc.6 work to settle, and discards
the eventual result. It is cooperative bookkeeping, not a DSH prompt-cancel
claim.

### Hard cancel

Hard cancel sets the BYQ session to `interrupted`, emits a cancellation event,
and calls the official SDK `close()` on the adapter-owned DSH runtime. The SDK
performs its documented shutdown/terminate/kill ladder. The adapter does not
patch the protocol or fabricate a successful cancellation response.

The persistence outcome is DSH-owned: the durable log may contain an
interrupted/incomplete turn. The next resume is a new run after the interrupted
boundary, and Phase 7 must define the complete product-level resume policy.

## Failure isolation and scaling

One owned runtime per active session limits a runtime crash to that session and
makes cleanup deterministic. Adapter process failure can still affect all
sessions assigned to that adapter instance; the deployment layer must restart
the adapter and use session ownership/affinity when scaling horizontally.

Phase 7 or later must add an explicit ownership registry if adapters are
replicated. A session must not be resumed on a second worker while the first
worker still owns its DSH process. DSH durable logs remain the source for Agent
Plane resume, while BYQ business artifacts remain Backend/Domain Plane state.

## MCP composition and security boundary

The SDK composition is `byq-product-sdk`, separate from the DSH Web patch but
using the same single BYQ product capability policy. It includes the SDK
JSON-RPC server and BYQ MCP client, with `failOnStartupError: true`. It
explicitly disables bash, jobs, skills, workspace context, and goals. No BYQ
source directory is mounted, and no application source write capability is
installed.

The adapter reaches MCP on the private compose network with
`BYQ_MCP_TOKEN`. The DSH runtime has no PostgreSQL, Redis, source repository,
Docker socket, or host-published Web port. The prototype endpoints are
internal-only and trust the private service network; they are not external
user authentication. Production deployment must add service identity,
authorization, and preferably mTLS or an equivalent authenticated internal
mesh before exposing any cross-host adapter call.

## Model configuration

The adapter passes the officially supported `deepseek-official` provider route
and `deepseek-v4-flash` model through the SDK initialize path. Phase 6 does
not mount or invoke a model provider, issue a real model request, or require
`DEEPSEEK_API_KEY`; this keeps the keyless runtime lifecycle prototype limited
to the official JSON-RPC and MCP startup seam. Phase 7 must add and validate
the exact provider composition, credential policy, and model routing before a
real Product Agent turn. No fake production model abstraction is introduced.

## Observability

Health/readiness reports the exact SDK/runtime-bin versions, explicit runtime
path, composition path, persistence owner, and process ownership. The SDK
keeps JSON-RPC stdout reserved for protocol frames and retains runtime stderr
diagnostics. Adapter logs and normalized WorkflowTrace events are the
Gateway-facing observability surface. Raw DSH event payloads and secrets must
not be logged.

## DSH upgrade compatibility

The current compatibility baseline is exact rc.6. Any DSH upgrade is a
separate compatibility decision requiring fresh npm/PyPI metadata, artifact
hash/closure inspection, composition validation, notification/initialization
contract tests, cancellation review, and an ADR update. A newer npm release
does not automatically change this baseline.

## Known rc.6 limitations

- no prompt cancel;
- no per-session close;
- no protocol version negotiation;
- prompt returns only an enqueue receipt;
- whole-agent idle interval owns the high-level run result;
- request timeout does not stop work;
- stdout is protocol-only;
- server/client request handling is not a complete approval flow.

These limitations are reflected in the adapter API and must not be described
as supported DSH features.

## Rejected alternatives

- DSH Web as Gateway API: violates the Web boundary and requires forbidden
  proxy/network workarounds.
- Gateway-owned DSH subprocess: couples web-worker lifecycle to agent process
  lifecycle and weakens failure isolation.
- Option A bundled zero-config runtime: coding-capable closure and missing MCP
  client.
- Option C TypeScript SDK: unnecessary extra language/process seam for the
  current Python Gateway.
- Forking or rebuilding DSH: prohibited by repository architecture rules.
- Gateway parsing raw DSH notifications: couples product contracts to DSH.

## Rollback

Rollback is to the Phase 5 topology: remove the Gateway internal runtime
routes and Runtime Adapter service, retain the container-local DSH Web
bootstrap, and keep the exact rc.6 Product MCP boundary. No database rollback
or business-data migration is required because Phase 6 stores no BYQ business
state.

## Exit criteria

Phase 6 may be marked complete only when all of the following are true:

- the official rc.6 Python SDK and runtime-bin metadata/artifact closure is
  recorded;
- Option A/B/C evidence and this ADR are reviewed;
- keyless initialize, MCP startup, hard cleanup, normalization, and adapter
  boundary tests pass;
- existing Phase 5 architecture, backend, MCP, Gateway, DSH, and smoke tests
  remain green;
- CI runs the new adapter tests and reliable keyless smoke;
- STATUS records Phase 6 complete and Phase 7 next.

If compatibility evidence becomes insufficient, this ADR must remain Proposed
and Phase 6 must stop at a documented architecture blocker.
