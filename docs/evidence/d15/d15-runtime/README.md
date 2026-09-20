# D15 real isolated BYQ runtime-continuity qualification

- Status: **PASS (scripted keyless provider; service-boundary runtime continuity)**
- Date: 2026-09-20
- Candidate: coherent `dsh-0.1.5rc1` / Python SDK `0.1.5rc1` / bundled runtime `0.1.5rc1`
- Build revision: `post-u8.160` (rebuild identity only; no selector/deployment change)
- Scope: this batch qualifies **runtime continuity only**. D15-4, D15-5, D15-G and R3
  are **not** in this batch and no full-D15 completion is claimed.

## What is real vs scripted

Real, in an isolated stack (dedicated compose project `byq-d15-runtime`, dedicated
network/volumes, fresh PostgreSQL, loopback-only ports):

- BYQ Gateway, runtime-adapter (rebuilt fixed 0.1.5rc1 candidate image),
  Backend and MCP services, all started as separate containers;
- BYQ Product API entry path (durable login, research task objective, strategy
  approval, paper-pool side effect) with real PostgreSQL persistence;
- the runtime-adapter durable lifecycle journal, generation ledger and stable
  executor epoch on an isolated session volume;
- real process faults: adapter container SIGKILL+restart, DSH bundled-runtime
  child SIGKILL, Gateway container restart, explicit executor takeover.

Scripted, and explicitly **not** real-LLM-quality:

- the model provider is a keyless deterministic loopback OpenAI-compatible
  server that streams a fixed assistant message. It drives real DSH/runtime
  turns but does not measure model semantics. `observations.v1.json` records
  `llm.class = scripted-keyless` and `llm.real_llm_quality = false`.

## Contract and fail-able observer

- `scripts/d15/runtime_continuity/contract.v1.json` — closed scenario set,
  invariants, required per-scenario before/after fields and fail-closed list.
- `scripts/d15/runtime_continuity/observer.py` — independent verdict; exits
  non-zero on any violation or on an unreadable artifact, and never treats
  missing evidence as a pass. `--selfcheck` mutates a known-good fixture in
  every fail-closed way and requires each mutation to fail.
- `negative-controls.v1.json` — 18 controls, `baseline_all_pass=true`,
  `all_controls_pass=true`; each control observed `all_pass=false`/`exit_code=1`
  while `pre_fix_would_pass=true`. For example `missing-evidence-field`
  fails with `scenario[adapter-process-restart].after: missing 'goal'`.

## Per-row results (real observations)

| fault row | continuity | adapter pid | generation | epoch | goal | side effect | approval | result |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| adapter-process-restart | `reattached` -> `rehydrated` | 3216725 -> 3218079 | +1 new | 1 -> 1 | retained | dedup (1) | approved | completed, seq 11 |
| gateway-disconnect-reconnect | `reattached` -> `reattached` | 3218079 -> 3218079 | same | 1 -> 1 | retained | dedup (1) | approved | completed, seq 11 |
| generation-replacement | `reattached` -> `interrupted` | 3218079 -> 3218079 | +1 new | 1 -> 1 | retained | dedup (1) | approved | completed, seq 18 |
| dsh-process-interruption | `reattached` -> `rehydrated` | 3218079 -> 3218079 | +1 new | 1 -> 1 | retained | dedup (1) | approved | completed, seq 25 |
| executor-takeover | `reattached` -> `reattached` | 3218079 -> 3218079 | same | 1 -> 2 | retained | dedup (1) | approved | completed, seq 25 |

- Goal retention is proven by an unchanged durable prompt receipt
  (`content_sha256` + `root_run_id`) in the lifecycle journal plus the persisted
  Product conversation message; a prompt replay with the original idempotency
  key returned the same run id and did not increment the provider call count.
- No duplicate side effect is proven by replaying the paper-pool idempotency key
  and observing the same `pool_id` with exactly one owner-scoped pool.
- Approval not bypassed is proven by the persistent strategy approval artifact
  remaining `approved` and unbypassed across every process restart; the observer
  additionally fails `expired-approval-reuse` and `initiator-self-approval`.
- Traceability is proven by contiguous WorkflowTrace sequences (strictly
  increasing) and persisted assistant result messages.
- Executor takeover incremented the monotonic epoch `1 -> 2`, wrote an immutable
  audit `.../executor-state/takeover-audit/20260920T044040Z.2.json`, modified no
  database row, and retained the session/evidence.

## Explicitly uncovered / not executed

- **Host reboot**: `NOT_RUN`. Rebooting the maintainer host or production is not
  authorized; a container restart is not equivalent to a host reboot.
- **Real-LLM semantic quality**: not measured (scripted provider).
- **Agent-driven domain side effects via model tool calls**: the domain
  goal/approval/action were driven through the real Product/Backend/MCP-wired
  stack, not by a model tool call. The scripted provider emits text only.
- **D15-4 subagent/fork, D15-5 persistent terminal, D15-G Go/No-Go**: not in
  this batch.
- **R3**: remains frozen; `R3_RESUME = NO`.

## Isolation and cleanup

`stack.v1.json` records the preflight (6 containers, loopback-only published
ports, candidate pinned, adapter image digest) and cleanup
(`containers_remaining=0`, `networks_remaining=0`, `volumes_remaining=0`). The
production `beyondquant` stack, its volumes and the Community repository were
never referenced or modified.

## Reproduce

```bash
python3 scripts/d15/runtime_continuity/run_qualification.py        # up -> scenarios -> cleanup
python3 scripts/d15/runtime_continuity/observer.py --selfcheck \
    --out docs/evidence/d15/d15-runtime/negative-controls.v1.json  # must exit 0
python3 scripts/d15/runtime_continuity/observer.py \
    --observations docs/evidence/d15/d15-runtime/observations.v1.json \
    --out docs/evidence/d15/d15-runtime/verdict.v1.json            # must exit 0
```
