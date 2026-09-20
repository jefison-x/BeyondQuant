# D15 real isolated BYQ runtime-continuity qualification

- Status: **PASS (scripted keyless provider; service-boundary runtime continuity)**
- Date: 2026-09-20 (v3 capture-layer review-fix revision)
- Candidate: coherent `dsh-0.1.5rc1` / Python SDK `0.1.5rc1` / bundled runtime `0.1.5rc1`
- Build revision: `post-u8.162` (rebuild identity only; no selector/deployment change)
- Scope: runtime continuity only. D15-4, D15-5, D15-G and R3 are **not** in this
  batch and no full-D15 completion is claimed.

## v1 / v2 are NOT qualification passes

The v1 and v2 artifacts are retained for history only. Their `all_pass` values
must **not** be read as a qualification pass: the v2 `capture()` hardcoded the
approval fields, fabricated a goal receipt / replay run id when evidence was
missing, and computed `trace_contiguous` from `sequence > 0` without target-run
attribution. The v3 revision fixes those capture-layer defects; only
`observations.v3.json` + `verdict.v3.json` are the qualification evidence.

## v3 capture-layer fixes

1. **No success defaults.** `capture_ok` / `capture_errors` are recorded; a
   missing durable journal receipt, a replay request error, or a replay run id
   that is not the durable target run produces an explicit error and a scenario
   `FAIL`. Nothing is fabricated and the replay never falls back to the original
   run id.
2. **Approval evidence is persisted, with real deny trials.** `state` and
   `decided_by` come from the persisted approval response; a persisted REJECT
   decision is created on a distinct strategy version and an invalid reuse of the
   approved idempotency key is attempted. Both are recorded as deny trials with
   `side_effect_created=false`. `bypassed` is derived (any trial side effect =>
   bypass), never hardcoded.
3. **Real continuity/attribution/completion.** `trace_contiguous` is computed
   from the full persisted WorkflowTrace sequence (must start at 1, no gaps);
   completion and the assistant answer are attributed to the **target run**
   (`target_run_id`, `terminal_kind`, `attributed_message_sequence`), not to any
   historical assistant message.
4. **Measured side-effect counts.** `make_receipt` has no default: the count is
   measured from the authoritative result (owner-scoped pool rows by unique name;
   persisted strategy-approval artifacts for the version) and each receipt
   carries an explicit `origin`.
5. **Manual vs Agent execution labeled.** `execution_model.action_origin =
   "product-api-manual"`, `agent_mcp_tool_calls = 0`. The domain goal/approval/
   side-effect are **manual Product API actions**, not Agent→MCP tool calls, and
   no "Agent at-most-once across faults" claim is made.

## What is real vs scripted

Real, isolated stack (compose project `byq-d15-runtime`, dedicated network/
volumes, fresh PostgreSQL, loopback-only ports) with Backend/Gateway/MCP rebuilt
from this branch (`stack.v3.json` records every image digest): the runtime-adapter
fixed `dsh-0.1.5rc1` candidate, durable lifecycle journal / generation ledger /
executor epoch, real Product API persistence, real process faults (adapter
SIGKILL+restart, DSH child SIGKILL, Gateway restart, executor takeover).

Scripted and explicitly **not** real-LLM-quality: a keyless deterministic
loopback provider (`llm.real_llm_quality=false`).

## Per-row results (v3)

| fault row | continuity | pid | generation | epoch |
| --- | --- | --- | --- | --- |
| adapter-process-restart | reattached -> rehydrated | 3314419 -> 3315908 | 1 -> 2 | 1 -> 1 |
| gateway-disconnect-reconnect | reattached -> reattached | 3315908 -> 3315908 | 2 -> 2 | 1 -> 1 |
| generation-replacement | reattached -> interrupted | 3315908 -> 3315908 | 2 -> 3 | 1 -> 1 |
| dsh-process-interruption | reattached -> rehydrated | 3315908 -> 3315908 | 3 -> 4 | 1 -> 1 |
| executor-takeover | reattached -> reattached | 3315908 -> 3315908 | 4 -> 4 | 1 -> 2 |
| host-reboot (OPTIONAL) | `NOT_RUN` | - | - | - |

Every row: goal prompt receipt linked to the target run, result attributed to the
target run with `terminal_kind=session.result` and a contiguous full trace,
measured side-effect counts of 1, approval deny trials denied with no side effect.

## Explicitly uncovered / not executed

- **host-reboot**: OPTIONAL, `NOT_RUN` (not authorized; container restart != host reboot).
- **Real-LLM semantics**: not measured.
- **Agent→MCP tool-call execution**: not exercised (manual Product actions only).
- **D15-4/D15-5/D15-G**: not in this batch. **R3**: frozen, `R3_RESUME=NO`.

## Fail-able observer and capture negatives

- `observer.py --selfcheck` -> `negative-controls.v3.json` (35 controls,
  `all_controls_pass=true`, `defect_targeting_pre_fix_passed=true`).
- `capture_negatives.py` -> `capture-negatives.v3.json` (5 capture-layer cases:
  deleted-journal-receipt, replay-error, approval-expiry-bypass, trace-gap,
  only-old-assistant-result). Each shows the reconstructed legacy algorithm
  passing the pre-fix (masked) observation and the fixed verdict failing the
  post-fix observation.

## Isolation, cleanup, reproduce

`stack.v3.json`: preflight (6 containers, loopback-only ports, candidate pinned,
image digests) and cleanup (`containers_remaining=0`, `networks_remaining=0`,
`volumes_remaining=0`). Production/Community untouched.

```bash
python3 scripts/d15/runtime_continuity/run_qualification.py            # up -> scenarios -> cleanup
python3 scripts/d15/runtime_continuity/observer.py --selfcheck \
    --out docs/evidence/d15/d15-runtime/negative-controls.v3.json      # must exit 0
python3 scripts/d15/runtime_continuity/capture_negatives.py \
    --out docs/evidence/d15/d15-runtime/capture-negatives.v3.json      # must exit 0
python3 scripts/d15/runtime_continuity/observer.py \
    --observations docs/evidence/d15/d15-runtime/observations.v3.json \
    --out docs/evidence/d15/d15-runtime/verdict.v3.json                # must exit 0
```

v1/v2 evidence (`observations.v{1,2}.json`, `verdict.v{1,2}.json`,
`negative-controls.v{1,2}.json`, `stack.v{1,2}.json`, `scenarios/*.v{1,2}.json`)
is retained unchanged and is **not** a qualification pass.
