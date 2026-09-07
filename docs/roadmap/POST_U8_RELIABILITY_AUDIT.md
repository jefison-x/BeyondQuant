# Post-U8 可靠性审计执行记录

状态：IN_PROGRESS，2026-09-07。DSH保持0.1.2rc1；Tushare数据扩容不在开发范围。
本记录是实施审计，不代表已完成所有接口检查。范围为既有R/S/F需求。

## 第一批实现：R1 历史运行记录（组件验证，构建认证门禁未通过）

2026-09-07，用户要求先做业务修复，CI分类优化暂缓。本批仅修复失败提示随新回合消失：
失败、取消与迟到丢弃保留为独立运行记录；不混入助手消息、模型上下文或重试命令。
规范化session/sequence去重，闭合错误文案，后续成功不删除历史。
组件与真实浏览器回归通过；整体架构测试因U7.3冻结源码清单漂移仍未通过，不能合并或部署。
后续修复使用独立新构建认证，绝不覆盖历史清单。本条不授权CI规则整改或降低认证门禁。
详见[R1验证记录](../evidence/post-u8-r1/VERIFICATION.md)。R2–R5、S1–S3及F项未因此完成。

## 发现方式与覆盖

第二批本地实现已覆盖 R2 恢复、R3 子会话租约、R5 等待提示及 R4/F3 公开状态切片。
组件与当前 DSH 的 scripted integration、Chrome Product API 投影检查已通过；
持久领域 AgentRun 收口、提交回执/未知结果核对及授权后台续接仍待修复，不关闭整体需求。
详见[本地切片证据](../evidence/POST_U8_RUNTIME_RECOVERY.md)。历史认证构建门禁仍未通过。

`python3 scripts/ci/inventory-reliability.py` 从源码枚举Python routes、MCP tools、Worker入口，
所有项目默认NEEDS_EVIDENCE。挂载路由、动态路由、Gateway catch-all实际映射和Cloudflare
TypeScript handlers需人工补齐后才能声明全量。不得将发现数量当作验证数量。

初始基线枚举结果：413个路由（Backend 227、Gateway 174、Runtime Adapter 10、Signal Sandbox 2），
78个MCP工具、4个Worker入口。全量接口的正确性结论仍为NEEDS_EVIDENCE。

2026-09-07新增指数入口后重新枚举：414个路由（Backend 228、Gateway 174、
Runtime Adapter 10、Signal Sandbox 2）、81个MCP工具、4个Worker入口。
增加的3个指数工具和1个精确核对路由已纳入本次切片检查；枚举仍不等于全量验收。

首轮测试审查发现 `services/mcp/tests/ml-research-test.ts` 明确断言unknownTraining.isError=false，
并只覆盖“提交超时后立即查到”与“立即404”两种结果，未覆盖晚于回合结束才落库和训练完成后的续接。
因此旧测试绿色并不能证明本次链路正确；新增回归必须覆盖迟到commit → 原identity核对 → 下游推进。

## 已确认及修复优先级

第四批本地切片：S1 指数目录/指定日核查、创建、状态及原键精确回执核对已接入封闭 MCP；
协调角色升为 v2.1.0，旧 run 不追溯增加权限。S2 新增 Data Worker 的有界导入补偿扫描，
每轮最多 100 个 active 跟踪池，按 verified 源日期/内容 identity 幂等入队，重启及并发不重复。
readiness 显示源日期、池日期及 stale；界面使用中文状态。原始源、冻结快照均不回填或倒退。
F7 公共 v1/v2 校验辅助器增加值隔离的字段/类别错误，MCP 再次封闭投影，仍未完成持久纠正次数台账。

