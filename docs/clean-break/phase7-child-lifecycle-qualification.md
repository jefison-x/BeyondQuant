# Phase 7 next-slice qualification — delegated child lifecycle

Status: **NO-GO for deleting `child_lease.py` with the qualified DSH 0.1.5rc1 Python SDK**. This is a read-only qualification decision, not a Phase 7 deletion gate or a change to the accepted 0.10 ownership model.

## Current boundary

DSH owns child Agent execution. The BYQ Adapter currently correlates child notifications with the parent delegation and uses `ChildLease` for per-child activity and timeout. Its expiry closes the active harness and emits a failure; Gateway projects that failure to Product clients. Deleting only the lease would make the ordinary root no-progress timeout apply to healthy long child turns, while dropping the timeout would leave stuck turns without bounded cleanup. Business idempotency and unknown external outcomes remain BYQ domain safety regardless of child runtime ownership.

The current Clean Break ADR-002 assigns generic Agent and subagent lifecycle to DSH. Historical ADR-0082 recorded DSH's proposed out-of-process `SubagentProvider.prepareContinuable` path, its absence in rc1, and rejection of a BYQ child-resume bridge. That historical record is evidence, not a current architecture constraint. A BYQ generic child-resume bridge or direct session-file access would violate the current DSH ownership boundary.

The locked Python SDK and runtime-bin are 0.1.5rc1 (`config/dsh/releases/dsh-0.1.5rc1.python.lock`, `services/runtime-adapter/requirements.dsh-0.1.5rc1-candidate.lock`). The recorded 0.1.5 SDK public Python surface is byte-identical to 0.1.2 (`docs/evidence/d15/upgrade-recon.v1.json`); `dsh_015.py` inherits `Dsh012Compatibility`. Its BYQ seam covers starting/running a root session and closing it, but has no child status, child-targeted cancellation, or persisted-child rebind method. The real candidate restart record (`docs/evidence/d15/d15-4/continuable/continuable-adapter-restart.v1.json`) reports `sdk_child_surfaces=[]` and no successful BYQ child rebind. Native Node DSH continuable APIs are a separate surface and do not establish a qualified Python Adapter contract.

## Required cutover contract

Before replacing this live BYQ lease, qualify one exact DSH release and test:

1. A stable DSH child handle bound to parent and invocation/call IDs; duplicate, foreign, late and out-of-order observations cannot complete the wrong delegation.
2. A status snapshot or event cursor with monotonic per-child progress and terminal result for parallel children; DSH owns inactivity and hard-limit policy if BYQ's lease disappears.
3. Idempotent child cancellation with terminal confirmation, or an explicit root-close fallback with proven terminal behavior.
4. Lookup/rebind of the same handle after Adapter and child restart, or an explicit interruption outcome that preserves BYQ business safety.
5. Gateway Product projection remains framework-neutral; no raw DSH event schema reaches the frontend.

Use the real qualified runtime and replacement contract tests in one bounded slice. Do not add a BYQ generic child manager, compatibility bridge, or private DSH SDK dependency. Until the contract passes, keep `child_lease.py` and its safety tests. No DB, Docker or workspace cleanup follows from this note.
