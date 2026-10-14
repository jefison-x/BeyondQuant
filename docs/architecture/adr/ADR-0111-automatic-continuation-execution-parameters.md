# ADR-0111 — 默认自动接续，执行参数与业务审批分离

- Status: **Proposed — 待维护者接受具体修订**
- Date: 2026-10-14
- Scope: DSH / ACP 专项维护；不推进 Product Phase，不改变 DSH 版本或生产部署。
- Audited source: `df941b2f5b34dc2a51f1bf4ce2210b72faf64dd6`。
- Maintainer requirements: “所有会话都能自动接续，且不应该有token限制、次数限制、时间限制。就算内部也不应该有”；随后明确“这些接续条件限制应该作为参数，而不应该作为许可”。

## 现状与问题

当前实现把自动接续依赖于单独 Task grant，固定 `max_turns=1`、最多24小时有效期；F6 与普通 ACP 的独立 profile 都强制16次 provider 请求、180秒期限，以及输入、输出和工具载荷配额。Adapter 还存在无进度、子 Agent 时间守卫。这些值能够终止正常任务，仅隐藏前端表格不能解决问题。

相关源码：`packages/contracts/continuation_request.py`、`product_turn_request.py`，Backend `research_continuation.py`，Gateway `task_continuation.py`，Adapter `runtime.py`、`research_request_gate.py`，`byq-continuation-budget.js`。

当前后台完成事件主要覆盖 signal Job 和 validated SignalSnapshot。需要逐项核对其他已有 Product Job 的完成投递；不能把一个 SignalJob 路径通过称为所有业务接续已通过。

