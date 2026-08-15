# ADR-0003: Gateway to DSH Runtime Integration

- Status: Accepted
- Date: 2026-08-15
- Decision scope: Phase 6 Product Plane / Agent Plane runtime seam
- Supersedes: the Phase 5 `NO DECISION YET` Gateway integration placeholder

## Context

Phase 5 deliberately stopped at a container-local DSH Web bootstrap. That Web
surface is not a product API: it remains bound to DSH's loopback interface,
has no host publication, and must not be proxied or worked around.

Phase 6 needs this programmatic path:

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
- DSH remains an exact-pinned external dependency and is not forked or
  rebuilt for BYQ.

The official rc.6 artifacts were inspected rather than inferred. npm uses
`0.1.0-rc.6`; Python/PyPI uses `0.1.0rc6`. The Python SDK owns a subprocess
and stdio JSON-RPC client, but rc.6 has no prompt cancel or per-session close.
`session/prompt` returns an enqueue receipt, not a completed result. These
limitations make process ownership part of the architecture decision.

## Options evaluated

### Option A: Python SDK plus bundled runtime

Rejected for the Product runtime. The official
`deepseek-harness-runtime-bin==0.1.0rc6` closure includes coding-capable bash
and local filesystem capabilities and does not include
`@deepseek-ai/dsh-mcp-client`. A custom composition cannot add an absent
package to that bundled closure. Rebuilding or forking the runtime to add MCP
would violate the repository boundary.

### Option B: Python SDK plus explicit npm DSH runtime

Selected. The Python SDK is the application-facing client. It launches an
exact-pinned npm rc.6 runtime through `launch_args_override` with the official
public `dsh-jsonrpc-agent` carrier (`lib/bin.js`) and a BYQ-controlled Cordis
composition containing:

- `@deepseek-ai/dsh-sdk-jsonrpc-server`;
- non-coding `@deepseek-ai/dsh-agent-spine-demo` configuration;
- DSH JSONL persistence/checkpoint policy; and
- `@deepseek-ai/dsh-mcp-client` connected to BeyondQuant MCP.

The public `lib/bin.js` and exported `packaged-bin.js` were both run from the
installed rc.6 artifact with the BYQ composition and healthy MCP. Both passed
keyless initialize/idle/close. The public `dsh-jsonrpc-agent` is selected
because it is the package's declared public bin and loads the BYQ composition
without a packaged-runtime base override. This is an rc.6 exact-pinned
decision protected by compatibility smoke; it is not a promise of stability
for future DSH versions.

### Option C: TypeScript SDK plus explicit npm DSH runtime

Not selected. `@deepseek-ai/dsh-sdk-client@0.1.0-rc.6` uses the same stdio
JSON-RPC protocol and inherits the same cancellation and process limitations.
A Python Gateway would need a Node adapter/sidecar or a Node Gateway, adding a
language/process boundary without improving lifecycle, event, or observability
behavior for this phase.

## Decision

BYQ adopts Option B with a dedicated Python Runtime Adapter as the only
Gateway-facing DSH runtime owner. The adapter uses FastAPI for its internal
HTTP/SSE prototype API and `deepseek-harness-sdk==0.1.0rc6` to launch one
explicit `@deepseek-ai/dsh-sdk-jsonrpc-demo@0.1.0-rc.6` public
`dsh-jsonrpc-agent` process per active BYQ session.

The adapter is an Agent Plane runtime boundary. It is not an Engineering DSH,
not a second generic agent harness, and not a public chat API.

## Runtime topology

```text
Gateway (Python)
  ├─ internal HTTP: health/session lifecycle
  └─ internal SSE: BYQ WorkflowTraceEvent only
       ↓
Runtime Adapter (Python/FastAPI)
  ├─ one DeepSeekHarness per active BYQ session
  ├─ official stdio JSON-RPC client
  └─ one owned node dsh-jsonrpc-agent/lib/bin.js process per session
       ↓
byq-product-sdk.cordis.yml
  ├─ @deepseek-ai/dsh-sdk-jsonrpc-server
  ├─ @deepseek-ai/dsh-agent-spine-demo (coding flags disabled)
  ├─ DSH JSONL persistence/checkpoint policy
  └─ @deepseek-ai/dsh-mcp-client
       ↓
BeyondQuant MCP (`/mcp/v1`)
```

The base compose contains Gateway, Runtime Adapter, MCP, and Backend. The old
Phase 5 DSH Web service is available only through `compose.dsh-web.yml` with
the `dsh-web` diagnostic profile; it is not in the product request path.

## Process ownership

The rc.6 initial lifecycle model is one DSH runtime process per active BYQ
session. The adapter owns startup, stdin/stdout/stderr pipes through the
official SDK, shutdown, termination, and cleanup. Gateway web workers do not
own subprocesses.

