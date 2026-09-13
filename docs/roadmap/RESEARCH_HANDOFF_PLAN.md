# 研究流程连续性整改计划

2026-09-13，维护者要求将简化流程图写入 README，结合剩余整改制定目标并继续优化。
本次属于独立维护，Product Phase 97 不变；不采用 DSH 原生长流程迁移，不建立第二套通用 Harness。
遵循 Accepted ADR-0062/0065/0067/0072。本次授权为开发；发布、合并、部署按开发流程另行执行。

## 问题与目标

最近审计发现：策略审批后，DSH 回合正常结束，ResearchTask 仍为 running，下一步文字写着创建回测，
但没有实际回测 job、下一动作审批或任务后台续接许可。回合没有超时，任务却没有执行者。
因此服务健康、回合 completed、审批 authorized、续接 submitted 均不能替代研究目标完成证据。

目标是让每次交接都有可核对的原目标、确切对象、已完成证据、剩余步骤与下一执行条件。
DSH 决定研究步骤，BYQ 强制业务授权、持久事实和续接准入；不将业务不变量交给提示词保证。

## 执行顺序与验收

| 批次 | 原整改对应 | 交付目标 | 验收条件与当前状态 |
|---|---|---|---|
| H1 审批后原目标交接 | F4/F5 | 修正“只做批准动作”的指令；要求精确 lineage 回读原任务、评估剩余目标并如实交接 | 本批实现指令层改进；重启重投、丢回执、拒绝分支回归。模型实际遵循及完整研究闭环尚待隔离验收 |
| H2 持久任务交接 | F3/F4/F5/F10 | 基于任务、审批、job 和投递事实区分完成、待审批、待作业、缺许可、已排队、阻塞；原目标及对象不靠聊天摘要猜测 | 本地实现与验收通过，见[H2记录](../evidence/research-handoff-h2/AUDIT.md)。基于持久事实识别交接状态；不改变原 lifecycle，不自动启动 H3 |
| H3 授权续接闭环 | 复用已交付 F6，补 F4/F5 连接 | 在已确认任务及许可下将交接接入现有投递、预算、取消与回执机制；不新增通用调度器 | 本地接入初次许可交接及策略审批动作完成；无许可、重复、撤销、未知回执等门禁通过回归，见[H3记录](../evidence/research-handoff-h3/AUDIT.md)。完整模型研究链留 H5 |
| H4 未决提交与错误反馈 | 剩余 F1/F2/F7/F8 | 按全接口清单逐项补写前持久化、原键核对、有界纠错和合同一致性 | 待逐接口补齐。不能把 ResearchTask/Experiment/Artifact 已完成切片算作完整 F2；不能把首两个工具算作完整 F7 |
| H5 数据准备与完整研究验收 | S3、F9/F10 回归 | 补历史指数成分准备及 readiness 说明；验证长研究三轮回测、选优和模拟账户链条 | 待实现/验收。无历史成分证据不能假装可研究；以隔离真实 Product API、持久结果和浏览器证据验收，不触发历史生产研究 |

H2/H3 实施前先确定闭合的任务交接合同及失败测试；若触及现有 ADR 未覆盖的边界，先补 ADR。
不能靠 H1 提示词宣布流程断裂已解决。后续模型模块和 1.0 稳定性门槛继续按 VERSION_PLAN 执行。

## 既有整改如何保留

以 POST_U8_RELIABILITY_AUDIT 的具名最新验收为准，历史章节不覆盖后续修订：

- F6 已完成范围保留，H3 是连接缺口，不能把已有预算/取消/幂等保障撤销或重新宣称全新完成。
- 已交付的原键核对、审批资源绑定、422 指引与轮询退避继续保留。
- 完整 F2、S3、全接口审计尚未关闭；F1–F10 的验收要求按上表归并，不因架构选择而撤销。
- 根/子默认总时长硬终止已取消；15分钟进度检查及新许可最长24小时遵循 ADR-0072，
  不恢复旧的15/10分钟默认硬终止，也不把进度检查当成自动续接许可。

## 本批实现范围及验证

H1 只调整 Gateway 发给 DSH 的审批交接指令。稳定审批 ID 仍是投递幂等键，
不把可变任务进度拼入该键对应的请求；原任务必须经 MCP 按确切 lineage 回读。
拒绝分支不执行被拒动作；批准后的额外动作仍受现有领域审批约束。
本批不修改业务状态机、后台调度、数据库或前端，不回填历史任务许可。

独立构建标识为 `dsh-0.1.2rc1-post-u8.52`，历史 `.51` manifest 保留。
本地验证：

- `make dev-check` 通过，隔离工作树校验及 `.52` manifest 校验通过。
- Gateway 审批准入、任务续接投递及许可定向测试：32项通过。
  使用现有 `.42` Gateway 镜像仅提供依赖，完整挂载本工作树当前源码，只读、无网络且自动删除测试容器；
  这不是 `.52` 镜像构建或发布资格证明。
- 架构 unittest discovery：124项通过；未声称包含仅由 pytest 收集的额外测试。
- 初次临时 Python 环境缺少 pytest/pip，未执行测试，随后改用上述隔离容器完成验证。

未调用真实模型、未执行生产任务、未做浏览器验收；本批没有 UI 改动。
远端受影响组件完整 CI、`.52` 镜像构建和完整研究自动闭环仍待后续验证。

## H2 本批进展

2026-09-13：只读持久事实交接、MCP 原任务详情和 Product 页面已完成本地验收，独立构建编号 `.54`。
具名范围与限制见[验收记录](../evidence/research-handoff-h2/AUDIT.md)。H3 为下一项；H4/H5 保留。

