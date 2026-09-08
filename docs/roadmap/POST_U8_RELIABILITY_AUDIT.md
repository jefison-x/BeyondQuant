# Post-U8 可靠性审计执行记录

状态：IN_PROGRESS，2026-09-07。DSH保持0.1.2rc1；Tushare数据扩容不在开发范围。

## 合并后的第二批恢复整改（2026-09-08）

维护者明确“授权提交合并”后，第一批修复通过平台门禁合并；随后明确要求继续整改。
本批从同步主线建立独立工作树，修复迟到回答关闭新问题、未回答主题混入已完成历史、
缺本轮起点误借旧成功回合身份三个恢复问题。证据及保留失败见
[迟到回答恢复](../evidence/post-u8-r1/LATE-ANSWER-RECOVERY.md)。
最终独立 .5 构建本地 CI 26/26 通过，Gateway 191、架构214、真实 Product API 浏览器9项通过，
scoped cleanup 后资源为零。构建和整体业务验收分别记录；F7 台账、S3、F6 及 UI 完整锚定仍未关闭。
本批开发不继承前一 PR 的单次合并授权，也不部署或恢复历史研究。

## 本轮测试范围修订（2026-09-07）

维护者明确要求：“Deep seek API测试相关内容跳过。”
本轮Post-U8整改不调用DeepSeek API，不再等待或申请此前提出的新增合成场景20元付费评测授权。
相关验收项记录为 `SKIPPED_BY_MAINTAINER`，不是PASS；历史评测、失败报告及认证保持不变。
维护者随后明确“就算通过了”，本轮将该项记为 `WAIVED_BY_MAINTAINER`（维护者豁免、门禁放行），
不再阻塞剩余整改；未执行的测试仍不记录为测试PASS，也不改变历史认证结果。
继续执行无密钥合同、隔离数据库、模拟Provider、官方本地进程及Chrome/Product API验证，
但这些证据不能代替真实模型对研究对象恢复、指令遵循和完整目标达成的语义验证。
该范围修订不改变剩余业务修复范围，不授权生产部署、历史研究续跑、训练或数据中心扩容。
本记录是实施审计，不代表已完成所有接口检查。范围为既有R/S/F需求。

2026-09-07 后续具名补充：维护者明确“最后的功能验证可以在关键点调用付费api”。
本次AgentRun收尾允许有限付费关键点验证：仅合成用户/固定注册提示及测试工具上下文，
最多2次模型请求、每次最多512输出token，唯一允许工具为合成AgentRun注册；不调用研究、
数据、训练或回测工具，不发送生产对话/用户数据，不向模型内容发送密钥。其他未执行
API场景仍保留上述豁免状态；本次实际结果单独记载，不覆盖历史测试或认证。

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

### F5 续接未知结果不重发与有界核对（2026-09-07）

进一步审计发现：旧submitting认领过期可重领、Gateway超时标failed以及页面无限重试组合，
可能在Adapter重启丢失内存幂等记录后重复执行。现30秒失联只转outcome_unknown且不重领；
明确未接收的重试最多8次并持久计数，耗尽needs_attention。相同attempt的真实迟到ack仍可确认，
旧attempt不能覆盖。此条修订本记录早前“过期重新认领”切片，保留此前测试历史，不追改证据。

Gateway要求有效accepted/run_id回执；5xx/损坏响应先精确查询原session/key/content摘要，
找到才标submitted，否则保留unknown。Runtime新只读prompt-receipt.v1不返回原文本；重建或缺失
内存记录只表示unknown，绝不证明未执行。页面最多8次检查，unknown/exhausted立即停止重发，
会话切换或卸载后不应用迟到结果。细则见[approval continuation reliability](../contracts/approval-continuation-reliability.md)。

Backend agent10项、Gateway完整128项、Runtime完整86通过5跳过；Frontend完整52文件160项，
追加卸载测试后AgentView13项通过，类型检查/构建通过。隔离Backend/Gateway/Frontend构建通过。
Chrome使用隔离库“已拒绝动作+unknown续接”夹具，不授予动作、不调用模型：真实Product继续
请求只返回unknown，不发起Runtime prompt；页面显示不会自动重发，跨多次检查continue请求总数
保持1，desktop/390×844无溢出，Console为空。未执行生产审批或训练。
接口枚举418 routes、81 MCP tools、4 Workers；新增1个Runtime只读回执路由。
持久Adapter回执、F4目标阶段/关联对象、任务绑定F6及完整F5/F10仍未完成，未宣称整体验收。

### R4/F10 恢复进程的权限隔离前置切片（2026-09-07）

