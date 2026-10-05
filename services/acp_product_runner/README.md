# Product ACP workspace slot

This process owner runs the fixed official DSH `dsh-v0.2.0-rc.2` ACP Product
composition for one configured personal BYQ workspace. One daemon accepts one
root at a time. It reuses the same durable workspace directory for completed
roots, so the Adapter can close a root, wait for Backend settlement, and resume
the same native DSH session and cwd for a later root with a fresh MCP identity.

The initial capacity is one active root for this personal workspace. A busy
slot rejects a new start; it has no queue. Team workspace support and multiple
slots require a separate contract and qualification. This daemon has no
dynamic allocator, per-root supervisor processes, UID pool, or writable cgroup
requirement. It owns no Backend authority or business decisions. The Adapter
remains responsible for user authorization, idempotency, unknown outcomes, and
the exact terminal ACK before it submits the next root.

## Fixed identity and storage

At startup the container requires:

- `BYQ_ACP_PRODUCT_WORKSPACE_ID`: the one workspace configured for this slot.
- `BYQ_ACP_PRODUCT_RUNNER_CONTROL_SECRET`: independent URL-safe base64 secret,
  at least 32 decoded bytes.

The daemon derives its session root as
`/var/lib/byq/dsh-sessions/dsh-v0.2.0-rc.2-acp/<workspace_id>`. The session
root is owned by root with group 10002 and mode `0770`, so the trusted Adapter
running as UID/GID 10002 can prepare a private leaf; the parent stays
`root:10002` mode `0710`. The mounted workspace volume is private to this slot.
Tombstone state is root-owned and private. A request supplies only a
validated `cwd_leaf` (`session-<32 lowercase hex>` or
`root-<32 lowercase hex>`); arbitrary commands and paths are never accepted.
The trusted Adapter prepares that leaf and its private `tmp` subdirectory as
UID/GID 10002 with mode `0700`; the runner verifies only the leaf from its
parent and does not traverse it as root. Completed roots may reuse that leaf.
The root-owned scope tombstone is durable and is written before DSH launch, so
a consumed root scope is never replayed.

The DSH process runs as UID/GID 10002 with no supplementary groups. The
Adapter control socket uses GID 10006. The slot's deployment must mount only
this workspace's session storage and the control socket for the trusted
Adapter. It must not join the judgment network or mount its control socket,
session volume, or provider proxy secret. Use `no-new-privileges`; retain only
the capabilities needed by the root PID 1 to set the fixed child UID/GID,
prepare private directories, and manage its Unix socket. The image itself does
not select networks, mounts, or deployment capacity.

## Control protocol

The Unix socket uses the existing bounded length-prefixed ACP relay framing and
the `byq-acp-runner-v1` / `byq-acp-runner-reply-v1` HMAC prefixes. The server
issues a signed challenge. The Adapter sends one signed `START` with exactly:

```json
{
  "v": 1,
  "challenge": "<server challenge>",
  "nonce": "<32 random bytes as lowercase hex>",
  "scope": {
    "workspace_id": "<configured workspace>",
    "owner_principal": "<authorized owner>",
    "session_id": "<public BYQ session>",
    "trace_id": "<request trace>",
    "root_run_id": "<32 lowercase hex>",
    "runtime_boot_id": "<32 lowercase hex>",
    "generation_id": "generation-<32 lowercase hex>",
    "cwd_leaf": "root-<32 lowercase hex>"
  },
  "env": {"<closed Product ACP identity and selected provider fields>": "..."},
  "deadline_at_ms": 0,
  "mac": "<HMAC over every preceding field>"
}
```

The child environment allowlist carries the Product MCP discovery and signing
credentials, runtime/root/session identity, optional persisted native DSH
session ID, and exactly one selected provider key. The daemon constructs
`PATH`, `HOME`, `TMPDIR`, and DSH storage variables itself. It rejects
authority, Backend, credential resolver, judgment, loader, proxy, and arbitrary
environment fields. It launches only the fixed ACP profile and composition.

`READY` and `EXIT` use the existing signed relay schemas. Their `scope_digest`
is SHA-256 over the canonical Product scope. `READY.cwd` is the canonical
workspace-specific cwd. DSH stdin/stdout bytes use the existing bounded relay
frames. `session/cancel` remains ACP input; the relay's `CANCEL` terminates the
current process only after the Adapter requests cancellation.

After each root, the daemon reuses the slot only when the shared cleanup helper
proves all DSH descendants have exited and the signed `EXIT` was sent. Cleanup
unknown, an unsent `EXIT`, or transport loss retires this daemon. As container
PID 1 exits, the container boundary stops the remaining processes. Any root
without an authenticated, proven `EXIT` stays unknown to the Adapter and must
be reconciled with Backend before reuse; the slot does not infer a business
result or issue a terminal ACK.

This image and protocol are a bounded runner component only. They do not
qualify Product API behavior, model provider routing, delegates, F6
continuation, session recovery, or default ACP promotion.
