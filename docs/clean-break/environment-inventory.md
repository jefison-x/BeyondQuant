# Phase 1–2 environment inventory

Captured 2026-09-25, Asia/Shanghai. Read-only inspection. No container, image, volume, network or database was changed. Docker source tables: [containers](docker-containers.tsv), [images](docker-images.tsv), [volumes](docker-volumes.tsv), [networks](docker-networks.tsv). Tables carry names, image ID/size/creation/use, mountpoints and attachments; `unverified` means the purpose or persistence has not been proved. Docker status can change after this snapshot.

## Git freeze

| Item | Finding |
|---|---|
| Synchronized main / origin/main | `d4c6a9e34f531d27dd0e94804be6ed0aa6f9fde3`, clean; latest fetched `origin/main` at capture |
| Freeze tag | local `pre-clean-break-main` → same SHA; created in this task, not pushed |
| Clean Break | `clean-break/runtime-simplification` from `origin/main`, isolated worktree `/home/jefison/projects/.byq-worktrees/clean-break-runtime-simplification` |
| P4 | P4-C1 code is in main commit; `STATUS.md` still calls it candidate/Draft. P4-C2 has a local worktree/branch 13 commits ahead of `origin/main`, unreviewed and preserved as reference. P4-C2/P4-D are not treated as merged or authorized. |
| Other worktrees | 144 total at capture; four other worktrees had uncommitted changes, two `/tmp` records were prunable. No cleanup performed. |
| Tags | `v0.9.0-beta`, `pre-clean-break-main` at capture. |

## Containers and services

| Container | Image | Status / port | Mount and purpose |
|---|---|---|---|
| `sleepy_leavitt` | `byq-v090-recovery-mcp:latest` | running; internal 8300/tcp | P4 worktree MCP source/tests bind mounts; legacy recovery test service on `bridge` |
| `byq-ci-postgres-p2local` | `postgres:16-alpine` | running; internal 5432/tcp | `byq-ci-postgres-data-p2local`; P2 test DB |
| `byq-p0-pg-p0-1208572` | `postgres:16-alpine` | running; internal 5432/tcp | `byq-p0-pgdata-p0-1208572`; P0 test DB |

There is no running standard BYQ Product Compose stack in this Docker snapshot. `compose.yml` declares 12 services: postgres, frontend, gateway, runtime-adapter, mcp, backend, data-worker, signal-worker, ml-worker, signal-sandbox, feedback-publisher and feedback-hub-relay. All except feedback-publisher are in the current default selection; only feedback-publisher has a Compose profile. `compose.dev.yml` adds loopback ports for four services, but Makefile does not select it automatically. Runtime service and DB availability outside this Docker daemon remain unknown.

## Images, volumes and networks

Docker has 156 repo:tag rows representing 150 unique image IDs and 80 repository references. The [image table](docker-images.tsv) records each repo/tag, ID, size, creation timestamp and running container use. Categories include BYQ GHCR untagged images, `byq-u7-artifact-local-* :retained`, rollback images, and reusable Postgres/Python/Node/Alpine bases. Current containers use `byq-v090-recovery-mcp:latest` and `postgres:16-alpine`. No image is marked safe to delete solely because it is untagged.

There are 45 volumes. Two are mounted by running test PostgreSQL containers; 43 are unmounted. Named candidates include `byq_postgres_data`, `byq_domain_state`, `beyondquant-domain-state`, `byq_ml_model_state`, `beyondquant-ml-model-state`, `byq_dsh_sessions`, `byq_workflow_traces`, preview/test and historical recovery volumes. Each volume's exact mountpoint and current attachment is in the [volume table](docker-volumes.tsv). The five networks are built-in `bridge`, `host`, `none`, plus `byq-ci-network-p2local` and `byq-p0-net-p0-1208572` with their test DB attachments. No default Product Compose network is running.

## Database and development configuration

Current `compose.yml` declares persistent Postgres/domain/ML/DSH-session/trace volumes and Product/sandbox networks. The local `.env` exists, mode 0600, ignored by Git; values were neither read nor recorded. Its overrides mean Compose defaults cannot prove the authoritative DB or volume. The only running PostgreSQL containers are test instances. Schema version, live database contents, authoritative volume and last validated backup remain **unknown**. No repository SQL dump or expected backup directory was found. Do not infer an empty database from an unmounted volume.

`.env.example` exists. Makefile has `build`, `up`, `down`, `ps`, `logs`, `smoke`, `test`, `dsh-config`, `local-ci`, `dev-check`; it lacks `dev-init/start/stop/reset/clean/seed` commands. Current init SQL contains static development-role credentials, which must be reviewed in the new rebuildable environment; no value is recorded here.

## Inventory gaps before cleanup

Identify the actual BYQ database and schema using a read-only, owner-approved connection; map its volume and backups; classify all 45 volumes and image retention obligations; inspect the four dirty worktrees before any Git cleanup. This inventory is a snapshot, not deletion authorization.
