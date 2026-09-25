# ADR-0085 P4-C1 — Adapter/DSH fault-safe convergence (0.9.1)

## Scope

This slice implements **ADR-0085 P4-C1** on top of the merged P4-A integration
foundation, the merged P4-B normal journey and the Accepted ADR-0086
request-scoped budget. It is a maintenance/stability change for the **0.9.1**
version. It does **not** deploy, does **not** write a version number, does
**not** create or move any tag or release, does **not** run a production canary,
does **not** resume Phase 100 and does **not** start 0.10.

P4-C1 verifies **Adapter/DSH process-interruption fault-safe convergence** over
the committed isolated four-boundary stack:

```
Product API (Gateway) -> authenticated Runtime Adapter judgment route
  -> real DSH runtime subprocess -> Backend admit/result seams (MCP read-only)
```

It does **not** claim DSH-native cross-process continuation or provider
recovery, and does **not** implement or claim **P4-C2** (Backend claim/settle
real consumer) or **P4-D** (unified final verdict).

## Result: `format_valid=true`, `all_pass=true` (P4-C1 scoped)

With real, isolated, non-production process faults injected, every frozen
gating row and assertion is derived TRUE from the raw boundary facts:

```
format_valid = true
all_pass     = true
blocked_rows = {}
```

This `all_pass=true` is **scoped to P4-C1** (Adapter/DSH interruption
convergence only). It is **not** an overall P4/P4-C2/P4-D pass, does not claim
DSH-native recovery, and does not unlock P4-C2.

## Injected faults and observed convergence

All faults are real: the Runtime Adapter container OS process is killed with
`docker kill`, the DSH runtime child OS process is `SIGKILL`ed inside a live
adapter, and the keyless provider is switched between deterministic fault modes
(`block_child`, `delay_child`, `no_progress_child`).

| id | injected fault | observed convergence |
|---|---|---|
| F1 | Adapter OS process killed while a provider request is in flight (provider held open) | retry of the undecided attempt = `409 research_judgment_in_progress`; 0 new provider calls; exactly 1 durable stage call `admitted` `call_index=1`; plan `strategy_draft` v1 unchanged; task pending; adapter pid changed |
| F2 | DSH runtime child OS process killed inside a live adapter | bounded turn fails closed `503 research_judgment_failed_closed`, no result submitted; adapter pid unchanged; retry `409`; 0 new provider calls; stage call stays `admitted` |
| F3 | repeated retries after restart | each retry `409` with 0 provider calls, no second stage call, no receipt |
| F4 | late request for the OLD attempt after completion + plan advance | `200` exact replay, `model_turn_skipped=true`, 0 provider calls, no new stage call, plan unchanged (`waiting_for_strategy_approval` v2) |
| F5 | late/forged result to the real Backend result seam for the old attempt | old identity = stored receipt replay, no second write; forged identity rejected `409`; plan/object counts unchanged |
| F6 | killed owner vs genuinely stuck owner (provider alive, blocked) | both yield the SAME closed `research_judgment_in_progress`; no auto-fence of the live attempt; no recovery claimed; no fabricated completion |
| F7 | normal long-running turn (provider alive, delayed 8s) + concurrent duplicate | original completes once (`200`, plan advances); duplicate `409`, preempts nothing; exactly the profile's 3 provider calls; exactly 1 completed stage call; no duplicate object |
| F8 | fresh result with no durable progress | plan+task atomically `needs_attention` (`blocked`) with `blocked_reason=no_durable_progress`; exactly 1 completed stage call `needs_attention`; no duplicate object; no over-limit call |
| F9 | aggregate object accounting | one task/plan per scenario (7), six stage calls, zero paper account/order/position/fill; no duplicate object |

Boundary rows: **B1** no/forged token `401`, forged/stale attempt rejected
(`503` fail-closed), controls reach neither the provider nor the stage-call
ledger; **B2** cleanup zero containers/networks/volumes with production
untouched; **B3** adapter-derived call identity == durable stage-call identity ==
receipt identity, `call_index=1`, no duplicate index, generation consistent;
**B4** the adapter derives identity/attempt/endpoint server-side, unknown result
fields are rejected `422`, a non-`none` durable-evidence identity is rejected
`422`; **B5** every observed terminal fault state is a contract-allowed durable
`admitted` pending or `needs_attention`.

