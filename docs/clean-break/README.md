# BYQ 0.10 Clean Break preparation

This directory is the Phase 0–6 review package. The user explicitly requested a development-period Clean Break and no historical runtime/data compatibility. Its architecture decisions are **proposed until the phase gate and maintainer acceptance/merge**. Existing Accepted ADRs remain the current baseline until superseded; Phase 7 destructive work must not start early. No old database, Docker volume, container or runtime code is deleted by this package.

## Documents

- [Development agent mode](development-agent-mode.md) — Phase 0 configuration and role contract.
- [Environment inventory](environment-inventory.md) — Phase 1–2 freeze and read-only environment facts.
- [Archive and environment plan](archive-and-environment-plan.md) — Phase 3 backup and Phase 8–9 plan.
- [ADR baseline](adr/README.md) — Phase 4 proposed decisions.
- [Ownership and deletion plan](ownership-and-deletion-plan.md) — Phase 5–6 decisions and P4 disposition.
- [Fidelity and execution plan](fidelity-and-execution-plan.md) — user journeys, risks and Phase 7–17 order.
- [Phase gates](phase-gates.md) — Tester, independent Reviewer and Root verdicts with activation limits.

Each phase records Tester, independent Sol Reviewer and Root verdict. A design PASS allows the next planning phase; it is not evidence that code, data backup or real-browser functionality has passed.
