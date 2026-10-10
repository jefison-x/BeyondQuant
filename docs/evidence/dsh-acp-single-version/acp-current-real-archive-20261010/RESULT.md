# Final-source real three-alias archive and source binding

## Scope and outcome

2026-10-10, existing isolated `codex/dsh-acp-single-version`, HEAD
`2d5810973240c5d7692569319c2b5ab337ae2082` plus preserved working changes.
Independent Tester executed one actual `docker save` from the retained unified
image. Independent Reviewer and Root give **limited PASS** for real archive
parsing and source-image binding under the final release parser.

This closes the prior final-source real-archive parsing gap. The earlier d09
archive remains a historical checkpoint. It does not qualify the complete
17-service `images.export`, cross-store loading, hosted runner or registry.

## Verified facts

| Check | Observed result |
| --- | --- |
| Final `scripts/release/images.py` | SHA-256 `dc68c24fd4436b0ddeee89b7e7486e8ec1894d3bcc2fb5faee37a9e257f6b783`, unchanged before/after |
| Existing image inputs | All 91 source/hash entries unchanged; no rebuild or F6 rerun |
| Executed probe | SHA-256 `1c775ba1dedd2c6a372e039e815e9b5911130085b5dd1797b42bc82fc3f5b89b` |
| Actual archive | 806,272,000 bytes; SHA-256 `e435117fad3db1b7d65d116a9156cf533a506952aeb5465b20eb0dac3117b37f` |
| Three exact temporary labels | One OCI manifest `sha256:15cdf5f97009e21af50c3cfd87d2f8d42af91e8ccaa2a82d57966bc4c2fbc6f5`; canonical config `sha256:a2ba7f82b86233338f1f2a49932f52bec6325f41e9b6b7842515d74f7a132ec3` |
| Layers and platform | Each label binds the same 28 ordered digest/size/diffID entries; source RootFS and linux/amd64 match |
| Source binding | Actual local inspection for each alias passed `_verify_local_image_binding(..., source=True)` |
| Time / memory | Save 13.077 s; parser 8.468 s; total 22.839 s; peak process RSS 425,180 KiB (about 415 MiB) |
| Existing resources | 26 containers, eight running, and 15 protected image tags unchanged |
| Exact cleanup | Three probe labels removed without force and absence verified; tar removed only after complete hash receipt file and parent-directory fsync; zero cleanup errors |

Actual local Docker is 29.1.3 with `io.containerd.snapshotter.v1` and
containerd 2.2.2. This is the observed local store; it does not establish the
future hosted runner version or archive shape. The archive size is not the
Docker listing's uncompressed image size.

The frontend had already exited before this turn's resource preflight. The
probe preserved that current eight-running baseline; it did not start or stop
any application. Earlier nine-running receipts remain historical facts.

## Evidence and limits

`artifacts/result.json` is the executed probe's PASS receipt.
`artifacts/proof-before-cleanup.json` contains the complete archive hash before
removal. The source, layer and resource metadata contains no Config.Env or
private inspection dump. `artifacts/tester/` contains the independent checks;
`artifacts/reviewer/` retains the read-only review. `artifacts/tester/execution-tool-result.json` preserves the observed original
`exec_command` return (chunk `58911a`, exit 0 and original stdout), copied from
the actual tool response without rerunning or reconstructing it from the probe
receipt. Its provenance is in `execution-attestation.json`. The Reviewer did
not reread the removed tar or repeat Docker commands; this execution return
was added after the initial final review.

Pre-execution review blocked an earlier probe version: an unwritable receipt
could have prevented alias cleanup. Independent cleanup steps now mark failures
without blocking remaining safe cleanup; unknown alias identities are retained.
A second review requested file/directory fsync before deleting the archive,
which was added before the sole execution. No claim of automatic cleanup after
SIGKILL or host loss is made. The normal executed path is fully receipted.

No source implementation change, build, container start, network/provider
request, Docker load, SBOM generation, registry write, commit or deployment
occurred. A same-store load was intentionally not added because it would not
prove transfer into a fresh or different image store.

Remaining gates are the complete exact-source adopting-commit architecture /
Full CI, genuine 17-service export and isolated/hosted loading, registry
manifest/config/platform/SBOM/attestation readback, historical signed-release
operation where needed, and separately authorized default adoption/deployment.
Overall adoption/release remains **NOT_READY**.
