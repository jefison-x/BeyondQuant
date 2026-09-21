# ADR-0083: BYQ TerminalAttachment persistence, reconnect and fencing boundary

- Status: Accepted
- Date: 2026-09-20
- Accepted: 2026-09-21 (maintainer decision; **as currently proposed**; **NOT implemented**)
- Decision record: `docs/evidence/v090-adr-decisions/README.md` / `decision-record.v1.json`
  (0.9 strict-order step 4 maintainer decision; no GitHub approval is claimed)
- Relates: ADR-0081, ADR-0079, ADR-0003, ADR-0023, ADR-0059
- Stage: D15-5 follow-up
- Evidence: `docs/evidence/d15/d15-5/`

## Context

D15-5 qualified the candidate DSH 0.1.5-rc.1 persistent terminal in isolation
(`docs/evidence/d15/d15-5/`). The real native stack
(`@deepseek-ai/dsh-terminal` owner-scoped `TerminalSessionService` +
`@deepseek-ai/dsh-terminal-bash` `shell` backend) was driven from separate client
OS processes. Real observations show:

- four client-side faults PASS without any DSH restart: page refresh, browser
  disconnect, frontend restart and gateway restart all rebind the **same**
  attachment and the **same** PTY (same attachment id / session id / pid) with no
  replay and no loss, permissions cannot be bypassed (`FOREIGN_SESSION`,
  `UNAUTHORIZED_PRINCIPAL`), a wrong terminal is rejected (`NO_SESSION`), a stale
  generation/epoch is fenced, and cleanup leaves no orphans;
- the native package documents sessions as **process-local** ("do not survive a
  harness restart");
- an adapter abort or a DSH runtime restart destroys the attachment; the old PTY
  dies with the runtime (`bwrap --die-with-parent`), and a fresh runtime rejects
  the old attachment. There is **no committed BYQ surface** that rehydrates or
  rebinds a terminal attachment: `interface-probe.v1.json` shows the BYQ
  composition does not compose `@deepseek-ai/dsh-terminal` or a persistent
  terminal tool, the runtime-adapter has no PTY/attachment route (its only
  `terminal` route is AgentRun terminal-state evidence), and the 0.1.5 compat
  boundary still inherits the 0.1.2 observation contract.

ADR-0081 §5 redefines **R4 TerminalAttachment** as *attachment lifecycle, not a
terminal runtime*: BYQ owns attachment identity, state, authorization and
reconnect; DSH owns PTY/shell/I/O. Persisting and exposing that lifecycle —
especially across an adapter/DSH restart and across multiple BYQ services — is a
**real architecture boundary change**. It touches the BYQ↔DSH boundary, the
Product API surface, authorization and executor-epoch fencing. D15-5 does not
implement it.

## Decision (accepted by the maintainer on 2026-09-21, as currently proposed — NOT implemented)

The maintainer accepts this ADR **as currently proposed**. If BYQ is to own a
persistent terminal attachment, the boundary is fixed as follows:

1. **BYQ owns a durable `TerminalAttachment` record** with a BYQ-minted
   `attachment_id` (never a DSH session id or pid), owner principal, runtime
   generation and executor epoch. It is stored and authorized by BYQ services,
   not by DSH and not by a second session store.
2. **The runtime-adapter exposes a bounded, authenticated attachment surface**
   (create/attach/read/signal/kill/reconnect) translated to the native
   owner-scoped `ctx.terminals` seam. The browser reaches it only through
   Gateway/Product API; no raw DSH event or PTY handle is projected.
3. **Reconnect is fenced** by generation + executor epoch, fails closed on a
   stale/mismatched token, and **never fabricates a reattach**. When native
   process-local state is gone, the status is `lost`/`interrupted`, not
   `reattached`.
4. **Cleanup is BYQ-observable**: attachment close and orphan detection are
   recorded; a surviving PTY with no attachment is `lost`, never silently reused.
5. **DSH continues to own PTY/shell/I/O.** BYQ MUST NOT implement a PTY runtime,
   a shell, or terminal I/O; it adapts, observes, authorizes and fails down.

**This ADR does not promise terminal continuity across a runtime restart.** The
native DSH terminal is process-local, so a runtime/DSH restart genuinely destroys
the PTY. The honest contract is **"reconnect where native state survives; otherwise
truthful `lost`/`interrupted`"** — never a fabricated `reattached`.

Accepting this ADR authorizes only a **candidate-specific, reversible** production
wiring of the BYQ attachment layer for D15-G qualification. It does **not** switch
the production selector/default, does **not** authorize a production cutover, and
does **not** authorize a second session store. The framework-neutral vocabulary
already exists in `packages/contracts/terminal_attachment.py`
(`attached`/`reattached`/`rehydrated`/`lost`/`interrupted`/`fenced`, the four
existence dimensions, and the BYQ/DSH ownership split). The production wiring that
D15-5 deliberately left unimplemented remains **NOT implemented** by this decision.

## Consequences (accepted)

- New BYQ state (attachment records) and a new Product/Gateway surface with
  authorization and audit implications; a candidate-specific, reversible
  implementation is possible but the surface/result shape is not transparent to
  callers.
- Native sessions remain process-local, so a restart genuinely loses a running
  shell unless DSH later provides a durable backend. The honest contract is
  therefore "reconnect where native state survives; otherwise truthful
  `lost`/`interrupted`", never a fabricated reattach.
- Terminal lifetime still never defines conversation or durable-job lifetime.
- Acceptance does **not** implement anything: D15-5 stays **PARTIAL/BLOCKED**,
  `R3_RESUME = NO`, and the production selector/default `dsh-0.1.2rc1` is
  unchanged. The candidate-specific attachment layer required by D15-G is a
  pre-gate D15-5 qualification slice, not a production default switch.

## Alternatives considered

- **Build a BYQ PTY runtime / persist raw PTY state.** Rejected: duplicates a
  generic DSH capability and violates "do not build a second harness" and
  ADR-0081 §3 (native capabilities first; BYQ adapts/observes/fails down).
- **Let the browser hold the attachment directly.** Rejected: violates the
  Gateway/Product-API-only browser boundary and BYQ-owned authorization.
- **Do nothing.** Acceptable as "no persistent terminal product capability"; the
  terminal remains unavailable rather than falsely reattached.

## Migration / rollback

- Implemented only after acceptance, candidate-specific and reversible; no
  database schema change without a separate named decision; production default
  and selector unchanged until D15-G and a separate cutover decision.
- On native state loss, roll back to truthful `lost`/`interrupted`; rollback of
  the surface is to stop exposing it and drop the candidate wiring; no historical
  evidence or immutable release registry is modified.
