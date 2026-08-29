# Community feature checklist

| Capability | Community classification | BYQ Phase 70 result |
|---|---|---|
| Bounded core index-weight batch | `PORT_LOGIC` / `PORT_TESTS` / `REFACTOR` | Six canonical identities use the closed BYQ adapter and trusted Data Worker. |
| Two-month recent coverage | `PORT_LOGIC` / `REFACTOR` | Requests are bounded to at most 62 days. |
| Shanghai/Shenzhen aliases | `REFERENCE_ONLY` / `REPLACE` | Duplicate provider aliases are excluded from Product identity. |
| Per-index progress/failure | `PORT_UX` / `PORT_TESTS` / `REFACTOR` | Failures are isolated; previous verified snapshots remain usable and safe summaries persist. |
| Monthly mutable completeness | `PORT_LOGIC` / `PORT_TESTS` / `REFACTOR` | Exact snapshot-level members, weights and hashes authorize Stock Pool creation. |
| SDK/Pandas, ORM, thread scheduler and internal API | `REPLACE` / `DROP` | BYQ PostgreSQL, independent Data Worker and Gateway/Product API remain authoritative. |

Community source, database, cache, credential, runtime and Git history remained read-only and were not copied.
