# ACP release handoff: Docker store identity (2026-10-10)

## Scope and status

Continuation uses `/home/jefison/projects/.byq-worktrees/dsh-acp-single-version`, branch `codex/dsh-acp-single-version`, HEAD `2d5810973240c5d7692569319c2b5ab337ae2082` plus preserved working changes. No reset or cleanup of source changes. ADR-0110 single-image candidate stays explicitly selected; the default Compose release route is unchanged.

The prior [current-image and synthetic F6 checkpoint](../acp-unified-retry-and-f6-20261010/RESULT.md) is reused. This slice changes only release export/publish identity handling and its focused tests, plus documentation/evidence. No build, container start, provider call, Docker load, SBOM generation, registry write, commit, push or deployment occurred. Three exact temporary tags were created for `docker save` and removed afterwards.

Final independent Tester **52 tests + 21 subtests PASS**, Reviewer Functional/Tests/Clean Break Architecture **PASS**, and Root **limited source/docs/precise-cleanup PASS**. Final source hashes match before/after testing; compile and diff checks PASS. The previous source checkpoint and actual archive proof have limited PASS; their hashes are kept separately below. Overall adoption/release remains **NOT_READY**.

## Defect and repair

On this Ubuntu containerd image store, the qualified image's local `.Id` is the OCI manifest digest `sha256:15cdf5f97009e21af50c3cfd87d2f8d42af91e8ccaa2a82d57966bc4c2fbc6f5`; its canonical config digest is `sha256:a2ba7f82b86233338f1f2a49932f52bec6325f41e9b6b7842515d74f7a132ec3`. Treating the former as config identity would reject a valid cross-store load or registry readback. The local manifest ID is not evidence of a published registry digest.

New internal handoffs use `byq-release-images.v2`: each service records the captured tested store ID, canonical config-byte hash, archive manifest and ordered layer digest/size/diffID bindings, and platform. Export verifies source inspection against archive bytes; publish verifies the whole receipt/archive and all loaded tags before any SBOM/push. The external `byq-release.v1` and DSH identity use canonical config ID. The three ACP aliases retain one image, repository, SBOM and push. Candidate-tag registry readback uses the Docker CLI `Descriptor.digest`/`Descriptor.platform` structure, verifies config/platform and raw manifest hash when present, and rejects ambiguity.

Both OCI and Docker compatibility views are verified against each exact tag/config/ordered layer tuple. Duplicate keys, aliases, unsafe tar members, unknown payloads, substitutions and conflicting metadata fail closed. Modern Moby classic-source saves may also contain OCI layout, raw tar layers, `LayerSources`, `repositories`, `Parent` and hash-named legacy metadata; the bounded branch verifies these without extracting files or rebuilding. A v1 receipt is accepted only when its ID equals the archive's actual canonical config hash, including verified modern OCI-layout saves. A manifest ID masquerading as a v1 config ID is refused before load.

## Evidence boundaries

| Gate | Result | Evidence and limitation |
| --- | --- | --- |
| Final focused source tests | PASS, limited | `artifacts/final-result.json`: 52 tests + 21 subtests, exit 0, 1.32 s pytest summary; before/after final hashes match; compile/diff PASS. Independent Reviewer and Root limited PASS in `artifacts/independent-review-and-root.json`. |
| Previous independent source checkpoint | PASS, limited | `artifacts/checkpoint-test-result.json`: 50 tests + 21 subtests, exit 0, unchanged `d09debdb…` / `0a73af02…` sources, compile and diff check PASS. Superseded for final source test status. |
| Actual Ubuntu archive | PASS, checkpoint only | `artifacts/checkpoint-three-alias-archive-proof.json`: 806271488 bytes; SHA-256 `ddc2fbdd457507bb9d86b167b9e4bb0c564c76fee1977385b86cab3a54c98b9d`; three exact aliases, one manifest/config, all 28 compressed layers and decompressed diffIDs verified. Parser 7.979 s; process maximum RSS 29816 KiB. Executed on the previous d09 source checkpoint, not the final source hash. No duplicate large-payload validation after classic support changes. |
| Classic/containerd loaded identity branches | Synthetic only | Small full 17-tag/15-payload export→v2→publish tests, including once-only ACP publication and pre-public-write negatives. Actual Docker load across stores NOT_RUN. |
| Modern classic real host export | NOT_RUN | Primary-shaped raw-layer fixture PASS is source evidence only; arbitrary classic archives are not qualified. |
| Actual trusted-main Full/registry/attestation | NOT_RUN / OPEN | No publication or hosted run. Adopting-commit architecture and historical 13-service v1 release compatibility remain open. |
| Existing build/role/F6 evidence | REUSED | No source changes in image COPY inputs; 91 current-image keys and 595 supporting-image keys rechecked with zero mismatches before this slice. Existing image and 14 supporting images retained for pending CI. |
| Exact probe cleanup | PASS | `artifacts/tar-cleanup.json`: three exact tar files removed after complete hash receipts (2418812416 bytes, ~2.42 GB). Original project 9 healthy active + 3 stopped containers unchanged; current qualified image preserved. Free space 67031171072 bytes (~62.43 GiB). No prune or Docker resource mutation. |

The actual archive proof calls loaded-store verification with metadata only; it does not constitute real cross-daemon loading. Final changes add strict raw-layer/Moby compatibility paths and do not retroactively change the proof's executed source hashes.

## Accepted limits and remaining work

External/foreign layer URLs, missing descriptor payloads, unrecognized metadata and unproved store IDs remain rejected. Moby can preserve a pulled layer's original compressed descriptor while exporting only raw DiffID bytes. Such an archive is not accepted by the strict OCI branch; do not infer hosted compatibility from the raw-layer fixture. Confirm the exact trusted-main Docker version/store/archive output before qualification. Pure traditional Docker-save archives stay under their strict legacy parser; no generic historical migration support is claimed.

Required next gates remain the adopting-commit architecture suite, authorized PR/Full CI, actual trusted-main shared registry manifest/config/SBOM/attestation binding, and historical release-manifest compatibility. Product phase progression and production rollout are separate gates.

## Failure history retained

The two diagnostic logs are summaries, not complete raw pytest output: initial stale Docker CLI fixture failures; untagged manifest bookkeeping failure; corrected real tagged/untagged parser checks; reviewer P2 on compatibility per-tag binding; and an isolated-test-cwd subtest failure. These failed runs remain failed. The subsequent checkpoint/final receipts provide their own source hashes and results. Modern-classic support was added after the large checkpoint proof, with source edits frozen during that proof.

## Primary format references

- [Docker CLI v29 manifest JSON types](https://github.com/docker/cli/blob/v29.0.0/cli/manifest/types/types.go): nested Descriptor and raw/payload shape.
- [Moby v28.5.2 save implementation](https://github.com/moby/moby/blob/v28.5.2/image/tarexport/save.go): classic save OCI layout, compatibility metadata and raw TarStream.
- [Moby v28.5.2 load implementation](https://github.com/moby/moby/blob/v28.5.2/image/tarexport/load.go): manifest.json load and layer decompression/diffID binding.
- [Moby layer implementation](https://github.com/moby/moby/blob/v28.5.2/layer/ro_layer.go): TarStream diffID verification and stored descriptor distinction.

Final small-artifact inventory is `artifacts/SHA256SUMS.json`. Independent review and Root status are recorded in `artifacts/independent-review-and-root.json`. The cleanup preflight initially counted all project containers as active, stopped before any deletion, then verified the recorded nine active IDs and all twelve original project states; the receipt retains this correction. Raw multi-hundred-MB tar files are not committed; hash/member/layer receipts are retained.