验证：Backend 完整 335 通过、1 跳过、7 subtests（S1/S2 初始切片）；后续 F7/指数 API 46 通过，
源日期/动态池/API 14 通过，角色升级门禁 6 通过。Gateway 前批完整 122 通过；Frontend 本批
51 files/152 tests、类型检查及构建通过。MCP 完整 17 suites 通过，含隔离真实 PostgreSQL 制品写入。
其中旧契约先因固定 0.1.1 插件版本断言失败；增加显式候选期望版本后通过，旧默认断言保留。
Chrome 仅在 18261 合成栈验收：两行虚构权重经真实校验器导入→202 创建→可信单次物化；
20260731→20260831→20260904 补偿刷新每次 1、重复 0，历史三份快照保留。源先更新时显示待更新，
刷新后显示已就绪；桌面/390×844 无溢出，最终 Console 空，13 个网络请求均同源 Gateway/Product API。
测试脚本首次误用缺少 /paper 的 Product 路径得到 404，未造成写入；纠正后才验证真实创建。

未宣称完成：新增指数工具的真实模型语义验收、S3 历史需求准备、领域 AgentRun 收口、持久未知核对、
复合研究目标/续接及全量接口审计仍未结束。独立构建认证门禁仍待通过，无生产部署。

第三批本地切片：ML 提交先保存 `ml-training-submit.v2` 回执，再由既有 ML Worker
执行覆盖评估和补齐排队。不可变请求语义排除 readiness、修复结果及最新证券主数据身份；
去重后的第二请求键有持久关联，重启后可精确查询，跨 owner/workspace 拒绝。
补齐轮询不重置 failed/completed 修复请求；并发相同需求返回同一修复身份。
MCP training_get 支持原幂等键精确核对，404 仍为 unknown；损坏回执也触发核对。
Gateway 写请求断连、5xx、损坏回执均投影 operation_outcome_unknown，显式 4xx 拒绝保持不变。
Backend ML/data-sync/data-demand 50 项、Gateway 完整 122 项及 MCP ML 编译/翻译测试通过。
其中测试准备阶段曾发生容器构建权限及未配置契约服务错误，不能算完整 MCP suite 通过。
持久退避核对、任务续接、提交与股票池引用的原子性、Worker 准备领取租约仍待关闭；
本条不代表 F1/F2/F10 完成，也不代表新构建认证或部署完成。

| 顺序 | 缺陷 | 代码证据 | 计划 |
|---|---|---|---|
| 1 | 未回答主题丢弃 | Gateway `_conversation_context`；ADR-0046 原 §2 | R2；ADR-0062已接受，待合同优先修复 |
| 1 | 活动失败/未知误标 | AgentActivityPanel、ml-research outcome_unknown isError=false | R1/F3；合同与UI联测 |
| 1 | 固定child截止、领域active不收尾 | Runtime `_enforce_run_guards`、生产盘点 | R3/R4/F10 |
| 2 | ML准备先执行、提交后落库 | Backend `create_ml_training_run` | F1；异步化并先登记identity |
| 2 | 仅一次核对，迟到结果丢链 | MCP `createTrainingWithReconciliation` | F2/F6；持久核对 |
| 2 | 审批submitted不代表完成 | Gateway `_continue`相关入口、Agent审批状态 | F4/F5/F6 |
| 2 | ML错误反馈过于粗略 | MCP `requestMl` 422处理 | F7；封闭字段错误 |
| 3 | index创建未接Agent，导入不触发刷新 | MCP `byq_pool_create`、stock_pool_producer | S1/S2 |
| 3 | 历史成分缺口 | 中证500仅2026年三份verified样本 | S3；不扩展新数据集 |

所有其他接口的8秒等待只是审计线索，尚未断言存在同样缺陷。读写授权、幂等、超时、
业务状态、通知及恢复逐项检查；后续批次在此记录VERIFIED_OK或CONFIRMED_DEFECT的证据。

第二轮源码审查新增两项CONFIRMED_DEFECT（代码路径证据，尚无本次生产重复写入证明）：

- Gateway `product_create_research_task` 每次POST新建UUID并用作幂等键，忽略调用者稳定请求身份。
  同一用户请求在响应丢失后重试会变成新的后端身份，需补稳定客户端请求键及scope/冲突测试。
- Gateway `_backend_request` 把所有transport errors合并为503 backend_unavailable，不区分读请求失败
  与写请求结果未知；且成功响应的JSON解码不在异常处理范围内。需闭合unknown与invalid-response投影，
  不能向用户暗示写入未发生。Factor MCP也有无结果核对的写超时路径，领域副作用需继续检查。

