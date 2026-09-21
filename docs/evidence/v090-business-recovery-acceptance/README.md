# v090 REAL business-recovery acceptance (ADR-0084 / merged #352)

This slice accepts the merged `#352` business-recovery vertical slice with a
**REAL ISOLATED SERVICE COMBINATION**, not a label PASS and not mock-only. It is
maintenance/qualification: it does not advance a Product Phase, does not switch
the DSH selector, does not deploy/release/tag, does not unfreeze Phase 100/R3,
does not start 0.10 and does not generate a D15 superseding assessment.

## What was run

An isolated Docker Compose project (`byq-v090-recovery`, own network/volumes,
fresh PostgreSQL, loopback-only ports) built from this branch. The committed
Backend, Gateway (real background task-continuation consumer), Runtime Adapter,
MCP and PostgreSQL are the real components; only the model is a controlled
keyless provider (`services/runtime-adapter/tests/v090_br_acceptance_provider.py`).
The production `beyondquant` stack is never joined, mounted or touched.

Reproduction:

```bash
python3 scripts/v090/business_recovery_acceptance/run_acceptance.py \
    --out docs/evidence/v090-business-recovery-acceptance/observations.v1.json
python3 scripts/v090/business_recovery_acceptance/observer.py
python3 scripts/v090/business_recovery_acceptance/observer.py --selfcheck
python3 -m unittest tests.test_v090_business_recovery_acceptance -v
```

## Real vs simulated boundary

* Real: PostgreSQL authority rows, Backend HTTP routes, the Gateway background
  `TaskContinuationDelivery` consumer, Runtime Adapter HTTP routes and its real
  append-only lifecycle journal + containment ledger, the MCP server, the real
  DSH 0.1.2rc1 runtime, and a real `SIGKILL`/restart of the Adapter OS process
  (container PID changes).
* Simulated: the model provider only. It is a scripted keyless OpenAI-compatible
  endpoint; it cannot influence any authority decision.

## Coverage

1. **Real before-state + real loss** — a real task/conversation/permission/
   reservation; a real Adapter run left open; the Adapter OS process is killed
   and restarted; the durable containment ledger marks the exact incomplete run
   `interrupted` with `loss_cause=executor-loss`.
2. **Real recovery seams** — the Gateway consumer detects the fenced containment
   and read-only anchor, the Backend re-derives step-safety/budget from its own
   evidence and mints the closed carrier, the Adapter admits it and installs a
   new target generation, and the accepted target is written back.
3. **Fail-closed negatives** (all real HTTP): forged loss run, snapshot change
   for an existing trigger, unknown attempt cost (`paused`), below the model-call
   floor, ordinal cap, stale target epoch, recovery-mode new key and cross-task
   domain claims.
4. **No duplicate side effects** — the read-only recovery leaves authoritative
   business row counts unchanged; the Adapter journal shows exactly one lost and
   one recovery generation; the retry reuses the exact accepted run and creates
   no second generation; the Backend ordinal does not advance.

## Defect found and fixed

Real acceptance found a genuine `#352` defect: after a real executor loss the
Gateway never reached the recovery seam because the Adapter's
`reconcile_prompt` reported the lost run's original prompt as `accepted`
(a prompt receipt proves only that the run *started*). The Gateway then
short-circuited before `_resume_lost_reservation`.

Minimal reversible fix in `services/runtime-adapter/app/runtime.py`
(`_reconcile_lost_receipt`): when the fenced containment ledger proves that exact
run was lost, the original prompt is reported `outcome_unknown`, so the Gateway
reaches the existing recovery path. A normal completion has no containment record
and is unchanged. Regression test:
`services/runtime-adapter/tests/test_business_recovery.py::test_lost_original_prompt_is_never_reconciled_as_accepted`.

## Files

* `observations.v1.json` — RAW machine-readable observations + cleanup proof.
* `verdict.v1.json` — fail-able observer verdict (re-derived, not label-trusted).
* `negative-controls.v1.json` — 20 defect-targeting observer controls.
* Driver/observer/seeder: `scripts/v090/business_recovery_acceptance/`.
* Contract: `scripts/v090/business_recovery_acceptance/contract.v1.json`.

## Boundaries unchanged

B1 `subagent-child-crash` and B2 `subagent-byq-adapter-restart` stay
`BLOCKED_EXTERNAL`; historical D15-G stays `NO_GO` (not rewritten); `R3_RESUME =
NO`; the production selector stays `dsh-0.1.2rc1`; no D15 superseding assessment
is generated; Phase 100/R3 remain frozen.