官方已安装0.1.2rc1 `Session.run(input, on_notification=...)`未提供逐回合MCP header参数。
此前BYQ_DSH_RUN_ID固定为整个会话ID；现改为每个owned process新建的BYQ generation identity，
与DSH私有session ID分离、不进入公开Runtime响应。Backend授权/新审批必须匹配可信会话和generation；
子运行还必须匹配活动父运行的actor/session/generation，不能跨恢复进程继承旧父运行。
既有审批的人工决定和精确读取仍允许在恢复后查询，不把旧授权自动扩展给新动作。

验证：Backend agent API/领域9项通过，Runtime完整86通过5跳过；开启真实官方进程和本地脚本
Provider的恢复/工具边界/子角色检查11项通过，无付费模型调用。首次Runtime测试因只读父挂载内
缺少子挂载目录未启动，改为各目录单独只读挂载后运行通过。
此identity是process generation而非root turn，尚不能据此关闭同进程中全部历史AgentRun。
逐回合终态持久化、迟到ack和F4/F6仍待实现；不把这项前置隔离宣称为R4/F10完整修复。

### F2 ML 持久回执核对切片（2026-09-07）

MCP/Gateway 在训练写请求前登记绑定 owner/workspace、原幂等键和固定研究对象的核对记录。
登记结果不明则不发送训练；已登记但未确认则只查询原结果，不再次发送训练。既有 ML Worker
负责精确数据库查询，最多8次、持久退避和24小时截止；重启不清预算，耗尽显示需要人工检查，
不能宣称任务不存在。真正训练回执提交与核对确认在同一事务；迟到回执仍可确认。
明确4xx拒绝必须匹配原固定请求身份，不允许换对象的失败请求误标原提交。
页面持久保存原提交键，恢复时只核对；确认框期间切换研究/股票池会阻止写入。

组件证据：Gateway125项、Frontend52文件158项、MCP训练/预测与9类写结果矩阵通过；
Backend ML API/训练26项通过，追加身份拒绝隔离后重跑26项通过（31.39秒）。
Backend/Gateway/Frontend/MCP隔离构建通过。重新枚举417 routes：Backend230、Gateway175、
Runtime Adapter10、Signal Sandbox2；81 MCP tools、4 Worker入口。枚举仍不是全量验收。

Chrome只在18261合成栈通过Product API创建未批准的策略定义，目录刷新与390×844布局通过，
无页面溢出、Console error/warn为空。尝试通过未审批训练请求验证拒绝回执时被安全审查拦截，
未执行该请求、未绕过、未启动训练；所以不得把本次浏览器检查作为回执恢复完整验收。
真实回执持久化、并发、重启和预算测试使用隔离测试数据库；浏览器恢复验收仍待授权安全路径。
其他领域未知结果核对、完整Worker制品、F4/F6、R4持久AgentRun及新构建认证仍未完成。
合同见[ML submission reconciliation](../contracts/ml-submission-reconciliation.md)。

后续安全浏览器路径：仅在隔离库登记具名watch夹具，训练记录计数为0；不调用训练POST或Worker。
Chrome经真实Product GET读取awaiting_receipt；将同一夹具截止时间置为过去后，刷新重选显示
needs_attention，既不宣称失败也不宣称已提交。原“只核对”按钮复用训练函数被审查拦截后，
进一步拆为纯查询处理函数；原键缺失时也不得进入训练，主入口同样fail closed。
追加前端完整52文件158项通过、类型检查/构建通过。最终Chrome点击纯查询按钮只产生
原键reconcile GET（另有全局审批GET），无训练POST；桌面/390×844无溢出，Console空。
这是持久查询状态与UI的真实集成证据，不替代被拦截的训练提交端到端验收。

### F8 业务指令与接口一致性（2026-09-07）

F3普通消息回执追加：原普通回合接口不检查accepted/有效run ID就返回accepted=true，且
保存消息缺少稳定identity仍启动Runtime。5项无效/丢失回执失败测试与1项缺少消息identity
失败测试复现。现在无消息identity先停止；无效或不明prompt回执仅精确GET一次原消息键，
确认后返回原run，否则安全中文prompt_outcome_unknown，绝不重复POST。
审批续接共用run ID校验。Gateway完整134项通过（1.20秒）；前端API/AgentView23项通过，
证明未知结果保留原问题、区别于维护拒绝且不自动重发。未执行真实模型或生产请求。

当前仍为IN_PROGRESS：R4/F10逐回合持久AgentRun绑定与收口、F6任务绑定受限主动续接、
非ML持久未知结果核对、全路径持久纠错预算、S3历史需求排队及缓存迁移、独立构建认证和
真实模型完整旅程仍需收口。Process generation不能代替root turn，不按session或时间猜测关闭
历史AgentRun。新增Post-U8合成提示不在原固定G1–G6付费许可内，尚未调用；生产保持不变。

