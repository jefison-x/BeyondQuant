# Phase 48 remaining Product gap register

This register separates completed Product scope from release decisions and
future optimization. None of these items is an unexplained Community parity
gap or a reason to claim Phase 48 incomplete.

| Item | Type / priority | Current evidence | Disposition |
|---|---|---|---|
| Human v1.0 release-candidate review | Release gate / required | Phase 48 implementation and evidence are complete. | Open and pending maintainer decision. Phase 48 does not self-approve the RC. |
| Production model-provider acceptance | Deployment / required before model-backed production use | CI proves encrypted credential/binding and real turn acceptance with a non-production secret; it deliberately does not store a real provider key. | Validate with deployment-owned credential during human RC/operator acceptance. Not a source-code parity gap. |
| Community market-cache bulk import | Data operation / conditional | Logical pipeline exists; ADR-0013 still requires a live read-only provenance audit before import. | Perform only when an auditable Community snapshot is supplied; quarantine unverifiable rows. |
| DSH Upgrade Lane | Maintenance / scheduled | Current DSH pin remains qualified. | Execute the separately approved `DSH_UPGRADE_LANE.md` workflow after Product completion or earlier for a critical advisory. |
| Backtest JavaScript chunk size | Performance / P2 | Production build warns that the Backtest route chunk exceeds 500 kB; functional and accessibility checks pass. | Measure Core Web Vitals on intended deployment, then split ECharts/result panels if the measured budget requires it. |
| `robots.txt` and `llms.txt` | Discoverability / P3 | Authenticated Lighthouse snapshot reports SEO 80 and Agentic Browsing 50; Accessibility and Best Practices are 100. | Decide public-indexing policy during deployment hardening. Do not expose private Product content to improve a score. |
| Cloud tenant provisioning and operator policy | Future architecture / planned separately | Current durable owner isolation is two-user verified; no cross-owner state was observed. | Define Cloud control-plane/provisioning ADR before multi-tenant commercial deployment; do not weaken current BYQ ownership boundaries. |

No fake page, mock Product result, local-only preference, hard-coded normal
user, direct internal-browser API or owner crossover remains in the Phase 48
acceptance path.
