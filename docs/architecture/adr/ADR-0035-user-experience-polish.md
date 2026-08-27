# ADR-0035：普通用户体验 P3 收口

- Status: Accepted
- Date: 2026-08-27
- Accepted: 2026-08-27
- Decision scope: Phase 62 user-experience polish
- Related: ADR-0018、ADR-0024、ADR-0028、ADR-0034

## 背景

Phase 61 已关闭真实用户验收累计 19 项问题中的全部 P0、P1 和 P2，并完成生产恢复与
真实模型复验。剩余非阻断项集中在三个方向：任务 readiness 仍需手工复制股票代码；普通
用户页面仍有少量英文工程术语；全量 ECharts 引入使回测页面包体超过构建建议阈值。

只读 Community 检查表明，其 Data Sync 的“选择股票池”意图值得复用，但实现使用硬编码
股票池、TODO API 和假进度；股票池候选选择可作交互参考；旧 Vite 配置没有可迁移的分包
策略。

## 决策

1. Data Center readiness 可以从当前用户的持久化股票池选择成分。读取仍经
   Gateway/Product API，使用当前不可变 snapshot；单次最多 20 只。超过上限时必须明确
   显示范围并允许用户选择，不得静默声称检查了整个股票池。
2. 普通用户工作台、导航和摘要使用中文任务语言。内部 ID 只显示缩略“记录编号”，状态
   使用统一中文映射。管理员诊断页可以保留必要的 Backend、Runtime、WorkflowTrace 等
   精确术语。
3. ECharts 改用官方模块化入口，只注册当前实际使用的折线图、坐标、提示、标题、图例、
   无障碍和 Canvas renderer。不得通过提高 warning 阈值伪装性能问题。
4. Phase 61 的状态源必须与已合并证据一致：P0/P1/P2 全闭合、正式环境已恢复；Phase 62
   不重新机械测试 CRUD 或扩大到自动策略执行、live broker 或新数据源。

## 验收

- 股票池直选与 snapshot fallback 有单元测试；真实浏览器能选择股票池、选择至多 20 只
  成分并完成 readiness 查询，Network 只出现 same-origin Product API。
- 普通工作台不再以 Backend、Artifact ID、Job ID、Product API、Gateway 或
  WorkflowTrace 作为首屏标签；技术诊断页不受影响。
- Frontend 全套测试和 production build 通过；回测/图表相关 JS chunk 均不超过默认
  500 kB warning 阈值，图表真实渲染。
- Architecture test、Mock Playwright 和真实 Product smoke 通过；证据记录在
  `docs/evidence/phase-62/`。

## 非目标

- 不新增或改变 Backend/MCP/DSH Contract、数据同步任务、审批、策略或回测 invariant；
- 不新增自动交易、策略自动驱动模拟账户、live broker、Provider 或团队工作区；
- 不复制 Community 组件、假数据、假进度、legacy API 或受禁止技术。

## Acceptance record

维护者于 2026-08-27 明确授权 PR #140 合并并继续下一阶段；本 ADR 接受由 Phase 61
验收报告直接导出的非阻断 P3 收口范围。
