# ACP judgment runner candidate

This service is a fixed DSH ACP process owner and byte relay. It does not make
Agent, model, tool, or business decisions. The Adapter remains the one
Gateway/Backend authority owner. The runner is root only to set child identity,
own private files, and reap the dedicated DSH process tree.

## Control socket and process boundary

The Compose candidate mounts `byq_acp_runner_control` into the Adapter and
runner at `/run/byq-acp-runner`. The runner creates that directory as
`root:10005` mode `0710` and `control.sock` as `root:10005` mode `0660`. The
Adapter uses supplementary GID 10005. The DSH child is started with UID/GID
10002 and `extra_groups=()`, so it cannot traverse the control directory. The
runner container drops all capabilities and adds only `CHOWN`, `SETGID`,
`SETUID`, and `KILL`; it uses `no-new-privileges`. It publishes no port and is
attached only to the internal `byq_acp_judgment` network.

Ordinary Product DSH processes in the Adapter container inherit its
supplementary GID 10005 and therefore may connect to this socket. They cannot
authenticate without the runner control secret, but repeated unauthenticated
connections can repeatedly occupy the sequential handler's five-second auth
window. This is a remaining **P2 availability gate**; HMAC does not make the
socket unreachable or guarantee an authorized START will be scheduled. Because
Adapter and Product DSH share UID/GID, Unix peer credentials cannot distinguish
the shim from a Product child. Threading or a shorter timeout can reduce the
impact of one connection but cannot reliably prevent repeated saturation.
The Adapter candidate sets `PR_SET_DUMPABLE=0`; the local same-UID `/proc`
negative passed. Its actual container behavior remains a promotion gate.

## Wire v1

All frames use a four-byte unsigned big-endian length that includes the
one-byte type, followed by the type byte and payload. The maximum frame length
is 1 MiB. JSON frames are UTF-8 objects with duplicate fields and non-finite
numbers rejected. Canonical JSON is
`json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
allow_nan=False).encode("utf-8")`.

Frame types are `CHALLENGE=0x01`, `START=0x02`, `STDIN=0x03`, `CANCEL=0x04`,
`READY=0x81`, `REJECT=0x82`, `STDOUT=0x83`, and `EXIT=0x84`.

The URL-safe-base64 `BYQ_ACP_JUDGMENT_RUNNER_CONTROL_SECRET` decodes to at least
32 bytes and is present only in the Adapter and runner processes. START MAC is
HMAC-SHA256 over
`b"byq-acp-runner-v1\\0" + canonical_json(START_without_mac)`. Runner reply MAC
is HMAC-SHA256 over
`b"byq-acp-runner-reply-v1\\0" + canonical_json(reply_without_mac)`.
MAC values are lowercase hexadecimal SHA-256 strings.

The first frame is a signed CHALLENGE object with exactly `v`, `challenge`, and
`mac`; the challenge is 32 random bytes represented as lowercase hex. START
has exactly `v`, `challenge`, `nonce`, `scope`, `env`, `proxy_token_env`,
`proxy_token`, `overlay_b64`, `deadline_at_ms`, and `mac`. It must echo the
challenge and carry a fresh 32-byte lowercase-hex nonce. Its scope has exactly
`task_id`, `call_identity`, `attempt_binding`, `root_run_id`,
`runtime_boot_id`, and positive integer `authority_epoch`.

The SHA-256 of canonical scope JSON is the deterministic session leaf and
one-shot tombstone filename. It does not authorize a request; the HMAC does.
Before launch, the runner creates `<digest>.used` with `O_EXCL`, writes only a
constant marker, and fsyncs both file and state directory. Existing markers,
state write/fsync errors, or lost state fail closed. Markers are not removed or
replayed. A future task/root must use a distinct canonical scope.

The runner signs CHALLENGE, READY, EXIT, and REJECT. READY has exactly `v`,
`challenge`, `nonce`, `scope_digest`, `cwd`, and `mac`. EXIT has exactly `v`,
`challenge`, `nonce`, `scope_digest`, `code`, `signal`, `reason`, `cleanup`,
and `mac`. REJECT has exactly `v`, `challenge`, `nonce`, `scope_digest`,
`code`, and `mac`. Every reply after START is bound to that connection's
challenge, nonce, and scope digest. EOF or an unverified receipt means cleanup
is unknown.

The child env is a fixed allowlist and must agree with task/call/root/boot
values in scope. It can contain only the derived per-root judgment MCP key and
the selected local provider proxy token. It never receives the runner secret,
judgment master, Gateway/Backend authority, or upstream provider API key. The
decoded overlay is at most 16 KiB and is written once as mode `0600`; START
cannot supply command arguments, a file path, or a working directory. The
deadline is absolute epoch milliseconds and the runner can shorten it to at
most one hour.

## Private session and cleanup

The runner-only tombstone volume is separate from the runner-only session
volume. The session root is `root:10002` mode `0710`; each deterministic leaf
and `tmp` directory is owned by the DSH UID and mode `0700`. The Adapter does
not mount this volume because ordinary Product DSH shares its UID. The final
entry therefore needs runner-signed or Backend-bound native-session proof
instead of the existing local root-marker read. Session contents are retained
for DSH recovery, not automatically deleted. The named local volume has no
configured quota; capacity monitoring and retention after exact settlement
are operational requirements. Tombstones need roughly one
filesystem block each (about 400 MiB for 100,000 roots with 4 KiB blocks).

The child starts a new session/process group with
`Popen(user=10002, group=10002, extra_groups=(), umask=0o077,
start_new_session=True)`. The fixed shell wrapper enters the private cwd
after UID drop and immediately `exec`s the pinned DSH command. PID 1 enables
child subreaping. On cancel, deadline, transport loss, or child exit, the
runner tracks descendants, including adopted double-fork children, with
`/proc` and pidfd identity checks, terminates and reaps them, and confirms
quiescence. `cleanup=proven` requires that proof, a reaped leader, stdout EOF,
and finished relay threads. Unverifiable state produces `cleanup=unknown`;
transport loss yields no EXIT and the client also records unknown. Container
restart or hard-kill windows are not crash-proven by these tests.

## Candidate topology and evidence limits

The Compose candidate attaches Adapter to product plus internal, isolated MCP
to product plus internal, runner only to internal, and Backend only to product.
That prevents DSH/runner from directly reaching Backend while the MCP retains
its proof/read route. The MCP source exposes only its fixed `/mcp/v1` and
`/healthz` HTTP routes; live routing/CONNECT negative tests remain NOT_RUN.

Seven tests with synthetic keys and temporary sockets passed, including a
double-fork process-group escape. The fixed-source complete local image
`sha256:297130a5c38316957a5f039504b03d97826a46c25c50d2d4ed78ea865159f020`
was built and run without network, with read-only root filesystem and the
candidate capabilities. A separate client container using Adapter UID/GID
received signed READY, then signed `EXIT(cancelled, cleanup=proven)` from an
actual official DSH process. These are bounded local qualifications, not
Product integration or provider acceptance. Actual MCP/tool/provider calls,
internal-network egress negatives, volume crash durability, restart cleanup
and Product API flows remain NOT_RUN.
