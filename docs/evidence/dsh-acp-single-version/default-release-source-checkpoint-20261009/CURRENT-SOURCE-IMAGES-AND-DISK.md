# Current-source images and exact disk cleanup — 2026-10-09

This record continues the existing `codex/dsh-acp-single-version` worktree. No reset, clean, service replacement, Full run, push, merge or deployment occurred.

## Current-source image identity

- Adapter `byq-acp-adapter-source-20261009`: build exit 0; immutable image ID `sha256:8f2e7b46926b706eeaaa7fd61968ad72fb5aa4b3d88b6ceb1a08cb4073c2d867`. A networkless, read-only hash check matched the current worktree's Adapter runtime, process secrecy, judgment turn and Product profile patch files. It was not run as the live Product service.
- Judgment runner `byq-acp-judgment-source-20261009`: authoritative rc.2 build exit 0; immutable image ID `sha256:7b3cf1ef2129ea050b2ffaaf6d4d0cf36cadf693de1e08d16dcc6f573c0ba4e3`. Dockerfile verified official source commit, lock, profile and identity during build. A networkless, read-only image check matched current worktree SHA-256 for `server.py`, judgment profile and identity, continuation budget and ACP MCP identity runtime files. The image entrypoint is `python3 /opt/byq/acp_judgment_runner/server.py`; the Docker image has no explicit `Config.User`, so service runtime privilege must be judged from Compose/controller behavior separately. No live Product execution is claimed.
- These two image builds do not constitute a captured 17-image batch, Full, SBOM/export, browser acceptance or release qualification. The ACP F6 fixture source gate is recorded separately and its actual Docker run remains NOT_RUN.

## Disk cleanup requested by the user

Before cleanup, the root filesystem had about 13 GB available (95% used). Docker showed 120 images, 93 containers (9 running), 76 volumes and 566 build-cache records. The running `byq-dev-c89ff732f2` stack was checked before and after.

Deleted only these exact untagged image leaves after verifying zero container references, zero image descendants and no tags:

- `sha256:01a03eeee25de83d627d5634f6e38a00a0fc501ebb2fad0d105c5a943f4cb088`
- `sha256:e0f749aaee1f6f878660021a59160eba3ae1cb250aa0e9cf2667862964889315`
- `sha256:ae21d62770e98bd0ca961fff2ec67893134fbd26cd0330a1be7891b7b2da0763`
- `sha256:8ca97f41c98278d6e2bf26de16d6f29dabf34a26a99eb8641588d42dff7d445c`
- `sha256:aacbd95beaa015354291df16d4083e9d4ba1bfb2b0fc0d0d3208b2bc8969ff2a`
- `sha256:cc5d2062886dc0e4a17ecbbccc0234167b6a60b43eca469ea7338bdfc02c3623` (labeled `byq.qualification=unqualified-candidate`)

`docker image rm` also removed unreferenced ancestors of the first three leaves. After cleanup the root filesystem had about 23 GB available (91% used), about 10 GB more than before. All 9 scoped test containers remained healthy; the current-source Adapter/Judgment and prior authoritative Product runner image IDs still resolved. No volume, container, named rollback image, cached native session or evidence file was deleted. No broad Docker prune was run.

Disk capacity remains constrained for a 17-image Full build. The existing secret-scan worktree gate is still FAIL/classified, and release remains NOT_READY.

## Follow-up: stopped-container and related-image cleanup

At the user's follow-up request, a second exact inventory found 93 containers: 9 running and 84 stopped. A private, secret-free target manifest was saved at `/tmp/byq-acp-stopped-cleanup-20261009/container-targets.json` (SHA-256 `2a260d01fca6a180292098d5a767fb189c92135aa2857b188f0f8e350d4a0a88`). `docker rm` without force or `-v` removed exactly 55 stopped containers from three inactive isolated test projects (`byq-ci-stack-local-2519718` plus its local Postgres, `byq-acpcand`, `byq-acp-iso`) and stopped temporary build/probe containers with no Compose project. The target list was rechecked for stopped state before deletion. No volumes or bind-mounted source files were removed.