## Why this is fail-closed and honest

- The Runtime Adapter never auto-retries: a completed admission replays with no
  model turn; an existing `admitted` admission returns `created=false` and the
  adapter raises `ResearchJudgmentInProgress` (`409`) without writing anything;
  only a freshly created admission runs a model turn (`services/runtime-adapter/app/research_judgment.py`).
- The Backend `record_research_judgment_result` is one atomic transaction: a
  completed call replays its stored receipt, a stale/foreign proposal fails the
  plan CAS, and a first call with no durable progress atomically fences
  plan+task to `needs_attention/no_durable_progress`
  (`services/backend/app/research_judgment.py`).
- Without a cross-process lease the system **cannot** prove an interrupted owner
  is terminal, so a killed and a genuinely stuck owner produce the same explicit
  pending; the slice claims no DSH-native recovery and does not use a widened
  call limit or a refreshed request budget to bypass the pending state.

## What was actually run

- **Real isolated non-production stack**: `byq-p4-judgment` compose project over
  `compose.runtime-qual.yml` + `compose.p4-judgment.yml` + `compose.p4c1.yml`
  (dedicated network/volumes, fresh PostgreSQL, loopback-only ports, keyless
  fault-mode provider).
- `scripts/v091/continuation_p4c1/run_faults.py` injected the faults and wrote
  `observations.v1.json`, then tore the isolated stack down to zero
  containers/networks/volumes with production untouched.
- Before serializing the evidence the driver deterministically redacts every
  plan-command `idempotency_key` to a stable `sha256:<digest>` marker
  (`_redact_idempotency_keys`): the raw high-entropy key is never published,
  while its presence and stable identity are preserved, so before/after plan
  equality and replay identity are unaffected. This is a truthful source-level
  redaction, not a fabricated value, and it is what keeps the evidence clear of
  secret-scanner false positives.
- The fail-able observer (`observer.py`) re-derives every row/assertion from the
  raw facts and produced `verdict.v1.json` (`format_valid=true`,
  `all_pass=true`).
- `--selfcheck` rejects all 55 defect-targeting controls while a legacy
  label-trusting gate accepts every one.

## Reproduce

```bash
# Observer self-check (fail-able; 55 defect-targeting controls all rejected).
python3 scripts/v091/continuation_p4c1/observer.py --selfcheck

# Governance/contract/matrix tests (architecture lane, no DB, no Docker).
python3 -m unittest tests.test_v091_continuation_p4c1

# Re-derive the committed verdict (exit 0: P4-C1 scoped all_pass=true).
python3 scripts/v091/continuation_p4c1/observer.py \
  --observations docs/evidence/adr-0085-p4c1-adapter-fault-safe/observations.v1.json \
  --out docs/evidence/adr-0085-p4c1-adapter-fault-safe/verdict.v1.json

# Real isolated stack fault injection (opt-in; requires Docker; no paid API,
# no production). Builds the current worktree's services/mcp dist first.
PYTHONPATH=services/runtime-adapter:. BYQ_P4_ROOT=<worktree> \
  python3 scripts/v091/continuation_p4c1/run_faults.py
```

## Production changes

**None.** P4-C1 adds only the isolated fault harness, its fail-able observer,
the frozen contract/matrix, the evidence and the governance tests. The Runtime
Adapter, Backend, Gateway and MCP runtime code are unchanged; the only
non-harness changes are the roadmap/status fact updates and the build-identity
refresh. The H4 reliability ledger is unchanged because this slice adds no new
discovered service/worker/route interface (it is re-verified complete by
`scripts/ci/check-reliability-review.py`).

## Non-claims

- No DSH-native cross-process continuation or provider recovery claim.
- No P4-C2 Backend claim/settle real consumer and no P4-D unified final verdict.
- No overall P4 `all_pass` and no phase completion.
- No production deployment, version write, tag or release.
- No production canary; only an isolated non-production stack.
- No real-LLM research-quality semantic claim; the driver uses a keyless
  scripted fault-mode provider.
- No Phase 100 resume and no 0.10 start.
- No second generic agent harness or session store; the model only submits a
  bounded research proposal and never chooses `next_action`, object identity,
  approval, idempotency, routing or recovery state.
