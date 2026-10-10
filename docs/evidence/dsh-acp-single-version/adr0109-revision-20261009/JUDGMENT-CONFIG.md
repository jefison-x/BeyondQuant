# Candidate judgment configuration — 2026-10-09

## Scope

Only the trusted Adapter environment in `compose.dsh-acp-rc2-candidate.yml` changed in this slice. The preserved before-file is `/tmp/byq-adr0109-qual-20261009-c89ff732f2/judgment-config-backup/compose.dsh-acp-rc2-candidate.yml`; inherited candidate changes are outside this review.

- Added the same judgment service token already required by the consumer.
- Added explicit lifecycle activation, default `0` (disabled).
- Exposed provider/model configuration while preserving existing resolver defaults.
- No credential literal, runner-control change, model request, database mutation, or production startup.

## Evidence and verdict

- PASS: merged Compose parses; token exists and matches the consumer; default activation remains off; provider/model defaults match the resolver; runner/MCP containers do not receive the judgment service token. Boolean-only receipt: `judgment-config-validation.json`.
- PASS: independent Reviewer configuration and architecture review. The ACP child environment explicitly strips the service token; DSH cannot inherit it.
- PASS: applied only to the fresh qualification Adapter with its existing exact pinned image; service healthy, judgment health reports authenticated, unauthenticated dispatch returns HTTP 401. Zero model calls; lifecycle remains disabled. Receipt: `judgment-config-live.json`.
- NOT_RUN: authenticated consumer dispatch and model execution under this changed startup configuration. Configuration/authentication checks are not Product integration acceptance.

The actual dedicated-judgment chain already recorded in `ACP-SINGLE-VERSION-REAL-ACCEPTANCE-20261008.md` remains historical bounded evidence for its exact images/configuration. It does not prove this fresh stack has enabled the route. The 2026-10-09 actual ordinary delegated turn proves its own attribution/ACK/cleanup boundaries and cannot replace dedicated judgment evidence.

Rollback: restore the backed-up candidate file. No new storage schema or migration; only the fresh qualification Adapter was recreated. Production and stopped historical test groups remain stopped.

## Independent Tester / Root

Tester independently parsed baseline and a private temporary opt-in overlay: lifecycle `1`, `opencode-go`, `deepseek-v4.1-flash` all reach the trusted Adapter configuration; the temporary 0600 overlay was removed and not applied. Baseline default remains disabled. Static runner child-env filters exclude control secrets.

After the Root-only Adapter recreate, Tester independently observed the same pinned image `sha256:0effdb8bae2b27c06e127185016bc97c34eb494ae8c1990872e7785abac80b8c`, healthy state, `/readyz` HTTP 200, judgment descriptor HTTP 200 with `authenticated=true`, and unauthenticated dummy-task dispatch HTTP 401. The descriptor is public and reports configured token presence; it is not proof of successful bearer authentication. No model calls or actual task dispatch occurred.

Root verdict: PASS for this bounded startup wiring / default-off / unauthenticated-rejection slice, with independent Tester and Reviewer. Enabled judgment completion, normal background-result continuation, default upgrade, CI/release and deployment remain separate gates.
