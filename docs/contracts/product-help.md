# Product Help Contract — Phase 76

本合同落实 ADR-0044 的只读产品帮助边界。

- `product-capability-catalog.v1` 是产品用途、固定 route、受众、前置条件、支持等级和限制的规范输入。
- `byq-product-guide` 只负责区分说明/导航与执行意图，并按领域读取必要 reference；Production Product DSH 不挂载源码。
- `byq_product_help_query` 是只读元数据查询，不创建 AgentRun、ResearchTask、Artifact、Approval 或 audit，不授予任何领域权限。
- 查询最多返回五项 `product-help-result.v1`；结果只含公开能力字段，不暴露 MCP tool、Product API、Backend path、workspace/owner identity 或任意 URL。
- 导航只能使用目录中的固定 `route_id`。管理员能力默认排除；显式查询管理员说明时仍必须标记 `ADMIN`，且不表示调用者拥有角色。
- “怎么用/在哪里/有什么区别”必须零 mutation；“帮我创建/训练/运行/取消/修改”只用产品帮助识别能力和前置条件，后续动作仍遵循独立角色、授权、审批和审计合同。
- 不支持的 Agent 动作必须诚实返回浏览器路径和限制，不得猜测 tool payload 或宣称已经执行。

验收至少覆盖模型配置与模型研究区分、普通/管理员过滤、未知功能、固定 route、无内部 tool 泄漏，以及说明请求不产生领域记录。
