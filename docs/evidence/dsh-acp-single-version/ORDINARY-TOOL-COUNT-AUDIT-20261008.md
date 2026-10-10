# Ordinary tool-call count (16) protection — capability audit + count-only wiring (2026-10-08)

No second harness, no generic supervisor. The provider HTTP budget is NOT a tool count.

> **Image identity caveat.** The wiring is source-level in this worktree; no candidate image has been built
> with it yet. Unit tests ran against the changed source; the running containers were hot-patched for
> targeted tests only. The original digests do not cover this.

## Existing capability (reused)
- `plugins/dsh-byq/runtime/byq-continuation-budget.js` (`inject = ['tools', 'agents']`) fences DSH tool
  dispatch at the `tools/pre-execute` hook: it counts admitted calls, blocks at
  `calls >= PROFILE_LIMITS.max_tool_calls` (16), and appends a durable journal row before dispatch.
- `services/runtime-adapter/app/continuation_budget.py::read_request_guard` reads that fsynced journal and
  returns `{tool_calls, blocked_reason, status}`; `runtime.py` uses `tool_receipt['tool_calls']` in
  `gate.request_usage(...)` / `exceeded_request_limits(...)`.

## Wiring implemented (source-level; continuing ADR-0106 authorization)
- **Plugin count-only mode**: an explicit `guardMode: "count-only"` selects a separate closed validator that
  requires the exact `product-turn.v1` identity (`profile_id`/`profile_version`/`profile_sha256`) and the
  exact `PRODUCT_TURN_LIMITS`; it refuses a `reservationId` (no downgrade from the strict continuation mode,
  and a missing `reservationId` without `guardMode` still fails the strict validator). It counts **every**
  tool (no allowlist), blocks the seventeenth, and writes `product-turn-tool-guard.v1` rows without a
  continuation identity.
- `create_acp_product_budget_overlay` now emits a **2-element** overlay: the single closed Go chat route plus
  the count-only guard insert (`guardMode`, `deadlineEpochMs`, `executionProfile`, `requestLimits`); the
  Adapter injects `journalPath`.
- `_write_continuation_guard` (Adapter) and `_validate_guard` (product runner) accept the 2-element ordinary
  overlay and inject/require the journal path. The Adapter validates the exact route + the count-only identity
  (and injects the journal path); the runner additionally enforces the exact `product-turn.v1` identity and
  the exact `PRODUCT_TURN_LIMITS`; the plugin independently validates both before dispatch.

## Verification (targeted; no full suite)
- Plugin: `node --test runtime/byq-continuation-budget.test.js` -> **11 passed** (incl. count-only counts
  generic tools and blocks the seventeenth; missing reservation without `guardMode` stays strict; a
  `reservationId`/widened limit/foreign profile on count-only is refused).
- Runtime-adapter: `test_product_turn_budget.py` + `test_acp_product_slot_runtime.py` -> **18 passed**
  (overlay is 2-element; the Adapter accepts it and injects the journal path).
- Product runner: `test_server.py -k validate_guard` -> **2 passed** (ordinary 2-element overlay accepted;
  a reservation/widened limit/foreign profile refused). The other runner cases need the container security
  context (e.g. `no_new_privs`) and are host-environment failures.
- `test_f6_synthetic_runtime_contract.py`: **37 passed / 10 failed / 55 skipped** — identical to the
  **baseline** (the 10 failures need a Backend instruction source mount), so no regression.

## Coverage boundary (honest)
- **Proven (unit)**: count-only counts every tool (generic included) and blocks the seventeenth; the
  identity/limits are explicit and the strict continuation mode is preserved.
- **NOT_RUN**: whether the `tools/pre-execute` root-composition listener actually observes **child-Agent**
  and **generic** tool dispatch in a live ordinary ACP process — this needs a real ordinary turn that
  dispatches tools. The provider proxy proves only the model HTTP budget. Tool-call count 16 stays **NOT_RUN**
  as real acceptance until that turn is qualified.
