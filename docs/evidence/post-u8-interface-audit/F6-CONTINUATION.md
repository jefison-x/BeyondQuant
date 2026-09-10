# F6 后台续接执行验收

当前状态：IMPLEMENTED / QUALIFICATION_IN_PROGRESS。不得据此宣称 F6 完成、生产已启用或真实模型研究验收通过。

## 授权与范围

维护者在本任务明确要求：`继续，F6 完成前不要停止，所有授权都允许。`
该授权覆盖完成 F6 所必需的开发、隔离验证、push/Draft PR，以及通过 ADR-0015/0059
精确提交门禁后的合并、受控部署；不取消检查，不授权直接推送 main、破坏性迁移或续跑历史研究。
Community 原实现检查遵循 Accepted ADR-0068 的持续豁免。

本批保持 Product Phase 97 和官方 DSH Python `0.1.2rc1` / npm `0.1.2-rc.1`。
依据 Accepted ADR-0062/0065，任务许可绑定原用户、工作区、会话、任务和确认制品；
24 小时、8 回合、每回合 900 秒、累计 token 上限分别执行。普通浏览器操作使用 Product API。

## 已实现的链路

Backend 在现有任务上持久保存许可、终态事件身份、累计预留、派发状态与精确结算。
Gateway 从既有持久会话身份扫描 BYQ 终态通知，核对原回执后启动受限 DSH 回合。
MCP 在原工具执行前向 BYQ 检查任务范围，领域工具继续执行既有逐动作审批。
DSH 不读取业务数据库；没有新通用 harness、Provider 代理或 fork。

