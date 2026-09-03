# Phase 87 Evidence

Phase 87 is a contract-only architecture baseline. It performs no database migration, runtime/API/MCP/frontend/Compose
change and makes no GitHub Issue request.

## Inspection and classification

- Read-only Community evidence inspected: `.github/ISSUE_TEMPLATE/config.yml`, `reproducible_bug.md`,
  `strategy_plugin.md`, historical requirements and open-source architecture guidance.
- Current BYQ evidence inspected: ARCHITECTURE, EngineeringTask domain/contract/tests, Product API, encrypted credential
  boundary, personal workspace, Product DSH image boundary and plugin/capability governance.
- Community templates are `PORT_UX`/`PORT_TESTS` or `REFERENCE_ONLY`; old Agent/API/runtime/storage is `REPLACE`/`DROP`.
- Community repository/database/Git history were not modified, imported or copied.

## Accepted artifacts

- ADR-0049 separates workspace-owned Product Feedback from EngineeringTask and GitHub publication.
- `product-feedback.md` freezes revisions, preview consent, deterministic redaction, publication snapshot, fingerprint,
  transactional outbox, lease/fence, retry/reconciliation, Product API and MCP boundaries.
- `PRODUCT_FEEDBACK_DELIVERY_PLAN.md` defines the serial Phase 88–90 implementation gates.

## Security and configuration conclusion

- Normal users configure no GitHub account, token, repository or permission.
- A deployment operator configures one fixed-repository GitHub App installation (preferred) or a single-repository
  fine-grained service token (fallback).
- The future publisher receives only the credential and fixed destination; Product DSH/Backend/Gateway/MCP/Browser do not.
- Unconfigured publication never disables internal feedback or fabricates an Issue URL.
- Required CI will use a fake GitHub endpoint and create zero real Issues.

## Validation

- Architecture tests assert accepted ADR/contract/plan and prohibited privilege widening.
- Markdown links and whitespace are validated by repository tests and `git diff --check`.
- Runtime deployment is unchanged in this phase; post-merge deployment verification is SHA + existing service health only.
