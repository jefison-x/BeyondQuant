# ADR-0110 single-image release path: bounded source change

Date: 2026-10-10. Scope: release subsystem source only (no build, publish,
registry, Docker, CI, commit, push, PR, merge or deployment).

Later same-day gate: a separate bounded BuildKit build has limited local PASS; see `../acp-unified-buildkit-20261010/RESULT.md`. The no-build statements below describe only this release-source slice.

## Capability -> gap -> change

- Capability already present: ADR-0110 topology derivation from the checked-in
  Compose route (`scripts/release/images.py`), explicit single-image vs per-role
  binding, and the additive candidate overlay
  (`compose.dsh-acp-single-image-candidate.yml`). The default
  `ACP_COMPOSE_ROUTE` stays per-role.
- Gap for one *actual published* artifact: `images.publish` still looped over all
  17 services, pushed the three local-identical ACP role images to THREE role
  repositories and ran syft three times; `manifest.validate` required a
  service-specific repository and `{service}.spdx.json` for every service, so a
  single unified repository/SBOM could never validate; overlay pull and
  promote repeated the three identical ACP references.
- Change (minimal, candidate-aware, no ambient selector):
  - `scripts/release/images.py`: a recorded `acp_image_topology` selects the
    publish shape. Under single-image the three ACP roles publish once to
    `ghcr.io/jefison-x/beyondquant/acp-unified`, produce one
    `acp-unified.spdx.json`, and all three manifest entries bind the identical
    digest-pinned ref and one SBOM receipt. Non-ACP services are unchanged.
  - `scripts/release/manifest.py`: validation is topology-aware; under
    single-image the three roles must share the unified repo ref and one SBOM,
    and overlay pull / promote each distinct ref exactly once. Per-role behavior
    is byte-for-byte the prior repository/SBOM/push mapping.
  - Narrow explicit schema addition: `acp_image_topology`
    (`single-image` | `per-role-image`) recorded in the `byq-release-images.v1`
    receipt and the `byq-release.v1` manifest. It is derived at export from the
    selected Compose route; there is no environment selector.
  - `tests/architecture/test_release_pipeline.py`: updated fixtures plus
    negative tests for forged shared ref/SBOM, missing/unknown topology, and
    partial/ambiguous registry digest (no manifest written).

## Reviewer blocker fix (this revision)

A previous revision of this note (and the code) claimed the registry digest was
proven by reading the local `docker inspect <tag> .RepoDigests` after
`docker push`. That claim was FALSE and is corrected here: a local RepoDigests
entry only records what the local daemon learned during its own push and does
NOT prove which digest the registry now serves for the candidate tag.

- `scripts/release/images.py` now performs a *remote* registry read-back with
  `docker manifest inspect --verbose <candidate-tag>` and fails closed unless
  the parsed reply is a single (non-list) manifest whose:
  - `Ref` is exactly the pushed candidate tag,
  - `Digest` is a valid `sha256:...`,
  - `SchemaV2Manifest.config.digest` is exactly the qualified image id, and
  - `Platform.os`/`Platform.architecture` are exactly `linux`/`amd64`.
  The remote `Digest` (not a local id, tag or RepoDigests) is what is written
  into the manifest. A missing, ambiguous, malformed, list-shaped, wrong-ref,
  wrong-config or wrong-platform reply raises before `manifest.json` is written.
- The recorded receipt topology is now bound to the checked-in
  `ACP_COMPOSE_ROUTE` at the actual publish step (`acp_image_topology_from_compose`),
  before load and before any registry write. A receipt topology that diverges
  from the checked-in Compose route fails closed; no ambient
  `BYQ_ACP_IMAGE_TOPOLOGY` selector can change it.
- Reviewer P2 decision: added narrow fail-closed SBOM verification to
  `manifest.verified`. Each *distinct* `sbom[service].file` listed by the
  attested manifest is re-read from the manifest's own directory and its
  `sha256` re-checked exactly once (single-image lists one SBOM for three
  roles). A missing, unreadable or mismatched SBOM fails closed. Manifest path
  semantics are preserved (paths resolve relative to the manifest file), and
  the schema, per-role mapping and signed/attested flow are unchanged.
- `tests/architecture/test_release_pipeline.py` now models the remote
  `docker manifest inspect --verbose` output and adds: remote digest governs
  while a stale local RepoDigests is never queried; negative cases for missing/
  malformed digest, wrong/missing config, wrong ref, wrong platform/os, list
  shape, non-JSON; receipt-topology divergence with an ambient selector; and
  SBOM checksum verification (once per distinct file, plus missing/mismatch).

## Reviewer P1 fix (this revision): publish runner had no Compose parser

