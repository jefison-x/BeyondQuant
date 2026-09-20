# D15 real isolated BYQ runtime-continuity qualification

- Status: **PASS (scripted keyless provider; service-boundary runtime continuity)**
- Date: 2026-09-20 (v2 review-fix revision)
- Candidate: coherent `dsh-0.1.5rc1` / Python SDK `0.1.5rc1` / bundled runtime `0.1.5rc1`
- Build revision: `post-u8.161` (rebuild identity only; no selector/deployment change)
- Scope: runtime continuity only. D15-4, D15-5, D15-G and R3 are **not** in this
  batch and no full-D15 completion is claimed.

## Review fixes in v2

The v1 observer conflated "the report is well formed" with "the qualification
passed". v2 separates them and hardens the checks:

- **`format_valid` vs `all_pass`**: `format_valid` means the artifact is well
  formed and every check that ran passed. `all_pass` is the qualification gate:
  every REQUIRED scenario must be present and `PASS`. A REQUIRED `NOT_RUN` or
  `BLOCKED` now yields `all_pass=false` and exit 1 while preserving its status
  and reason.
- **OPTIONAL scenarios** are declared separately in the contract
  (`optional_scenarios`). `host-reboot` is optional and reported `NOT_RUN`; it
  does not gate the required coverage.
- **Contract-authoritative continuity**: `allowed_continuity` /
  `forbidden_continuity` come only from the trusted contract. An observation
  that declares them is rejected; the previous `setdefault` override is gone.
- **Recovery relationships / linkage**: PASS requires real relationships, not
  field existence or a self-reported `fault_applied`. See below.
- **Honest pre-fix comparison**: `run_selfcheck` executes a reconstructed
  legacy algorithm and records its actual result (`legacy_algorithm_all_pass`),
  instead of hardcoding a claim.

## What is real vs scripted

Real, in an isolated stack (dedicated compose project `byq-d15-runtime`,
dedicated network/volumes, fresh PostgreSQL, loopback-only ports), with the
services rebuilt from this branch:

- BYQ Gateway, Backend, MCP and runtime-adapter (fixed 0.1.5rc1 candidate),
  each a separate container; `stack.v2.json` records every image digest.
- BYQ Product API entry path (durable login, research task objective, strategy
  approval, paper-pool side effect) on real PostgreSQL.
- durable lifecycle journal, generation ledger and stable executor epoch.
- real faults: adapter SIGKILL+restart, DSH child SIGKILL, Gateway restart,
  explicit executor takeover.

Scripted and explicitly **not** real-LLM-quality: a keyless deterministic
loopback provider. `llm.class=scripted-keyless`, `llm.real_llm_quality=false`.

**Harness defect found and fixed during review:** the first v2 attempt reused
`beyondquant-backend:latest` (built 2026-09-05), whose `create_pool` had no
idempotency, so replaying the pool idempotency key created duplicate pools.
Rebuilding Backend (and Gateway/MCP) from this branch restored real idempotent
receipts; `observations.v2.json` is the post-fix run.

## Per-row results (real observations, v2)

| fault row | continuity | pid | generation | epoch |
| --- | --- | --- | --- | --- |
| adapter-process-restart | reattached -> rehydrated | 3279144 -> 3280473 | 1 -> 2 | 1 -> 1 |
| gateway-disconnect-reconnect | reattached -> reattached | 3280473 -> 3280473 | 2 -> 2 | 1 -> 1 |
| generation-replacement | reattached -> interrupted | 3280473 -> 3280473 | 2 -> 3 | 1 -> 1 |
| dsh-process-interruption | reattached -> rehydrated | 3280473 -> 3280473 | 3 -> 4 | 1 -> 1 |
| executor-takeover | reattached -> reattached | 3280473 -> 3280473 | 4 -> 4 | 1 -> 2 |
| host-reboot (OPTIONAL) | `NOT_RUN` | - | - | - |

Verified relationships: adapter restart changes PID; generation replacement and
DSH interruption increment the generation index with a new generation id;
executor takeover increments the monotonic epoch; Gateway reconnect keeps
identity/generation; the goal prompt receipt links to the result run id; the
pool and approval replay receipts equal their originals (one side effect); the
WorkflowTrace sequence is contiguous.

## Explicitly uncovered / not executed

- **host-reboot**: OPTIONAL, `NOT_RUN` (host reboot not authorized; a container
  restart is not a host reboot).
- **Real-LLM semantics**: not measured (scripted provider).
- **Model tool-call-driven domain actions**: domain goal/approval/action were
  driven through the real Product/Backend stack, not by a model tool call.
- **D15-4/D15-5/D15-G**: not in this batch. **R3**: frozen, `R3_RESUME=NO`.

## Fail-able observer

`contract.v2.json` (authoritative required/optional scenarios, invariants,
relationships, fail-closed list) + `observer.py`. Negative controls:
`negative-controls.v2.json` (27 controls, `all_controls_pass=true`,
`defect_targeting_pre_fix_passed=true`). For the five defect-targeting controls
the reconstructed legacy algorithm returns `all_pass=true` while the fixed
verdict returns `all_pass=false`/exit 1:

- `all-required-not-run` (legacy True -> fixed False, format still valid)
- `single-required-blocked`
- `reasoned-not-executed`
- `observation-relaxes-allowed-continuity`
- `observation-clears-forbidden-continuity`

The synthetic `valid_fixture` is `evidence_class=unit-fixture` and is rejected
by the runtime verdict (`required_evidence_class=runtime-isolated-stack`); it
only exercises the observer's unit/negative tests.

## Isolation, cleanup, reproduce

`stack.v2.json`: preflight (6 containers, loopback-only ports, candidate pinned,
all image digests) and cleanup (`containers_remaining=0`, `networks_remaining=0`,
`volumes_remaining=0`). Production/Community untouched.

```bash
python3 scripts/d15/runtime_continuity/run_qualification.py            # up -> scenarios -> cleanup
python3 scripts/d15/runtime_continuity/observer.py --selfcheck \
    --out docs/evidence/d15/d15-runtime/negative-controls.v2.json      # must exit 0
python3 scripts/d15/runtime_continuity/observer.py \
    --observations docs/evidence/d15/d15-runtime/observations.v2.json \
    --out docs/evidence/d15/d15-runtime/verdict.v2.json                # must exit 0
```

v1 evidence (`observations.v1.json`, `verdict.v1.json`,
`negative-controls.v1.json`, `stack.v1.json`, `scenarios/*.v1.json`) is retained
unchanged.
