# ADR-0082 / ADR-0083 maintainer decision record (0.9 strict order step 4)

Status: **recorded — decision only, no implementation.** This document encodes the
repository maintainer's human decision on ADR-0082 and ADR-0083, delivered as the
0.9 strict-order step 4 maintainer instruction on 2026-09-21. It is **not** a GitHub
review, approval, or merge artifact, and it does **not** impersonate one.

Machine-readable form: [decision-record.v1.json](decision-record.v1.json).

- Decision authority: repository maintainer (human).
- Decision date: 2026-09-21.
- Decision scope: ADR-0082 status + option choice; ADR-0083 status; the non-actions
  that acceptance does and does not authorize.
- Base at decision recording: dynamic `origin/main` (`f3c3381`, step 3 merged).

## ADR-0082 — MODIFIED acceptance (Option 1 only)

The maintainer accepts ADR-0082 with a **modification**: only **Option 1** is chosen.

- **Option 1 chosen.** DSH provides, in the future, an independent-process
  continuable provider / `prepareContinuable`; generic child resume and independent
  child-crash recovery belong to **DSH**.
- **Option 2 rejected for now.** The BYQ runtime-adapter child-resume bridge is
  **rejected as the current architecture direction**. BYQ does **not** build a second
  session store or a generic agent harness.
- **Post-qualification requirement.** Option 1 is upstream work that does not exist in
  the 0.1.5-rc.1 candidate. The `subagent-child-crash` blocker therefore stays
  `BLOCKED` until a qualifying out-of-process continuable provider exists and is
  qualified; acceptance alone resolves nothing.
- **Rollback / escape path.** No production change is made. If a future provider does
  not materialize, the escape path is to keep foreground delegation and leave the
  native continuable seam unexercised; the R3 freeze and `R3_RESUME = NO` continue to
  hold.
- **No second harness.** Acceptance never authorizes a BYQ-owned session store, a
  child-attach/epoch fence in the adapter, or a second generic agent harness.

## ADR-0083 — accepted as currently proposed

The maintainer accepts ADR-0083 **as currently proposed**, with no modification.

- BYQ persists only `TerminalAttachment` identity, permission, generation, epoch and
  state, and exposes **bounded** interfaces through Gateway/Product API.
- **DSH continues to own PTY/shell/I/O.** BYQ adapts, observes, authorizes and fails
  down; it does not implement a PTY runtime.
- ADR-0083 does **not** promise PTY survival across a runtime restart. On native
  process-local state loss it **MUST** report truthful `lost`/`interrupted`, never a
  fabricated `reattached`.
- The `terminal-adapter-restart` and `terminal-dsh-runtime-restart` blockers stay
  `BLOCKED` until the candidate-specific attachment layer is implemented and
  qualified; acceptance authorizes only a candidate-specific, reversible qualification
  path, not a production default switch.

## Explicit non-actions (nothing is implemented by this decision)

- No out-of-process continuable provider and no `prepareContinuable` provider.
- No BYQ child-resume bridge / `resume_delegated_child` seam.
- No `TerminalAttachment` API, persistence, or database schema change.
- No D15/R3 unfreeze; `R3_RESUME = NO`.
- No production selector/default switch (`dsh-0.1.2rc1` unchanged).
- No deployment, tag or release.
- The four D15-G atomic BLOCKED items remain BLOCKED: `subagent-child-crash`,
  `subagent-byq-adapter-restart`, `terminal-adapter-restart`,
  `terminal-dsh-runtime-restart`.
- 0.9 is **not** closed.

## Frozen constraints after this decision

- `R3_RESUME = NO`; production selector/default `dsh-0.1.2rc1`; deployment `none`.
- ADR-0082 / ADR-0083 are **Accepted** but **not implemented**.
- The paused `codex/phase-100c` branch (Draft PR #338) is untouched.
