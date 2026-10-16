# 浏览器后验合同修正（2026-10-16）

专项维护，不推进 Product Phase。功能源码 `d5b1aa0a487d9d8b71febf69e7716fe5e274cc26`。

## 问题与停止范围

当前浏览器已经完成一次只读输入，页面显示 `planned / waiting_event / null`，明确自动接续无需单独许可。刷新前后六个页面文章全文一致。后验采集原批仍为 **FAIL_POST_OBSERVATION_STOP**：Root 临时加入 `binding.closed == True` 断言，错误地把公开会话结束当成本轮清理。

`services/runtime-adapter/app/runtime.py` 的持久化实现明确写入 `closed = record.conversation_ended`。前一批格式验收的已存原件和当前原件均是 `closed=false`、进程退出与原生会话关闭已确认、清理无不确定性。原批 native exit 1 保留；停止新输入、模型、Job、账号创建及测试扩展。

保存证据分析另发现 Root 的固定“新增两条持久消息”假设也不成立：同一次回答可以保存前言和最终回答两段。当前数据库消息从5到8，新增1条用户和2条助手，页面按既有投影显示新增2个文章；前5条消息与前4个文章均未改变。不能按固定消息条数判断重复历史。

两处均为观察合同错误，不能据此改动正常 Product 生命周期或消息投影。以后复用下面清单与已存实例，不为每批重写生命周期和消息条数断言，不新增通用测试框架。

## 最小后验清单

1. 用当前会话 PRE/POST 的 Root 差集定位本轮，核对 owner、Workspace、SID、trace、boot、原生绑定和 AgentRun；不借旧任务身份。
2. 分开核对公开会话与本轮状态：普通结束后公开会话仍 active、binding.closed=false；本轮 completed、authority closed、unknown=0。
3. 核对本轮精确 settlement 序号及事件摘要，Gateway ACK 相同；签名清理回执必须核验完整 scope 和 MAC，进程退出及原生关闭已确认，domain-call 游标已排空，槽位与待 ACK/清理均释放。
4. 按实际 ingress 和审计核对调用、授权、结果及副作用范围；保留未知原件，不重放。
5. 读取精确本轮的 provider journal 记录实际调用、HTTP 和用量。工程观察上限不写入 Product 执行参数；Adapter 汇总 usage=0 不代表没有真实模型调用。
6. 页面刷新后全文比较；持久消息按差集、角色和顺序核对。允许同轮助手分段，不固定要求新增两条；已存旧消息和旧任务/Job 原件不变。
7. 任一命令、解析或身份失败即停止该批，保存原件。先核对现有证据和源码语义，再决定有限补查；不重发模型请求修观察器。

## 有限后读

独立 Sol 只读审查后，另批仅各一次读取本轮已存在的 provider journal、精确 scope 签名清理回执和有限 Gateway 日志，未新增输入、模型或 Job。6次请求均 HTTP200，input196814（其中 cache-read187904）、output1174；MAC 验证成功；Root `d64f11fa540940f09574efa367a433f5` 的 ACK30 与 Backend/binding 终态摘要 `da0177a39e53ed7a1b535128b58fe4e9b1a205cf148a08f365e4aad24634b704` 一致。

这不改写原批 FAIL。限定现存结果已通过独立 Sol 与 Root 验收，收据为私有 `poststop-existing-read-v1/ROOT-SCOPED-PASS.json`；原始 MCP ToolResult 正文未采集，不能把 Agent 回答当成原始 ToolResult。实际 Product GET、工具入口/审计与 Agent 当前回答分别保留。

## 尚未验证

旧显式撤销对已有 v3 派发的围栏仍是独立缺口；双用户、在途进程异常、迟到请求和业务未知结果等未闭合范围不因本片通过。15项参数保存/执行按用户要求延期。完整 CI、推送、合并、生产部署均 NOT_RUN。保留测试环境和当前页面。
