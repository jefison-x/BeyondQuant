# ADR-0074：0.10 数据基准与资格调查边界

- Status: Accepted
- Date: 2026-09-17
- Relates: ADR-0071（1.0 机器学习发布计划）、ADR-0072、ADR-0062、ADR-0059、ADR-0084
- Does not supersede any existing decision.

## Context

[VERSION_PLAN](../../roadmap/VERSION_PLAN.md) 规定 0.10.0 交付 S3、历史成分准备与
可版本化特征/时点数据基础，并要求在实施模型前先完成 HIST 历史关系可行性调查与深度学习
环境资格调查（不能在 0.15 才寻找历史关系）。ADR-0071 已冻结该顺序，但没有定义 0.10
阶段可接受的边界、证据与禁止事项；缺少该边界时，数据扩容、GPU 采购或 HIST 复制容易
被默认授权。

本 ADR 只定义 0.10 的阶段边界与资格门槛，不实现数据扩容、不引入 HIST、不授权 GPU、
不改变运行能力或生产状态。

## Decision

0.10 拆为可独立验收的 Phase，第一个是 **Phase 98（本 ADR）前置资格与数据基准合同**：

1. **数据基准合同先冻结后实施**：除非 `V1_DATA_BASELINE_CONTRACT` 明确标的、区间、
   频率、缺失/停牌/退市口径、时点来源、单位、许可、摘要与覆盖范围，否则不得开始
   特征或模型的规模化实现。禁止用“全市场全历史”代替有限、可测的支持范围。
2. **HIST 只做调查，不做迁移或复制**：`V1_HIST_DATA_QUALIFICATION` 必须给出历史行业/
   概念 membership 的来源、许可、历史可见性、缺口与可用区间。无法证明时登记 `blocked`，
   由维护者明确修订 ADR-0071，禁止静默删除必备项或用当前关系回填历史。
3. **深度学习只做环境资格**：`V1_DEEP_LEARNING_ENVIRONMENT_QUALIFICATION` 必须给出候选
   Python/PyTorch、模型格式、CPU/GPU profile、镜像大小、代表性训练/推理耗时与峰值内存。
   未知项保持 `not_measured`，不根据“包可安装”推定支持；GPU 采购与镜像发布不在本 ADR。
4. **框架中立与边界不变**：复用 BYQ capability registry、领域任务与模型/预测/信号合同；
   Product 仅经 Product API，Agent-to-Domain 仅经 BYQ MCP；DSH 不训练、不推理、不读业务库
   或模型对象；不引入第二任务引擎、第二 Agent harness 或 Community 兼容层。
5. **按边界风险决定是否新增 ADR**：新增信任主体、持久化权威、跨 Plane 调用、外部写权限、
   不可逆迁移、新付费资源或生产拓扑时，实施前必须取得具名 Accepted ADR。同一版本、同一
   信任边界和同一数据/执行拓扑内的普通合同实现可由一个实施 ADR 覆盖，不要求为每个模型、
   profile 或接口重复建 ADR；ADR-0043/0048 的现行限制在本 ADR 下不解除。
6. **证据状态机**：模型/任务/profile 使用 `planned → implementing → qualified →
   release-verified`，`blocked` 必须记录原因；调查结论是规划台账，不改变 runtime 注册表协议。

## Consequences

- 0.10 的产出是合同与调查证据，不是“新模型已支持”；0.11+ 才实施传统模型。
- 数据扩容与 HIST 实施仍受维护者独立授权与既有迁移规则约束（AGENTS 29–33）。
- 调查不产生 Provider 下载、数据迁移、GPU 采购、凭据读取或生产部署授权。

## Alternatives considered

- 直接实现 0.11 传统模型：违反 VERSION_PLAN 的顺序依赖与 0.10 门槛。
- 用现有缓存或当前行业关系代替历史关系：会造成时点泄漏，被拒绝。
- 依赖“包可安装”宣称深度支持：不满足 1.0 验收的资源与数值证据要求。

## Migration / rollback

纯规划与证据交付，无数据迁移、无运行时变更。若调查结论要求修订必备项，须修订
ADR-0071/VERSION_PLAN 并保留原因；本 ADR 可被后续具名 ADR 精确取代。

## ADR-0084 superseding clarification（2026-09-21）

0.10 资格调查仍必须如实产生 `qualified`、`blocked` 或 `not_measured` 证据。外部数据/环境缺口
只阻塞依赖该缺口的功能或发布声明；在不违反数据时点、许可、完整性和安全边界时，不冻结无关
数据合同、维护任务或后续调查。0.10 完成后按 ADR-0084 对 1.0 矩阵执行
`core`/`extended`/`deferred` 具名范围复核。
