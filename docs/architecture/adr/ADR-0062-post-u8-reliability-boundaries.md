# ADR-0062：Post-U8 任务恢复、提交回执和受限续接

- Status: Accepted
- Date: 2026-09-07
- Scope: R1–R5、S1–S3、F1–F10 的 BYQ 边界变更；当前 DSH 保持不变。
- Acceptance: 2026-09-07，维护者明确“确认 ADR-0062方案”，并要求同步修订 ADR-0046 和 ADR-0045。
  本次接受覆盖下述精确边界及整改开发，不构成生产部署或既有研究任务续跑授权。
- Supersedes: ADR-0046 §2 尾部未回答消息丢弃规则及对应验收要求；ADR-0045 的禁止无用户回合
  主动模型执行规则仅按下述有限授权例外修订。其余身份、MCP、Provider、审批边界不变。

## 1. 恢复与失败事实

Gateway 从持久公开消息和规范化 WorkflowTrace 提供 bounded completed history、最近未回答
user turn、公开 failure code、稳定 turn/run identity。Runtime 在新 generation 分区注入这些事实，
当前用户明确新指令优先；同文重试去重。失败事实不冒充 assistant message，不泄露私有推理。
无法唯一恢复主题时要求确认，不能用工作区最新对象填补。服务健康与会话失败独立。

## 2. 活动与生命周期

BYQ public activity 增加可关联回合及 unknown/waiting/cancelled 等必要状态，历史失败可重放。
60秒等待提示只表示系统等待，不续租；同一child的可证明新活动续租180秒 inactivity lease，
child硬上限600秒、根回合900秒。无法关联的事件不得续租。兼容层只读取事件时间和identity，
不公开推理。正常/失败/取消终态统一关闭所属活动与BYQ Agent run，业务job保持独立。
领域状态转换仍通过MCP/Backend合同，不授予DSH数据库权限。

## 3. 接收先持久化

BYQ在安全验证与授权后，先原子保存owner/workspace-scoped提交identity、固定输入和幂等键，
返回稳定operation/job identity；耗时readiness和数据准备由现有可信Worker执行。
请求语义hash排除可变readiness和repair结果。提交重试先查原identity，不重复执行准备副作用。
超时是unknown；精确查询和持久核对有预算、退避、重启恢复，不以列表前100条查不到证明不存在。
不新建通用队列/Agent harness；扩展已有领域任务、lease和通知设施。

## 4. 有限的后台续接授权

用户明确要求完成复合研究任务时，BYQ持久化任务绑定的续接许可；许可只允许恢复原目标、查询结果，
以及执行经现有BYQ策略另行判定已授权的下一动作。单个策略审批不授权所有训练/预测/回测。
缺少动作授权时暂停在审批状态，不能用“自动继续”绕过。

许可绑定owner/workspace/conversation/task及已确认artifact lineage；默认有效期24小时、最多
8次后台模型回合，每次仍受900秒硬上限及原有token/cost预算约束，以先耗尽者为准。
重启不能重置预算；取消任务、禁用用户、撤销许可或过期立即阻止新回合。上述默认值进入合同测试。
用户可查看许可状态和取消；既有运行不自动追溯授权。此次生产会话不自动重新训练或续跑。

可信领域完成事件产生持久通知，BYQ Gateway通过既有Runtime seam消费一次续接意图；
Backend/Worker不直接调用DSH。租约、幂等和ack区分“回合已接收”“动作已确认”“目标已完成”。
重启/重复事件先查现状，unknown outcome先核对再决策。DSH仍负责通用Agent编排。

## 5. 指数池

允许小巴经封闭MCP目录、截至日期readiness、创建和状态查询复用既有index producer；
不开放任意Provider和删除权限。validated import经既有持久任务入队及有界补偿刷新active池；
旧快照不能推进当前版本倒退。历史研究引用保持冻结，持续跟踪与历史一次性快照显式区分。
历史成分准备只扩展已有封闭data-demand/repair，不扩容Tushare dataset目录。

## 6. 验收、实施与停止

先提失败测试及审计清单，分批修复；每批更新合同、Community分类和受影响组件完整tests。
验收当前DSH的合成完整研究、迟到提交、重启、重复通知、跨owner拒绝、授权撤销与时点冻结，
UI须Chrome真实Product API证据。不得以旧版对照替代这些验收。
本ADR已接受，可按上述边界进行隔离、合同优先的整改；接受不代表实现或验收已经完成。
通过ADR不等于生产部署授权，保留独立build、PR/CI和deployment门禁。
