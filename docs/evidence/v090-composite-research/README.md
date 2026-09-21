# 0.9 composite research fault regression (0.9 strict order, step 3)

- Status: **Draft PR — maintenance/audit, executed on an isolated stack.**
- Date: 2026-09-21
- Scope: one fully successful improve-strategy composite journey plus a
  service-boundary fault matrix, on a synthetic user and an isolated stack.
- Provider: scripted keyless synthetic runtime (`real_llm_quality=false`). This
  is **service-boundary fault-regression evidence, NOT real-LLM-quality
  semantic evidence**.
- Product Phase marker stays **97**; `R3_RESUME = NO`.

This batch does **not** implement Proposed ADR-0082/0083, does **not** switch the
production DSH selector, does **not** deploy, does **not** create or move any
tag/release, does **not** resume Phase 100 and does **not** inspect or copy the
Community repository.

## Evidence versioning

- **v2 is the current, rectified evidence.** `contract.v2.json`,
  `observations.v2.json`, `verdict.v2.json`, `negative-controls.v2.json`,
  `capture-negatives.v2.json`, `acceptance-matrix.v2.json`.
- **v1 is retained for provenance and is NOT qualification evidence.** It is
  marked `superseded` in `acceptance-matrix.v1.json`. The v1 fault rows
  hardcoded generation/epoch, reused one trace/run for unrelated fault actions
  and over-claimed scenario names (approval 3-in-1, data-wait). v1 must not be
  read as 9/9 PASS.

## Rectification (P1-1..P1-8)

- **P1-1 gitleaks**: the over-broad `docs/evidence/v090-composite-research/.*.json`
  directory allowlist was removed from `.gitleaks.toml`; `.gitleaks.toml` and
  `.gitleaksignore` have **no changes vs `main`**. The trigger was removed at the
  source: high-entropy content-addressed idempotency keys in the journey
  receipts are redacted to a short `sha256:` digest (`_redact_key`), and the
  offending local variable was renamed away from the `key = "…"` pattern. The
  CI gitleaks version/config reports **0 findings** over `origin/main..HEAD`.
- **P1-2 provenance**: every PASS scenario carries a `provenance` block for
  trace/run/generation/epoch/pid. The trace is read from the authoritative
  `ml_training_runs.trace_id` (or `agent_runtime_turns.trace_id`) and is
  associated with the scenario's receipt object; run/generation/epoch are
  explicit `not_applicable` + reason at the ML boundary (no fabricated
  `1 -> 2`); pid is measured per restarted service. The observer rejects a
  missing provenance, a value without a contract-allowed source, a
  `not_applicable` without a reason, an unrelated trace object and a
  restart without an actual pid change.
- **P1-3 approval split**: `approval-rejected` and `approval-stale-reuse` are
  independent real rows; `approval-revoked` is a separate required row honestly
  **BLOCKED** (no revoke path exists at the ML or agent approval layer).
- **P1-4 cancel gate**: `cancel-terminal` requires the authoritative terminal to
  be `cancelled` (`terminal_status_raw == "cancelled"`), re-checked after the
  worker recovers, with no downstream prediction. A `completed` cancel fails.
- **P1-5 late-success**: requires **zero** delta for prediction/signal/backtest/
  report (not `<=1`); one next step fails.
- **P1-6 data-wait**: the queue row is renamed `queue-worker-resume` (real) and
  the ADR-0077 `data-ready-continuation` is a separate required row honestly
  **BLOCKED** (the journey exercises the ADR-0045 budgeted continuation, not the
  `data_ready` grant). A real `bounded-continuation-exactly-once` row is derived
  from the journey's authoritative continuation ledger.
- **P1-7 boundaries**: rows now name their boundary
  (`gateway-product-api`, `backend`, `gateway`, `ml-worker`, `backend-domain`,
  `runtime-adapter`); the Gateway and worker boundaries are exercised
  separately; the runtime-adapter tool-call boundary is a separate required row
  honestly **BLOCKED** (D15 scope).
