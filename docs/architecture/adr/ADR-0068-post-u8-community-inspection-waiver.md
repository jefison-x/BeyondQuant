# ADR-0068：后续开发免除 Community 原实现检查

- Status: Accepted
- Date: 2026-09-09
- Scope: 当前及之后所有开发步骤，包括 Product Phase、维护、领域与前端整改。
- Acceptance: 维护者先回复“现在不用检查了”，随后明确：“之后所有开发步骤都免除 Community 原实现检查”。
- Supersedes: AGENTS、开发流程和历史 Phase/计划/验收清单中以 Community 原实现检查为实施前置或停止条件的要求。

不再强制定位、读取或重新检查 Community 原实现；源码缺失不阻塞后续开发，
不重复请求检查豁免。实现依据当前 BYQ 架构、Accepted ADR、领域合同和失败回归，
可使用已有历史分类作为参考，不冒称本轮重新检查。
前端仍须功能清单与真实 Product API 浏览器验收，清单可依据当前需求和已有历史记录，
无需重新读取 Community 页面。历史已执行检查的证据保持原样。

不授权盲目复制代码：如主动复用外部代码，仍需确认来源、许可、迁移分类和架构适配。
Community 只读保护及禁止 BaoStock、AKShare、VectorBT、旧 harness 的边界不变。
本决定免除原实现检查，不免除真实数据迁移的来源、单位、schema、完整性与只读逻辑
导出/验证门禁。没有改变 Product Phase、push/merge、部署、付费模型或历史研究续跑权限。