S3历史模式切片：新增明确的historical_snapshot创建模式，原请求日期写入定义并使用once调度；
新成分不会自动推进，也不能通过手动刷新改成另一日期。readiness按冻结日期核对，避免误报
“当前成分落后”。默认follow_index和原请求哈希兼容，既有池不追溯改变。
失败优先1项复现模式缺失；生产器/股票池闭环/动态存储7项通过（10.33秒），MCP构建及股票池/
研究合同通过。没有Provider调用。历史数据需求排队、Community缓存实际证据检查与逻辑迁移、
页面明确模式展示及合成完整旅程仍未完成，本项不代表S3整体完成。

F4 持久阶段切片：原API无证据completed返回200，阶段字段被422拒绝，2项失败测试复现。
现有ResearchTask新增可空progress字段；原transition记录stage/next_action/blocker、同任务
Artifact/Experiment引用及validated完成证据。终态不能新写阶段；未知/跨任务引用拒绝；
未完成Experiment/ML训练/预测/回测阻止generic API完成。模型回合终态不修改研究状态。
原记录不追溯变更；此证据校验不等于证明投资结论语义或完整用户目标已经达成。
MCP传输与协调角色指令已更新，专业子角色仍不得越过allowlist。

F4验证：受影响Backend23项通过；新隔离Backend制品完整359通过、1跳过、7 subtests通过
（399.07秒）。MCP构建/研究契约通过；Frontend53文件164项通过、类型/构建通过。
Chrome18261经真实Product GET读取合成blocked阶段和下一动作，刷新后保留，桌面和390×844
无页面溢出、Console error/warn为空。该夹具不启动模型、审批、训练或回测；生产未部署。
F4任务到conversation自动绑定、端到端模型遵循、F6受限主动续接和R4持久终态仍未关闭。

来源引用追加切片：原通用接口按dict读取、合同实际为list，导致股票池登记不执行；
四类跨owner引用也未校验。纠正workspace夹具后，5项失败测试完整复现。
现在在单一事务验证固定领域引用、登记多个股票池快照、保存Artifact，原键认领串行化。
注入登记后异常证明Artifact与引用均回滚；重复原键保持同一回执。研究API/Store及股票池
闭环22项通过（28.67秒）。历史产物不追溯修改；描述性来源标签不被视为可信领域授权。

追加通用研究写入口检查：五个 mutation 缺少可信 owner/workspace 校验，失败优先测试
得到5项失败；通用 Artifact 还可自称策略/审批/模型等可信 producer 类型，追加测试失败。
现已强制可信身份、所属范围和 typed producer 边界；普通笔记/证据仍可创建，专用领域
生产路径不受影响。Backend 完整351通过、1跳过、7 subtests通过（393.49秒）；
MCP 构建与18组测试通过。仅隔离合成数据，未执行生产审批、模型训练或部署。
来源引用的跨对象校验与原子股票池登记仍需下一切片，不把入口校验视为F8全部完成。

删除ML角色“审批后重查workspace列表”的旧路径，要求原run/key、固定研究对象和明确类型；
列表只能提供肯定证据，不能证明不存在，未知引用不得替换为最新对象。补充watch四类状态语义、
ML与规则策略kind/schema分流，以及“回合结束不等于用户目标完成”的公共角色合同。
这是现有DSH业务指令修订，不增加工具/角色权限，不是新harness或真实模型语义验收。
指令/能力合同6项通过；连同修正后的市场角色架构断言7项通过。

本次完整架构检查106项首次为1失败6错误（6项只读环境无法创建临时目录）；允许测试临时写入
重跑后为1失败1错误：失败是Phase59错误地断言root旧2.0.0而非market角色，已改为具体market
角色1.4.0并定向通过；错误是冻结构建清单检查在模拟docker之前拦截，因而没有calls文件。
后者保留待独立Post-U8构建认证，不修改历史manifest、不降低构建检查，未宣称架构全绿。

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

R4/F3 批次结果遗漏切片：BYQ 的0.1.1/0.1.2 compatibility代码均只选首个tool-result，
同批后续公开活动未收口，2项失败优先测试复现。现逐call ID转换，每项保留各自状态，
隐藏控制/无效/重复结果不影响后续项，重复回执无重复终态，原公开字段和数量上限不变。
不修改或回退DSH，不把此代码复现认定为历史生产会话的唯一根因。
Runtime 完整95通过、5跳过（0.72秒），含混合隐藏/无效/重复结果与重放去重，未调用API。

