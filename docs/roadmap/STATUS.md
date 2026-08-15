# BeyondQuant Status

This file is the phase source of truth. It is intentionally short so a new
Codex session does not infer project state from commit history.

- Current completed phase: **Phase 6**
- Next phase: **Phase 7**
- Accepted runtime ADR: **ADR-0003**
- Open architecture decisions: none for the Phase 6 runtime seam;
  [ADR-0003](../architecture/adr/ADR-0003-gateway-dsh-runtime-integration.md)
  is Accepted.
- Active architecture blockers: **none**

Git SHA is not phase state. The current clean baseline must always be derived
from `git fetch origin` followed by `git rev-parse origin/main`; this file must
not hard-code a SHA or describe a transient pull request/merge state.