## Community检查与分类

### F2/F3 全MCP写传输未知结果分类（2026-09-07）

策略、回测、研究记录、因子计算、数据需求、反馈、Agent审批/审计及Learning共8类写适配器
补充统一分类：断连、5xx、成功HTTP但JSON损坏/非对象均为`outcome_unknown`，不自动重试，
保留有界原幂等键并要求精确核查；不传播原始异常或代理页面。原401/403/404/409/422/429
仍是明确拒绝；只读请求不可用不误标为未知写入。股票池及ML沿用前批对应修复。
网页证据写入5xx不再声称“未保存”，因为提交可能已经发生。

统一模块只分类传输结果，不新增队列、执行器或工作流。`isError=false`表示返回了可解释
的结果分类，不表示领域成功；public normalizer按`status=outcome_unknown`显示未知状态。
MCP完整18套契约通过，新增矩阵覆盖8类写×5类未知响应、8类×6类明确拒绝和7类只读失败；
每例断言仅一次请求。真实MCP契约写入仅发生在隔离合成研究记录，不访问付费模型。
持久核对台账/退避/预算及下游续接仍待完成，不据此关闭整个F2或全接口审计。
后续检查补齐ML非训练创建写入口（策略、审批、预测、取消）的同类分类；训练创建保留
原幂等键的精确核对步骤，不因返回可解释unknown而提前跳过。无网络矩阵扩为9类写、
8类读并通过；ML训练/预测翻译契约同时通过。

### 研究任务创建的稳定请求身份（2026-09-07）

Gateway接收有界ASCII `x-idempotency-key`，与可信owner/workspace派生稳定Backend身份；
相同请求重试不再生成新UUID。Backend任务创建加事务认领锁，跨进程同键提交返回同一任务，
同键不同内容继续拒绝。未带键的旧客户端保留兼容，不宣称其可以安全盲重试。
研究页面在首次提交前持久保存本用户/工作区的原请求及随机键；unknown期间不允许换对象，
刷新恢复原字段，“核对本次提交”复用原键；显式输入拒绝可修正，未知结果不清空记录。
浏览器记录不代替Backend任务或全服务持久核对台账。

Gateway完整123通过、Backend research/API 9通过（含独立store并发）、Frontend52files/156tests
与类型/构建通过。Chrome使用18261隔离合成账户，真实Product POST完成后故意丢失回执；
刷新恢复原请求，同键核对得到原`task_8cd1ae8c3d664f47b5389efd0de4267f`且列表精确计数1。
浏览器发现unknown期间的空态仍鼓励创建，已改为未知提示；网络原始错误改为封闭中文文案。
首次浏览器路径误用`/research`为404页面，未创建任务；正确路径为`/user/research`。

集中Backend完整回归：342通过、1跳过、7subtests通过，1项失败为Phase58旧角色版本
固定断言2.0.0，与本次已接受的协调角色2.1.0不符；更新当前合同断言后需单独复验。
此处保留失败事实，不将这次完整回归标为全绿，不修改历史认证报告。
后续Phase58领域流程和Agent研究/API定向复验9项通过。
最终浏览器构建再次注入回执丢失，封闭中文提示生效；刷新后原请求恢复，精确任务计数1、
确认后本地pending清除。桌面和390×844无页面溢出，最终Console为空，12个请求均为
同源Gateway/Product API（含Gateway会话兼容路由），没有Backend/MCP直连或模型调用。

### F1 训练回执与股票池引用原子性（2026-09-07）

`ml-training-submit.v2`在同一Backend事务内登记训练记录、提交幂等映射和股票池引用。
引用登记复用Paper领域校验，锁定所属股票池以与生命周期变更串行，并拒绝引用身份
指向另一个快照；同一引用重试不会增加计数。历史receipt不批量改写。
故障测试在引用插入后主动抛错，要求三类记录均回滚；之后同键提交成功且引用唯一。
隔离Backend ML API、训练与Paper领域测试37项通过。
这关闭新v2提交的分裂事务路径，不代表Worker准备租约、历史缺口修复或全部F1完成。

