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
"archive this session", never as a retryable server error.

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
