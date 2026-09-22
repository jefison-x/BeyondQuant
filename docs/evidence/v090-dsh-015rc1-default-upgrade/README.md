# 0.9 formal repo default dependency/selector upgrade (DSH 0.1.5-rc.1)

Isolated worktree/branch `codex/v090-dsh-015rc1-default-upgrade`, base dynamic
`origin/main` `4671c3e948b77c75a87c84a514888974f683a54b` (contains PR #353).

This slice executes the sole next 0.9 task in the retained closeout order:
**formally upgrade the repository default dependency/selector from
`dsh-0.1.2rc1` to the already-qualified coherent `dsh-0.1.5-rc.1` pairing**
(Python `0.1.5rc1` + bundled npm `0.1.5-rc.1`), with a verifiable rollback and
targeted real verification. It is maintenance/qualification, **not** a Product
Phase, and it does **not** deploy to production.

## Inventory (reused assets, not a reimplementation)

- `config/dsh/candidates/dsh-0.1.5rc1/candidate.json` + `python.lock` (D15-1).
- `services/runtime-adapter/Dockerfile.dsh-0.1.5rc1-candidate` +
  `requirements.dsh-0.1.5rc1-candidate.lock`.
- `services/runtime-adapter/app/compat/dsh_015.py` (byte-identical Python SDK
  surface, D15-0 recon).
- D15 evidence (`docs/evidence/d15/…`) and the B2/B3/B4 candidate slices.

No DSH code is reimplemented; no cross-process continuable provider, no second
agent harness, no fork/patch.

## Default selector / dependency / profile / image changes

- `config/dsh/deployment.json`: `default_release` -> `dsh-0.1.5rc1`,
  `candidate_releases` -> `[dsh-0.1.2rc1]` (rollback).
- `config/dsh/releases/dsh-0.1.5rc1.json` + `.python.lock`: new registered
  release descriptor (upstream tag/commit/archive from D15-0) and its exact lock.
- `config/dsh/candidates/dsh-0.1.5rc1/candidate.json`: status `promoted`,
  `production_default = dsh-0.1.5rc1`, rollback `dsh-0.1.2rc1`.
- `config/dsh/generated/deployment.identity.json` (default selector identity)
  and `config/dsh/generated/dsh-0.1.2rc1.identity.json` (rollback candidate).
- `services/runtime-adapter/Dockerfile.post-u8-candidate`: selector, embedded
  build manifest `dsh-0.1.5rc1-post-u8.200`, installed-version assertion.
- `services/runtime-adapter/requirements.candidate.lock`, `pyproject.toml`:
  dependency pin `0.1.5rc1`.
- `compose.yml`: default `BYQ_DSH_COMPATIBILITY_RELEASE:-dsh-0.1.5rc1` and
  session root `dsh-0.1.5rc1`.
- `services/runtime-adapter/app/compat/__init__.py`: 0.1.5 is the default
  boundary; 0.1.2 remains selectable for rollback.
- `scripts/dsh/build_revision.py`: current release `dsh-0.1.5rc1`, new build id
  `dsh-0.1.5rc1-post-u8.200`; the frozen `dsh-0.1.2rc1-post-u8.199` is retained
  as a historical rollback identity.
- `scripts/dsh/historical_inputs.py` + `release.py`: an in-tree promoted release
  is verified against the current build tree; archived 0.1.1/0.1.2 keep their
  pinned-commit verification.
- `runtime.py` `continuation_qualified`: the F6 continuation gate now accepts
  the exact coherent 0.1.5 pair as well as 0.1.2, so the default upgrade does
  not silently disable an already-qualified business capability.
- Two committed v090 evidence bundles that bind `runtime.py` were refreshed
  **digest-only** (`docs/evidence/v090-session-containment/observations.v2.json`,
  `docs/evidence/v090-business-recovery/observations.v1.json`).

## Rollback

See `rollback.v1.json`. The prior baseline is preserved byte-for-byte: the
`dsh-0.1.2rc1` release descriptor, Python lock and `dsh-0.1.2rc1-post-u8.199`
build manifest match the base commit Git blobs; the archived 0.1.2 identity and
the previously deployed image digest are recorded. `verify.py` fails closed if
any rollback artifact drifts.

## Verification (targeted, real)

See `business-verification.v1.json`: the upgraded
`Dockerfile.post-u8-candidate` image builds (id `sha256:a4892dd85c7f…`),
`/readyz` reports `release_identity=matched` for `dsh-0.1.5rc1`, the in-image
runtime/domain-wire suite passes (244 passed, 40 skipped), the F6 continuation
budget suite passes (10 passed), and the keyless D15 start probe reaches
`ready`/`idle` with a contiguous event sequence and a real `mcp__byq` tool call
while the message tool stays blocked.

`verify.py --selfcheck` rejects 13 defect-targeting negatives (a
result-trusting gate passes them). This is keyless service-boundary evidence,
not real-LLM-quality semantics.

## Boundaries (unchanged)

B1 `subagent-child-crash` and B2 `subagent-byq-adapter-restart` remain
`BLOCKED_EXTERNAL`; historical D15-G stays `NO_GO` and is not rewritten; no D15
superseding assessment is generated; no production deployment, tag or release;
Phase 100 is not resumed; 0.10 is not started.