A single shared runtime with multiple `sessionId` values was evaluated. It
would lower aggregate cold-start and idle overhead, but rc.6 cannot reliably
hard-cancel one session without affecting other sessions and shares the
whole-agent result interval across queued work. It is not selected until DSH
provides reliable prompt cancellation and per-session close.

The prototype baseline measured fresh Gateway-to-adapter initialize at
`0.355827s` and hard cancel at `0.039565s` on 2026-08-15. At idle after
initialize, `docker stats` reported `101.3MiB` for the Runtime Adapter
container and `docker top` reported `121112KiB` RSS for the owned Node child.
These are baseline measurements, not capacity guarantees; Phase 7 must repeat
them under target CI/production limits.

## Session lifecycle

The adapter state vocabulary is:

```text
starting → ready → idle → running → idle
                         ├→ cancelling → idle
                         ├→ failed
                         └→ interrupted → closed
```

The implementation also accepts normal release from `ready`, `idle`, `failed`,
or `interrupted` to `closed`.

1. Create validates BYQ `session_id` and `trace_id`, creates the DSH-owned
   session root, starts the explicit runtime, and completes JSON-RPC
   `initialize`; the state becomes `ready`.
2. `submit_prompt` is accepted only in `ready` or `idle`. Under the session
   lock it claims one `active_run`, atomically changes the state to `running`,
   and only then starts one `Session.run()` worker. A second prompt receives
   409 and cannot create concurrent active runs.
3. Normal completion clears only that active run and changes the state to
   `idle`; a non-cancel failure changes it to `failed`.
4. `release` is allowed only with no active run. It changes the state to
   `closed`, closes/reaps the owned harness, emits a close trace, sends SSE
   termination, and removes the live record. Recreating the same BYQ session
   after release creates a new owned runtime under the future resume policy.
5. Duplicate create while a live record exists is an explicit 409 conflict.

## Streaming

The internal prototype selects SSE from Runtime Adapter to Gateway. SSE maps
to the adapter's ordered notification queue and is sufficient for the
one-way internal event stream. Internal streaming HTTP remains a future option
if backpressure or bidirectional control requires it.

SSE carries only serialized BYQ `WorkflowTraceEvent` envelopes. Gateway code
does not parse DSH notification methods, event types, or payload schemas.

## Event normalization and ordering

The framework-neutral minimum envelope in `packages/contracts/workflow_trace.py`
is:

```text
trace_id, session_id, sequence, timestamp, kind, source, payload
```

The adapter translates `session.status` and selected `session.event` values
into BYQ-owned events. Unknown DSH event types become bounded
`session.progress` events. Raw DSH payloads never cross the Gateway boundary.

Each RuntimeSession has one ordering lock. Sequence allocation and queue
publication happen within that lock, so sequence values are unique, strictly
increasing, and published in the same order even when notification, cancel,
result, and failure paths race.

## Cancellation

### Soft cancel

Soft cancel is valid only for the current active run. It transitions the
session to `cancelling`, emits a BYQ cancellation event, and lets rc.6 work
settle because rc.6 has no prompt-cancel operation. The eventual result is
discarded and the state returns to `idle`. The cancel request is scoped to the
active run and cannot permanently contaminate a later prompt.

### Hard cancel

Hard cancel is valid only for the current active run. It transitions the
session to `interrupted`, detaches that run, emits a BYQ cancellation event,
and calls the official SDK `close()` on the adapter-owned DSH runtime. The SDK
performs its documented shutdown/terminate/kill ladder. The adapter does not
patch the protocol or fabricate a successful cancellation response.

A prompt after hard cancel receives 409; the closed harness is never reused.
The durable log may contain an interrupted/incomplete turn. A future resume
must create a new owned runtime under an explicit resume policy; Phase 7 owns
the complete product resume flow.

## Failure isolation

One owned runtime per active session limits a runtime crash to that session and
makes cleanup deterministic. Adapter process failure can still affect all
sessions assigned to that adapter instance; deployment must restart the
adapter and preserve ownership/affinity when scaling horizontally.

## MCP composition

The selected SDK composition is
`plugins/dsh-byq/compositions/byq-product-sdk.cordis.yml`. It is the single
Product capability source and includes the SDK JSON-RPC server and BYQ MCP
client with `failOnStartupError: true`. Coding tools are `NONE`: bash,
terminal, write, edit, str-replace, codex, Git mutation, and source filesystem
write are not installed or enabled. DSH reaches business data only through
BeyondQuant MCP and never directly accesses PostgreSQL or Redis.

## Model configuration

The adapter passes the official `deepseek-official` provider route and
`deepseek-v4-flash` model through the SDK initialize configuration. Phase 6
does not mount or invoke a model provider, issue a real model request, or
require `DEEPSEEK_API_KEY`. Phase 7 must validate real Product Agent model
routing and credentials; no fake production model abstraction is introduced.

## Persistence