R4 终态身份前置切片：Runtime 显式携带捕获的原 root run ID，覆盖正常完成、模型失败、
软/硬取消、看门狗超时、活动进程关闭及软取消迟到结果；同一进程连续两轮身份不混用。
新增用例初次5项失败复现缺失身份；修复后 Runtime 完整默认93通过、5跳过（0.79秒），
跳过项未当作通过，未调用 DeepSeek API。此切片不关闭 Backend AgentRun 持久绑定整改。
Gateway 追加同一会话两轮终态身份的 TraceStore 重开重放验证，完整135通过（1.28秒）；
仅本地模拟/持久化组件测试，不证明跨服务 AgentRun 终态消费者已实现。

R4/F3 活动额度及跨轮清理切片：达到256条后普通结果被丢弃，而取消收尾反而可生成未展示
活动并突破上限，2项失败测试复现；下一轮reset遗忘无回执活动，另1项失败测试复现。
现为已展示活动预留收尾额度，重复/隐藏项不生成终态；新一轮先将旧轮遗留公开步骤标记unknown。
不修改领域Job状态、不将丢失回执当成功、不重放操作。
Runtime 完整98通过、5跳过（0.78秒），未调用API。

R4/F10 持久收尾组件：已建立注册摘要→精确root关联、第一份终态、pending_binding拒绝授权、
迟到注册/实际写入不复活、同进程另一轮隔离、审计与状态原子更新。新增6项合同先因缺接口失败，
不计作原有业务红灯；定向Agent Store/API16通过。Backend完整366通过、1跳过、7 subtests
通过（455.49秒），随后追加并发、回滚、子运行与generation测试，生命周期10项通过（13.35秒）。
Runtime+共享合同117通过、6跳过（1.39秒）；其中Runtime107、纯合同10，跳过未算PASS。
真实官方进程仅使用本地scripted Provider；首次探针错误假定arguments为dict，观测为JSON字符串后
改成准确合同。未调用DeepSeek API。来源只输出原注册摘要与捕获的root，不输出原键/原始参数/generation。
最终明确0.1.2兼容层的真实通知→注册键探针1通过（1.81秒）；架构及共享WorkflowTrace/生命周期
合同83通过、3 subtests通过（3.32秒）。宿主无pytest，改用已有禁网测试镜像，未安装宿主依赖。
Gateway可靠消费、持久ack、Backend接收端、MCP pending回执查询及强制绑定接入仍未完成；
尚未关闭R4/F10，不修改历史AgentRun，不处理生产禁用用户记录，不代表完整发布认证。

Gateway重连补充：2项失败测试分别复现跨session事件落盘与旧序号重放抛TraceConflict终止采集。
现核对当前session/trace并跳过已有序号，新事件继续落盘；原TraceStore顺序约束不放宽。
Gateway完整137通过（2.20秒）。没有生产访问或领域写入。

本批验证结束后，已按精确Compose项目byq-ci-r2-recovery-20260907执行down --volumes
--remove-orphans --rmi local；复核该项目容器、卷、网络均为零。清理的是6个合成测试服务、
4个临时卷、5个测试镜像及测试网络，未保留这些临时卷备份；后续测试须重新生成合成夹具。
正式beyondquant服务、生产数据库、历史U7/U8证据及私有备份未改动。

R1/R4 非完成终态切片：原 Runtime 仅将error/failed判为失败，max_tokens及cancelled反而发
session.result，可能使恢复逻辑认为需求已经回答。修复为仅completed成功，显式取消原路径不变。
最初3项失败中1项为测试错误地将字符串回执当dict；纠正后2失败1通过，明确复现业务缺陷。
修复后Runtime完整101通过、5跳过（1.11秒）；没有DeepSeek API调用，未部署生产。

R1/F10 回答目录补存切片：重连跳过已落盘序号时，原先目录保存失败的回答不会再次投递。
现采集器启动从同session/trace持久BYQ投影补存原workflow_sequence/content，Runtime已404
亦可恢复；目录503或无法解析回执时停止该次历史补存，事件不删除。复用Backend既有唯一
约束与内容冲突检查，不重投prompt、不恢复研究执行。新增2项重启/故障回归与1项损坏回执
回归；未记录修复前红灯。Gateway完整140通过（1.22秒），架构/共享合同83通过、3 subtests
通过（3.03秒）。独立Gateway镜像构建成功，禁网测试，无DeepSeek API、数据库或生产访问。
尚未实现持久投递游标、长连接期间独立有界重试或迟到答案排序；重启会重查历史答案，
该切片不关闭R4/F10跨服务AgentRun消费者整改。一次性容器自动删除，新建Gateway测试镜像
已删除（可重新构建）；核查测试容器、Compose项目容器/卷/网络为零。

## AgentRun 跨服务收尾、持久回执与有界重试（2026-09-07）

