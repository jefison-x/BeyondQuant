# Phase 58 Community checklist

The corresponding BeyondQuant-Community implementation was inspected read-only
before implementation. Community is evidence only and was not edited or copied.

| Community area | Classification | Phase 58 disposition |
|---|---|---|
| Agent tool policy | `PORT_LOGIC` / `PORT_TESTS` / `REFACTOR` | Keep candidate research separate from the coordinator's explicit owner-scoped write; enforce in BYQ role catalogue. |
| Stock-selection output | `PORT_UX` / `PORT_TESTS` / `REFACTOR` | Preserve canonical symbols, evidence date and frozen candidates; use normalized WorkflowCards rather than raw runtime output. |
| Artifact/approval executor | `PORT_LOGIC` / `PORT_TESTS` / `REFACTOR` | Model intent is not authority; trusted owner/workspace, Backend invariants and separate audit outcomes remain authoritative. |
| Strategy prompt/validator/tests | `PORT_LOGIC` / `PORT_TESTS` / `REFACTOR` | Publish one exact executable contract, safe validation detail and one informed repair. |
| Gateway idempotency tests | `PORT_TESTS` / `REFACTOR` | Reuse request intent and prohibit blind role/state/payload guessing after authorization or validation failures. |
| PydanticAI/Hermes runtime, direct SQL/internal APIs | `REFERENCE_ONLY` / `DROP` | Keep DSH + BeyondQuant MCP + Product API; no second harness or direct business-data access. |
| VectorBT/BaoStock/AKShare and Community runtime/storage | `DROP` | No compatibility layer, dependency, import or mutable Community access. |

No Community source, database, cache, credential, runtime or Git history was
modified, imported or copied.
