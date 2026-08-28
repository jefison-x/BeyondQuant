# Agent stream recovery Community checklist

The corresponding Community conversation implementation was inspected read-only before this fix.

| Community surface | Classification | BeyondQuant decision |
|---|---|---|
| `AgentView.vue` error/finally cleanup and retry affordance | `PORT_UX` | Preserve the invariant that every run reaches a visible terminal state and unlocks input; implement it from durable Product API replay. |
| `AgentThinking.vue` progress disclosure | `PORT_UX` | Show only normalized public WorkflowTrace activity and close orphan activity when a terminal event follows it. |
| `api/agent.js` raw streaming endpoint | `DROP` | Continue using Gateway/Product API SSE only, with reconnect and `Last-Event-ID` replay. |
| Raw tool calls, internal reasoning, and runtime event schemas | `DROP` | Do not expose DSH internals or couple the frontend to its notification schema. |
| PydanticAI/Hermes orchestration | `DROP` | Keep DSH as the generic runtime and BYQ MCP as the Agent-to-Domain boundary. |

No Community source, data, or Git history was modified or copied.
