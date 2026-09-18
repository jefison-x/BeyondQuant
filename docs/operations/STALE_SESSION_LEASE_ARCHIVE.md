# Stale Session Leases: Classification and Reversible Archive

## What a stale lease is

The runtime-adapter `LifecycleJournal` binds each durable session to the host
that wrote it:

```
lease_identity = sha256(boot_id : st_dev : st_ino : token)
```

`boot_id` is `/proc/sys/kernel/random/boot_id` and changes on every host boot.
When the host reboots, every journal written before the reboot has a stored
`lease_identity` that can never be reproduced again, so `LifecycleJournal.claim`
raises `JournalIdentityMismatch("journal identity mismatch")`. Such a session is
**known** (its evidence is intact) but can never be claimed. Synthetic/demo
sessions created before the 2026-09-10 reboot are the current population.

## Error classification

A stale lease is not an unknown session and not a storage fault. The adapter maps
it to an explicit outcome:

| Condition | Exception | HTTP | Machine code |
| --- | --- | --- | --- |
| Stale lease (boot changed) | `StaleSessionLease` | `409` | `stale_session_lease` |
| Unknown session | `KeyError` | `404` | – |
| Real storage/runtime failure | generic | `503` | – |

Enforced in `services/runtime-adapter/app/main.py` (global exception handler plus
the create/resume routes) after `LifecycleJournal.claim` raises
`JournalIdentityMismatch`, which `RuntimeAdapter._rehydrate` converts to
`StaleSessionLease`. Callers should treat `409 stale_session_lease` as
"archive this session" or, when the conversation must keep its evidence and
resume, "explicitly re-lease this session" (below) — never as a retryable
server error.

## Reversible archive

`scripts/ops/archive_stale_sessions.py` identifies stale-lease sessions and
moves their evidence out of the live roots without deleting anything.

Audit only (default, no mutation):

```sh
python3 scripts/ops/archive_stale_sessions.py \
  --session-root "$DSH_SESSION_ROOT" \
  --trace-root "$BYQ_WORKFLOW_TRACE_ROOT" \
  --database-url "$BYQ_DATABASE_URL"
```

Apply (explicit; the operator runs this):

```sh
python3 scripts/ops/archive_stale_sessions.py --apply \
  --session-root "$DSH_SESSION_ROOT" \
  --trace-root "$BYQ_WORKFLOW_TRACE_ROOT" \
  --database-url "$BYQ_DATABASE_URL"
```

The tool:

* classifies each session as `current`, `stale`, `active` (owner lock held),
  `unprovable` (missing/invalid lock or journal) or `archived`;
* joins each session to its gateway trace file and, read-only, to the owning
  `product_conversations` row (conversation id, owner, title, status, message
  count, created/updated);
* only `stale` sessions are moved; everything else is untouched.

Archive layout (timestamp is `YYYYMMDDTHHMMSSZ`, UTC):

```
$DSH_SESSION_ROOT/<archive-name>/<timestamp>/<session-id>/byq-lifecycle-evidence/<session-id>.json
$DSH_SESSION_ROOT/<archive-name>/<timestamp>/<session-id>/byq-lifecycle-evidence/<session-id>.lock
$DSH_SESSION_ROOT/<archive-name>/<timestamp>/<session-id>/dsh-session/…
$BYQ_WORKFLOW_TRACE_ROOT/<archive-name>/<timestamp>/<session-id>.ndjson
$DSH_SESSION_ROOT/<archive-name>/<timestamp>/manifest.json
```

Manifest fields (per session): session id, reason, stored and current lease
identity, owner, workspace, conversation lookup result. Per file: kind, original
path, archived path, size, sha256. The manifest also records
`database_rows_modified: false` and `production_data_deleted: false`.
`plan.json` is written alongside it before any move.

Reversal is a manual copy back from the manifest's `original_path` /
`archived_path` pairs; nothing is overwritten in place.

## Explicit re-lease (ADR-0078)

Archiving discards a session's ability to be resumed. When the conversation must
be preserved, `scripts/ops/reanchor_session_lease.py` is the sanctioned
post-reboot recovery defined by
[ADR-0078](../architecture/adr/ADR-0078-explicit-session-lease-reanchor.md): it
rewrites **only** the stored `lease_identity` to the current boot-derived
identity and leaves `sequence`, `events`, `prompts`, `terminal_acks`, `calls`,
`open_root` and `context` intact in the lifecycle journal.

Audit only (default, no mutation; lists the selection):

```sh
python3 scripts/ops/reanchor_session_lease.py \
  --session-root "$DSH_SESSION_ROOT" \
  --trace-root "$BYQ_WORKFLOW_TRACE_ROOT" \
  --session-id "$SESSION_ID"
```

Apply (explicit selection is required; there is no implicit mass re-lease):

```sh
python3 scripts/ops/reanchor_session_lease.py --apply \
  --session-root "$DSH_SESSION_ROOT" \
  --trace-root "$BYQ_WORKFLOW_TRACE_ROOT" \
  --session-id "$SESSION_ID"
```

`--session-id` is repeatable; `--session-file` accepts one session id per line
(`#` comments allowed). Output is written to
`$DSH_SESSION_ROOT/byq-lease-reanchor/<timestamp>/audit.json` and
`manifest.json`, recording each old/new lease identity and both journal sha256
values. Re-running with the same timestamp reports `already_reanchored`. The
adapter also commits a per-session audit under
`$DSH_SESSION_ROOT/byq-lifecycle-evidence/reanchor-audit/`; the archive tool's
top-level `*.json` enumeration ignores that subdirectory.

Safety boundaries:

* Only `stale` sessions are rewritten. A live owner (`active`), an already
  current lease (no-op), or an `unprovable`/`archived` selection aborts the whole
  run before any mutation.
* The stored lease observed during inventory must still match at apply time; a
  concurrently changed lease is a fail-closed conflict, never a blind overwrite.
* The session's exclusive owner lock must be acquireable: a live runtime owner is
  refused, so re-lease cannot create a second writer.
* No files are deleted and no business/database rows are written. The Gateway
  stores no lease-bound state — `TraceStore` is keyed by session id and ordered
  by `sequence`, and the lifecycle delivery ledger stores only a cursor over
  those sequences — so re-lease requires no Gateway cursor or ledger refresh.
* If any executor identity other than `boot_id` changed (volume, lock inode,
  token) or a concurrent writer exists, re-lease fails closed; investigate
  instead of forcing it.

The durable fix (a boot-independent lease identity with a monotonic executor
epoch and explicit takeover) is proposed in ADR-0078 and is **not** implemented;
until it is accepted, explicit re-lease is the supported recovery.

## Safety properties

* **Fail closed.** Malformed journals, symlinks, missing lock tokens, existing
  archive directories without a manifest, and sources that escape their root all
  abort before a move. A configured database lookup that fails aborts the run.
* **Idempotent.** Re-running after a completed archive is a no-op and reports
  `already_archived`.
* **No domain mutation.** `product_conversations` is read under a read-only
  transaction. The script never inserts, updates or deletes database rows. Any
  conversation/message cleanup is a separate, operator-gated decision made after
  reviewing the manifest.
* Session directories are only archived when they are keyed by the public
  session id under `DSH_SESSION_ROOT`; private `resume-*` DSH directories are
  intentionally left in place because they cannot be attributed to one BYQ
  session without parsing DSH state.