已接通Runtime规范事件→Gateway持久投递账本→Backend可信目录消费者→原子收尾/审计/回执。
Product DSH注册未绑定时不能授权或审批，MCP有界查询与receipt_only原键只读查询已接通；
后到注册按原终态关闭，首终态不被软取消后的丢弃通知覆盖。不修改业务Job/Approval状态。
每事件8次/24小时预算在网络调用前落盘，跨进程锁防并发重复投递；丢失ACK/重启按原事件重投，
完整摘要不匹配不确认。预算耗尽保留attention_required，只读Product接口可查询，不自动重置。
Backend镜像补打包新增共享合同，避免仅测试只读挂载掩盖真实镜像缺模块。

验证结果（均隔离合成环境）：

- Backend完整373通过、1跳过、7 subtests通过（407.99秒）。首轮372通过/1失败，为旧策略审批
  测试没有建立新的Product运行绑定；补真实绑定前置条件后通过，未放宽pending保护。
- Gateway完整148通过（1.22秒）。新增鉴权用例初次未设置合成bootstrap token，实际503非预期401；
  补齐认证配置后保持原401断言通过。新增只读路由首次被架构检查发现缺OpenAPI，补完整schema。
- Runtime默认108通过、9跳过（1.07秒）；默认不启用网络/付费场景，未将跳过当PASS。
- MCP完整18个测试入口通过；首次缺token、第二次缺真实合成workspace导致合同失败，补隔离
  用户/workspace后通过；未使用生产身份，未跳过失败合同。
- 架构及共享合同83通过、3 subtests通过（2.76秒）。四个受影响组件的开发镜像构建成功；
  不是新release认证，不修改历史U7.3构建清单或宣称远端CI已执行。
- 官方DSH 0.1.2rc1 +真实MCP/Backend/PostgreSQL +Gateway HTTP采集/持久消费者：完成/硬取消
  两项通过（13.90秒）。本地scripted Provider只注册合成AgentRun；故意在Backend提交后丢ACK，
  重启Gateway消费者仍只重投原root/sequence事件，持久run收口且账本清空。
- 按本轮补充授权，付费关键点1项通过（9.38秒），严格2次DeepSeek请求，每次最多512输出token；
  Provider代理只放行固定原键/角色的单次注册工具调用和随后文本确认，禁止其他工具。重复了
  真实收尾、丢ACK与重启核对。密钥仅用于HTTPS认证，不进模型内容/日志/仓库；没有生产用户、
  真实对话、市场数据、研究、训练或回测调用。未扩大为完整研究语义或历史场景重新认证。

边界：完全崩溃未产生终态、禁用用户/工作区后的写触发器收尾、历史无绑定记录，以及所有模型
入口的跨轮确认屏障仍单列待办；本次为有精确规范终态路径的闭环，不关闭全部R4/F10。
未部署生产、未续跑历史任务、未修改main或Community；本次仅本地修复交付。
验收后已删除该隔离项目3个服务容器、2个合成数据卷、4个测试镜像和1个网络；一次性
测试容器自动删除，复核项目容器/卷/网络及验收容器均为零。合成数据未备份，可重建；
生产服务和私有备份不在清理目标内。

## 禁用身份后的受限 AgentRun 清理（ADR-0063，2026-09-07）

维护者明确回复“批准这个受限清理例外”，接受 ADR-0025 disabled fail-closed 的窄修订。
已增加 Accepted ADR-0063 并同步 ADR-0025/0062、租户及生命周期合同；不扩大普通用户、
管理员、MCP/model 或后台研究的访问权限，不部署生产，不自动续跑历史任务。

实现：内部 Gateway 目录消费者仍核对 owner/workspace/session/trace；Backend 在事务中锁定
既有 personal owner/membership 关系，只有终态事件可容许 disabled 状态。既有 root 身份
必须精确一致，禁用后不能创建 root、补注册/绑定或创建 AgentRun。root/run/审计/回执同事务
提交，精确重复回执幂等。触发器只放行既有绑定 run 的终态/version/更新时间和对应的精确审计
INSERT；不允许临时激活身份、通用 bypass、任意审计改写或更改业务 Job/Approval。
安全复核另加 AgentRun 既有 owner/workspace 不可改写约束，防止将归属同时替换为另一活跃
身份来逃避禁用；nullable workspace 的原归属验证迁移仍保留。

