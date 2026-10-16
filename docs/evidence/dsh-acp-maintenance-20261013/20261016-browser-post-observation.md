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

## 原生输出格式也必须复用

2026-10-16 后台软取消批次中，Root 重写了日志解析片段，丢掉既有 `GATEWAY-LOG-NATIVE.json` 明确记录的 `plainlogs;exact structuredACK JSON suffix only` 合同。实际日志有 `INFO: terminal_ack_observed ` 前缀；对整行做 JSON 解析并跳过异常，错误地产生空 ACK 列表。原批保留 **FAIL_OBSERVER_STOP**，第二条输入 **NOT_RUN**；不得据此重发模型或创建另一个 Job。

这是采集流程错误。修正使用现有原件、现有命令和下表，不新增框架或功能测试代码。后续原生采集记录必须带回对应模板的 `format`，先确认格式再解释内容；不能只复用 argv 后重新猜解析规则。

| 原件 | 实际格式 | 核对方法 |
| --- | --- | --- |
| psql 元数据、三路官方回执、provider journal | JSONL，各行独立对象 | 逐行解析，按实际 `row_type` / `kind` / 请求类型分组；不当作一个 JSON 文档，不固定行数。 |
| Runtime binding + operations、MAC 验证结果 | 一个 JSON 对象 | 完整解析，再核对当前准确 Root 与 scope；汇总 usage 不替代 provider journal。 |
| Gateway 日志的 stdout 和 stderr | 普通日志，ACK 是固定前缀后的 JSON | 两个流均保留；仅解析 `terminal_ack_observed ` 后的完整 JSON，精确匹配 schema、Root、SID、trace、boot、序号和摘要。匹配前缀后的格式错误必须停止，不能静默跳过。 |
| 本地 native 包装回执 | 共同执行字段为 `argv`、`exit_code`；原始 stdout/stderr 另存 | `container_id`、`utc` 与 `utc_started`/`utc_ended` 等仅为各次采集的辅助字段，须先读取实际形状；不得猜额外字段名作为执行或身份合同。准确身份由原生 stdout、白名单 STATE 及 argv 交叉证明。 |
| Docker `create` | stdout 为一个完整64位容器ID | 从原始 stdout 取准确 CID，与受限 STATE 的 `id`、镜像及 `cp` argv 交叉核对；本地包装回执的额外 `container_id` 不是必备字段。 |
| Docker `cp ... -` | tar 二进制 | 按 tar 读取目标成员，再核对实际文件内容、SHA、字节与权限；不按文本解析。 |
| Docker 受限 `inspect --format` | 精确 ID 集的 JSONL | 使用已核准白名单；挂载按 Destination 比较完整对象，不比较数组顺序，不采集完整 Env。 |
| 浏览器文章快照 | 有序字符串数组 | 全文与顺序比较；持久消息允许同轮助手分段，不固定新增条数。 |

零条匹配 ACK 表示证据尚不足，不表示没有发生 ACK；不得继续发送下一条测试输入。相同身份、序号和摘要的重复 ACK 日志应保留原始次数，并按同一个终态核对，不能计成多次业务执行。清理回执中的原因字段也不能代替真实业务终态。

任一格式错误仍按第7条停止该批。先独立审查保存原件和缺口，限定旧结果的核对与后续新批次分别记录；原 FAIL 不改写。

## 有限后读

独立 Sol 只读审查后，另批仅各一次读取本轮已存在的 provider journal、精确 scope 签名清理回执和有限 Gateway 日志，未新增输入、模型或 Job。6次请求均 HTTP200，input196814（其中 cache-read187904）、output1174；MAC 验证成功；Root `d64f11fa540940f09574efa367a433f5` 的 ACK30 与 Backend/binding 终态摘要 `da0177a39e53ed7a1b535128b58fe4e9b1a205cf148a08f365e4aad24634b704` 一致。

这不改写原批 FAIL。限定现存结果已通过独立 Sol 与 Root 验收，收据为私有 `poststop-existing-read-v1/ROOT-SCOPED-PASS.json`；原始 MCP ToolResult 正文未采集，不能把 Agent 回答当成原始 ToolResult。实际 Product GET、工具入口/审计与 Agent 当前回答分别保留。

## 尚未验证

旧显式撤销对已有 v3 派发的围栏仍是独立缺口；双用户、在途进程异常、迟到请求和业务未知结果等未闭合范围不因本片通过。15项参数保存/执行按用户要求延期。完整 CI、推送、合并、生产部署均 NOT_RUN。保留测试环境和当前页面。

## 薄镜像归档校验的同类错误

随后薄镜像读回批次的本地汇总器依赖额外 `container_id` 字段，而分段手工采集和批量采集写出的包装回执并不相同，发生 `KeyError`。该批仍为 **FAIL_OBSERVER_STOP**，未安装服务、未增加模型或 Job。执行方摘要“Backend临时容器保留、Gateway未创建”也被保存原件否定：Backend准确rm已成功，Gateway已创建且3文件/2目录已读回。Root按原生时序记录事实，不采纳该错误摘要。