- **P1-8 observer**: 58 negative controls, all non-zero, 21 defect-targeting,
  covering no-provenance, hardcoded generation, unrelated trace, restart without
  pid change, missing revoke/stale/gateway/adapter scenarios, cancel that
  completed, late delta=1 and queue impersonating `waiting_for_data`.

## Composite journey (real result: PASS)

Owner `f6-chain-user`; the original task and all persisted objects are recorded
in `observations.v2.json`. The observer verifies lineage, owner/workspace, the
original key, the persisted approval, canonical identities and report/terminal
consistency.

## Fault matrix (real result: 13 PASS + 4 declared BLOCKED)

| row | boundary | result |
| --- | --- | --- |
| response-loss-before-write | gateway-product-api | PASS |
| response-loss-after-write | gateway-product-api | PASS |
| duplicate-delivery | gateway-product-api | PASS |
| process-restart-backend | backend | PASS |
| process-restart-gateway | gateway | PASS |
| process-restart-ml-worker | ml-worker | PASS |
| late-success | ml-worker | PASS |
| cancel-terminal | ml-worker | PASS |
| approval-rejected | backend-domain | PASS |
| approval-stale-reuse | backend-domain | PASS |
| queue-worker-resume | ml-worker | PASS |
| bounded-continuation-exactly-once | backend-domain | PASS |
| model-or-domain-failure | backend-domain | PASS |
| approval-revoked | backend-domain | **BLOCKED** — no revoke path exists |
| timeout-terminal | ml-worker | **BLOCKED** — no deterministic timeout boundary |
| data-ready-continuation | backend-domain | **BLOCKED** — ADR-0077 data_ready not exercised |
| runtime-adapter-tool-boundary | runtime-adapter | **BLOCKED** — needs D15 tool-call fault injection |

Every PASS row records fault timing, its boundary, real per-service PIDs,
authoritative before/after counts, receipt/trace/run provenance, recovery action,
terminal state and the six assertions; no active/pending orphan remains. The four
declared BLOCKED rows are honestly non-qualifying, so the observer verdict is
**`format_valid=true` only if no structural failure exists; `all_pass=false`**
because four REQUIRED rows are BLOCKED. This is the honest result; it does not
claim 9/9 PASS.

## Observer and negatives

- `observer.py --selfcheck` → `negative-controls.v2.json`: **58 controls, all
  rejected; 21 defect-targeting** (pre-fix result-trusting gate passed them).
- `capture_negatives.py` → `capture-negatives.v2.json`: **12 cases**, each
  post-fix fail / pre-fix pass.
- `observer.py --observations observations.v2.json` → `verdict.v2.json`:
  `format_valid` true, `all_pass` false, coverage_failures = the four BLOCKED
  rows.

## Isolation, cleanup, reproduce

Dedicated compose project `byq-v090-composite-local`, dedicated network/volumes,
loopback-only ephemeral ports, fresh synthetic PostgreSQL, images rebuilt from
this branch. Cleanup leaves `containers_remaining=0`, `networks_remaining=0`,
`volumes_remaining=0`, `production_untouched=true`.

```bash
python3 scripts/v090/composite_research/run_regression.py --no-build
python3 scripts/v090/composite_research/observer.py \
  --observations docs/evidence/v090-composite-research/observations.v2.json \
  --out docs/evidence/v090-composite-research/verdict.v2.json
python3 scripts/v090/composite_research/observer.py --selfcheck \
  --out docs/evidence/v090-composite-research/negative-controls.v2.json
python3 scripts/v090/composite_research/capture_negatives.py \
  --out docs/evidence/v090-composite-research/capture-negatives.v2.json
python3 -m unittest tests.test_v090_composite_research
```

## Reproduced 0.9-scope defects

None reproduced. The 13 exercisable required rows pass on the current candidate
without a code change; the rectification is in the harness, contract, observer
and evidence, not in product code. The four BLOCKED rows are declared with
reasons rather than substituted.

## Limitations

- Scripted keyless provider: not real-LLM-quality semantics.
- Four required rows are BLOCKED (see above); the verdict is not `all_pass`.
- `host-reboot` remains OPTIONAL `NOT_RUN`.
