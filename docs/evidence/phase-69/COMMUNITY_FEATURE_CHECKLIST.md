# Community feature checklist

| Capability | Community classification | BYQ Phase 69 result |
|---|---|---|
| Unified stock-pool catalogue | `PORT_LAYOUT` / `PORT_UX` / `REFACTOR` | Custom, index and dynamic pools share one Product catalogue and owner/workspace authorization. |
| Version history and member comparison | `PORT_UX` / `PORT_LOGIC` / `PORT_TESTS` | Immutable snapshots expose deterministic added, removed, changed-weight and retained results. |
| Producer definition portability | `REFERENCE_ONLY` / `REPLACE` | Only normalized intent is portable; imported producer pools are inactive/draft until revalidated. |
| Static sample universe | `DROP` | No sample or fabricated membership is used. |
| Fake dynamic placeholder | `DROP` | Phase 68 closed evaluator and trusted worker remain the only dynamic producer. |
| Direct ORM/internal API/auth | `REPLACE` / `DROP` | Browser traffic is same-origin Gateway/Product API only. |

The source repository remained read-only. No Community source, runtime, data or Git history was copied or modified.
