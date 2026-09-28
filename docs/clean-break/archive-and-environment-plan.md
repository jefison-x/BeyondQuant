# Phase 3 archive and Phase 8–9 environment plan

Status: historical Phase 3 plan. The final old-DB archive was subsequently
created and checksum-verified; see the [current Phase 8 inventory](environment-inventory-20260928.md).
One [authorized Phase 8 first pass](phase8-first-pass-evidence.md) removed two
old test DB volumes, their empty networks and one old recovery-MCP image.
No Product DB, backup, running service or other state was removed or reset.

## Final archive preflight

1. Resolve the actual BYQ database, endpoint, schema version, volume and writer set without reading credentials into logs. Separate Product DB, test DBs, Community read-only DB and DSH-owned storage.
2. Record UTC and local timestamp, freeze Git SHA/tag, environment name, Compose/config file hashes and sanitized variable names/defaults. Archive the exact current Compose and non-secret config. Keep secret values in the existing secret store, not Git.
3. Quiesce writes or use a consistent PostgreSQL snapshot. Create `pg_dump -Fc` from the actual old Product DB to a protected archive destination, then calculate SHA-256. The destination must be selected after capacity and access check; `/tmp` alone is not an archival destination.
4. Restore a copy into a uniquely named isolated scratch DB with a guard against collisions; verify schema/table counts, selected row counts and dump readability. `scripts/pg-backup-restore.sh` can inform the procedure but must not be used with an existing scratch DB because it drops that database.
5. Write a manifest: timestamp, commit, schema version, environment, DB identity, source volume, archive location, dump bytes/checksum, validation commands/results, operator and read-only retention policy. Make archive read-only, prohibit automatic restore, prohibit use as BYQ 0.10 migration input or test fixture.

Until these facts are proven, `byq_postgres_data` and any unknown Postgres/domain/ML volume stay untouched. Community cache remains separately read-only and is never physically copied or mounted as BYQ storage. This user request authorizes planning and later Clean Break implementation; it does not make an unidentified database safe to delete.

## Scoped cleanup order after Phase 7 gate and archive

| Resource | Candidate action | Required proof |
|---|---|---|
| P4/old BYQ app, Adapter, workers, sidecars | stop, remove container, verify absence | exact Compose project/container ownership and no active unrelated user |
| Session/checkpoint/trace/runtime-cache/test volumes | remove only named BYQ-owned obsolete volumes | mount/content/backup classification and no active consumer |
| Old Product DB volume | archive then isolate/read-only; remove only after verified retention decision | validated final dump and manifest |
| P0/P2 test DB containers and networks | stop/remove only after owner/use check | exact test project scope and no active worktree use |
| BYQ-only obsolete images | remove after containers, by image ID/tag | no running reference, rollback/retention decision |
| Postgres, Redis, Python, CUDA, ML base, DSH and rollback images | retain for first pass | new stack verified before second-pass prune |

Never run global `docker volume prune` or broad image/network prune. Remove containers before images. Preserve valuable datasets, benchmark data and model caches until classified.

## Rebuildable developer environment design

One task-scoped `make` entrypoint will provide `dev-init`, `dev-start`, `dev-stop`, `dev-reset`, `dev-clean`, `dev-seed`, `dev-test`. `dev-init` validates `.env.example` and config templates without committing secrets; `dev-start` launches core services; `dev-reset` stops transient services and idempotently resets one workspace/runtime without deleting accounts or shared config; `dev-clean` previews exact BYQ Compose project/container/volume/network/cache targets before scoped removal and baseline recreation; `dev-seed` installs minimal default workspace, basic config, sample strategy, research fixture and small dataset; `dev-test` runs contract and Golden Scenarios. No target will delete source, credentials, reusable datasets or base images by default.

Profiles: `core`, `research`, `backtest`, optional `ml`, `full`. GPU/ML need not run for ordinary development. Target stack is BYQ API, thin DSH adapter, DSH, database, necessary queue, CPU worker and optional ML worker/frontend. Product MCP remains separate from Engineering MCP. Variables are documented as required/optional/default and mapped once into SystemConfig; artifact/data/worker/DSH paths and credential locations are explicit. The acceptance path is clone → init → start → reset/seed → tests on a fresh schema.
