# D15 real isolated BYQ runtime-continuity qualification

- Status: **v4 service-boundary qualification PASS (scripted keyless provider);
  NOT a real-LLM-quality pass and NOT a full original-task qualification.**
- Date: 2026-09-20 (v4 scope/approval/Agent-MCP revision)
- Candidate: coherent `dsh-0.1.5rc1` / Python SDK `0.1.5rc1` / bundled runtime `0.1.5rc1`
- Build revision: `post-u8.163` (rebuild identity only; no selector/deployment change)
- Scope: runtime continuity only. D15-4, D15-5, D15-G and R3 are **not** in this
  batch and no full-D15 completion is claimed.

## Limited vs full — read this first

| evidence set | what it proves | what it does NOT prove |
| --- | --- | --- |
| v1 | early service-boundary observation | capture hardcoded approval, fabricated missing receipts, `sequence>0` continuity |
| v2 | observer/coverage fixes | same capture-layer defects |
| v3 | capture-layer fixes (no success defaults, persisted approval, real trace attribution) | **no real Agent→MCP→Domain action**; approval denial inferred from any error; no protected-operation attempt |
| **v4** | **the required business at the service boundary**: process recovery, goal preservation, real Agent→MCP→Domain at-most-once, authoritative approval denial via a protected operation, traceable result | **real-LLM-quality semantics** (provider is scripted/keyless); host reboot; D15-4/D15-5/D15-G; production cutover |

Only **v4** is the qualification evidence. v1/v2/v3 are retained history and are
**not** qualification passes. Even v4 is a **limited service-boundary pass with a
scripted provider** — it is not a full original-task (real-model) qualification.

## v4 additions

1. **Real Agent→MCP→Domain at-most-once across a fault.** The scripted provider
   emits a real tool call `mcp__byq__byq_research_task_create`; the real MCP
   server executes it against the real isolated Backend, creating
   `task_07fd57ffe5c247edbe7821bb87fd741c`. The adapter is then SIGKILLed and
   restarted; the same tool call/idempotency key is re-delivered and returns the
   **same task id** with a measured side-effect count of 1. Recorded:
   provider tool name/count, the call, the domain receipt, the run id, the full
   WorkflowTrace, and the fault timing (pid `3414070 -> 3418327`, generation
   `1 -> 2`, continuity `fresh -> rehydrated`). A dedicated required scenario
   `agent-mcp-domain-at-most-once` gates the verdict.
2. **Authoritative approval denial.** `derive_approval` no longer infers denial
   from an arbitrary error. It records the HTTP status and domain error code and
   actually attempts the protected operation (a backtest requiring an authorized
   strategy approval) with the REJECTED approval, measuring the authoritative
   backtest-job count before/after:
   - invalid reuse: HTTP `409`, `product_domain_rejected`;
   - protected operation: HTTP `422`, `product_domain_rejected`
     ("strategy version is not approved for execution"), backtest count `0 -> 0`;
   - reject decision: persisted `rejected`, `execution_authorized=false`.
   A 5xx/timeout is **not** a denial, and a rejection with an increased
   side-effect count fails the verdict (capture-layer negatives below).

## What is real vs scripted

Real, isolated stack (compose project `byq-d15-runtime`, dedicated network/
volumes, fresh PostgreSQL, loopback-only ports) with Backend/Gateway/MCP rebuilt
from this branch (`stack.v4.json` records every image digest). Scripted and
explicitly **not** real-LLM-quality: the keyless deterministic provider
(`llm.real_llm_quality=false`).

## Per-row results (v4)

| fault row | continuity | pid | generation | epoch |
| --- | --- | --- | --- | --- |
| adapter-process-restart | reattached -> rehydrated | 3412601 -> 3414070 | 1 -> 2 | 1 -> 1 |
| gateway-disconnect-reconnect | reattached -> reattached | 3414070 -> 3414070 | 2 -> 2 | 1 -> 1 |
| generation-replacement | reattached -> interrupted | 3414070 -> 3414070 | 2 -> 3 | 1 -> 1 |
| dsh-process-interruption | reattached -> rehydrated | 3414070 -> 3414070 | 3 -> 4 | 1 -> 1 |
| agent-mcp-domain-at-most-once | fresh -> rehydrated | 3414070 -> 3418327 | 1 -> 2 | 1 -> 1 |
| executor-takeover | rehydrated -> reattached | 3418327 -> 3418327 | 4 -> 4 | 1 -> 2 |
| host-reboot (OPTIONAL) | `NOT_RUN` | - | - | - |

(PIDs vary per run; see `observations.v4.json`.)

## Explicitly uncovered / not executed

- **Real-LLM semantics**: not measured (scripted provider). This is the main
  reason v4 is a limited service-boundary pass, not a full qualification.
- **host-reboot**: OPTIONAL, `NOT_RUN` (not authorized; container restart != host reboot).
- **D15-4/D15-5/D15-G**: not in this batch. **R3**: frozen, `R3_RESUME=NO`.

## Fail-able observer and capture negatives

- `observer.py --selfcheck` -> `negative-controls.v4.json` (39 controls,
  `all_controls_pass=true`, `defect_targeting_pre_fix_passed=true`).
- `capture_negatives.py` -> `capture-negatives.v4.json` (7 cases, each legacy
  `all_pass=true` -> fixed `all_pass=false`): deleted-journal-receipt,
  replay-error, approval-expiry-bypass, **denial-from-500-timeout**,
  **rejected-response-but-side-effect-exists**, trace-gap,
  only-old-assistant-result.

## Isolation, cleanup, reproduce

`stack.v4.json`: preflight (6 containers, loopback-only ports, candidate pinned,
image digests) and cleanup (`containers_remaining=0`, `networks_remaining=0`,
`volumes_remaining=0`). Production/Community untouched.

```bash
python3 scripts/d15/runtime_continuity/run_qualification.py            # up -> scenarios -> cleanup
python3 scripts/d15/runtime_continuity/observer.py --selfcheck \
    --out docs/evidence/d15/d15-runtime/negative-controls.v4.json      # must exit 0
python3 scripts/d15/runtime_continuity/capture_negatives.py \
    --out docs/evidence/d15/d15-runtime/capture-negatives.v4.json      # must exit 0
python3 scripts/d15/runtime_continuity/observer.py \
    --observations docs/evidence/d15/d15-runtime/observations.v4.json \
    --out docs/evidence/d15/d15-runtime/verdict.v4.json                # must exit 0
```

v1/v2/v3 evidence is retained unchanged and is **not** a qualification pass.
