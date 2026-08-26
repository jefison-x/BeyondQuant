# Phase 60 Community checklist

Read-only source: `/home/jefison/projects/BeyondQuant-community`.

| Surface | Classification | Result |
|---|---|---|
| `AgentThinking.vue` collapsible progress | `PORT_UX` / `REFACTOR` | Keep a bounded activity drawer, but render only BYQ-normalized domain progress with localized phase/state. |
| Tool name, control-contract and reasoning labels | `REFERENCE_ONLY` / `REPLACE` | Hide authorize/audit/control tools and raw capability names; never present hidden reasoning. |
| `AgentView.vue` final answer plus step list | `PORT_LAYOUT` / `REFACTOR` | Keep answer and activity separate; use text-only DSH completion anchors for public answers. |
| Community raw Agent API/SSE/message contract | `REPLACE` | Browser remains on same-origin Gateway/Product API and BYQ WorkflowTrace. |
| PydanticAI/Hermes runtime, direct Agent API/domain access | `DROP` | No dependency, fallback, compatibility path or runtime code is migrated. |

No Community source, database, cache, credential, runtime or Git history was
modified, imported or copied.
