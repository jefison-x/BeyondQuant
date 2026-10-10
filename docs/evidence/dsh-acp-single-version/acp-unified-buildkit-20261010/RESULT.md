# ADR-0110 BuildKit path: bounded local qualification (2026-10-10)

Status: independent Tester/Reviewer and Root **limited PASS for the single local BuildKit path**; ADR-0110 adoption remains OPEN. Reused the existing dirty isolated `codex/dsh-acp-single-version` worktree at HEAD `2d5810973240c5d7692569319c2b5ab337ae2082`. No source reset, default route change, image prune, push, registry publish, PR, merge or deployment.

## Exact attempt

- Host before build: 11 GiB RAM, 8 GiB swap; about 6.4 GiB MemAvailable, 4.1 GiB SwapFree and 65 GiB free disk. Nine existing BYQ service containers were healthy and untouched.
- Host Docker lacked a Buildx CLI plugin. Downloaded Ubuntu `docker-buildx` 0.30.1 package into `/tmp` and extracted only its plugin to `/tmp/byq-acp-docker-config/cli-plugins`; no system package was installed. Plugin SHA-256: `6a74d756c0877c53763672273fc4462af8e8128d9942e8b69a15f0b12cb03540`.
- Created only `byq-acp-0110-buildkit-20261010` with the `docker-container` driver, BuildKit v0.33.1, `[worker.oci] max-parallelism = 1`, and Docker-confirmed container limits Memory=4,294,967,296 bytes, MemorySwap=5,368,709,120 bytes. Source was the existing `services/acp_unified/Dockerfile`; all 20 `BYQ_DSH_BUILD_*` arguments came from `scripts.dsh.acp_build.build_environment` and the authoritative resolver. The output was `--load`, local only.
- Build tag `byq-acp-unified:cur-2d581097-20261010-buildkit`; exit **0**, no resource abort, elapsed 450.0 seconds. New local ID `sha256:2f225ce10631ec2ba6bc5d8dfc99cf2f6dac446367fb3711c86cdd8ef6ada8d1`, `docker image inspect .Size` 806,234,442 bytes, default User `byq`, platform `linux/amd64`. The earlier legacy-built local ID `sha256:3d599eb4cf62d3bfd76443e7c69ca94de2a0f43185a7e74047a310c4818f73f8` was preserved; different image IDs are expected for separate builder outputs and do not establish identical layer bytes.
- 45 ten-second samples: minimum MemAvailable 3.346 GiB, SwapFree 3.913 GiB, free disk 54.015 GiB. The monitor would have aborted after two low samples below 2 GiB, 1 GiB or 25 GiB respectively. Builder `.State.OOMKilled=false` after build.
- Narrow **network-disabled** checks on the BuildKit image: missing role exit 64, unknown role exit 64, Adapter as root exit 77. In-image readback matched authoritative DSH source commit `639ed015397290b3745d163aafe02ffee4aa3f84` and both Product/Judgment profile SHA-256 values. These checks passed; they do not replace a three-role Compose boot on this new image.
- Removed only the named temporary builder and its own cache. Its scoped container and volume were absent afterward. The new image was retained. Root free disk returned to 62 GiB.

## Local receipts

Ignored local evidence under `.ci-artifacts/acp-unified-buildkit-20261010/`: `build.log` (SHA-256 `c119a3a9c0ec02ab228ceecc6a37591a5a752bf5ff73d2fc11ed67490a49895e`), `receipt.json`, `resources.csv`, `runtime-readback.json`, `postbuild-image-inspect.json`, `postcleanup-inventory.json`, `source-fingerprint.json`, and `builder-tool-output-transcript.md`. The latter explicitly transcribes earlier successful Codex `exec_command` output; it is not a fresh inspect of the removed builder. The two post-build JSON files come from subsequent read-only Docker commands, while the selected source fingerprints were calculated after the build. The temp Buildx executable/config and orchestrator script are under `/tmp/byq-acp-*`; they are not committed release artifacts. No secret values were supplied as build args.

## Independent gate

- Tester: **limited PASS** after independently checking the BuildKit log hash/order/completion, 45 resource samples, authoritative source/profile hash readback, the retained image's ID/user/platform and absence of exact-name builder resources. Tester did not build or start a container. Tester notes that the Dockerfile is untracked in this dirty worktree; HEAD alone does not identify the full build context. The post-build selected source hashes mitigate but do not eliminate that limitation.
- Independent Reviewer: **limited PASS** for one local BuildKit path after matching the exported ID to a fresh image-inspect receipt and checking the fresh exact-name cleanup inventory. Builder cap/OOM and removal original outputs are in this chat; the file transcript is secondary evidence. No claim of independently re-runnable limit inspection after the builder was removed.
- Root: **ADR-0110 criterion 5 local BuildKit path limited PASS**. This is one successful resource-capped local build with focused identity and entrypoint checks, not a production release or a waiver. It does not advance the default topology or the remaining adoption criteria.

## Limits

This proves one bounded local BuildKit build and the listed readback checks. No full three-role boot on this *new* image, 17-image batch, F6 business chain, Full/hosted CI, registry digest/readback, attestation, promotion or production deployment occurred. ADR-0110 adoption remains OPEN until its remaining criteria are met; the default per-role Compose route is unchanged. This result is not a BuildKit waiver or a release qualification.