An independent Reviewer found a P1 in the release workflow. `images.publish`
now derives the ACP topology through `acp_image_topology_from_compose()`, which
requires PyYAML, but `publish` is a separate fresh `ubuntu-24.04` job
(`needs: qualify`) and only `qualify` installed the locked PyYAML. The publish
runner would therefore fail closed before publishing any image.

- `.github/workflows/release-images.yml`: the `publish` job now runs
  `actions/setup-python` with `python-version: '3.13'` and then installs the
  SAME `scripts/release/requirements.release-runner.lock` with
  `--require-hashes --only-binary=:all: --no-deps`, both BEFORE the
  `Publish exact tested images and SBOMs` step. Job set, triggers, the
  `publish` permissions (`contents: read`, `packages: write`, `id-token: write`,
  `attestations: write`) and every other step are unchanged.
- `tests/architecture/test_release_pipeline.py`: added a narrow static test,
  `test_release_publish_runner_installs_pinned_offline_compose_parser_before_publish`,
  that parses the `publish` job in isolation and asserts exactly one
  `actions/setup-python@` step (`python-version: '3.13'`) and exactly one locked
  install step, both ordered before `Publish exact tested images and SBOMs`. The
  earlier `test_release_runner_installs_pinned_offline_compose_parser_before_export`
  only covered the `qualify` job.

## Workflow assumptions inspected (SBOM boundary unchanged)

- `.github/workflows/release-images.yml` does not hardcode SBOM file names: it
  attests `release-manifest/manifest.json` and uploads the whole
  `release-manifest/` directory, so one `acp-unified.spdx.json` (still listed in
  the manifest `sbom` map for all three roles) crosses the same boundary.
- `grep` found no `spdx` reference outside `scripts/release/` and tests.

## Verification (offline only)

- `python3 -m unittest tests.architecture.test_release_pipeline` -> Ran 46
  tests, OK (was 45; the one added test is the publish-runner static test).
- `python3 -m py_compile scripts/release/images.py scripts/release/manifest.py
  tests/architecture/test_release_pipeline.py` -> OK.
- `git diff --check` -> clean.
- ruff is not installed in this environment (NOT_RUN).

## Independent review and Root gate (source slice only)

- Independent Tester: PASS for the six targeted remote-binding/SBOM/topology
  tests (including nine remote-response subcases), then PASS for the added
  publish-runner test (1/1); `git diff --check` clean. Accepted OC's 46/46
  focused module receipt without repeating the full module or prior live boot.
- Independent Reviewer: Functional PASS, Tests PASS, Clean Break Architecture
  PASS for the new 17-service candidate publication **source path** after the
  publish-runner dependency fix. The previously reported local RepoDigests
  binding and missing publish-runner PyYAML blockers are closed in source.
- Root: **PASS for this bounded source slice only**. It does not authorize
  selecting the candidate as the default route or mark registry, attestation,
  F6, Full CI, release, promotion or deployment as passed. Historical signed
  `byq-release.v1` compatibility remains OPEN as noted below.

## Honest limits (all external gates NOT_RUN)

- No Docker build, image load/tag/push, **live registry remote read-back**,
  syft run, SBOM file generation, CI lane, F6 chain, three-role boot or full
  suite was executed or re-run.
- The remote `docker manifest inspect --verbose` read-back is exercised only
  through mocked subprocess calls that model the documented single-manifest
  fields; it is NOT qualified against a live GHCR registry, a real published
  digest or a real manifest list response. The exact remote `Ref`, `Digest`,
  `SchemaV2Manifest.config.digest` and `Platform` values, and the registry's
  behavior for OCI vs Docker media types, remain unverified live.
- `manifest.verified` SBOM checksum verification and `gh attestation verify` /
  `gh api` are exercised only against mocks; no signed attestation or GitHub
  API call was made.
- The release workflow fix (setup-python + locked PyYAML install in `publish`)
  is asserted only by a static workflow test. No CI workflow run, GitHub
  Actions execution, GHCR login, or real publish was performed; real
  CI/registry behavior remains NOT_RUN.
- The additive `acp_image_topology` field changes the `byq-release.v1` manifest
  shape and validation now fails closed when it is absent, so compatibility with
  historically signed `byq-release.v1` manifests is OPEN for a later explicit
  decision. It is NOT claimed solved or verified here.
- ADR-0110 criteria 4 and 5 have separate limited local PASS receipts; criterion 6 (17-image/F6/Full CI/release) remains OPEN/NOT_RUN. Overall adoption remains OPEN. Default release topology is unchanged (per-role).
- All prior receipts and the current qualification ledger are preserved; this
  note adds no qualification claim.
