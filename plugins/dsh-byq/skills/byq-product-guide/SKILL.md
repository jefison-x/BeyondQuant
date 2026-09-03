---
name: byq-product-guide
description: Answer how to use, find, distinguish, or prepare current BeyondQuant Product features using versioned BYQ guidance and fixed Product routes. Use for product help and navigation; do not use it as authorization to execute a domain mutation.
---

# BYQ product guide

First distinguish an explanation/navigation request from a request to act.

- For “在哪里、怎么用、有什么区别、下一步是什么”, answer from this skill and,
  when the exact current capability or route is needed, call `byq_product_help_query`
  at most once. This read is Product metadata: do not start a domain AgentRun, request
  authorization, create an audit record, or create ResearchTask/Artifact state for it.
- For “帮我创建、训练、运行、取消、修改”, use this guide only to identify the
  correct Product capability and prerequisites, then follow the relevant BYQ role and
  domain contract. Product help never authorizes that later action.
- If the user asks how to do something that Product supports but Agent execution does
  not, explain the browser flow and state the limitation. Do not guess an MCP payload.

Use only a returned fixed `route_id`; never invent an external URL, arbitrary query,
internal Backend path, MCP path, Artifact ID, workspace ID, or tool name in the public
answer. Say “进入模型研究” rather than exposing `/api/product/ml/...`. An ADMIN result
must be labelled as administrator-only and never implies that the current user has
that role.

Keep the answer task-oriented: what the feature is for, the shortest usable path,
required prerequisites, the next action, and one relevant limitation. Do not recite
the whole catalogue. When a query has no match, say which user goal is unclear and ask
for that goal instead of inventing a feature.

Read only the reference matching the user's request:

- Market research, ResearchTask and approval: [references/research.md](references/research.md)
- Stock pools and rule strategies: [references/pools-and-strategies.md](references/pools-and-strategies.md)
- Model research and Backtest: [references/ml-and-backtest.md](references/ml-and-backtest.md)
- Paper Trading: [references/paper-trading.md](references/paper-trading.md)
- Personal settings and assets: [references/user-settings.md](references/user-settings.md)
- Product feedback and suggestions: use the dedicated `byq-product-feedback` skill.
- Data Center, Operations and plugins: [references/admin.md](references/admin.md)

Product language distinguishes “模型配置” from “模型研究”: the former configures
write-only LLM credentials and Agent bindings; the latter trains auditable quant ML.
Never call either one simply “模型”.
