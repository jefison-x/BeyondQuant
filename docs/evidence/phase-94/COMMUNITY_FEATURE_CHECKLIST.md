# Phase 94 Community Feature Checklist

The Community repository was inspected read-only before implementation. Its GitHub Actions and Issue templates are reference evidence only; it contains no Cloudflare Workers Builds, Wrangler Git deployment or equivalent two-Worker delivery implementation.

| Feature / invariant | Community evidence | Decision | Phase 94 result |
|---|---|---|---|
| Repository CI on pull requests | `.github/workflows/ci.yml` and `security.yml` | `REFERENCE_ONLY` | Existing BYQ required CI remains the merge gate; Cloudflare does not become a GitHub Actions deployment path. |
| GitHub issue intake templates | `.github/ISSUE_TEMPLATE/` | `REFERENCE_ONLY` | Phase 92/93 central feedback contract and publisher remain unchanged. |
| Direct GitHub-to-Cloudflare delivery | No corresponding implementation | `REPLACE` | Two Cloudflare projects import the same official repository with isolated deploy commands and `main`-only production builds. |
| Account/resource setup | No corresponding implementation | `REPLACE` | Wrangler declarations allow automatic D1/DO/Queue/DLQ configuration without committing account-specific ids. |
| Community runtime, storage and credentials | Incompatible direct boundaries | `DROP` | No Community runtime, database, secret, workflow or Git history is copied or activated. |

The Community repository/database/runtime/credentials/Git history remained read-only and were not modified, imported or copied.
