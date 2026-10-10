# ACP unified candidate: current-source local image and three-role boot (2026-10-09)

**Status: evaluation only; ADR-0110 adoption OPEN.** Existing dirty isolated worktree and all prior evidence were preserved. No commit, push, PR, merge, release publication or deployment was performed.

## 2026-10-10 later BuildKit-path follow-up

A separate resource-capped BuildKit build of the same unified Dockerfile completed and passed focused source/profile readback and entrypoint refusal probes. Tester, independent Reviewer and Root gave ADR-0110 criterion 5 **limited local PASS**; see `../acp-unified-buildkit-20261010/RESULT.md`. That new BuildKit image has not received a full three-role Compose boot, and registry digest/F6/17-image/Full CI gates remain OPEN. Statements below about BuildKit NOT_RUN describe the earlier boot checkpoint.

## 2026-10-10 green-script follow-up

A fresh evidence directory reused the same image for one more bounded isolated three-role boot. The corrected script exited 0 (`failed=0`); each running container returned the same local `.Image` ID, healthy state, expected role, PID1 identity and per-role boundary. Exact project cleanup returned down_rc=0 and 0/0/0 leftovers. Independent Tester, independent Reviewer and Root gave **ADR-0110 criterion 4 local boot limited PASS**. The original exit-1 receipt below is preserved as historical evidence and was not overwritten. New local receipt: `.ci-artifacts/acp-unified-three-role-boot-green/ROOT-RESULT.md`. Registry digest binding, BuildKit and unified release/F6/Full CI gates remain OPEN or NOT_RUN.

## Local image build

The current-source unified image `byq-acp-unified:cur-2d581097-20261009-4g` built with the legacy Docker builder under a 4 GiB RAM / 5 GiB combined RAM+swap limit. Its local image ID is `sha256:3d599eb4cf62d3bfd76443e7c69ca94de2a0f43185a7e74047a310c4818f73f8`. The build reached Step 82/82 and in-image DSH source/release/profile readback passed. `docker inspect .Size` reported 806,269,384 bytes (0.806 GB / 0.751 GiB); separately, `docker images .Size` displayed 3.62GB. Those are separate Docker display fields, not a measured exclusive disk footprint. The build receipt does not record a build-time Dockerfile byte hash. BuildKit remains NOT_RUN.

Raw local build evidence: `.ci-artifacts/acp-current-source-4g/receipt.md`, `build.log`, `verification.json`; Root correction and original negative-test output: `/tmp/opencode/acp-unified/evidence/ROOT-CURRENT-SOURCE-IMAGE-EVIDENCE.txt` and `ROOT-CURRENT-SOURCE-4G-BUILD-PASS.txt`. Independent Tester and Reviewer gave limited PASS for build identity and fail-closed entrypoint negatives.

## Three-role boot evidence

One isolated `compose.yml` + candidate overlay + resource cap run started exactly `runtime-adapter`, `acp-product-runner` and `acp-judgment-runner` with `--no-build --pull never --no-deps` in project `byq-acp-liveproof-20261009155239-3257336`. Each **running container** returned the same local `.Image` ID above and `healthy`, with the expected role-specific Config.User, read-only rootfs, memory, capabilities and security option values. Adapter readyz reported `runtime_adapter=ready` and release identity matched; both runner ready checks passed. PID 1 identity and commands matched. Earlier bounded negatives rejected missing/unknown role, adapter-as-root, and the two runners as non-root.

**The evidence script exited 1.** Its extra Adapter role check read `/proc/1/environ` as UID 10002 and obtained no value. Adapter startup deliberately sets `PR_SET_DUMPABLE=0`, denying same-UID reads of that file. Tester and independent Reviewer classified this as a harness false negative; Root accepts a **limited functional PASS** for local shared image ID and positive three-role boot, while the green-script receipt remains OPEN. After this run, the harness was corrected to filter only `BYQ_ACP_ROLE` from Docker `Config.Env`; that corrected script has not been rerun. Do not present the executed script as PASS.

Cleanup returned `down_rc=0`; this project's containers, networks and volumes left behind were `0/0/0`. The candidate image was preserved. Current local resources after the run: about 7.1 GiB memory available, 3.7 GiB swap free and 66 GB filesystem free.

Local evidence: `.ci-artifacts/acp-unified-three-role-boot-liveproof/ROOT-RESULT.md`, `liveproof-console.txt`, `evidence/inspect-*.txt`, `evidence/ready-*.txt`, `evidence/pid1-*.txt`, `evidence/down-rc.txt` and `evidence/leftover-check.txt`. The earlier first smoke and follow-up root-guard probes are under `.ci-artifacts/acp-unified-three-role-boot/` and `.ci-artifacts/acp-unified-three-role-boot-followup/`. These `.ci-artifacts` and `/tmp` paths are local receipts, not committed release artifacts.

## Still OPEN / NOT_RUN

- **ADR-0110 criterion 3 OPEN:** same local `.Image` ID is not a published registry digest. The release manifest has not bound one verified registry digest to all three roles.
- **Criterion 4 formal script receipt OPEN:** functional boot evidence is limited PASS, but the executed script exited 1 for the protected `/proc` probe.
- Base Compose's Backend/MCP dependencies were skipped deliberately. Full Product dependency route, actual credential resolver/provider calls, DB/Agent/F6/browser business flow and zero-egress proof are NOT_RUN. `OPENCODE_API_KEY` was empty, but the base Compose supplied a default resolver token and readyz reported `model_credentials=resolver`; this was not a no-credentials run.
- BuildKit, the unified-image 17-image release batch, Full/CI, registry publication, default adoption and deployment are NOT_RUN for this candidate. The current default release topology remains three per-role images. No plugin or DSH content trimming was attempted; the candidate's `docker images .Size` display remains 3.62GB.
