# ADR-0082 / ADR-0083 sufficiency review and maintainer decision package

Status: **review only.** Both ADRs remain **Proposed (DRAFT for review — NOT accepted,
NOT implemented)**. This document does **not** accept, modify or implement them, and
does **not** impersonate a maintainer decision.

Reviewed:
[ADR-0082](../../architecture/adr/ADR-0082-dsh-continuable-child-resume.md) and
[ADR-0083](../../architecture/adr/ADR-0083-terminal-attachment-boundary.md).

Machine-readable form: [acceptance-matrix.v1.json](acceptance-matrix.v1.json)
`adr_sufficiency`.

## Verdict: neither is sufficient to resolve its blockers as written

### ADR-0082 — sufficient? **No**

What it gets right: it is an honest decision gate; it records that rebinding a
continuable child across a BYQ adapter restart is a real architecture boundary change; it
keeps the production foreground path untouched; and it forbids a second session store.

Gaps:

1. **It is a gate, not a resolution.** It lists two options and explicitly states that
   until one is accepted D15-4 stays `BLOCKED`. Acceptance alone does not produce the
   evidence D15-G needs.
2. **`child-crash` is not solvable by option 2.** ADR-0082 itself states "option 1 is
   required for that item". The 0.1.5-rc.1 candidate ships **no** out-of-process
   continuable provider (`routing.v1.json`), so this blocker is upstream-bound unless BYQ
   qualifies an independent-process child by another route.
3. **Option 2 needs an enforceable contract, not just a list.** The ADR names exactly-once
   settlement, original-goal linkage, orphan cleanup and an epoch fence, but does not
   define: tenant/workspace scoping; the authorization model; the idempotency/at-most-once
   settlement contract; the epoch/generation fencing token; crash/orphan reconciliation;
   rollback; or a testable acceptance matrix. Without these, "must not become a second
   session store" is not enforceable.
4. **No qualification path stated.** It does not say whether acceptance authorizes a
   candidate-specific, reversible implementation sufficient to re-run D15-G before R3.

### ADR-0083 — sufficient? **No**

What it gets right: BYQ owns attachment identity/state/authorization/reconnect, DSH owns
PTY/shell/I/O; reconnect is generation+epoch fenced and fails closed; `lost`/`interrupted`
is preferred over fabricated reattach; BYQ must not build a PTY runtime.

Gaps:

1. **It defers the exact thing the blockers need.** Durable attachment persistence is
   deferred to "a separate named decision", yet `terminal-adapter-restart` /
   `terminal-dsh-runtime-restart` require that persistence to be qualified.
2. **No authorization matrix.** Foreign-session and unauthorized-principal denial are
   observed in D15-5 but not defined as contract: who may create/attach/read/signal/kill;
   how ownership and tenancy are enforced; how revoked authority fails closed.
3. **No at-most-once / fencing specifics.** Unique attachment creation and idempotent
   attach are unstated; the fencing-token format and stale-token behavior are unstated.
4. **No cleanup / GC / rollback / migration.** Orphan reconciliation and the rollback of
   the new attachment state are not defined.
5. **Unresolved sequence tension.** Terminal blockers gate D15-G before R3, but
   productization is R4 after R3.

## Required ADR revisions (for the maintainer to direct)

### ADR-0082

- State which option is chosen, its feasibility owner and its timeline; if option 1 is
  required for `child-crash`, state plainly that the blocker cannot close until a
  qualifying out-of-process continuable provider exists.
- For option 2, add: tenant/workspace scoping; authorization matrix; at-most-once
  settlement contract; epoch/generation fencing token; crash/orphan reconciliation;
  rollback; acceptance criteria.
- State that acceptance authorizes only a candidate-specific, reversible qualification
  path to re-run D15-G — not a production default switch.

### ADR-0083

- Name the persistence-store decision, or explicitly authorize a candidate-specific
  evidence-only store for D15-G, without creating a second session store.
- Add: tenant/workspace authorization matrix; idempotent unique attach; epoch/generation
  fencing-token semantics; orphan GC; rollback/migration.
- Define the candidate-specific evidence path that lets D15-G pass
  `terminal-adapter-restart` / `terminal-dsh-runtime-restart` before R4 productization.

## Boundary checklist both ADRs must make explicit

| Boundary | 0082 (child) | 0083 (terminal) | Must be defined |
|---|---|---|---|
| Safety | no second store, no fork/patch | no PTY runtime, fail-closed | enforceable invariant + observer |
| Permission / authorization | child rebind authority | attachment create/attach/kill authority | principal + role matrix |
| Tenant / workspace | child owner/workspace | attachment owner/workspace | cross-owner denial |
| Epoch / generation fencing | stale writer cannot duplicate | stale/cross-generation token fenced | token format + fail-closed |
| At-most-once | single settlement | single unique attach / idempotent create | contract + measured count |
| Cleanup | orphan child/session GC | orphan PTY GC / lost reconciliation | crash reconciliation |
| Rollback | revert candidate wiring | drop surface / drop candidate wiring | no second store, no DB change without named decision |

## Maintainer decision package (no decision is taken here)

| # | Decision | Options | Recommendation |
|---|---|---|---|
| D-1 | ADR-0082 direction | Option 1 (upstream out-of-process provider) / Option 2 (BYQ child-resume bridge) / reject both | Decide after reviewing whether BYQ may qualify an independent-process child; record that `child-crash` is option-1-bound |
| D-2 | ADR-0083 persistence | named durable store / candidate-specific evidence-only store / reject | Choose evidence-only for D15-G, with the durable store deferred to R4 |
| D-3 | Sequence tension | accept candidate-specific layer for D15-G then R4 / reorder D15-G and R4 / split the terminal gate | Prefer candidate-specific layer for D15-G then R4 productionization |
| D-4 | ADR status | accept with revisions / keep Proposed / reject | Keep **Proposed** until the revisions above are written |
| D-5 | Blocker resolution order | B1→B2→B3→B4 serial / B1+B3 then B2+B4 | Keep the serial order in [DSH-015RC1-CLOSEOUT-SLICES.md](DSH-015RC1-CLOSEOUT-SLICES.md) |

## Explicit non-actions in this batch

- No ADR is accepted, modified or implemented.
- No `resume_delegated_child` (or equivalent) is added to the runtime adapter.
- No terminal/PTY wiring or `TerminalAttachment` persistence is added.
- The production selector stays `dsh-0.1.2rc1`; `R3_RESUME` stays `NO`.
