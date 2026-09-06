# U6 operator admission and isolated rehearsal

Status: implementation under validation; NOT a production deployment receipt.
Read [U6 validation](../evidence/dsh-012rc1/u6/VALIDATION.md) and the
[rollout plan](DSH_012RC1_ROLLOUT.md) before use.

## Single-host gate contract

`scripts/dsh/admission.py` is a trusted operator-only writer. Product images
contain only `packages/operations/admission.py`, which opens the file read-only.
There is no Product deployment button, gate-write API or DSH tool.

All serving Gateway and Runtime replicas must receive
`BYQ_CHAT_ADMISSION_FILE=/run/byq-admission/admission.state` and a read-only
directory mount at `/run/byq-admission`, referring to one local-filesystem inode.
Use a dedicated non-secret gate directory; never mount an administrator's parent
directory or credentials. Keep the directory traversable and gate readable by
service UIDs, with write authority confined to the trusted operator.

The operator CLI accepts `init`, `close` and `open`, plus an explicit absolute
`--file` ending in `admission.state`. `init` exclusively creates a closed gate and
refuses to replace an existing file. `close` acquires an exclusive lock, waits at
most the chosen `--timeout` (default 30 seconds, maximum 120), then writes
`closed` in place. Timeout leaves the previous state unchanged. Do not unlink,
replace or rename the live gate. `open` explicitly restores new admission.

This implementation is for one host and a local filesystem. It does not claim
multi-host or NFS coordination. Verify every replica's exact read-only mount and
environment before relying on the gate. An unset variable means no gate; this
preserves existing deployment behavior, not a completed deployment preflight.

After `close` succeeds, keep the gate closed and poll normalized Runtime
`active_prompts` until zero within the existing whole-run ceiling plus shutdown
grace. Malformed/unavailable accounting aborts the switch. Do not infer drain from
one zero reading before closing admission. Do not kill active production work on
timeout without separate authorization. Existing SSE/release/cancel remain usable;
approval decisions may persist but their continuation stays queued for explicit
retry after reopening.

## Synthetic rehearsal entry point

U6 uses `Dockerfile.u6` / `Dockerfile.u6-candidate` and independent immutable
`config/dsh/builds/*-u6.3.json` manifests under ADR-0061. Historical Dockerfiles,
release descriptors and `compose.dsh-candidate.yml` stay frozen; use the new
`compose.dsh-u6-candidate.yml` overlay for current U6 candidate builds. Ordinary
Compose source builds still select the old upstream release with the U6 operational
revision. Editing these inputs does not change a running deployment.

Check selected revisions with `scripts/dsh/build_revision.py check --build` plus
the exact build ID. There is no refresh/overwrite command. After a bound source
change, create a new revision and requalify; do not rewrite an earlier revision.

From the isolated U6 worktree, the reviewed test runner is:

```text
python3 -m tests.dsh_upgrade.rehearsal --model-key-env-file <explicit-approved-env-file> --browser-window-seconds 300
```

Only the literal `DEEPSEEK_API_KEY` field is read, never shell-sourced. Paid calls
are fixed G6 plus G5 and the BYQ approval continuation, with synthetic users and
test objects. All external feedback stays in the fake Hub; real Hub/Issue actions
are not available. Use only within the maintainer's bounded evaluation authority.

For final acceptance, pass `--ci-scope` with the exact successful `local-u6-*` CI
scope. The runner aliases those tested images into its closed test scope, verifies
identity equality, and starts with `--no-build`; only the fake Hub fixture is
built separately. It does not retag production images or fetch a floating candidate.

Also pass `--qualify-g1-g4` to re-run the other four fixed synthetic scenarios on
the same candidate artifact after the core old→new→old journey. Only G3 receives
the existing synthetic approval option. Each scenario runs once with a bounded
timeout; any failure fails the whole run. These additional G3/G4 domain writes are
separate from the core rollback's unchanged-object assertions. The runner returns
to the old artifact and drains again before cleanup.

The runner reuses the closed U5 fixture with a narrowly validated temporary U6
gate mount. It creates a unique `byq-u5-u6-*` project, exact eight services,
loopback-only ingress, independent volumes/networks, and distinct release homes.
The `u5` prefix identifies the reused isolation fixture, not a second U5 claim.
It holds the existing heavy-test lock and requires at least 3 GiB available memory.

In diagnostic mode the runner builds both Runtime images; final acceptance reuses
the CI images. It starts the old release, seeds a completed synthetic backtest
and linked artifacts, generates one G6
pending approval, and closes admission for a bounded Chrome review window. It
performs a synthetic logical PostgreSQL dump and restores it to a new database
inside the isolated PostgreSQL container. It compares every public table count,
critical conversation/approval/feedback/backtest/artifact/research row fingerprints,
and validates database constraints. Raw dumps remain outside Git under a private
`backups` directory with 0600 files; they are not production backups.

Switches use the generated exact project/manifest with `up --no-deps --no-build`
for `runtime-adapter` only. Other container IDs/start times must remain unchanged.
The same public conversation continues after the switch and rollback; no hidden
journal is migrated and no business database is rolled back. Duplicate approval
continuation is checked against one feedback and one fake intake.

Normal success and Python exception paths run ownership preflight, scoped Compose
cleanup and zero-container/network/volume verification. Drift stops cleanup rather
than broadening deletion. A host crash or unhandled OS termination is not claimed
to run `finally`; identify the exact emitted scope and validate its closed manifest
before diagnostic cleanup. Never use these synthetic cleanup commands on production.

Result files contain metadata/counts only. A diagnostic PASS is not release-ready
until final build identities, required CI and the complete U6 checklist are valid.
