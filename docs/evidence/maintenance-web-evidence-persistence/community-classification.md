# Web evidence persistence UX — Community classification

Read-only inspection covered Community `agent-service` web-search/provider paths,
research repository/evidence references, public prompts, and
`XiaobaAssistantDrawer.vue` guidance. No Community file or database was changed.

| Community evidence | Classification | BYQ decision |
| --- | --- | --- |
| Tavily/SerpAPI provider selection and Agent Service direct web research | `DROP` | DSH official qualified `web_search` remains the only generic search capability. |
| Agent Service repository and evidence blob persistence | `REPLACE` | BYQ MCP → Backend → existing PostgreSQL ResearchTask/Artifact is authoritative. |
| Preserve clickable URL/title/source/time and fail explicitly | `PORT_UX` | Keep provenance and plain-language degradation, without raw tool/schema details. |
| Public hint that configured search can inspect public sources | `REFERENCE_ONLY` | No frontend change is needed for this maintenance fix. |

The defect is therefore not repaired by copying Community runtime or storage.
BYQ generates internal source identity, saves the task and evidence atomically,
and keeps the public conversation limited to an understandable saved/not-saved
status.