The related image manifest `/tmp/byq-acp-stopped-cleanup-20261009/image-targets.json` (SHA-256 `b7e042e5524d9f17a46b008aee419ad0e58cd31a53dda573ff1e018651150f90`) records 22 image IDs. Every selected image was formerly used by a removed container, had no remaining container or image-descendant reference, and carried only the retired test project's local tags/digests or no tag. One image had two retired CI tags; Docker rejected ID deletion without force, so both exact tags were removed instead. The other 21 were removed by exact image ID without force. Images shared with retained F6 containers, the Postgres base image, historical qualification-tagged images, foreign digest references and current-source images were excluded.

After this second cleanup: 38 containers (9 running, 29 stopped), 97 images, 76 volumes, about 33 GB root-filesystem space available (87% used). All 9 running `byq-dev-c89ff732f2` services remained healthy. The 29 retained stopped containers belong only to the user's closed local `beyondquant` stack (14), F6 qualification/rollback including explicit rollback handoff containers (12), and the current `byq-dev-c89ff732f2` Worker/Sandbox stack (3). Those were classified as protected, not as proven disposable. No broad prune or new build was run in this follow-up.

## Root-cause audit and 60 GB free-space gate

The follow-up root-cause audit corrected the earlier incomplete accounting. Privileged `du` found about 144 GB in `/var/lib/containerd` (about 116 GB overlay snapshots and 28 GB content store); `/var/lib/docker` was about 9.3 GB, mostly preserved volumes. Docker initially attributed about 149 GB to images and 40.55 GB to build cache. Ordinary unprivileged `du /` had omitted the root-owned containerd store, explaining its misleading 52 GB total versus `df`.

Docker reported zero active build-cache records. The pre-prune `docker system df -v` snapshot is private at `/tmp/byq-acp-stopped-cleanup-20261009/docker-df-before-cache-prune.txt` (SHA-256 `c0340c45ceca579d9d673aa110ea1da3451e233f7818921a2d648ed12c18c44f`). A build-cache-only prune of unused entries older than 24 hours reported 19.17 GB reclaimed; a second default dangling-cache-only prune reported 4.884 GB. Neither operation removed images, containers or volumes. Actual root free space rose from 33 GB to 55 GB after cache cleanup.

At the user's correction that historic rollback images are no longer required, all 12 stopped `byq-acpf6` containers, including the old rollback-handoff names, were removed without `-v`; their secret-free private target manifest is `/tmp/byq-acp-stopped-cleanup-20261009/f6-stopped-container-targets.json` (SHA-256 `a46158fffa118a8059afe21bb6b155cc71a227da2e7afe39f8db7546e378934b`). Five exact old `prebuild`, `pre-diag` and 2026-10-05 qualification image IDs were checked for zero container/descendant references and removed without force. Their tags were `byq-acpf6-runtime-adapter:prebuild-20261008`, `byq-acpf6-runtime-adapter:pre-diag-20261008`, `byq-acpf6-acp-product-runner:prebuild-20261008`, and `byq-runtime-adapter-acp:qualification-20261005-slot-fix6` / `slot-fix7`. Current running and current-source images remained intact. Volumes were not removed.

Final readback: root filesystem 251 GB total, 176 GB used, **63 GB available** (74% used); 94 images, 26 containers (9 running), 76 volumes, 74 build-cache records. All 9 `byq-dev-c89ff732f2` services were healthy. The requested at-least-60-GB free-space gate is PASS. Existing ACP release and secret-scan gates are still separate.

## Post-fixture disk readback and cleanup

The captured F6 batch temporarily reduced root free space from 63 GB to 20 GB. Its exact CI scope `acpf6-20261009-8c8c5264` was removed only after preserving the failed fixture and synthetic database receipts described in `ACP-F6-RELEASE-FIXTURE.md`. `scripts/ci/cleanup-resources.sh --scope=acpf6-20261009-8c8c5264` returned 0; a separate `--verify-only` readback passed. This removed the scope's temporary containers, images, networks and volumes; no `byq-dev-c89ff732f2` service or its data volume was touched. Root free space rose to 35 GB.