验证过程保留：初轮针对性测试 13 失败/16 通过，均为新增拒绝断言错误预期 403，而既有
AgentUnauthorized 合同为 401；修正断言后 29 通过（41.46秒），没有放宽授权。随后新增
缺失 membership、跨目录身份及活跃 owner 替换负例。第一次完整 Backend 回归为纳入最后
归属加固而主动停止，不计 PASS。停止恰逢测试 schema 重建间隙，导致旧镜像负例首次收集
失败；只重建隔离 byq_domain_test 的空 public schema。再次旧镜像检查因镜像已不可用未执行，
不把这些环境失败记为业务缺陷已复现的红灯。最终证据以下方最终镜像完整运行结果为准。

最终本地证据：Backend 镜像重新构建成功，镜像内完整测试 390 通过、1 跳过、7 subtests
通过（408.96秒）；未挂载替代应用源码。架构与共享合同 83 通过、3 subtests 通过（3.83秒）。
新增 17 项覆盖三类禁用×四类终态、审计回滚、数据库额外字段/归属替换拒绝、伪造审计、
跨目录身份、membership 缺失、历史未绑定保持拒绝及普通 API 权限回归。
本轮无付费 API、真实用户/对话、训练或生产访问，未运行或冒充远端 CI/发布认证。
验证后已清理本轮隔离 PostgreSQL 容器、1 个合成数据卷、1 个网络和专用 Backend 测试镜像；
一次性测试容器均移除，项目标签/测试名称及镜像复核为零。合成数据未备份，可重新生成；
正式服务、历史证据与私有备份不在清理范围内。

历史无绑定记录仍不猜测清理；Adapter 无终态崩溃、跨轮收尾确认及其他 F4/F6/F10 流程仍是
独立待办。此例外实现不等于全部 Post-U8 整改或研究语义验收完成。

## 同进程跨轮收尾确认（2026-09-07）

已确认源码缺口：Runtime 将根回合置为 idle 后，Backend 的异步终态投递可能仍未确认；
同一 DSH process generation 下一轮可在这一窗口复用旧 active AgentRun。本批在所有
submit_prompt 入口共用的 Runtime 会话锁中增加终态确认屏障，不在各个业务工具复制检查。
原 prompt 幂等重放只返回原 run，不执行模型；旧轮、错误摘要/序号、浮点序号或跨会话
回执不能清除当前轮屏障。首终态为准，软取消后迟到通知不重新设置已经确认的旧屏障。

Gateway 先验证 Backend 完整持久终态回执，再经私有 terminal-receipt 入口通知 Runtime；
通知失败保留原投递和既有 8 次/24 小时预算，重启按原 root/sequence 重投。已释放会话
404 不再需要放行旧进程，其余错误不当作成功。真正重建 DSH 进程后使用新 generation，
旧 AgentRun 继续由 Backend 的精确 generation 检查拒绝；不以新 generation 猜测关闭历史 run。
这不是新 Agent harness，不修改 DSH、不增加 MCP/Browser 写权限或生产操作。

验证：Gateway 完整 149 通过（1.36秒）；最终 Runtime 完整 111 通过、9 跳过（0.81秒）；
架构/共享合同 83 通过、3 subtests 通过（3.00秒）。新增保护没有记录修复前红灯，不虚构
红绿证据。官方 DSH 0.1.2rc1 +真实 MCP/Backend/PostgreSQL +Gateway HTTP 联测 2 通过
（21.75秒）：正常完成/硬取消均注入 Backend 已提交但 Runtime 通知失败，确认新 prompt
被拒绝且未执行；再注入 ACK 后响应丢失并重启消费者，精确重放后账本清空、屏障解除。
本轮仅 scripted Provider 和合成 AgentRun 注册，付费场景未选择，无研究/训练/回测或生产数据。

仍未关闭：Adapter 整体崩溃且没有任何终态的持久恢复、历史无绑定记录盘点，以及其他
F4/F6/F10 业务续接整改。当前屏障解决同一存活进程的跨轮复用窗口，不宣称崩溃恢复、
新构建认证、全部接口验收、远端 CI 或生产发布已完成。

本批验证后已清理 3 个隔离服务容器、2 个合成数据卷、4 个测试镜像和1个网络；项目资源
复核为零，合成数据未备份但可重建。正式服务、私有备份和历史认证均未改动。

下一项源码核查：Runtime 的 sessions、prompt_idempotency 和 history 没有持久崩溃证据。
因此提出 [ADR-0064](../architecture/adr/ADR-0064-runtime-crash-recovery-evidence.md)，仅允许
在可证明原执行者失效时，从 BYQ 持久身份生成精确中断收尾证据。该新增可信恢复来源为
Proposed，等待维护者对精确范围接受；没有实施，不把普通“继续”视为新架构授权。

## 2026-09-08 顺序整改：F4 会话绑定与通知归属

