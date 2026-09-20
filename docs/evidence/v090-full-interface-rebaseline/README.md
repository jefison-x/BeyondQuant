# 0.9 Full-Interface Re-Baseline (real `complete=true`)

Status: **Draft PR — maintenance re-baseline, not merged, no implementation, no
deployment, no tag/release.** This batch re-does the current candidate `main`
full-interface reliability ledger to a real machine-checkable `complete=true`.

- Baseline (H4 ledger commit): `b109d2804aa7724501356c8ee06943904e1e605e` (#280)
- Candidate: `origin/main` = `21c1812cfb388d6daecca8fa2000d9586e684779` (#339)
- Worktree/branch: `codex/v090-full-interface-rebaseline`
- Product Phase marker stays **97**; `R3_RESUME = NO`.

This batch does **not** implement Proposed ADR-0082/0083, does **not** switch the
production DSH selector, does **not** deploy, and does **not** create or move any
tag/release. It does not inspect or copy the Community repository and does not
resume Phase 100.

## 1. Why the ledger read `566 discovered / 560 reviewed / 6 unreviewed`

`scripts/ci/inventory-reliability.py` discovers Python literal route decorators,
literal MCP `registerTool` names and worker `worker.py` files under
`services/`, `workers/`, `packages/`. On the candidate tree it discovers
**566** interfaces (481 routes + 81 MCP tools + 4 workers).

The H4 ledger (`docs/evidence/research-handoff-h4/INTERFACE-REVIEW.json`,
committed in #280) contains **560** rows. The **6 missing rows** are all Phase 101
credential-driven model-catalogue interfaces that landed after #280:

| Missing row | Boundary | Handler |
|---|---|---|
| `GET /v1/users/model-credentials/{credential_id}/models` | Backend | `discover_model_credential_models` |
| `POST /v1/users/model-profiles/{profile_id}/disable` | Backend | `disable_model_profile` |
| `POST /v1/users/model-profiles/{profile_id}/enable` | Backend | `enable_model_profile` |
| `GET /settings/models/credentials/{credential_id}/models` | Gateway/Product API | `product_model_credential_models` |
| `POST /settings/models/profiles/{profile_id}/disable` | Gateway/Product API | `product_model_profile_disable` |
| `POST /settings/models/profiles/{profile_id}/enable` | Gateway/Product API | `product_model_profile_enable` |

The old auditor exited 0 without `--require-complete`, so "reporter green" was
never a business PASS. The old H4 `complete=true` was only true at its own
commit and was not reproducible later.

## 2. Source-drift breakdown (files and commits)

The old ledger recorded a `source_sha256` for each row's file plus dependency
digests. On the candidate tree **20 files drifted**; 17 changed after the H4
commit, and **3 recorded hashes never matched the committed H4 tree at all**
(false baseline):

| File | Kind | Drift commits |
|---|---|---|
| `services/backend/app/main.py` | source | #287, #294, #298, #301 |
| `services/gateway/app/product_api.py` | source | #291, #294 |
| `services/mcp/src/server.ts` | source | **false baseline** (recorded `aee5acc` blob; unchanged since #280) |
| `services/gateway/app/main.py` | source | **false baseline** (recorded `049104e` blob) + #302, #316 |
| `services/runtime-adapter/app/main.py` | source | #302, #304 |
| `workers/signal/worker.py` | source | #303 |
| `services/mcp/src/backtest.ts` | dependency | **false baseline** (recorded `df17e33` blob; unchanged since #280) |
| `services/mcp/src/request-validation.ts` | dependency | #297 |
| `services/backend/app/credentials.py` | dependency | #287, #288, #289, #294, #295, #296 |
| `services/backend/app/data_provider.py` | dependency | #286, #337 |
| `services/backend/app/signal_producer.py` | dependency | #293, #298, #300, #303 |
| `services/backend/app/market_readiness.py` | dependency | #299, #300, #301, #303, #337 |
| `services/backend/app/research_continuation.py` | dependency | #305, #312, #315 |
| `services/backend/app/continuation_scope.py` | dependency | #305, #312 |
| `services/backend/app/backtest.py` | dependency | #301, #303 |
| `services/backend/app/research.py` | dependency | #312 |
| `services/runtime-adapter/app/runtime.py` | dependency | #290, #302, #304, #309, #316 |
| `services/signal-sandbox/runner.py` | dependency | #300, #301, #303 |
| `apps/frontend/src/api/settings.ts` | dependency | #291, #294 |
| `plugins/dsh-byq/runtime/byq-continuation-budget.js` | manual surface | #306, #309, #315 |

Machine-readable form: [acceptance.v1.json](acceptance.v1.json).

### Per-boundary findings

- **Backend (ADR-0047 aggregation)**: `_partition_market_requirements` moved to
  `app/market_plan.py` and is now `partition_market_requirements`; readiness is
  assessed and repaired **per partition**; `requirement_plan` is frozen and
  included in the signal request hash; over-cap requirements terminalize as
  `failed(market_requirement_exceeded)` instead of crashing the worker.
- **Backend (ADR-0023 bounded input)**: signal job input and signal snapshots
  store one `bars_frame.v1` columnar document (`signal-snapshot-v2`), decoded
  compatibly for v1; ready bars carry the frozen absolute `adjustment_factor`;
  `AGGREGATE_ROW_LIMIT` replaces the retired 50,000-cell cap at the backtest and
  sandbox boundaries.
- **Backend (ADR-0075/0076 model catalogue)**: credential-driven discovery
  (`discover_models`) with an 8 s bounded outbound call, full-refresh persistence
  of only allowlisted models, and a fail-closed `RUNTIME_MODEL_ALLOWLIST` gate on
  profile creation and resolution; profile `disable`/`enable` with durable status
  receipts and same-transaction unbind.
- **Gateway (ADR-0079 R2 runtime continuity)**: session create/resume project a
  framework-neutral `continuity` status; the durable trace is reopened on rebind
  so `persisted+1` can be appended, and a real `TraceConflict` stops projection
  instead of crashing or masking the sequence.
- **Runtime adapter**: a stale journal lease that can never be re-claimed (host
  reboot) maps to HTTP `409 stale_session_lease` instead of `404`/`503`;
  continuation qualification uses `rehydrate=False` and never constructs a
  session.
- **MCP**: `request-validation.ts` correction hints now declare a per-hint
  `repair_limit` (0 = domain/data-scale blocker must not be resubmitted, 1 = one
  repair allowed); the transport (`server.ts`) itself is unchanged since #280 and
  only its recorded digest was wrong.
- **Worker**: the signal worker logs promoted/failed/completed outcomes
  structurally (no secrets or full payloads) and terminalizes over-cap jobs.

## 3. Re-verified semantics and fixes

Every missing row and materially changed interface was re-verified against the
current code. The ledger's existing per-interface fields
(owner/authorization/idempotency/timeout/errors/retry/authority/recovery) were
updated where the drift changed the reliability contract; otherwise they were
re-affirmed and the digest refreshed. No interface was deleted, no row was
bulk-marked, and no hash was changed without the corresponding review.

- New rows: full review fields recorded (owner + trusted actor, idempotency via
  durable receipts, provider/outbound timeout bounds, closed error mapping,
  receipt/original-key lookup, reversible cleanup).
- `create_agent_data_demand`, `create_ml_training_run`, `create_signal_producer_job`,
  `prepare_backtest_task`, `create_backtest_job`: idempotency/errors/recovery
  updated for the frozen partition plan, `bars_frame` decode and aggregate bound.
- `create_model_profile`, `resolve_model_credential`, `reconcile_model_command`:
  fail-closed allowlist and the new `disable_profile`/`enable_profile` receipt
  operations recorded.
- `create_product_session`, `resume_product_session`, `create_session`,
  `resume_session`, `continuation_qualification`: continuity/reopen/stale-lease
  semantics recorded.
- 80 MCP tool rows that depend on `request-validation.ts`: error mapping updated
  for bounded per-hint `repair_limit`.
- Manual surface `framework_middleware_callbacks` was corrected to actually
  describe its file (`byq-continuation-budget.js`): exact qualified route
  (provider, model) from the Backend allowlist, per-call ceilings, the
  data-ready call/token bound, and fail-closed budget errors.
- Manual surface `mcp_transport`: digest corrected to the real committed
  `server.ts` (false baseline), fields unchanged because the file did not change.

## 4. Machine-readable acceptance

`scripts/ci/check-reliability-review.py` is now a **fail-closed auditor**:

```
discovered 566, reviewed 566, missing 0, stale 0, fake_pass 0, complete true
```

It exits non-zero whenever the audit is not `complete`. It rejects:

- **missing rows** (a discovered interface without exactly one reviewed row),
- **stale hashes** (a recorded source/dependency digest that differs from the
  current tree, including a missing file),
- **fake PASS** (`VERIFIED_OK` with an empty/missing review field, a
  non-digest `source_sha256`, or no evidence recorded),
- absent/duplicate/unknown interfaces and manual surfaces, and missing evidence
  files.

Reproduction:

```bash
python3 scripts/ci/check-reliability-review.py          # exit 0, complete true
python3 scripts/ci/check-reliability-review.py --require-complete
```

Regression: `tests/test_reliability_review_audit.py` asserts the real ledger is
complete and that a tampered ledger (dropped row, zeroed hash, emptied evidence)
makes the CLI exit `1` with `complete=false` and the matching `missing`/`stale`/
`fake_pass` count.

## 5. Constraints frozen by this batch

- No Community inspection/copy; no ADR-0082/0083 implementation.
- No DSH production selector switch (`dsh-0.1.2rc1` unchanged), no
  deploy/tag/release, no Phase 100 resume.
- No real Product-path behaviour was changed; no Gateway/Product API runtime
  verification was required because no runtime path was modified. The only
  Gateway/Product API rows touched are read/write proxies whose real flows are
  covered by `services/gateway/tests/test_product_api.py`,
  `apps/frontend/src/api/settings.spec.ts` and the Phase 101 browser evidence.
- Build identity advanced to the next unused revision `dsh-0.1.2rc1-post-u8.178`
  because `scripts/` and `tests/` are build inputs; the historical `.177`
  manifest and evidence are preserved unchanged.
