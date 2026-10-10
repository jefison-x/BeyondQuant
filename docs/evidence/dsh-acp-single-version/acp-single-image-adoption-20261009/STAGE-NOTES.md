# ACP single-image candidate — pre-adoption stage notes (2026-10-09)

Subsystem: BYQ ACP single-image candidate (`services/acp_unified/`). Sole writer.
Scope of this stage: **documentation + one narrow candidate contract test only**.
No image rebuild, no architecture-subset/full suite/build, no model/provider call,
no env/secret read, no push/PR/merge/deploy. Dirty tree and prior evidence preserved.

## Produced in this stage

- `docs/architecture/adr/ADR-0110-acp-single-image-three-role-topology.md`
  — **Proposed** draft (never self-marked Accepted) for one digest serving the
  adapter / product / judgment roles.
- `services/acp_unified/tests/test_single_image_contract.py`
  — Docker-free static contract for the candidate compose/Dockerfile/entrypoint
  (single image reference + per-role security boundaries only). It does not
  touch accepted three-image topology assertions.

## Targeted checks (this stage)

| Check | Result |
|---|---|
| `python3 services/acp_unified/tests/test_single_image_contract.py` | PASS (7/7) |
| `sh services/acp_unified/tests/test_entrypoint.sh` | PASS (7/7) |
| `sh -n services/acp_unified/entrypoint.sh` | PASS |
| `sh -n services/acp_unified/tests/test_entrypoint.sh` | PASS |
| `python3 -m py_compile …test_single_image_contract.py` | PASS |
| candidate compose YAML parse (`yaml.safe_load`) | PASS |
| `git diff --check` (tracked) | PASS (RC=0) |

## NOT_RUN gates (unchanged; do not read as PASS)

- Architecture subset / full suite / any build (including the candidate image).
- BuildKit path; 17-image release batch; F6 ACP live chain; Full/CI.
- Publication, deployment, default promotion, Phase advance.

## Pre-existing architecture test failures — dirty-tree contract drift

These 7 failures are **pre-existing on this dirty branch**, are owned by their
owning feature slices, and are **independent of the additive single-image
candidate** (the architecture subset was run before this candidate test existed;
none of the failing assertions reference `services/acp_unified/` or
`compose.dsh-acp-single-image-candidate.yml`). They are recorded here for
separation only and are **not** fixed in this stage.

| # | Test | Failing assertion (file:line) | Dirty-tree drift cause |
|---|---|---|---|
| 1 | `test_acp_authoritative_version.py::…::test_candidate_dockerfiles_pin_the_manifest_commit` | manifest `source_commit` literal must appear in candidate Dockerfiles (`test_acp_authoritative_version.py:69`) | Dirty tree rewrote the per-role Dockerfiles to resolver-fed `ARG BYQ_DSH_BUILD_SOURCE_COMMIT`; the hard-coded commit literal was removed. |
| 2 | `test_architecture.py::…::test_base_compose_uses_runtime_adapter_as_the_only_product_dsh_path` | `byq_dsh_sessions:/var/lib/byq/dsh-sessions` must be in the `runtime-adapter` block (`test_architecture.py:353`) | Dirty tree mounts the resolver session root under `byq_acp_product_sessions` for the ACP product slot on `runtime-adapter`. |
| 3 | `test_architecture.py::…::test_phase7_auth_and_model_secret_boundaries_are_separate` | `DEEPSEEK_API_KEY` must be in the `runtime-adapter` block (`test_architecture.py:720`) | Dirty tree switched the route to `opencode-go-chat` (ADR-0105) and `compose.yml` now uses `OPENCODE_API_KEY`. |
| 4 | `test_architecture.py::…::test_local_ci_isolated_mcp_contract_dependency` | `Dockerfile.post-u8-324-candidate` must be in `scripts/ci/local-ci.sh` (`test_architecture.py:1153`) | Dirty tree moved CI to the resolver-managed `acp_build.py` path; the literal candidate Dockerfile name was removed. |
| 5 | `test_architecture.py::…::test_compose_smoke_resources_are_ci_isolatable` | `docker compose port frontend 80` must be in `scripts/ci/local-ci.sh` (`test_architecture.py:1210`) | Dirty tree calls the managed `acp_compose port frontend 80` wrapper instead. |
| 6 | `test_publication_license.py::…::test_declaration_inventory_is_current` | `scripts/ci/license-inventory.py --check` must pass (`test_publication_license.py:36`) | `docs/legal/python-dependency-inventory.json` is STALE w.r.t. the changed dependency set. |
| 7 | `test_release_pipeline.py::…::test_full_profile_runs_integration_even_with_documentation_diff` | `F6 ACP live business chain NOT_RUN` must be in `scripts/ci/local-ci.sh` (`test_release_pipeline.py:320`) | Dirty tree changed the `local-ci.sh` F6 chain string. |

