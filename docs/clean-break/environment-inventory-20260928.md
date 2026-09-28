# Phase 8 current environment inventory — 2026-09-28

Read-only snapshot for the Phase 8 worktree at parent commit `9af6a466`.
This supersedes the **Docker state** in the 2026-09-25
[inventory](environment-inventory.md); it does not rewrite that historical
snapshot. Docker list/inspect metadata and backup file metadata were read.
No service, database, volume, image, network, backup or secret was changed.

| Resource | Current observation | Difference from September 25 |
|---|---|---|
| Containers | One exited, unlabelled `exciting_goldstine` (image `sha256:b8aaa328…`, no mounts or published ports); no running BYQ stack. | The old `sleepy_leavitt`, P2 PostgreSQL and P0 PostgreSQL containers are absent. Ownership of the remaining exited container is unverified. |
| Images | Regular list: 156 tag/digest references, 150 unique IDs, matching the old snapshot. Full list: 202 rows/196 unique IDs; 46 additional untagged IDs are visible. | Do not infer that untagged images are unused. Preserve recent intermediate IDs, rollback/retained images and reusable bases pending attribution. |
| Volumes | 45 names, same set as old snapshot, none attached to the only current container. | Both old test PostgreSQL volumes are now detached. Other volume contents and retention needs have not been inspected. |
| Networks | Built-in `bridge`, `host`, `none` and two empty P0/P2 test networks. | The two test networks now have zero endpoints. |

## Final old database archive

`/home/jefison/backups/byq-clean-break-final-20260927T234310Z/byq-domain.dump`
is 2,102,827,616 bytes, mode `0400`. Its current SHA-256
`0d62af957f545da40fc13083914c1d4cc614f04414fe6806d36bc772a4d06183`
matches the private archive manifest and the Phase 7 gate record. The manifest
identifies a PostgreSQL 16 custom-format backup of `byq_domain`, source
volume `byq-postgres-clean-20260904`, with a previously recorded readable TOC
and isolated restore check. That source volume still exists and is currently
unmounted. Its application schema revision is recorded as **unidentified**;
the manifest's `byq-clean-break-db-archive.v1` is only the manifest version.
The host lacks `pg_restore`, so this inventory did not independently repeat
the TOC or restore check. It did not connect to the old database.

## Current ownership limits

The old Product database source volume, other Compose-labelled persistent
volumes, `byq-preview` volumes, 28 anonymous volumes, retained/rollback
images, reusable infrastructure bases and 46 newly visible untagged image
IDs are **not Phase 8 first-pass deletion targets**. The only initial review
candidates are the two former test DB volume/network pairs and the old
recovery-MCP test image in the [scoped preview](phase8-cleanup-preview.md).
Current metadata does not prove contents of detached volumes are disposable;
an exact operation authorization is still required. The unlabelled exited
container is also excluded because its owner is unknown.
