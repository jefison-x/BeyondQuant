# ADR-0116 — 官方 DeepSeek 的 ACP F6 资格

- Status: **Accepted — 实现通过定向门禁；真实资格待验收** (2026-11-01).
- Acceptance: 维护者在该精确方案独立审查通过后回复：“接受 ADR-0116，继续实施验收”。接受范围为本文件的官方 DeepSeek F6 profile、隔离实现和真实验收；不授权发布、运行栈部署或 Product Phase 推进。
- Scope: 在固定官方 DSH ACP rc.2 上，为现有官方 DeepSeek 路线增加一个独立的 F6 接续 profile。
- Accepted extension: ADR-0103/0105 的精确 provider/model 接纳范围；保留 ADR-0111 的自动接续与执行参数语义。
- Non-scope: Judgment、任意 provider router、新 Harness、DSH fork、旧结果重放、Product Phase 推进、发布或运行栈部署。

## 已确认的缺口

本轮以已完成用户级参数修正的本地 `96407fe7` 为起点，复用其测试环境和
源码/持久身份/UI证据。六个必要服务健康；只读检查显示 Runtime 无运行输入、
无 held/awaiting 槽位，现有七个 SignalJob 均 completed。检查没有新建 Job、
调用模型或修改原页面。用户级设置验收与旧 synthetic F6 不替代本 ADR 的真实链。

当前保留普通实例使用 `deepseek-official / deepseek-flash`。但
`packages/contracts/continuation_request.py` 的 F6 profile 固定
`opencode-go-chat / deepseek-v4.1-flash` 与 OpenCode Go Chat 上游。
Runtime 的资格检查和执行前检查都要求该精确配对。F6 flags=1 不改变此合同。
ADR-0106 的官方普通路线修订明确不改变历史 F6/Judgment profile。
OpenCode Go 额度已耗尽，不能把旧路线当作本轮真实验收入口。

普通真实回复/ACK 和 hosted synthetic F6 均保留其原范围，不作为本次真实 F6 PASS。
旧真实 F6 的已提交或未知输入、Job、reservation、receipt 及失败证据保持原样。

## 接受的最小决策

1. 保留旧 F6 profile 的内容、版本、哈希和历史解释，新增独立版本化的
   `task-ready-read.official-deepseek.v1` profile。只接纳
   `deepseek-official / deepseek-flash`、上游
   `https://api.deepseek.com/anthropic`、请求路径 `/v1/messages`。
   不通过改写旧常量或放宽为任意字符串实现资格。
2. 复用现有 Backend 模型/凭据接纳、request gate、native overlay 和
   Messages 流处理；精确绑定 owner/workspace/conversation/task、事件、
   profile 哈希、用户执行选项 revision/hash 及新 Root/generation/MCP 身份。
   API key 继续来自加密用户凭据库，不进入配置、Git、模型上下文或采集输出。
3. 使用当前 ADR-0111 的自动 task-ready/reservation 合同。自动接续不另建 grant；
   缺省/null 数值选项不实施 BYQ 上限，显式用户值才生效。不得复制旧16次/180秒
   默认硬限、使用巨大整数假装关闭，或增加跨请求余额。保留连接/ACK故障检测、
   用户取消/禁用、逐动作业务审批与身份、去重和 unknown 保护。
4. F6 proxy、guard 与 overlay 必须对同一 Messages profile 闭环核对请求、流式
   终态及真实 `input_tokens/output_tokens`。缺失/丢失的用量保持 unknown，
   不填0、不为补账重发。已存在的普通 Messages 支持是复用基础，不自动证明 F6。
5. 遵守 ADR-0103/0096 的健康原生上下文接续：后台输入形成新的 BYQ Root，
   精确 ACK/清理旧 Root 后接续正确 native session，只发送新输入。保留原
   provider/model binding；不切换旧会话模型，不复制历史或恢复失败 Agent。
6. 仅在离线合同、独立审查与 Root 准入后，在保留测试环境执行一次受影响真实链。
   必要的局部服务更新先核对源码/镜像、原配置和可回退材料；不清理旧容器、卷、
   数据或当前页面，不触碰 `beyondquant` 运行栈。

## 验收及停止条件

- 定向合同覆盖精确新旧 profile、错误 route/model/path、用户选项快照/null、
  Messages 流与实际用量、Root/native/terminal ACK、重复事件、取消和 unknown。
  不重跑已经有效的整套 Golden 或 Full，不新建测试 Harness/采集器。
- 真实链采用新的测试 conversation/task/准确业务审批，最多一个新 SignalJob、
  两个前台输入和一次自动后台结果输入；总观察窗口15分钟。这是工程验收批边界，
  不是产品执行期限。观察超时先记 NOT_OBSERVED/验收未完成并对账，不杀任务或
  重放；只有实际 provider/业务结果无法证明时才记 outcome_unknown。
- 启动 Worker 前只读核对源/镜像、队列和目标数据。仅使用已验证的现有数据，
  不新下载市场数据；Worker 不得误执行其他未决任务。
- 核对同一 Job 的完成/Artifact、自动后台派发一次、独立 Root/MCP、native
  上下文、持久化回答、准确用量/结算、terminal ACK 和清理。所有会话遵守同一
  用户配置，不建立会话级 override；默认不修改原用户参数，不为收尾关闭整个
  用户的自动接续。确需修改时先保存完整原值/revision，通过用户 API 精确 CAS
  更新并恢复；遇到并发修改停止写入核对，不覆盖用户的新值。只停止本轮准确
  测试 Worker/场景。旧 grant 若存在，按原准确版本处理，不能创造新许可。
- 通过 Gateway/Product API 的真实登录与现有 Playwright 验证只读用量/结果 UI，
  刷新后仍一致；不重置原用户密码/身份，不读取个人浏览器私有存储。
  原测试页面保持打开。浏览器或身份前提未满足时，UI 明确记 NOT_RUN。
- Tester → independent Reviewer → Root 只裁定本次真实 F6 的准确范围。
  有失败保留原 FAIL；不由本 ADR 或该单项 PASS 自动关闭 Phase 17。

## 授权边界

维护者已明确接受本 ADR，授权实施该扩展和相应隔离真实验收。
提交、push/PR、merge、release
与运行栈部署继续遵循各自授权；不将过去 PR #418 的合并例外作为本任务权限。

## 实现检查点

实现提交 `771cd22c`，测试断言修正提交 `dd1ae266`。独立审查对源码、受影响
定向测试和架构给出 PASS；四个必要测试角色已局部更新并健康，旧容器和卷保留。
当前验收窗口尚未完成原账号正常登录，真实模型/SignalJob/F6 链为 **NOT_RUN**，
不由本实现检查点宣称官方 F6 已有真实资格。详见
[本轮证据和限制](../../evidence/acp-official-deepseek-f6-20261101.md)。
