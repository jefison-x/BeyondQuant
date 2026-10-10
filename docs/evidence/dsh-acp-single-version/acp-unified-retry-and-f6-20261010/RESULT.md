# ACP unified image: retry repair and local F6 (2026-10-10)

**Root: limited local PASS after Tester and independent Reviewer. Overall adoption/release NOT_READY.**
Existing isolated worktree `codex/dsh-acp-single-version`, HEAD `2d5810973240c5d7692569319c2b5ab337ae2082` plus preserved uncommitted changes. No reset, commit, push, PR, merge, publication or deployment; Phase 17 remains OPEN. Default ACP release/Compose routing remains per-role; the single-image route was an explicit isolated candidate.

## Current accepted local checkpoint

| Gate | Actual result | Evidence |
| --- | --- | --- |
| Retry/unknown-START source | 48 passed in 20.83s; six file hashes unchanged; 17 prepared-guard cases | `acp-runtime-unified-20261010-04.*`, independent audit |
| One new ACP BuildKit image | exit 0, 452.2s; 4 GiB memory/5 GiB total cap, concurrency 1; 91 source keys unchanged | `.ci-artifacts/acp-unified-retry-buildkit-20261010/` |
| Baked source / role rejection | 87 target hashes match, including both runner contract copies; five exact exit+stderr negatives PASS, no leftover probes | `unified-source-check.json`, `negative-entrypoint.json` |
| Current three-role boot | same local image ID, healthy; Adapter UID/GID 10002:10002; two root runner PID1s with read-only roots | `.ci-artifacts/acpunified-20261010-c42f17/unified-baseline-live-roles.json` |
| Supporting batch reuse | 14 B images reused after complete 595-key COPY source/hash equality; 17 service refs/15 distinct image IDs | `batch-reuse-receipt.json`, `reused-14-source-inputs.json` |
| Synthetic local F6 wrapper | one run, primary PASS + distinct closeout PASS + desktop/mobile 2/2; diagnostic hashes validated; exact same session/Job across Gateway restart | `f6-acp-release-result.json`, primary/closeout receipts |
| C scope cleanup | supervisor exit0/173.5s; cleanup0; containers/networks/volumes/role aliases empty; original9 unchanged | `f6-supervisor-receipt.json`, `postcleanup-inventory.json` |
| Obsolete test-image cleanup | 19 exact tags removed, two stale unified images absent; new image and 14 supporting images retained; original9 unchanged | `obsolete-test-cleanup.json`, `old-test-images-inventory.json` |

Current tag: `byq-acp-unified:cur-2d581097-20261010-retryfix`.
Local Docker image ID: `sha256:15cdf5f97009e21af50c3cfd87d2f8d42af91e8ccaa2a82d57966bc4c2fbc6f5`. Docker inspect Size: **806,240,209 bytes** (~806 MB); user `byq`, linux/amd64. This is one image used by three ACP containers. It is a local image identity; a published registry digest has not been qualified.

## Repair and evidence preserved

The real first ordinary-slot retry defect was an exclusive guard collision after known busy/missing-credential no-START. `_write_continuation_guard` now returns the exact payload hash; guard retirement requires private ownership/mode, root/hash identity and safe link state. First-slot START now requires a durable cleanup fence with current Backend authority. Only proven no-START may retire the exact guard and remove its exact empty prepared binding under the authority lock. Unknown START, write uncertainty, changed binding and failed retirement keep the retry fence; they do not overwrite a changed recovery file. Existing completed-root terminal-ACK rotation is separate and unchanged. Backups are preserved at `/tmp/acp-prepared-guard-backup-20261010/`.

Failures remain failures: initial Runtime collection lacked the retired SDK; full `-02` was 658 passed / 6 failed / 104 skipped; `-03` was 35 passed / 4 failed and its incorrectly prefixed source-hash receipt is invalid. The six original failures are covered by the subsequent focused slot tests and the prior green chat/usage selections. `-04` is a distinct green focused receipt, not a rerun of the 658 accepted tests or a claim of one green full Runtime suite. The new guard suite has 16 functions / 17 parameterized cases. Host-only execution had 6 PASS and 11 fixture setup errors due to missing httpx; the actual container gate is the authoritative 48 PASS.

Earlier architecture repair reached 1004 tests / 11 skipped / exit0 (`acp-architecture-repaired-20261010.log`) before the latest runtime/CI edits. It is retained as a checkpoint; architecture on the adopting commit remains NOT_RUN. A's role-readback false failure occurred before any F6 call and is preserved. B's 14-image build was PASS and F6 NOT_RUN; C reused those unchanged images and rebuilt only ACP.

## Remaining gates and continuation

- ADR-0110 criterion 2: complete architecture evidence on the actual adopting commit, not this dirty-tree checkpoint.
- Criterion 3: registry-verified shared manifest/config digest and release binding. Local BuildKit export reports a manifest digest as Docker `.Id` and a distinct config digest; publisher/transfer behavior for this containerd store is unqualified. Keep runtime capture IDs and registry config binding separate when closing this gate.
- Criterion 6: Full/hosted CI and trusted-main release qualification. Current local 17-reference capture and synthetic F6 close their limited local slices only.
- The fixture reports provider usage unknown, crash recovery NOT_RUN, and duplicate/revoke/budget/lost-response/unfinished-root negative scopes NOT_RUN. It is not external provider or model-quality qualification; earlier accepted real-provider evidence was reused without another paid call.
- Historical 13-service `byq-release.v1` compatibility is separately OPEN; it does not invalidate this current 17-service candidate receipt.

Fourteen supporting images remain under exact `byq-acp-qualified-batch:acpunified-20261010-c42f17-*` tags for pending CI. Their planned/created IDs are in `retained-batch-images.json`; end-of-qualification cleanup uses the captured exact-tag helper, never prune. B's obsolete aliases and the two older test-image IDs are now retired. Current disk available: 67054944256 bytes (62.4 GiB). Nine original services remain running and healthy; their three pre-existing stopped legacy containers were outside this cleanup scope.
