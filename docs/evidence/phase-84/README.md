# Phase 84 Acceptance Evidence

## Scope

Phase 84 implements the ADR-0048 code-owned ML capability registry, immutable v2 strategy lock,
purged walk-forward fold manifest, deterministic Ridge JSON learner and qualified Worker dispatch.
It preserves the complete ADR-0043 LightGBM v1 path and deliberately does not enable v2 prediction,
regime routing, MCP or frontend creation.

## Community inspection

The read-only Community ML import, strategy validation, runtime prompts and tests were classified in
`COMMUNITY_MIGRATION_INVENTORY.md`. No Community file or database was modified. Arbitrary ML imports,
Backtest-time fit/predict and VectorBT remain `DROP`; only the honest-capability product invariant is retained.

## Automated evidence

- `scripts/ci/local-ci.sh --base=origin/main --with-e2e --auto-smoke`: **PASS**, 12 gates.
- Backend full PostgreSQL suite: **PASS**, including v1 identity regression, v2 registry/strategy validation,
  fold generation, label visibility, Ridge model Artifact persistence and owner/workspace isolation.
- Full isolated Compose smoke: **PASS**; all healthchecked services healthy.
- Existing real LightGBM → prediction → frozen signal → Backtest browser journey: **PASS**.
- Six real Product API browser journeys: **PASS**.
- ML Worker restart identity and two-user isolation: **PASS**.
- `docker run ... byq-phase84-ml-worker python worker.py --probe`: **PASS** under read-only filesystem,
  tmpfs, dropped capabilities and `no-new-privileges`; covers LightGBM native round-trip, Ridge JSON format,
  registry integrity and two-fold walk-forward dispatch.
- CI resource cleanup verification: **PASS**.

## Security and compatibility

- Registry contains no module, class, command or path dispatch data.
- Ridge model is canonical finite JSON; pickle/joblib and arbitrary deserialization are absent.
- Backend/MCP/DSH remain free of LightGBM/NumPy runtime dependencies; only the trusted ML Worker imports them.
- Existing v1 strategy normalization, runtime identity, ModelArtifact and prediction/backtest journey remain green.
- v2 prediction fails closed until Phase 85 supplies frozen regime/bundle/routing lineage.
