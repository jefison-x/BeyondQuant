# BYQ 0.10 Clean Break preparation

This directory contains the Phase 0–6 review package and the accepted BYQ 0.10 architecture baseline activated by [ADR-0088](../architecture/adr/ADR-0088-clean-break-baseline-activation.md) in the Clean Break branch. The maintainer explicitly requested a development-period Clean Break with no historical runtime/data compatibility. Phase 7 proceeds only in bounded reviewed slices; no old database, Docker volume, container or runtime code was deleted by the Phase 0–6 package.

## Documents

- [Development agent mode](development-agent-mode.md) — Phase 0 configuration and role contract.
- [Environment inventory](environment-inventory.md) — Phase 1–2 freeze and read-only environment facts.
- [Archive and environment plan](archive-and-environment-plan.md) — Phase 3 backup and Phase 8–9 plan.
- [ADR baseline](adr/README.md) — Phase 4 proposed decisions.
- [Ownership and deletion plan](ownership-and-deletion-plan.md) — Phase 5–6 decisions and P4 disposition.
- [Fidelity and execution plan](fidelity-and-execution-plan.md) — user journeys, risks and Phase 7–17 order.
- [Development verification gates](verification-gates.md) — risk-selected slice tests, review and rebuild milestones.
- [Phase gates](phase-gates.md) — Tester, independent Reviewer and Root verdicts with activation limits.
- [Phase 17 residual simplification](phase17-residual-simplification.md) — current ownership audit, source slices and pending final Golden gates.
- [Agent stop/session issue](runtime-stop-session-issue.md) — diagnosed hard-cancel/resume and terminal reconnect defects; repair deferred.
- [Personal workspace menu issue](personal-workspace-menu-issue.md) — stale Bootstrap Admin label after nickname changes; repair deferred.
- [Phase 7 Gateway slice](phase7-gateway-proxy.md) — first bounded removal and replacement contract.
- [Phase 7 generation history slice](phase7-generation-ledger.md) — second bounded removal and gate evidence.
- [Phase 7 child lifecycle qualification](phase7-child-lifecycle-qualification.md) — current DSH 0.1.5rc1 contract gap and NO-GO cutover decision.
- [Phase 7 containment route slice](phase7-gateway-containment-routes.md) — third bounded removal and gate evidence.
- [Phase 7 ResearchTask business action design](phase7-pending-business-action.md) — reviewed next-slice boundary; implementation pending.

Each phase records Tester, independent Sol Reviewer and Root verdict. A design PASS allows the next planning phase; it is not evidence that code, data backup or real-browser functionality has passed.