维护者要求按推荐顺序逐步整改；继续既有独立修复工作树，不推进 Product Phase、不部署。
前文 ADR-0064 Proposed 为历史提案记录，已由维护者批准并在 `d3583a8` 实现首版；
精确边界及验证见 `docs/evidence/post-u8-r1/ADR-0064-VERIFICATION.md`，不再列为未实现。

F4 第一切片：通用 ResearchTask 创建在同一事务中校验可信 owner/workspace/session/trace
及 active conversation 并保存公开 conversation_id。Product Agent 缺失目录拒绝创建，
幂等重放不能重绑其他会话或补绑历史记录；非会话领域生产器保留无绑定语义。
另确认 ML 通知原先仅按工作区筛选；现 Agent inbox 在 SQL 分页前核对任务的精确会话关联，
其他会话及无绑定历史训练不进入当前会话。普通授权查询不受影响，不自动执行模型或训练。

新增绑定测试在修改前镜像 4 项失败：缺少关联字段，missing/foreign owner/wrong trace
仍返回 201。修复后另补 archived、payload trace、历史不回填和分页前通知筛选断言。
首次完整 Backend 回归为补入通知筛选而主动停止（退出 137），不计通过。
最终定向测试 23 项通过；完整 Backend 397 通过、1 跳过、7 subtests 通过，另有 1 项
旧策略审批夹具因缺少真实会话目录失败。仅补齐该测试前置条件、应用源码不变，随后完整策略
API suite 加本次会话/ML 定向测试合计 29 项通过（46.89秒）；不声称重新跑过一次全绿全量。
最终架构及共享合同 83 通过、3 subtests 通过。最终应用镜像构建成功，测试夹具最后修订
使用只读挂载，不挂载替代应用源码。无外部 Provider/付费 API、生产数据或真实研究执行。
F4/F6 整体仍未关闭。接下来处理明确用户授权的任务许可、动作授权复核、
24 小时/8 回合预算、撤销/取消、持久事件去重及 Gateway 续接；不把本次关联当作执行许可。

最终运行第一次因主动停止恰逢夹具 DROP/CREATE schema 间隙而收集失败；只恢复隔离
`byq_domain_test` 的空 public schema 后重跑，不计业务红灯或测试通过。

验证后按受限清理授权删除本轮隔离 PostgreSQL 容器、一个合成卷、Backend 测试镜像和
网络；项目与一次性测试容器查询为空。合成数据未备份，可重建；生产及私有备份未修改。

## 2026-09-08 F6 累计预算准入的决策缺口

继续实现前核对 ADR-0062 §4，发现“既有 token/cost 预算”尚无任务累计硬限制的实现证据。
当前 Runtime 不传 SDK max_tokens；Product patch 的数值仅用于压缩/搜索。官方 SDK
配置及 run/client 接口已在锁定版本镜像中只读检查，未修改上游。
新增 `test_dsh_budget_semantics.py` 在 --network none 容器使用 loopback 合成 Provider，
仅两次请求、无真实密钥：max_tokens=8 的同一回合发送两次均为8的请求并 completed，
1项通过（1.46秒）。不存在真实模型计费，也未触发任何有效业务工具；不能将单次输出
限制误作任务累计预算。不据此断言所有官方扩展都无相应能力。

提出 ADR-0065：保留强预算要求，明确用户额度、BYQ 持久预留/未知结算、官方受支持接口
资格验证及无合格接口时拒绝启动。尚未接受，不修改运行时权限或启用后台续接。
默认 Runtime suite 118 通过、12 显式跳过；新增资格测试另行执行通过，不把跳过计通过。
架构及共享合同 83 通过、3 subtests 通过。没有修改应用实现；未做发布资格认证。
一次性验证容器均自动退出删除，已移除本轮 Runtime 测试镜像标签；未创建数据卷，未访问
生产或私有备份，后续可从锁定构建重新生成测试镜像。

## 2026-09-08 ADR-0065 接受与首轮接口资格

维护者明确“批准”，ADR-0065 已标 Accepted；前节“尚未接受”为历史记录。
已补充 `docs/contracts/task-continuation-budget.md`，固定明确额度、精确任务许可、
事务准入、重复事件、撤销竞争、未知费用保留及可信唯一结算要求；账本与消费者尚未实现。
锁定官方 0.1.2rc1 的实际 Product composition 有用量计量器，未加载 agent-budget；
单请求 max_tokens 的多步反例再次通过。外置预算包尚不满足官方发布者及准确制品资格，
没有安装或扩大权限。不能据此声称全部公开接口不存在，但当前无合格证据可启用后台续接。

Runtime 120 通过、11 跳过；架构 83 通过、3 subtests 通过。仅本地无网络合成测试，
没有付费 API、生产数据、训练、远端 CI 或部署。细节见
`docs/evidence/post-u8-r1/ADR-0065-QUALIFICATION.md`。F6 仍未关闭，不将批准或合同计为完成。