A subsequent build-cache-only prune reported 23.42 GB reclaimed and raised free space to 57 GB. The two now-unreferenced diagnostic Adapter/Judgment source images identified above were removed by exact tag without force; their identity evidence remains in this document. A frozen private manifest listed 192 older-than-24-hour, untagged images with no container reference: `/tmp/byq-acp-stopped-cleanup-20261009/old-dangling-image-targets.json`, SHA-256 `2a096b96ee77146694a44730ee95353ae4995ae8c9eb25e413993fa852f9ce23`. `docker image prune --force --filter until=24h` then deleted only old dangling images and reported 3.387 GB reclaimed; containerd garbage collection produced additional delayed free-space gain. No tagged image or volume was selected by that prune.

Final independent readback: root filesystem 251 GB total, 168 GB used, **71 GB available** (71% used). All 9 existing `byq-dev-c89ff732f2` services were healthy. The user's at-least-60-GB free-space gate is PASS after the new build and its cleanup.

## Second F6 batch space readback

The second captured 17-image scope `acpf6-20261009-4f0c7e21` started with about 71 GB free and bottomed at about 28 GB during the build and early fixture. Its failure receipts and synthetic PostgreSQL dump were retained before cleanup; see `ACP-F6-RELEASE-FIXTURE.md`. The exact-scope cleanup returned 0 and an independent `--verify-only` check passed. Free space rose to 43 GB. `docker system df` then showed 20.47 GB reclaimable in unused build cache; `docker builder prune --force` reclaimed that reported amount. Final `df -h /`: 251 GB total, 177 GB used, **62 GB available** (75% used). All nine original `byq-dev-c89ff732f2` services remained running. The requested 60 GB free-space gate is PASS after this batch.

## Third F6 batch space readback

The third 17-image scope `acpf6-20261009-81d40a6e` started with 62 GB free and reached a low of about 19 GB during build and fixture. After preserving its failed structured-audit receipts and isolated database, exact-scope cleanup and independent verification passed; free space rose to 34 GB. An ordinary unused build-cache prune reclaimed 20.22 GB, yielding 53 GB free. With no active build, `docker builder prune --all --force` reclaimed another 43.15 GB of unused cache. Final root readback: 251 GB total, 149 GB used, **90 GB available** (63% used). All nine original development services were healthy. The requested 60 GB free-space gate is PASS after the third batch.

## Fourth F6 batch space readback

The fourth 17-image scope `acpf6-20261009-9a762c14` began with 90 GB root free space and was at about 47 GB when the background-chain failure was saved. After private native-session, Product-state, database, log and image-manifest preservation, exact-scope cleanup plus independent `--verify-only` passed. Free space rose to 62 GB. With the build ended, `docker builder prune --all --force` reclaimed 30.42 GB of unused cache. Final root readback: 251 GB total, 149 GB used, **90 GB available** (63% used). The user's at-least-60-GB gate is PASS after this batch.

## Fifth F6 batch space readback

The fifth captured 17-image scope `acpf6-20261009-5c31e8a4` began with 90 GB free and reached about 47 GB while its live fixture ran. The saved primary chain passed but the wrapper failed for a missing independent closeout; the bounded browser readback and private evidence are described in `ACP-F6-RELEASE-FIXTURE.md`. After those files, isolated database, logs and native-session copies were preserved, exact-scope cleanup exited 0 and an independent `--verify-only` check passed. Root free space rose to 62 GB. With the build ended, `docker builder prune --all --force` reclaimed 30.42 GB of unused cache. Final root readback: 251 GB total, 149 GB used, **90 GB available** (63% used). All nine original `byq-dev-c89ff732f2` services were healthy. The requested at-least-60-GB gate is PASS; release qualification remains separate.