固定官方版本的 [ACP入口](https://github.com/deepseek-ai/deepseek-harness/blob/639ed015397290b3745d163aafe02ffee4aa3f84/packages/acp/acp/src/index.ts) 将 `session/prompt` 交给原生会话，并未在该入口要求调用次数或总执行deadline。[SDK说明](https://github.com/deepseek-ai/deepseek-harness/blob/639ed015397290b3745d163aafe02ffee4aa3f84/python/sdk/README.md) 也区分可选请求timeout/max_tokens与初始化握手。这是源码能力证据，不代表当前ACP完整调用链、原生compaction或provider已完成无BYQ默认配额验收，不授权切回SDK。

## 决定

### 1. 所有 Product 会话默认具备自动接续能力

原授权工作仍有待处理步骤，或原任务收到可验证的业务结果时，Agent 自动接着处理并持久化回答。正常回合结束不关闭公开会话。没有待办时会话保持空闲。

接续驱动来自 DSH 原生在途生命周期或 BYQ 可信 Job/Artifact 完成事件。BYQ 不扫描自由文本或trace来推断Agent待办。“所有会话”表示统一能力/参数资格；各类实际Job结果投递仍需分别验收。

普通连续输入、委派结果返回、后台 Job 结果返回遵循同一产品语义，不另申请“续接许可”。已有真实业务 DECISION / ACTION 仍通过右上角铃铛处理。自动接续只延续原目标，不授予跨工作区、工程、数据库、源码或新的业务动作权限。

### 2. 条件和资源限制是可选执行参数

- 自动接续默认启用；用户可以主动关闭或取消。
- token、请求/工具调用次数、接续次数、时长、无进度时限，以及会因累计载荷而截断执行的资源配额，均不得有 BYQ 强制默认值。
- 审计并替换所有仍执行的同类数值门：`DATA_READY_MAX_TURNS=8`、`STAGE_MODEL_CALL_LIMITS=2`、专用判断阶段调用配额、profile `max_concurrent=1`、Adapter注入的`max_tokens=8192`、composition `maxTokens`、child180秒/no-progress120秒。并发若配置则是可选执行参数；同一会话仅一个有权root及同事件至多提交一次是独立业务身份规则，不可通过参数关闭。
- 可选参数缺省或 `null` 表示对应 BYQ 上限不启用。用户显式设置后才实施该项参数。不能用巨大整数表示关闭，不能在后台保留16次、180秒、一次接续、默认grant TTL等隐含上限。
- 参数通过当前用户的普通 Product 配置写入和读取，不生成 ApprovalRequest、grant 或许可审批。模型输入不能提高或改变用户配置。
- `execution_options`精确归属owner/workspace/conversation，字段类型、单位和作用范围在DTO中固定；避免新增全局累计余额。用户修改只作用后续root/新事件，旧执行保存原参数快照。
- 连接建立、控制RPC、ACK/关闭确认的故障检测期限单独列账和审计；无日志、UI轮询停止或响应等待超时不能杀掉仍活着的模型/child，不能据此推断旧root已闭合。实际丢失的响应保持unknown并按准确身份对账，旧root未闭合或隔离不能获得新root授权。
- 优先在现有会话配置边界增加一个有类型的 `execution_options`；没有该持久字段时做最小字段/API扩展。首批不建设通用 TaskConfig / WorkspaceConfig 管理框架或新的调度系统。
- 每次执行记录所用参数版本/快照；修改应用于后续执行，已提交或未知的旧请求不因修改参数重新派发。
- 模型服务/官方 DSH 固有的上下文、协议、输出能力和服务限流应如实报告。BYQ 不通过虚假无限值绕过这些约束；当前官方 API 无法取消的内部执行配额必须明确记录为缺口，不得宣称已完成。

### 3. 保留业务事实与终止控制

保留 owner/workspace、准确 conversation/task/Job/Artifact、root/child身份、逐动作权限、用户取消与禁用、重复事件去重、一次事件至多一次提交、旧授权撤销、准确终态 ACK 和进程清理。

用户取消、明确业务失败、进程/连接实际异常、业务结果未知或需要用户作出决定时，按真实事实停止或等待核对。不能把固定时钟到期或累计用量阈值当作默认失败原因。用量可观察、可计量；未知仍为 unknown，不伪造为0，不重发以补齐用量。

DSH 继续拥有 Agent loop、上下文压缩、子 Agent、原生会话接续和取消。BYQ 不增加模型自循环、第二套 Harness、恢复协调器或 DSH fork。

中断后先核对原 Job 和业务调用；原 child 不可恢复时新建 child 接着完成业务，不宣称恢复原 child。未知原请求不可自动重放。旧 root 未准确关闭或隔离时不能让迟到请求获得新一轮身份。

### 4. 旧事实与配置切换

旧 grant、reservation、usage、receipt 和失败证据原样保留，用于只读审计与精确核对，不迁移成伪造的新许可、不重置额度后重发。新执行采用新参数合同。

明确用户撤销/取消仍有效；自然过期属于旧许可合同，不等同于用户取消。切换时依据当前业务事实判定新事件，不从旧许可余额推导资格，不重放已提交事件。

旧grant的用户撤销仍作为原task/conversation的关闭自动接续意图；不会影响别的任务或会话。自然TTL到期不作为新执行资格门。鉴别不清的撤销/旧未知结果须核对，不能按默认启用直接忽略。认证凭据的失效/撤销检查保留，健康长执行的凭据更新不得被实现成隐藏会话总期限，也不能重新授权已撤销的旧root。

## 具名修订范围（仅本 ADR 接受后生效）

| 既有规范 | 替换的要求 | 保留的要求 |
|---|---|---|
| ADR-0090 | 单独 grant、固定一次/有效期、强制每请求限额及限额profile作为准入条件 | 责任记录、精确业务绑定、幂等、真实/未知用量、未知结果不重放 |
| ADR-0103 | F6依赖permission与预算、强制有界provider配额 | 新root/原生resume、准确结果、独立身份、终态ACK、去重 |
| ADR-0105 | closed limits、guard只能收紧、限额执行证明作为成功前提 | 已资格provider路由、凭据隔离、真实模型终态、业务事实、未知结果处理 |
| ADR-0106 | 普通Product强制product-turn.v1数值配额 | root身份、已资格路由、未知外发结果与旧请求隔离 |
| ADR-0097/0098及专用判断合同 | 若其中绑定了强制阶段调用、token或执行时限，则改为同样的可选参数；解除以旧配额hash为前提的执行准入 | 专用只读工具、阶段输出语义、精确root/终态结算、取消与未知责任 |
| Clean Break ADR-002 | 无条件固定时长、子Agent无进度watchdog及必须以总时限证明完成的要求 | DSH唯一Harness、取消、实际失败、业务权限fence、原child恢复能力边界 |

专用研究判断路径及任何其他 Product 模型路径也须检查同类配额；遗漏路径不能称为“所有会话已取消默认上限”。BYQ历史重水合截断与UI有限轮询需要分别核对是否截断业务执行或仅控制显示，不得将显示观察结束冒充会话结束。provider/schema/业务参数校验与工程验收批次的有限调用数、观察时限，不作为隐藏的产品执行配额。

## 实施与验收切片

1. **参数合同与普通会话**：先审计官方API，定义缺省/null/用户显式值和只读历史；在替身上超过旧token/16次/180秒阈值验证不会被默认截断，显式参数仍生效。
2. **默认后台接续**：无需grant；不同完成事件持续处理，同一Job/结果只读取一次对应提交；回答持久化；已取消、跨用户、迟到旧请求、未知结果均按真实状态处理。
3. **委派与生命周期**：子Agent长期有工作和短时无新日志不会被默认watchdog杀死；用户取消与新输入、空闲释放、进程异常、原Job核对与新child业务接续分别验证。
4. **Product浏览器**：历史页只读；执行参数通过配置入口修改，无许可申请；业务审批仍在铃铛。复用已有证据，只补受影响项。

每个切片先冻结脚本/观察器合同，再离线验证、独立Sol审查、Root PASS，之后才运行声明了调用/Job上限和总观察时限的小批真实测试。观察超时是验收未完成，不冒充产品期限或业务失败。同类采集错误出现即停该批、保存原证据并修正，不扩大测试。

参数去限额与自动接续不因文档接受即成为PASS；报告区分本地、合成、真实模型、浏览器和生产。保留现有环境和页面供用户互动；生产数据库、卷和无关服务不操作。源码修改、仓库门禁与生产部署仍分别验收，不自动推进Phase。
