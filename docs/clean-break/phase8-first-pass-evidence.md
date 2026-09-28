# Phase 8 first-pass cleanup evidence — 2026-09-28

The maintainer explicitly approved **only** the five targets in the
[read-only preview](phase8-cleanup-preview.md), accepting permanent loss of
the two old test database volumes. No permission was given for any other
Docker resource, Product database, user data, service or backup.

Before cleanup, Root rechecked both volume creation timestamps/labels and
zero container attachments; both network IDs and zero endpoints/attachments;
and the old image ID with zero container references. All five matched the
preview. The commands then removed exactly:

| Kind | Removed target |
|---|---|
| Volume | `byq-ci-postgres-data-p2local` |
| Volume | `byq-p0-pgdata-p0-1208572` |
| Network | `byq-ci-network-p2local` |
| Network | `byq-p0-net-p0-1208572` |
| Image | `byq-v090-recovery-mcp:latest`, ID `sha256:befddd5955022daca6b8d1e952aefaab9e7f99b4403c014098134abd4ccad9c5` |

Post-action inspection found all five absent. Docker volume count changed
from 45 to 43 and network count from 5 to the three built-ins. The old
Product DB source volume `byq-postgres-clean-20260904`, representative
other BYQ state volumes (`byq_dsh_sessions`, `byq_workflow_traces`,
`byq_domain_state`, `beyondquant-domain-state`) and the 2,102,827,616-byte
final archive file were still present. No running service was stopped, and no
global prune, Compose down, database command, push, merge or deployment ran.

This is a scoped Phase 8 slice. Other BYQ-labelled and anonymous volumes,
retained/rollback images and the unlabelled exited container remain
unclassified or intentionally retained. Phase 8 overall is still **OPEN**.