最终自查将研究资产/审批目录的状态列恢复原样，只有任务目录显示“未完成”。
`.53` 是本地浏览器验收候选，保留不可变清单；`.54` 包含这两处标签范围修正，后端和交接面板行为相同。

## H3 本批进展

2026-09-13：新许可有限交接已复用 F6 投递；旧许可不扩展触发，后台工具范围不变。
同时修复 HTTP 环境下许可面板无法打开。下一项 H4：剩余接口提交/核对及错误反馈。

## H4 第一切片

2026-09-13：修复 HTTP 研究创建入口的提交标识生成，保留持久凭据和原键重试。
[本地证据](../evidence/research-handoff-h4/AUDIT.md)；H4 总范围仍进行中，真实浏览器合并证据待补。

H4 第二切片：原键核对的 Experiment/Artifact 回执须与原任务一致；[证据](../evidence/research-handoff-h4/RECEIPT-LINEAGE.md)。完整接口审计仍进行中。

H4 第三切片：三类研究对象按 ID 读取及已确认回执回读均拒绝错对象；[证据](../evidence/research-handoff-h4/EXACT-READ.md)。全接口剩余审计保留。

## H4 集成验证

完整 MCP 测试、17项数据库回执恢复与真实 HTTP 创建浏览器验证通过；[未决接口族及证据](../evidence/research-handoff-h4/INTEGRATION.md)。H4仍未关闭。本轮维护者接受统一推送及远端CI，创建Draft PR；不包含合并或部署。

H4 因子提交：原键锁内复用规范化结果，避免成功重试/并发重复计算；未知回执提供原任务Artifact核对。见[证据](../evidence/research-handoff-h4/FACTOR-RECOVERY.md)。

H4 继续：四类实际HTTP提交的丢回执/Backend重启/新进程原键只读恢复通过，见[CROSS-PROCESS](../evidence/research-handoff-h4/CROSS-PROCESS.md)。策略版本内容去重新增每个原键的持久回执，见[STRATEGY-RECEIPTS](../evidence/research-handoff-h4/STRATEGY-RECEIPTS.md)。

H4/H5 数据修复重复请求：完整已验证指数月份可复用缓存，缺失月份才取数，证据损坏停止。
[验收与真实覆盖缺口](../evidence/research-handoff-h4/INDEX-REPAIR-CACHE.md)；H5完整研究尚未完成。

H4 因子有界纠错：完成独立官方观察资格、持久计次、同事务结果回执和原生停止接入，
见[FACTOR-CORRECTION](../evidence/research-handoff-h4/FACTOR-CORRECTION.md)。H4全接口及H5继续执行。

H4/H5前置数据需求恢复：需求及修复引用原子提交，重试复用冻结计划并支持原键只读核对，
见[DATA-DEMAND-RECOVERY](../evidence/research-handoff-h4/DATA-DEMAND-RECOVERY.md)。历史指数范围尚待接入。

H5历史单次指数快照准备已接入既有data-demand/Worker/Product页面，并完成合成数据下真实浏览器
丢回执恢复→准备→创建→物化；[特性清单及限制](../evidence/research-handoff-h5/INDEX-PREPARATION.md)。
真实历史来源和完整模型研究仍待验收，H系列不因此关闭。

H4 股票池创建已补持久原键及刷新恢复，见[POOL-RECOVERY](../evidence/research-handoff-h4/POOL-RECOVERY.md)。
H5已验证真实沪深300三个月缓存及实际Worker无外部取数完成；单次真实范围来源通过，
三年调仓覆盖与完整模型研究仍未完成。

H4 学习运行/迭代/评估信号/经验提案已补原键核对，最后一轮回执丢失可恢复，
见[LEARNING-RECOVERY](../evidence/research-handoff-h4/LEARNING-RECOVERY.md)。总范围继续进行。

H4 反馈草稿及原命令核对已接入，真实浏览器刷新恢复不重复创建；
见[FEEDBACK-RECOVERY](../evidence/research-handoff-h4/FEEDBACK-RECOVERY.md)。全接口映射与H5继续。

H4 六类领域对象的实际HTTP丢回执→Backend重启→新MCP进程原键GET恢复通过，
持久数量无重复；见[CROSS-PROCESS补充](../evidence/research-handoff-h4/CROSS-PROCESS.md)。

H4 模拟账户并发资金校验及换绑/订单原键恢复已修复，
见[PAPER-ORDER-SERIALIZATION](../evidence/research-handoff-h4/PAPER-ORDER-SERIALIZATION.md)。其余模拟命令恢复继续。

H4 模拟账户六类命令原回执及页面刷新恢复通过；账户创建、下单连续两次丢回执后
只读找回原结果，未重复扣款，见[PAPER-COMMAND-RECOVERY](../evidence/research-handoff-h4/PAPER-COMMAND-RECOVERY.md)。
账户导入、剩余接口映射和完整H5模型研究继续。

H4账户导入已补原键事务回执、摘要键及真实浏览器刷新恢复，见[PAPER-IMPORT-RECOVERY](../evidence/research-handoff-h4/PAPER-IMPORT-RECOVERY.md)。

H4回测及派生任务、信号快照的精确ID读取和原键未知结果指引已补齐，见[BACKTEST-EXACT-READ](../evidence/research-handoff-h4/BACKTEST-EXACT-READ.md)。

H4模型绑定同版本并发覆盖已修正，逐接口结论台账起稿37项；见[MODEL-BINDING-CONCURRENCY](../evidence/research-handoff-h4/MODEL-BINDING-CONCURRENCY.md)。剩余接口仍继续核对。

H4 凭据原提交回执、并发创建与浏览器刷新恢复通过，后续重试拒绝不再清除先前未知记录；见[CREDENTIAL-RECOVERY](../evidence/research-handoff-h4/CREDENTIAL-RECOVERY.md)。
