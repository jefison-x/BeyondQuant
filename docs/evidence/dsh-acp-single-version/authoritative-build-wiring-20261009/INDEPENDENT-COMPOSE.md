# Independent Compose wiring follow-up

Date: 2026-10-09
Worktree: `/home/jefison/projects/.byq-worktrees/dsh-acp-single-version`

## Tests

Command: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider tests/architecture/test_dsh_authoritative_build.py::DshAuthoritativeBuildTests::test_merged_compose_uses_resolver_family_and_root_over_inherited_sdk tests/architecture/test_dsh_authoritative_build.py::DshAuthoritativeBuildTests::test_candidate_compose_fails_closed_without_helper_resolver_values tests/architecture/test_dsh_authoritative_build.py::DshAuthoritativeBuildTests::test_wrapper_replaces_ambient_build_selectors_only`

Result: **PASS, 3 passed in 0.36s**. No failures or skips. The Compose checks ran `docker compose version` and `docker compose config` only; no build, pull, service start, network request, or model call.

Coverage: resolver values override inherited SDK family/session-root in candidate merged config; candidate config rejects missing helper values despite inherited SDK values; wrapper replaces ambient DSH build selectors while preserving unrelated runtime auth environment.

## Safe config summary

- Resolved compatibility family: `dsh-v0.2.0-rc.2-acp`
- Resolved session root: `/var/lib/byq/dsh-sessions/dsh-v0.2.0-rc.2-acp`
- Candidate merged runtime-adapter reports those same two values.
- Default Compose has 14 services and retains its SDK runtime-adapter path. Candidate merged Compose has 18 services. The candidate overlay service-key set is unchanged from `/tmp/acp-authoritative-wiring-20261009/compose.dsh-acp-rc2-candidate.yml.before-compose-merge-fix`; the default stack remains separate from the ACP runners/consumer.
- No environment credentials or secret values are included in this result. Compose config used test-only interpolation values held in process memory.

## Source pins at test time

- `scripts/dsh/acp_build.py`: `5fbbd76d089667d41874bbaf819dc11b158d202ea19ad6dea1a946e7fca8cb30`
- `scripts/dsh/authoritative_version.py`: `dda5fe20e948a9c728c25def4865f80254e89e02fbd29ca1de345fa3c7160826`
- `compose.dsh-acp-rc2-candidate.yml`: `40b9d447dc7c9f45ad23ae083ec12acb6038820fa91fc484012c9e364517c8b9`
- `services/runtime-adapter/Dockerfile.acp-0.2.0-rc.2-candidate`: `82b6953f39cfd2264bc9da163840754b1451c9034efb9532f7211aaef03f4df5`
- `services/acp_product_runner/Dockerfile`: `1721eb5501aff402f892a794e60eab26364591a022dd094288061d4c4bda65ba`
- `services/acp_judgment_runner/Dockerfile`: `4959879991172303e3eab140e2454bb5e8048e91fd95ea825a9e4112d5f31720`
- `scripts/ci/local-ci.sh`: `c83894d730002569bb8311c4533a10cfa1aaccf304928103ee40b569519bb022`
- `tests/architecture/test_dsh_authoritative_build.py`: `7eb7d74c6acb5f022ca311b7d06be33e1d1c9631acc1e68d10bfdb4b738d89c6`

The CI script has no diff against `/tmp/acp-authoritative-wiring-20261009/local-ci.sh.before-compose-merge-fix`; the candidate helper invocation is already present in that snapshot. This follow-up did not evaluate CI execution or image release behavior.

This is isolated architecture/Compose-config evidence only; it does not qualify built images, Product runtime, or release behavior.
