# Phase 8 first-pass cleanup preview — 2026-09-28

Status: **read-only proposal; nothing below has been stopped or deleted.**
The current [inventory](environment-inventory-20260928.md) and verified old
database archive support a small first pass. The existing database, users,
backup, running services, anonymous/Compose volumes, unrelated container and
rollback/base images are outside this proposed action.
Volume reclaim sizes are unmeasured: host directory access is denied and the
optional Docker disk-usage report was stopped when it ran too long. No space
saving is promised by this preview.

| Exact candidate | Identity/ownership evidence | Proposed action after authorization |
|---|---|---|
| `byq-ci-postgres-data-p2local` | Created 2026-09-22 21:29 +08; label `byq.ci.scope=p2local`; old inventory shows attachment to P2 test PostgreSQL, now detached. | Remove this **test DB data volume** only after confirming P2 test data may be discarded. |
| `byq-p0-pgdata-p0-1208572` | Created 2026-09-22 15:34 +08; old inventory shows attachment to P0 test PostgreSQL, now detached; no owner label. | Remove this **test DB data volume** only after confirming P0 test data may be discarded. |
| `byq-ci-network-p2local` | Network ID `9ee912ee1f293de63a930a5b015e020054dacf83bbd58737e4054b0b64b405ac`; label `byq.ci.scope=p2local`; zero endpoints. | Remove after exact ID/empty-endpoint recheck. |
| `byq-p0-net-p0-1208572` | Network ID `6dbdc52f91088a927c3ad7418a6d82950b7e6e00fdeb4646adce4b988c8313cd`; old P0 test network; zero endpoints. | Remove after exact ID/empty-endpoint recheck. |
| `byq-v090-recovery-mcp:latest` | Image ID `sha256:befddd5955022daca6b8d1e952aefaab9e7f99b4403c014098134abd4ccad9c5`; old inventory ties it to the now-absent `sleepy_leavitt` P4 test container. | Remove the exact old recovery test image after confirming no container reference; do not prune other images. |

Before any action, re-read each exact resource ID/label/attachment and abort
on drift. There are currently no matching live containers to stop. Execute
only the approved names/ID in this order: volumes and now-empty networks,
then the one old image; verify each target absent and all excluded resources
still present. If a volume has a new attachment or the image has a new
container reference, skip it and report. No global Docker prune and no
`compose down --volumes` are permitted by this preview.

The old Product database source volume
`byq-postgres-clean-20260904` is **KEEP**. Its archive checksum matches the
recorded manifest, but the application schema revision is unknown and the
current host cannot repeat the restore validation. Other state volumes remain
unclassified. A separate later decision must identify each of them before any
additional cleanup. This preview is not a Phase 8 completion claim.
