# Phase 7 slice 1 — retire Gateway private runtime proxy

Status: implementation in isolated Clean Break worktree; not yet Phase 7 completion.

## Decision and replacement

The Gateway exposes a Phase-6 private pass-through surface for creating/prompting/cancelling/releasing Adapter sessions and streaming raw private workflow events. `services/gateway/app/main.py` itself labels it a compatibility seam. Product traffic already uses authenticated `/v1/agent/*` and `/v1/workflows/*`; the latter replays BYQ normalized trace projections. No Product source caller of the Gateway pass-through routes was found. Old smoke and tests are the identified consumers. [ADR-002](adr/ADR-002-dsh-boundary.md) now makes the Product API the direct replacement and supersedes ADR-0004's old retention instruction.

Delete only the Gateway route handlers and their route-only request DTOs. Keep Gateway's service-client calls to the Runtime Adapter and keep the Adapter's `/internal/runtime/*` API. Do not touch DSH SDK compatibility, conversation authorization, business approval, exact idempotency, normalized trace store or Agent-owned long compute in this slice.

## Contract and verification gate

- Existing public Product API tests must still prove owner-scoped session/turn lifecycle and bounded normalized workflow stream/replay.
- Negative route test proves obsolete Gateway pass-through paths are unavailable; no stub or redirect is added.
- Gateway suite, affected architecture tests, shell syntax and `git diff --check` must pass. The old private-proxy smoke is removed while Product API smoke and direct Adapter lifecycle smoke remain.
- This slice does not change the qualified DSH `0.1.5rc1` SDK boundary. The retained Adapter uses the pinned version and its existing `Session.run`/lifecycle tests; later Adapter simplification must qualify the exact DSH API again.
- Tester → independent Sol Reviewer → Root PASS is required before a second Phase 7 deletion slice. A unit-green result alone does not assert Product browser or full-stack Golden Scenario fidelity.

## Initial gate result (2026-09-25)

The maintainer explicitly approved deletion of these six Gateway proxy paths. The bounded code change and replacement contract are implemented in this worktree. Independent Tester ran the changed Gateway test modules in an offline, read-only container: **14 PASS**; the broader Gateway suite: **274 PASS** after fixing the local test-module import in `test_domain_call_delivery.py`. Python syntax, smoke shell syntax, `git diff --check`, historical DSH release check, and promotion check pass.

Independent Sol Reviewer inspected the actual diff and rated **Functional PASS / Clean Break Architecture PASS / Tests FAIL**. The current `.215` immutable build manifest hashes Gateway source and therefore fails `build_revision.check()` after this deletion; `scripts/ci/local-ci.sh` requires that check before image build. The proposed `.216` shortcut was reverted because the DSH release descriptor also hashes the Adapter Dockerfile that names the selected manifest. Root gate is **NOT PASSED**. No next deletion slice, service cleanup, or database cleanup may start until a coherent build-identity update and the required tests pass.

## Build-identity repair and retest (2026-09-25)

The first gate failure is resolved with current operational build `dsh-0.1.5rc1-post-u8.216`. Its revision-specific `Dockerfile.post-u8-216-candidate` embeds the new manifest; CI selects that file. A tracked Compose override selects it for ordinary `docker compose` while preserving explicit `BYQ_DSH_RUNTIME_DOCKERFILE` selection; Docker Compose resolution was checked for default, explicit old, and CI modes. The original `.215` manifest, its Dockerfile, the DSH `0.1.5rc1` release descriptor and `compose.yml` remain byte-identical. `.216` manifest SHA-256 is `0a28e9c6037f82caf367df1928217439f7e3936669f334c60fc1603226aa57ee`; `.215` remains `81a7631851ca3d90caa8ce15b27911b45e3d1cb8537189ca973a534271106c56`. Current and frozen build checks, release historical-input check, and promotion check pass.

The current H4 interface ledger has been updated for exactly the six deleted routes and the unchanged Gateway interface implementations affected by the whole-file hash; its fail-closed auditor reports 572 discovered/reviewed, zero missing, stale or fake pass. Historical 0.9 tests continue checking committed evidence, but no longer re-derive a 0.9 verdict from changing 0.10 source files. Independent Tester: Gateway 274/274 in an offline read-only container; host architecture `unittest` 918 passed with 11 existing skips; reliability, build identity, shell syntax and diff checks PASS. Independent Sol Reviewer inspected the actual diff and returned **Functional PASS / Tests PASS / Clean Break Architecture PASS** after the Compose repair. Root accepts **PASS for Phase 7 slice 1 only**: the six private Gateway routes, current build identity and reviewed interface ledger are consistent. Phase 7 as a whole remains in progress. No full-stack smoke or browser Golden Scenario has been claimed.
