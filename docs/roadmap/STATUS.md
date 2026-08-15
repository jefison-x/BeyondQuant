# BeyondQuant Status

This file is the phase source of truth. It is intentionally short so a new
Codex session does not infer project state from commit history.

- Current completed phase: **Phase 8**
- Next phase: **Phase 9**
- Accepted runtime ADR: **ADR-0003**
- Accepted Phase 7 authentication ADR: **ADR-0004**
- Accepted Phase 8 data-provider ADR: **ADR-0005**
- Open architecture decisions: none for the Phase 8 data-provider boundary;
  [ADR-0003](../architecture/adr/ADR-0003-gateway-dsh-runtime-integration.md)
  is Accepted.
  [ADR-0004](../architecture/adr/ADR-0004-phase7-product-authentication.md)
  is Accepted.
  [ADR-0005](../architecture/adr/ADR-0005-phase8-data-provider.md) is Accepted.
- Active architecture blockers: **none**

Git SHA is not phase state. The current clean baseline must always be derived
from `git fetch origin` followed by `git rev-parse origin/main`; this file must
not hard-code a SHA or describe a transient pull request/merge state.