The named Compose volume `byq_dsh_sessions` is mounted only at
`/var/lib/byq/dsh-sessions`. The runtime user can write that Agent Plane
volume and required temporary storage; application, config, and runtime
installation paths remain root-owned/read-only. The adapter resolves each
session path and proves it remains below `DSH_SESSION_ROOT`.

Gateway stores/transmits only BYQ session identity and BYQ trace identity. DSH
durable session logs belong to the Agent Plane runtime owner. Future BYQ
business artifacts remain Backend/Domain Plane state.

## Security boundary and internal trust

The prototype endpoints trust the private Compose network and use the MCP
token for the adapter-to-MCP call. They are not external user authentication.
No source mount, Docker socket, host network, host-published DSH Web port,
engineering credential, or broad writable application path is available to
Product DSH. A production cross-host deployment must add service identity and
authorization, preferably mTLS or an equivalent authenticated internal mesh,
before exposing the adapter beyond the private network.

## Observability

Readiness reports exact SDK/runtime-bin versions, explicit carrier path,
composition path, persistence owner, and process ownership. SDK stdout remains
reserved for JSON-RPC frames; diagnostics remain on stderr. Adapter logs and
normalized WorkflowTrace events are the Gateway-facing observability surface.
Raw DSH payloads and secrets are not logged.

## Horizontal scaling

The adapter is independently deployable from Gateway. A replicated deployment
must add an ownership registry or affinity rule so a session is not resumed on
a second adapter while the first still owns its DSH process. The named DSH
volume and durable-log strategy must be replaced or provisioned per adapter
with explicit shared-storage semantics before horizontal session migration.

## DSH upgrade compatibility

The compatibility baseline is exact rc.6:

- npm `@deepseek-ai/dsh@0.1.0-rc.6` and explicit runtime packages;
- Python `deepseek-harness-sdk==0.1.0rc6`; and
- `deepseek-harness-runtime-bin==0.1.0rc6`.

Any DSH upgrade is a separate compatibility decision requiring fresh npm/PyPI
metadata, artifact hashes/closure inspection, carrier validation,
composition/initialization/MCP tests, notification contract review,
cancellation review, and an ADR update. A newer npm release does not
automatically change this baseline.

## Known rc.6 limitations

- no prompt cancel;
- no per-session close;
- no protocol version negotiation;
- prompt returns only a MessageId enqueue receipt;
- whole-agent idle interval owns the high-level run result;
- request timeout does not stop already-running work;
- stdout is JSON-RPC protocol-only; and
- server/client request capabilities for future approval flow are incomplete.

These are current limitations, not available future features. The adapter's
hard-cancel process close is a BYQ ownership policy, not a claim that DSH rc.6
supports prompt cancellation.

## Base Web DSH decision

The old Phase 5 Web DSH is removed from base production compose and retained
in `compose.dsh-web.yml` under the explicit `dsh-web` diagnostic profile. It
has no host port, source mount, socket, proxy, or host networking. Product
requests use only Gateway → Runtime Adapter → owned JSON-RPC DSH → MCP. The
diagnostic profile exists for bootstrap/configuration inspection and is not a
second product request path.

## Rejected alternatives

- DSH Web as Gateway API: violates the Web boundary and requires forbidden
  proxy/network workarounds.
- DSH Web in base production compose: creates a second non-request DSH path
  and obscures the selected JSON-RPC ownership boundary.
- Gateway-owned DSH subprocess: couples web-worker lifecycle to agent process
  lifecycle and weakens failure isolation.
- Option A bundled zero-config runtime: coding-capable closure and missing MCP
  client.
- Option C TypeScript SDK: unnecessary extra language/process seam for the
  current Python Gateway.
- Forking or rebuilding DSH: prohibited by repository architecture rules.
- Gateway parsing raw DSH notifications: couples product contracts to DSH.

## Rollback

Rollback is to the Phase 5 topology by removing Gateway runtime routes and the
Runtime Adapter service while retaining the container-local diagnostic DSH Web
bootstrap. No BYQ business-data migration is required because Phase 6 stores
no business state. The rollback must retain the no-proxy/no-host-network Web
boundary.

## Exit criteria

Phase 6 is complete only when:

- official rc.6 Python/npm metadata and bundled closure evidence is recorded;
- Option A/B/C evidence and this ADR are reviewed;
- lifecycle, duplicate-create, hard/soft cancellation, release, identifier,
  ordering, filesystem, and persistence tests pass;
- keyless JSON-RPC initialize, MCP startup, normalization, Gateway contract,
  and process cleanup smoke pass;
- base compose and diagnostic Web profile checks pass; and
- CI runs Phase 5 plus Phase 6 tests and remains at the human merge gate.

If compatibility evidence becomes insufficient or a new DSH behavior breaks
the seam, this ADR must be changed to Proposed and Phase 6 must stop at a
documented architecture blocker.
