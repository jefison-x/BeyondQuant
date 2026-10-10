# Dedicated research-judgment ACP entry (0097/0098) — wiring audit (2026-10-08)

Audit only. Draft B is the implementation/qualification plan for the **Accepted** ADR-0097/0098; no new ADR
acceptance is required. `/acp-root/run` returning 503 is NOT completion.

## Current state
- `docs/architecture/adr/ADR-0097-product-acp-judgment-process-scope.md` — **Accepted** (2026-10-04).
- `docs/architecture/adr/ADR-0098-acp-judgment-pre-result-terminal-settlement.md` — **Accepted** (2026-10-05).
- **Correction (2026-10-08): the entry is NOT a stub.** `research_judgment_entry.py`
  (`run_acp_judgment_root` / `recover_acp_judgment_root`) is committed and calls the
  full committed lifecycle in `research_judgment_acp_turn.py`. The route
  `POST /internal/runtime/research-judgment/{task}/acp-root/run` returns
  **503 `research_judgment_acp_lifecycle_unqualified`** only because
  `judgment_acp_lifecycle_enabled` is **default-disabled** (opt-in via
  `BYQ_JUDGMENT_ACP_LIFECYCLE_ENABLED == "1"`). Three states must be distinguished:
  (1) **default disabled** (503 gate), (2) **isolation flag on** (the isolated
  `byq-acpf6` stack sets it to `1`), and (3) **full qualification** (combined
  MCP->Backend admission, exact terminal ACK readback, late/unknown/cancel
  settlement, restart recovery, two-user isolation, independent Tester/Reviewer).
  Do **not** promote the flag to production merely to remove the 503.
- One proven entry defect was fixed (2026-10-08): the entry hardcoded
  `DEEPSEEK_API_KEY` while the stack runs `opencode-go-chat` (ADR-0105); it now
  resolves the credential by the exact provider route
  (`judgment_provider_resolution`). No ADR decision changed.

## Reliable implementable scope (Draft B = plan, already Accepted)
Wire `/acp-root/run` to the already-built lifecycle, keeping the dedicated socket/secret/tools isolated:
1. Trusted entry consumes the Backend `begin` receipt once (`created:true`); preserves the private prompt
   journal across container replacement; a lost first response stays unknown (no replay).
2. Dedicated root create + native register (fixed read-only AgentRun, stage-scoped ingress).
3. Five read-only tool calls through the isolated judgment MCP with the per-root derived key bound to the
   **live** proxy and the frozen stage budget.
4. Result + close + exact Backend terminal ACK; settlement for success / never-dispatched-fail / user-cancel /
   dispatched-unknown; no automatic replay.

## Necessary qualification gates
`/acp-root/run` stays 503 until: combined MCP→real-Backend admission, exact terminal ACK readback,
late/unknown/cancel settlement, adapter restart recovery, two-user isolation, and an independent
Tester/Reviewer pass. No default promotion, no version change.

## Boundary
- Any change to an Accepted ADR-0097/0098 decision (dedicated role set, stage budget values, child-veto
  semantics) must be split out as its own ADR revision and paused until Accepted — not silently changed.
- No second harness, no generic supervisor; the ADR-0097 slices are PASS-bounded but the integrated entry
  is not qualified.