## 2026-09-08 许可基础、持久回答与注销修复

新增精确 ResearchTask continuation permission 的持久化、个人会话确认/撤销 API，
同一幂等键不能变更额度、确认产物或会话。首版每任务只有一个不可变许可；
所有 can_start 仍为 false。尚无执行预留/结算、财务额度、续期或后台消费者，F6 未关闭。
许可验证见 `docs/evidence/post-u8-r1/CONTINUATION-PERMISSION.md`。

回答投递现独立于 SSE，先计次后发送、核对精确消息回执，未知提交跨进程保留并幂等补齐；
真实子进程在 Backend 提交后退出的演练已通过。演练还发现注销删除成功却返回 500、
Gateway/前端吞错，已修复三个边界并完成桌面/手机 Chrome 审查。
最终 Backend 414 通过/1 跳过、Gateway 175 通过、Frontend 170 通过及类型检查/构建通过，
架构合同 83 通过。详见 `docs/evidence/post-u8-r1/ANSWER-DELIVERY-AND-LOGOUT.md`。
均为隔离合成测试，无付费调用、生产部署或历史研究执行；不把这些切片标作全部整改完成。
下一项继续核查 F7 持久纠错次数及无进展停止边界。

F7 后续输入边界审计新增 7 项真实失败反例，修复非法 JSON 类型和超大整数导致的
TypeError/OverflowError，并保留专家嵌套字段定位。最终 ML 策略/安全响应测试 30 通过，
MCP 17 项本地脚本通过；独立证据见 `docs/evidence/post-u8-r1/ML-VALIDATION-BOUNDARIES.md`。
尚未完成持久纠错计次；runtime generation 会跨回合复用，不可直接作为纠错回合身份。

S3 界面切片：明确历史快照/持续跟踪选择及历史必选日期，详情读取持久定义，禁止历史池或
未确认定义的刷新。Frontend 54 文件/172 项通过、类型检查/构建通过；Chrome 桌面/手机
经真实 Product API 分别创建两种合成池，领域物化及导入补偿后仅跟踪池推进至新日期，
历史池不变。详见 `docs/evidence/post-u8-r1/INDEX-MODES-UI.md`；数据扩容未实施，历史需求
排队、缓存证明/迁移及全部研究语义旅程仍未关闭。当前修复均未推送或部署。

本批交付门禁复核：架构/共享合同 83 通过。扩展治理测试暴露构建前置校验仍指向冻结
旧输入；release.py check 报 Runtime build input drift，build_revision.check 也拒绝，
promotion.py check 通过。未将其隐藏为测试成功，未刷新旧 release/build 摘要或认证报告。
下一交付步骤需明确授权新增 Post-U8 独立构建身份及重新认证、当前修复分支 push/Draft PR；
旧 U1–U8 的推送/发布授权不自动扩大到本轮。生产部署及历史研究续跑保持未授权。

## Post-U8 独立构建交付授权（2026-09-08）

维护者明确回复“允许”，批准保留历史记录、新增 Post-U8 独立构建身份和重新认证，
将当前修复分支推送至 `jefison-x/BeyondQuant` 并创建 Draft PR；不合并、不部署。
ADR-0061 已补充本次精确范围。旧 U8 提前结束、历史失败和剩余 F6/F7/S3 不因此关闭。
本次构建及验证进度见[独立构建记录](../evidence/post-u8-r1/BUILD-REQUALIFICATION.md)。

新增独立构建 `.3` 的本地 keyless CI 已通过 26/26，214 项架构测试、Gateway 183 项、
Runtime 119 项及 12 项真实进程、20 项模拟浏览器和 9 项真实 Product 浏览器流程通过。
Backend 421 通过/1 跳过，Runtime 14 跳过，均未将跳过计作通过。前两轮取消/失败记录保留；
完整 smoke 发现并修复“明确无凭据拒绝被误标未知”的边界缺陷，以及中文就绪度的过期测试定位。
源输入、实际镜像及清理已核验；这只关闭本地独立构建/keyless 验证，不关闭剩余业务整改。

## 本次交付授权与顺序（历史记录）

2026-09-07，维护者在“先合并U8收尾，再合并ADR与审计记录，再从更新后的main建立修复分支”
的明确建议后回复“好的,按顺序开始做.”。本次授权覆盖上述文档/审计分支的push/PR和
CI-green合并；按ADR-0015/0059执行精确head门禁，不直接push main、不绕过检查。
后续修复开发保持独立工作树、合同优先和逐批验收。该授权不包含生产部署或历史研究续跑。