解决范围只使用已有 CREATE stdout → STATE raw → cp argv → tar 原件，另写派生核对结果，不补写字段、不改原件、不重复 Docker 读回；后续临时容器清理和安装分别准入。所有观察器都以实际输出格式与准确身份为依据，包装摘要不作为原生执行证明。

## 新一轮与只读刷新的不同核对范围

取消后的一次普通输入已完成并取得准确终态ACK247及签名清理证明；1次HTTP200，没有新Job或模型工具调用。旧69条持久消息、23条Root、7个Job及7条ledger原件不变。原批仍保留 **FAIL_BROWSER_HISTORY_PREFIX_STOP**：全43个article前缀比较把两张历史运行卡也当作不可变消息，实际只有它们追加“后续已发起新一轮（不表示原任务已完成）”。

`AgentView.vue`将消息与`aria-label="历史运行记录"`卡片都渲染成article；`workflow.ts`依据更晚的`session.started`设置`laterTurnStarted`。因此必须使用当前Product投影语义：

- 持久消息按准确message_id、角色、顺序及内容摘要核对；页面消息正文与旧正文不变，允许同轮助手分段。
- 历史运行卡保留原始状态、时间及位置；只允许由准确新轮开始证明的`laterTurnStarted`提示变更，本次仅原第42、43个article的该后缀，不能普遍忽略卡片差异。运行中临时状态不当作持久消息。
- 无新轮次的只读刷新仍比较当下全部有序article全文；任何差异继续HOLD，不能用前述动态提示规则豁免刷新丢失或重复。

只分析已保存差异、SQL、页面DOM和源码，不重发消息修观察器。原批未执行的刷新保留NOT_RUN，后续仅可另批限定一次只读刷新检查现有回答持久化；不扩大真实模型、Job或双用户测试。

## 执行前冻结判据，禁止临时增加假设

第二账号准备只执行了容器与三源码元数据两次读取，native均0；Root在运行时额外加入未审查的“Backend必须UID/GID0”断言而失败。实际Dockerfile的`USER byq`、保存镜像元数据和PID1/exec均为10001，源码文件root归属与进程身份不是同一概念。原批保留FAIL_STOP；SQL、密码生成、账号创建及后续浏览器均NOT_RUN，不改权限或重建镜像。

反复错误的共同原因是只审采集argv，执行时又临时编写解析与判据。后续每个小批必须同时冻结：命令、实际格式和字段路径、每条具名判据的源码/既存原件来源、允许变化与STOP边界；Root只执行已冻结范围，不临时添加硬编码断言。事实不明先保存并HOLD，不推断默认值或伪造通过。优先直接审阅原生事实和已有投影，不新增验证框架。

| 必须分别核对的事实 | 准确来源 | 不得替代它的其他属性 |
| --- | --- | --- |
| 镜像默认启动用户 | 准确Image.Id的白名单元数据、Dockerfile | 源文件UID/GID |
| 实际容器/进程用户 | 已用Compose图与PID1/exec的实际UID/GID | 其他服务的root设置或猜测 |
| 文件归属与可读权限 | 准确tar成员/文件stat | 当前进程UID |
| 前端持久消息与动态运行卡 | message身份/内容及已规范化状态投影 | 所有article一律不可变 |

本片后续只可先使用已保存原件核清判据，独立Sol审查完整剩余命令后才准入；不得重复已成功的两次读回来修复本地断言，也不据此扩大模型/Job或双用户测试。


## 时间属性与显示文字必须使用同一读取表达式

第二账号浏览器批次又出现 Root 采集错误：基线的 `time` 来自 `time.getAttribute('datetime')`，Root 本次却重写为 `time.textContent`。`AgentView.vue:699` 明确将原时间戳放在 datetime 属性、将本地化时间放在显示文字；5张历史卡因此不同，正文、class、aria-label及45篇有序全文均无差异。原批保留 `FAIL_BROWSER_ATTRIBUTE_COMPARISON_STOP`，在独立复审前停止后续日志和所有实时测试，不据此修改产品代码或重发模型。

前段“冻结字段”仍不足以约束执行时手写访问器。随后唯一补证把表达式作为字符串传给 evaluateAll，实际返回undefined并在保存时失败；无新目标JSON，日志尚未执行。接口内部机制尚未确认，不归因Product，原失败收据保留，当前停止所有补证。整改应冻结完整调用源码，包括传参形式、结果类型、序列化和写出，复用此前成功的 function literal 形式，不再引入函数字符串传递或其他动态转换。时间属性和可见文字分别命名；若基线只有属性，就不把本地化文字转换后宣称精确属性相等。未来只可审查准确完整调用后补缺失证据，不重建账号、不刷新重试、不增加业务请求，当前没有新的live GO。
