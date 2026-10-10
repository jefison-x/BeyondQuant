# Signed-child FAIL — minimal delegate-persona fix + free verification (2026-10-08)

Follow-up to `RESULT.md` (child FAIL: `acp_ingress_observation_unavailable`/409 because the
delegated child never bound its own native AgentRun). Root authorized the minimal persona/identity
fix. No real acceptance run in this step; the FAIL evidence is preserved.

## Root cause (Tester-confirmed)
The child (`6f46d7a0…`, `origin:subagent`, `parentSession=deb02e05…`) called `mcp__byq__byq_research_get`
as its first BYQ tool without first calling `byq_agent_run_start`; ADR-0094/0097 require a bound
native AgentRun per ACP Agent, so Backend `POST /internal/acp/tool-ingress-observe` returned `409`
and the MCP returned `acp_ingress_observation_unavailable`. The root persona already binds
(`role_id "quant_orchestrator"`); the 5 business delegate personas did **not**.

## Fix (one writer; minimal; probe/persona only)
`plugins/dsh-byq/profiles/acp-0.2.0-rc.2/byq-product.patch.yml` — prepend one sentence to each of the
5 business delegate personas (role ids taken from the **closed** catalog in
`services/mcp/src/server.ts:1293`; not guessed):

> Before the first BYQ business tool of your turn, first call `byq_agent_run_start` with role_id
> "<role>" and a stable idempotency key to bind your own AgentRun (control-plane binding, not a
> business write); never reuse or inherit the parent's AgentRun.

| tool | role_id |
|---|---|
| delegate-market-research | `market_researcher` |
| delegate-factor-research | `factor_researcher` |
| delegate-strategy-research | `strategy_researcher` |
| delegate-backtest-analysis | `backtest_analyst` |
| delegate-ml-research | `ml_researcher` |

Unchanged: the single bounded `research-judgment-turn` role keeps its read-only 5-tool allowlist and
does **not** receive `byq_agent_run_start`. No Backend auto-registration, no ingress relaxation, no
new harness, no business/permission change.

## Composition hash / identity (kept consistent; no bypass)
New patch sha256 `aeb4e9bd19401cfae9d5af82489af74563c62f387502e6df5c8c55ca7d8a111a`, applied in all
pins: `byq-product.identity.json` `composition_hash`; `config/dsh/acp/authoritative.json`
`profiles.product.sha256`; and the `services/acp_product_runner/Dockerfile` build assertion.
(Note: the dirty baseline already diverged the patch from the committed manifest, so this also
re-aligned the manifest.) Identity file sha256 `4f730166aab0534703c805237b51c36c2e6575dde85014f85d5ff1e4d95a894f`
recorded in `profiles.product_identity.sha256`.

## Free verification (no model, no network)
Added `test_business_delegate_personas_bind_their_own_child_agent_run` in
`tests/architecture/test_acp_authoritative_version.py` (asserts each delegate persona binds its exact
role, the binding tool is allowlisted, the judgment role has none, and the identity hash equals the
patch bytes).

`docker run … pytest tests/architecture/test_acp_authoritative_version.py tests/architecture/test_product_capability_catalog.py`
→ **11 passed**.

## Candidate images (rebuilt, implementation only)
- acp-product-runner `3da73530…` → `sha256:4a52d4ed982b216e6874ddd8c6aa27c92809d1f60e59e3719865a4122aea35e8`
- runtime-adapter `c324ef80…` → `sha256:dfb6d627c563252a826595c09c8f4b394a3370596bdeded4318c28f3dde444f1`
Build logs were written under `/tmp/opencode/sca-fix-20261008/` but that directory has since been
cleared (`/tmp` reset); those logs and the pre-fix baseline copy are **no longer readable** and are
not relied on as evidence. The image IDs above are the build outputs (image content persists in the
Docker store); the free-test result is reproducible from the committed test file via the command
shown above (source and tests are readable in the repo).

**Not recreated:** the temp compose env/override (`/tmp/opencode/byq-acpf6.env`,
`byq-acpf6-override.yml`) were cleared by the reboot and are **not** reconstructed (secret-bearing).
The running containers therefore still carry the old persona until a recreate is performed; no new
real acceptance was attempted. Recreate + the one new signed-child acceptance are deferred until
Root has reviewed this fix.

## Reviewer
Independent Reviewer verdict: **PASS on all seven requirements**; fix minimal, correct, safely
worded. See `REVIEWER.md`.

## Boundaries
No push/PR/merge/deploy/default/release/tag/Phase. Default remains SDK. No business/permission/
recovery change. FAIL evidence preserved.
