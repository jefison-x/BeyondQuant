# Public session end-state projection (2026-10-08)

> 2026-10-09 correction: the event-only `session.closed` public-end rule below was found incorrect during real browser qualification. Accepted ADR-0093/0096 distinguish runtime teardown from BYQ conversation end. Active/archived conversations must not be ended by Adapter release/shutdown events, and unowned hard-cancel events must not be exposed as terminal. Preserve this original evidence as historical; it does not qualify next-turn availability. See [current contract repair](public-release-contract-20261009/RESULT.md).

Minimal, routine bugfix: the public session status now reflects a normalized hard end. No schema/enum
change, no durable catalog change, no second lifecycle. No push/merge/deploy/tag.

> **Image identity caveat (2026-10-08, corrected later the same day).** At the original
> verification the running Gateway loaded this change via `docker cp` into the isolated
> `byq-acpf6` container as a **hot-patch**; the digest at that time did not contain the change.
> **Correction:** the candidate Gateway image was subsequently built and recorded as
> `sha256:839e964aeea56ce5b1b50e8b36ed4c33e75a2789cd14e38d45cdcf5008059e08` (see
> `ORDINARY-COUNT-ONLY-CANDIDATE-20261008.md`), which bakes this change in; the source hash is
> `services/gateway/app/main.py` `d2c467c681d9b8d48e1d6d2b5afbddbada4899246b7977f62f4fa53a5167f11f`.
> The original hot-patch observation above is preserved as historical evidence and is not
> overwritten.

## Contract basis recorded on 2026-10-08 (corrected above)
- `ARCHITECTURE.md` K.1 invariant 3: "Terminal lifetime MUST NOT define conversation or durable-job
  lifetime." The durable `conversation_catalog.status` is `active|archived` (organizational/archive), not
  a runtime lifecycle. ADR-0079/0083/0085 are **historical-only, superseded** by the Clean Break baseline
  (ADR-0088 + Clean Break ADRs 001-006); they are NOT the current terminal-API basis.
- The frontend list filter is the durable archive filter (`"active" | "archived"`, `AgentView.vue:31`);
  the terminal is derived from events (`session.closed` / `session.cancelled mode hard`, `AgentView.vue:128`).
  `AgentSession.status` is a free `string` (`api/types.ts:47`).

## Change (Gateway only)
- `services/gateway/app/main.py`: new `_conversation_hard_terminal(events, runtime_session_id, trace_id)`
  reuses `session_containment._owned` ownership rules — exact `runtime_session_id` + `trace_id` and a
  normalized `runtime-adapter`/`byq-domain` source only; a missing identifier, a raw DSH event or a raw
  model event is never a source. Only `session.closed` or `session.cancelled` with `mode == "hard"` end the
  public status; a normal `session.result` or a soft cancel does not. The `session.cancelled` payload is
  validated as a dict before reading `mode` (`session.closed` never inspects the payload).
- `_public_conversation_status(...)` gains an optional `hard_terminal` that takes precedence over the
  still-matching live binding, while `stored != active` (archived) keeps its existing priority.
- The GET uses the **raw** trace events (before the public `session_id` re-marking) and reuses them for the
  containment projection; the list reads the owned events per active row.

## Targeted tests
- `services/gateway/tests/test_product_agent.py`:
  `test_hard_end_event_overrides_active_binding_but_normal_result_does_not` (result + soft cancel stay
  `active`; `session.closed` -> `closed`; hard cancel -> `cancelled`) and
  `test_hard_terminal_helper_rejects_untrusted_and_missing_identity` (raw `model` source, non-dict payload,
  missing trace identity are not evidence).
- `services/gateway/tests/test_product_agent.py` + `test_session_containment.py` -> **78 passed**.

## Free real Gateway/browser verification (no model call)
- `browser_status_projection.mjs` (real login `acpchain-user`, Gateway-only fetch) on
  `conversation_abc35cf6c59d48999c514dbc86cf6b60`:
  - GET `/v1/agent/sessions/{id}` -> HTTP 200, `conversation.status = "cancelled"`,
    `containment.status = "cancelled"` (was `active`).
  - GET `/v1/agent/sessions?status=active` -> HTTP 200, `total = 37`; the session is listed (not archived)
    with `listed_status = "cancelled"` — the durable archive filter semantics are preserved.
  - The ended banner still renders. Result: `browser-observe/status-projection.json` (the raw browser
    artifact + script live under `/tmp/opencode/`, not in the worktree).
- This is a Gateway-only read; no provider call and no raw DSH/model event is trusted.
- `total` counts durable-archive-filter rows while each row's derived status may be `cancelled`/`closed`;
  this is intentional (the filter is the durable archive status, the row status is the runtime projection).
  The list reads the owned events once per active row (bounded by `limit` ≤ 100).

## Preserved
- Old Gateway image not rebuilt; failure evidence (#1-#9, ADR-0106 failures A/B/C) unchanged.
