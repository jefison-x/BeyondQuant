# BeyondQuant Status

This file is the phase source of truth. It is intentionally short so a new
Codex session does not infer project state from commit history.

- Current completed phase: **Phase 30**
- Next phase: **Community feature-depth gap closure (next: Backtest product depth)**
- Accepted runtime ADR: **ADR-0003**
- Accepted Phase 7 authentication ADR: **ADR-0004**
- Accepted Phase 8 data-provider ADR: **ADR-0005**
- Accepted Phase 9 research-entities ADR: **ADR-0006**
- Accepted Phase 11 strategy-artifact ADR: **ADR-0007**
- Accepted Phase 12 backtest-worker ADR: **ADR-0008**
- Accepted Phase 13 quant-research-agent ADR: **ADR-0009**
- Accepted Phase 14 quant-learning-loop ADR: **ADR-0010**
- Accepted Phase 15 engineering-plane ADR: **ADR-0011**
- Accepted Phase 16 product-api ADR: **ADR-0012**
- Accepted Phase 16 durable-market-data-storage ADR: **ADR-0013**
- Accepted Phase 24 user-auth ADR: **ADR-0014**
- Accepted pre-release auto-merge ADR: **ADR-0015**
- Open architecture decisions: none for the Phase 30 release-candidate boundary;
  [ADR-0003](../architecture/adr/ADR-0003-gateway-dsh-runtime-integration.md)
  is Accepted.
  [ADR-0004](../architecture/adr/ADR-0004-phase7-product-authentication.md)
  is Accepted.
  [ADR-0005](../architecture/adr/ADR-0005-phase8-data-provider.md) is Accepted.
  [ADR-0006](../architecture/adr/ADR-0006-phase9-research-entities.md) is Accepted.
  [ADR-0007](../architecture/adr/ADR-0007-phase11-strategy-artifact.md) is Accepted.
  [ADR-0008](../architecture/adr/ADR-0008-phase12-backtest-worker.md) is Accepted.
  [ADR-0009](../architecture/adr/ADR-0009-phase13-quant-research-agents.md) is Accepted.
  [ADR-0010](../architecture/adr/ADR-0010-phase14-quant-learning-loop.md) is Accepted.
  [ADR-0011](../architecture/adr/ADR-0011-phase15-engineering-plane.md) is Accepted.
  [ADR-0012](../architecture/adr/ADR-0012-phase16-product-api-bff.md) is Accepted.
  [ADR-0013](../architecture/adr/ADR-0013-phase16-durable-market-data-storage.md) is Accepted.
  [ADR-0015](../architecture/adr/ADR-0015-phase-release-automerge.md) is
  Accepted until the BeyondQuant Next v1.0 release boundary.
- Phase 23 acceptance evidence covers the Community Feature Parity Matrix,
  golden journey E2E smoke, release-candidate status, and explicit DROP/DEFER
  classifications for remaining hardening work.
- Phase 23 produced a Product Skeleton release-parity baseline. It did not
  establish final Community feature parity. Remaining product-depth work is
  tracked in Phases 24-30.
- Phase 30 acceptance evidence covers the V2 parity matrix with no `FAIL`
  items, a golden journey covering core product pages, and BYQ artifact/
  approval list surfaces without raw DSH or backend exposure.
- Community Parity Delivery Plan Phases 1-8 restored the product shell and
  Chrome MCP browser evidence, but
  `docs/roadmap/COMMUNITY_FEATURE_PARITY_GAP.md` records substantial remaining
  `PARTIAL`/`MISSING` product-depth workflows. The v1.0 RC review gate is not
  yet satisfied.
- Release reminder (ADR-0015): at the BeyondQuant Next v1.0 official release,
  disable GitHub auto-merge and restore the single-maintainer human merge gate.
- Active architecture blockers: **none**

Git SHA is not phase state. The current clean baseline must always be derived
from `git fetch origin` followed by `git rev-parse origin/main`; this file must
not hard-code a SHA or describe a transient pull request/merge state.