### F1 Worker准备认领与迟到结果隔离（2026-09-07）

现有ML Worker准备入口在扫描/构建前领取数据库随机凭据，10分钟租约在有界准备阶段
之间检查并续期；同一任务的并发Worker不能同时领取有效凭据。readiness、repair引用、
失败与queued转换都校验相同有效凭据和waiting状态。取消或过期后旧结果不能复活任务。
过期认领最多恢复两次，第三次失联终止为`ml_preparation_recovery_exhausted`；计数持久化，
重启或旧请求的finally释放不能清空计数。正常等待数据的轮询不消耗失联恢复计数。
准备凭据、有效期和内部计数不进入公开训练响应；不改变实际训练Worker已有执行租约。
隔离Backend训练与ML API测试26项通过，覆盖重启、迟到成功/失败、取消、重复领取、
三次失联预算耗尽与公开响应无认领凭据。

取消检查发生在阶段边界；已开始的数据修复或不可中断的特征计算不会被假称立即撤销。
这些迟到结果不允许推进已取消训练。不可中断阶段的资源释放和完整Worker制品认证仍需
后续集成验收，不能由组件测试替代。

### F5 审批续接认领隔离（2026-09-07）

审批续接的30秒过期认领原先没有代次隔离，旧请求迟到的提交/失败回执可以覆盖
重新认领后的状态。现由Backend在事务锁内递增持久`continuation_attempt`；Gateway
必须持有本次认领序号才能确认提交或失败，缺失序号在启动续接前拒绝，旧序号无权更新。
序号只用于内部协议，不进入Product审批投影。`submitted`仍不等于领域动作完成。

隔离验证：Gateway全套123项通过；Backend agent research/API 8项通过，包含存储重启、
过期重新认领、旧成功/失败回执、缺失认领序号与授权状态不误标完成。
这仅关闭认领覆盖缺陷，不关闭Adapter重启后的提示幂等、持久结果核对、F4/F6或完整F5验收。

只读检查 `BeyondQuant-community/agent-service/app/harness/workflow.py`：
保留“阶段从持久artifact/approval派生”语义为REFERENCE_ONLY；不复用旧repository/runtime。
其失败后 `retry_with_new_idempotency_key` 不适合unknown outcome，分类DROP；
其捕获所有异常返回空数组不能用作数据不存在证据，分类DROP。
后续涉及具体领域或UI前继续检查对应实现并更新正式migration inventory。

## 架构门禁

2026-09-07 R2 本地切片：Gateway 已分离未回答主题与失败事实，Runtime 新 generation
一次性消费、同文去重、明确新指令优先，歧义短续接在启动前拒绝。
Gateway 103项通过；当前 DSH Runtime 默认 suite 79项通过、2项真实 MCP 进程测试未启用。
合同及限制见 [conversation recovery](../contracts/conversation-recovery.md)。
状态为 COMPONENT_VERIFIED_INTEGRATION_PENDING，未部署、未认证发布制品；
R2 端到端模型语义、R3–R5、S1–S3及领域提交/续接整改不能据此关闭。

2026-09-07，维护者明确确认ADR-0062，并要求同步修订ADR-0046和ADR-0045。
ADR-0062现为Accepted：ADR-0046原先的未回答消息丢弃规则已被保留、分区恢复与去重规则替代；
ADR-0045仅增加有任务绑定许可、24小时/8次回合预算和逐动作授权的后台续接例外。
其余MCP、Provider、身份与审批边界不变，不追溯授权既有生产研究，不授权部署或数据扩容。
架构接受门禁已解除；下一步为失败合同测试与分批实现，尚未宣称代码修复或验收完成。

## 本次交付授权与顺序

2026-09-07，维护者在“先合并U8收尾，再合并ADR与审计记录，再从更新后的main建立修复分支”
的明确建议后回复“好的,按顺序开始做.”。本次授权覆盖上述文档/审计分支的push/PR和
CI-green合并；按ADR-0015/0059执行精确head门禁，不直接push main、不绕过检查。
后续修复开发保持独立工作树、合同优先和逐批验收。该授权不包含生产部署或历史研究续跑。