Baseline observation (not re-run here): the saved architecture subset recorded
`7 failed, 226 passed, 103 subtests passed in 11.44s`
(`/tmp/opencode/acp-unified/evidence/architecture-subset.txt`). The single-image
candidate adds no architecture-suite test, so it changes none of these.

## Independent Reviewer revision (2026-10-09)

Narrow corrections only, to the three produced files. No service/image/content
change and no widened claim.

- **ADR-0110 no-new-privileges fact.** Verified against `compose.yml`,
  `compose.dsh-acp-rc2-candidate.yml` and the candidate overlay: only the two
  runner services set `security_opt: ["no-new-privileges:true"]`; the
  `runtime-adapter` service sets neither `read_only` nor `no-new-privileges` in
  any of the three files. The ADR Decision item 2 and the role table now state
  that current fact. Adding an adapter `no-new-privileges` is recorded as a
  future maintainer decision (Human review point 8), not a silent boundary edit.
- **ADR-0110 build/digest scope.** Context, Decision 1, Decision 5 and Benefits
  no longer read as if the shared registry digest and three-role binding are
  already true. What is demonstrated is one local build yielding one local image
  ID; registry digest publication, release-manifest binding of one digest to the
  three roles, and three live containers sharing one digest are adoption gates.
- **ADR-0110 authoritative manifest.** Corrected: the single resolved
  `release_id` is a DSH-*version* value and does not mean the three images share
  one profile/release identity. The accepted judgment image contains only the
  judgment profile/identity and no deployment release identity (adapter/product
  additionally bake `deployment.identity.json`).
- **`test_single_image_contract.py`.** Docstring, class name and the renamed test
  `test_role_boundaries_are_per_service_in_the_candidate_overlay` now state the
  file reads the *candidate overlay* only and does not claim field-for-field
  equivalence with the accepted topology. The entrypoint order check extracts the
  adapter branch, drops comment lines, requires a real `exit 77` command, and
  asserts it precedes the `exec ... uvicorn` line in the same branch.

Status is unchanged: ADR-0110 remains **Proposed**; this stage does not mark it
Accepted and claims no release PASS.

## Reviewer-stage targeted checks

| Check | Result |
|---|---|
| `python3 services/acp_unified/tests/test_single_image_contract.py` | PASS (7/7, RC=0) |
| `sh -n services/acp_unified/entrypoint.sh` | PASS |
| `git diff --check` (tracked) | PASS (RC=0) |
| trailing-whitespace check on the three produced files | PASS (none) |

## Remaining NOT_RUN (unchanged; do not read as PASS)

- Candidate image build; registry digest / release-manifest digest binding;
  three live containers sharing one digest.
- BuildKit path; 17-image release batch; F6 ACP live chain; Full/CI.
- Publication, deployment, default promotion, Phase advance.
- Architecture subset / full suite; `services/acp_unified/tests/test_entrypoint.sh`
  was not re-run in this revision.
