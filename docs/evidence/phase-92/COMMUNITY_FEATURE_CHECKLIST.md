# Phase 92 Community Feature Checklist

| Feature / invariant | Community evidence | Decision | Phase 92 result |
|---|---|---|---|
| Central feedback intake service | No corresponding service | `REPLACE` | Standalone FastAPI/PostgreSQL Hub with anonymous intake, validation, moderation and status capability. |
| Anonymous installation delivery | No corresponding relay/outbox | `REPLACE` | Persisted non-user installation ID and isolated local relay; no GitHub or business-database credential. |
| Official GitHub publication | No built-in trusted publisher | `REPLACE` | Only centrally accepted feedback enters the fixed-repository GitHub outbox. |
| Approval inbox and source conversation | Approval-center UX only | `PORT_UX` / `REFACTOR` | One exact feedback approval in the global center, then durable conversation continuation. |
| User GitHub OAuth/PAT setup | No applicable flow | `DROP` | Normal users configure no GitHub identity, token or repository. |
| Direct browser/DSH access to Hub or GitHub | No safe boundary | `DROP` | Browser uses Gateway/Product API; DSH uses BeyondQuant MCP; relay alone reaches Hub. |

The Community repository and database remained read-only. No Community source, data, runtime, storage, credential or Git history was copied or modified.