预算插件使用官方公开 `llm/stream` 调用前 waterfall，先 fsync 保守预留，再允许 Provider 请求。
根调用、子 Agent、压缩和失败重试共享同一只增日志；并发请求不能重复使用额度。
仅资格验证 `deepseek-official` / `deepseek-v4-flash`。每次按输入最大上下文 1,048,576
加本次最大输出计入保守额度；默认后台输出上限 8,192，因此单次需 1,056,768。
该数值是保守额度扣减，不是实际 token 消耗或人民币账单；金额限额与其他路由尚不提供。
官方模型限制来源：[DeepSeek 模型与价格](https://api-docs.deepseek.com/quick_start/pricing/)。

公开源码和真实进程证明搜索插件存在绕过 `llm/stream` 的直接模型调用。
后台专用配置禁用 `web-search-deepseek` 与 `tool-web`；普通主动研究配置不变。
后台只推进既有数据上的预测、冻结信号、回测和比较，不能通过搜索绕过预算。

提交不确定时保留全部预留，不把超时当作拒绝、不重复提交新身份。
结算须证明原根回合已结束、进程关闭、日志完整；回执持久化并校验身份与摘要，
可跨会话空闲释放和 Adapter 重启恢复。无法证明的费用不会自动返还。
撤销、禁用、到期、取消和额度不足阻止新准入；已在执行的外部请求不能被描述为瞬时撤回。

## 验证记录

以下为隔离预检，不替代当前源码构建的完整 CI：

- 公开 hook 的纯 Node 测试 5 项通过。
- 真实候选进程预算测试 10 项通过：根调用、连续调用、子 Agent 并发、压缩、
  Provider always-retry、搜索绕过/禁用、相同预算日志拒绝重开，以及释放/Adapter 重启后结算恢复。
- Backend 全量预检 563 passed、1 skipped，Gateway 212 passed，Runtime 152 passed、42 skipped；
  这些计数对应各预检时的源码，后续代码仍须最终完整 CI。
- 前端预检 179 项通过，生产构建通过。
- MCP 预检构建通过；独立 npm test 因未提供测试 token/实时 MCP 合同环境停止，不能称全量通过。
- `.25` 当前源码候选镜像的付费关键资格通过：官方 `deepseek-v4-flash` 处理固定
  合成提示，回合 `completed`，日志恰有一次受保护请求、保守扣减 1,056,768。
  只有容器内临时合成目录，没有挂载生产业务数据、会话或 MCP。凭据经 stdin 注入，
  不写入参数、证据或日志。该检查只证明真实模型协议与受限配置兼容，不代表全链研究质量。

`.25` 是本批首个全链候选构建，完整 CI 为 **24 passed / 4 FAILED**，不能晋升。
失败包括旧架构断言只识别固定变量名、F6 全链用例被误收进 mock 组、许可下拉框
点击遮挡，以及 Gateway 消费者误用模型回合身份校验（真实内部请求 401）。
手机截图还显示确认说明不换行导致横向溢出；Gateway 重启的临时端口变化也未被夹具重新发现。
确认消费者持续 401 后终止该失败链路的等待，保留原日志，没有将中断记作成功。
当前真实 Product API 桌面/手机许可操作及训练→预测→信号→原生回测→持久比较报告仍在验收中。
`.26` 的 Runtime/真实集成定向执行为 **13 passed / 2 FAILED**：消费者 HTTP 边界
修复后，Gateway 重启确实恢复原任务，预算、终态和结算链路运行；但前序 Phase 48
夹具替换证券主数据，训练返回 `ml_data_repair_not_ready`。模型回合失败和需关注状态
如实保留，未伪造预测或完成。浏览器进一步暴露隐藏 checkbox 原始节点不可点击，
下一修订改为真实点击可见标签并检查选中状态。
另一个隔离数据库负例证明：带首尾空白的其他任务 ID 被领域层规范化，而范围检查未规范化，
造成同一用户跨任务准入。该版本明确不合格，下一修订须堵住并加入回归测试。
`.26` 辅助预检：架构边界 66 项、Gateway 恢复 13 项、模型资格 6 项、
消费者 HTTP/数据库及 MCP 范围 10 项通过。这些仍不替代最终全量 CI。
脚本 Provider 全链只证明真实领域组件连接正确，不证明真实模型推理质量；
测试数据与合成用户有明确标记，不使用历史生产研究作为夹具。

## 交付状态

后续隔离调试保留 `.ci-artifacts/f6-positive-debug/CHAIN{,-2,-3}.log` 的失败任务，
未重置许可、去重键或账本。第三次运行的安全调用栈定位到 `LifecycleJournal.observe`
将内部回测卡片引用误按完整公开卡片校验；这才是这组运行在回测读取后失败的直接原因。
下一修订对两个既有内部引用采用封闭身份校验，只记序号、不进入恢复事件；
Gateway 的 owner-scoped hydration 与公开卡片合同保持不变。日志回归 9 项通过。
另补会话空闲释放竞态防护：原回合固定截止时间加有限清理宽限，不随消费者轮询续期；
未知结果不因此退款。该风险由竞态测试证明，不再把它当作上述失败的已证实原因。
Gateway 全量 217 项通过。首尾空白跨任务负例修复后，消费者/范围测试 12 项通过。
移动端下拉框宽度、长编号和确认说明修复后，真实 Product API 保存、重载、隔离与撤销通过；
390px 表单截图已人工检查，无横向裁切。这些调试构建仍不替代最终不可变构建全量验收。

第五个独立合成用户的真实领域链路通过：task `task_ab567669f56a488584143da11b150a7b`，
1 次训练、1 次预测、2 次原生回测（含既有基线），3 次唯一事件/派发/结算，
累计保守额度 19,021,824，未确认预留为 0。完成证据为 validated `research_report`，
`report_type=strategy_comparison`，使用两次真实回测汇总计算收益差；
前一失败夹具误用的 `comparison_report` 并非既有完成证据类型，领域合同未为夹具放宽。
桌面 1440px、手机 390px 的 Product API 完成状态及报告读取两项通过；手机结算截图已人工检查。
此处“真实”指真实 DSH/MCP/领域/数据库/Worker/回测执行，Provider 决策和行情输入均明确为合成。

中间候选源码提交 `e03c034`，不可变构建 `.27`（未晋升）：

- baseline manifest：`sha256:f2d26aa6b043215aa6c99751bdbb0dd8a8d673ad284d2d9fbf5281bd58a44cb2`
- candidate manifest：`sha256:4d68102528c131b6a3c166770c4dfcf674828d09b8e62191cebe4e51c5b887d1`
- 本地 CI scope：`local-u7-f6-completion-27`，文档及 228 项架构检查通过，
  Backend 全量执行期间自审发现 `byq_agent_context` 会提供同会话其他任务摘要和 inbox，
  主动终止资格运行（exit 143），未计作全量通过。资源清理及独立 verify 通过。
- `.26` 调试栈及三个临时 Runtime、Gateway/Frontend 镜像已清理；独立 cleanup verify 为零。
- 生产只读前置核对：当前续接许可总数及未过期数均为 0；尚未改变服务或启动历史研究。

`.28` 去掉后台 `byq_agent_context` 准入，指令明确仅使用已注入身份及精确原任务读取；
普通前台 context/inbox 不变，新增拒绝回归。没有对 Product API 或公开卡片合同放宽权限。
最终全量 CI scope 为 `local-u7-f6-completion-28`，当前 RUNNING。
baseline manifest：`sha256:38bbbbbd3b8e840241717292bcbf60dee409cdba33a0c7a9b9742a693726cd8f`；
candidate manifest：`sha256:f0980d9fb0da4966f826220e4ffeb3479cbb9ff28cd88b2f525df8e71432b29f`。

### 验收定位

| 要求 | 主要证据 |
|---|---|
| 原用户/工作区/任务/已确认策略边界 | `test_research_continuation.py`、`test_continuation_scope.py`，包含空白 ID 绕过负例 |
| 并发额度、撤销竞争、未知结果不退款 | PostgreSQL `test_continuation_budget_ledger.py` |
| 发出前额度保护、根/子/压缩/重试/搜索 | 真实官方进程 `test_continuation_budget_process.py` 和公开 hook Node 测试 |
| 精确事件去重及恢复 | `test_continuation_notifications.py`、`test_task_continuation_delivery.py`；全链 Gateway 重启后只派发 3 次 |
| 进程释放/Adapter 重启后的结算 | `test_continuation_budget_process.py` 的原身份持久证明测试 |
| 模型回合与任务完成分离 | `f6-chain-verification.py` + `f6-chain-fixture.py` 核查持久领域对象与 validated 报告 |
| 用户许可、重载、越权拒绝、撤销 | `real-product.spec.ts` 桌面/手机真实 Product API 流程 |
| 完成状态、对比报告和额度可读 | `f6-chain.spec.ts` 桌面/手机；无外部请求及页面错误 |
| 当前精确构建回归 | `.28` 全量 CI，尚待结果，不用上面的定向通过替代 |

待补最终构建身份、完整 CI、浏览器视觉检查、关键模型资格、清理、PR/远端检查及部署结果。
在这些证据就绪前维持 `QUALIFICATION_IN_PROGRESS`，不关闭 F6 或总整改计划。
