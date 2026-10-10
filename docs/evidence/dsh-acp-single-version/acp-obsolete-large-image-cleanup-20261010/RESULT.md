# ACP obsolete large-image cleanup — 2026-10-10

## Root limited maintenance PASS

The user asked to inspect and clean the particularly large images, continuing the prior authorization to remove useless stopped build/test containers and related images. Read-only current inventory and exact references preceded mutation. Existing worktree/source and accepted build/F6 evidence were reused; no build, test, model call, publication or deployment.

- Exact planned large-image targets removed: **70**, including obsolete tagged ACP images and untagged build intermediates. None remain. Docker may also remove unused parents automatically; the target count is not a claim about the total number of metadata objects deleted.
- Removed one stopped mount-free OOM build container `b7395956180505b4d574e4cafbf6f08c90a06522772c55021da51b7f5ea41a30`, exit 137, failed corepack/pnpm native build. Its writable layer was listed at 2.57 GB. No business containers removed.
- Actual filesystem available-space increase: **83291058176 bytes = 83.29 GB = 77.57 GiB**. Free afterward: **150320320512 bytes = 140.00 GiB**.
- All remaining container identities, image IDs, running states and health states match the before inventory with only that build container omitted. Nine active services remain healthy; stopped business containers are unchanged.
- Current qualified unified image and all fourteen qualified supporting tags/IDs preserved. Parent ancestry of container/qualified images protected. No forced removal, broad prune, volume/database/configuration mutation.
- All 71 exact mutation commands returned 0. Deletion inventory and action receipts were flushed before/after mutations. Non-force deletion processed child images before parents.

## Size correction

The current image `byq-acp-unified:cur-2d581097-20261010-retryfix` / `sha256:15cdf5f97009e21af50c3cfd87d2f8d42af91e8ccaa2a82d57966bc4c2fbc6f5` is **3.62 GB in `docker images` and `docker system df -v`**. The earlier approximately 806 MB value is the compressed archive/content metric (actual three-alias tar 806271488 bytes; image inspect Size 806240209 bytes), not the Docker listing footprint. Earlier statements that called it simply an 806 MB image lacked this distinction; this checkpoint corrects that reporting. The image bytes themselves have not changed.

Default `docker images` now lists eight distinct images above 2 GB: one current 3.62 GB unified candidate plus seven 6.39–6.52 GB old images. Three old images are directly used by the running Adapter/ordinary/judgment containers; four are their parents. The judgment parent has two tags. These are live references/dependencies, not newly retained rollback copies. Removing these stored dependencies requires completing the separately gated route adoption and retiring the old containers. This cleanup does not authorize or perform that rollout.

## Receipts

- `plan.json`: exact IDs, listing sizes, captured tags/digests, direct references, decisions and parent IDs. Inspect content Size differs from CLI listing Size; the CLI listing selected the >2 GB scope.
- `images-before.json`: complete image inventory including intermediate parents, with secrets/Config.Env excluded.
- `stopped-build-before.json`: filtered state/command/mount proof; no environment values.
- `receipt.json`: precise command results, before/after container binding and qualified image checks, available-space measurement.
- `remaining-large-images.json`: post-cleanup CLI rows; list includes the two tags on one parent.
- `exact-cleanup.py`: executed bounded implementation. Initial plans were revised before mutation to protect ancestor chains and distinguish local byq RepoDigests from hosted release evidence.

No pending Product phase, Full/hosted CI, cross-daemon load, registry release or deployment gate is closed by maintenance. Prior [release handoff source PASS and remaining limits](../acp-release-store-identity-20261010/RESULT.md) remain applicable.
