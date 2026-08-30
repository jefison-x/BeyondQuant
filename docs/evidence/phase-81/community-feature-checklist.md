# Phase 81 Community Feature Checklist

| Surface | Community evidence | Classification | Phase 81 decision |
|---|---|---|---|
| Conversation retry/failure UX | Community frontend search found no durable DSH multi-process resume surface | `REPLACE` | Use BYQ Product conversation catalog and normalized failure copy. |
| Legacy Agent runtime recovery | `agent-service/app/workflows/*` and `runtime/pydantic_ai.py` | `DROP` / `REFERENCE_ONLY` | Do not migrate runtime, graph persistence, PydanticAI, API or event schema. |
| Retryable error semantics | Legacy bounded error categories and retry guidance | `PORT_UX` | Preserve honest retry guidance, but derive authority from BYQ WorkflowTrace. |

The Community repository was inspected read-only and was not modified.
