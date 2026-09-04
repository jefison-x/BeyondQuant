# ADR-0050：模型研究归档与工作台统一管理操作区

- Status: Accepted
- Date: 2026-09-04
- Accepted: 2026-09-04
- Decision scope: Post-Phase 90 Product lifecycle maintenance
- Related: ADR-0007、ADR-0008、ADR-0020、ADR-0035、ADR-0043、ADR-0048

## 背景

股票池、策略、模型研究和回测工作台已经分别实现各自领域生命周期，但停用、删除、取消和归档按钮散落在
列表行、详情标题和编辑表单中。相同位置的按钮具有不同风险，用户也难以判断已完成的模型研究为什么不能
删除。ADR-0043 同时要求训练、模型、预测、信号和回测历史在回滚或停用后继续作为只读审计证据。

只读 Community `StockPoolView.vue`、`StrategyView.vue` 和 `BacktestView.vue` 证明了管理动作需要明确状态、
确认和移动端入口，但其列表行危险操作、直接 `/api/v1` 调用和物理删除语义不能迁移。Community 没有对应
的可审计 ML 研究工作台。

## 决策

1. 四个研究资产工作台使用同一个 Product `ManagementActionBar`，固定在选中对象的详情标题之后、业务内容
   之前。该区域只放生命周期或任务管理动作；创建、编辑、批准、分析等工作流动作继续留在各自上下文。
2. 目录列表用于筛选、选择和比较，不承载回测删除等危险动作。桌面和移动端使用同一详情管理入口，避免
   同一动作存在多套位置和可用条件。
3. 股票池继续遵守 ADR-0020 的 `active ↔ inactive` 与 tombstone delete；策略只允许移除可编辑草稿；
   回测只允许取消活跃任务或删除终态目录记录。共享组件不改变任何领域不变量。
4. ML 研究增加 Product 目录生命周期 `active ↔ archived`。实现复用该 ML StrategyVersion Artifact 的
   status 字段，但使用专用 ML lifecycle API 和校验，不扩展通用 Artifact transition graph。
5. 只有已存在训练、预测或回测记录，且这些记录全部处于终态时，ML 研究才可归档。归档研究不能发起新的
   训练或执行；其 StrategyVersion 内容/hash、Approval、TrainingRun、ModelArtifact、PredictionSnapshot、
   SignalSnapshot 和 Backtest 全部保持不变并可按“已归档”目录读取。
6. 归档可恢复为 active/validated。没有任何执行记录的研究继续使用原有软删除：StrategyVersion 与相关
   Approval 转为 superseded 并从目录隐藏；不执行物理删除。已有执行记录永远不能走删除接口。
7. 可用动作、原因和活动运行计数由 owner/workspace-scoped Backend 计算，经 Gateway/Product API 的稳定
   projection 返回。Browser 不根据局部列表猜测领域不变量，也不调用 Backend、MCP、DSH 或 PostgreSQL。

## 后果

- 已完成模型研究可以清理目录而不牺牲复现、审计或后续恢复。
- 四个工作台具有稳定的管理操作心智模型，同时保留不同领域的真实语义。
- Artifact 通用 transition API 不获得任意 archive 能力；该状态只由专用 ML lifecycle boundary 写入。

## 拒绝的替代方案

- 允许删除已执行 ML 研究：会破坏 ADR-0043/0048 的不可变 lineage 和审计要求。
- 只在前端隐藏研究：无法跨设备持久化，也不能阻止新的执行。
- 用共享前端按钮统一后端语义：会错误地把股票池墓碑、策略 supersede 和回测任务删除解释成相同操作。
- 复制 Community 列表行删除和旧 API：违反 Product API 与新领域边界。

## 验收

Contract test 必须证明：未执行研究只能软删除；活动运行阻止归档；终态运行允许归档；默认目录隐藏归档项；
归档目录仍可加载全部有界证据；恢复后不修改既有运行；owner/workspace 隔离、幂等和 Gateway allowlist 保持。
Frontend build、组件测试和真实浏览器检查必须证明四页管理区位置一致、危险动作不再散落于回测目录行。

## 回滚

关闭 lifecycle Product 入口并隐藏归档操作，保留 status 已为 archived 的研究及全部证据为只读；不得物理删除
或重写其 Artifact。恢复入口可作为最小管理工具保留，直到所有归档项由所有者明确恢复。
