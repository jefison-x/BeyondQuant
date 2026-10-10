# Independent Reviewer — signed-child delegate-persona fix

Read-only. Scope confirmed: only the 5 listed files were touched at 20:47–20:49 (patch 20:47:46,
identity 20:48:03, manifest 20:48:23, test 20:49:02, Dockerfile 20:49:46); all other dirty files
predate the fix; the root `personaPrefix` binding sentence is pre-existing and not attributed here.

| # | Requirement | Verdict | Evidence |
|---|---|---|---|
| 1 | 5 delegates bind own native AgentRun, correct role, no inherit | **PASS** | `byq-product.patch.yml:191,219,242,267,292`; allowlist has `mcp__byq__byq_agent_run_start` at `:196,224,247,272,297` |
| 2 | Role ids from closed catalog (not guessed) | **PASS** | `services/mcp/src/server.ts:1293` enum + `plugins/dsh-byq/registry/plugins.json`; all 5 match exactly |
| 3 | Judgment role unchanged, no binding tool | **PASS** | `byq-product.patch.yml:329-344`; persona `:336` no run_start; allowlist `:339-343` = read-only 5 tools; no hunk touches it |
| 4 | No product/permission/ingress/Backend/harness change | **PASS (note)** | 5 files = personas + hash pins + test only; Dockerfile also carries a pre-existing ADR-0106 `product_turn_request.py` COPY (not this fix) |
| 5 | Hash pins consistent | **PASS (recomputed)** | patch `aeb4e9bd…` == identity `:4` == manifest `authoritative.json:14` == `Dockerfile:72`; identity file `4f730166…` == manifest `:18` |
| 6 | Test non-vacuous | **PASS** | `test_acp_authoritative_version.py:81-96` (per-role phrase+allowlist, judgment exclusion, identity==patch hash); minor: Dockerfile hash literal not directly asserted (acceptable) |
| 7 | No over-reach / unsafe wording | **PASS** | wording safe ("control-plane binding, not a business write", "never reuse or inherit the parent's AgentRun"); consistent with `server.ts:1039` where `byq_agent_run_start` is excluded from ingress observation |

**(a) Minimal + correctly targeted:** YES — the Tester-confirmed cause (child called `byq_research_get`
first without a bound native AgentRun → 409 `acp_ingress_observation_unavailable`) is addressed
directly by the five persona binding sentences; no ingress relaxation, no Backend auto-registration.

**(b) Deferred recreate:** acceptable interim state. Containers still carry the old baked persona; no
live run attempted; `FIX.md` states this plainly and defers recreate + the one signed-child acceptance
to Root review. Static/free tests pass; the live signed-child acceptance remains **pending**.

**Overall: PASS on all seven requirements; fix is minimal, correct, safely worded; live signed-child
re-acceptance still outstanding.**

## Notes
- `/tmp` build logs and the pre-fix baseline copy were cleared and are **not readable**; not relied on
  (image IDs persist in the Docker store; the free test is reproducible from the repo).
- No push/PR/merge/deploy/default/release/tag/Phase; default remains SDK.
