# DSH / ACP 专项维护当前验收（2026-10-13）

不推进 Product Phase。应用闭包基线为 `55033eb0937665bf1d19f848de1f185353f7dbc0`，基于同步后的 `origin/main=ad5f7df1ad18e54dd0d9860d424241297187eef8`。新增租约观察切片的五文件源码 SHA 单独记录于 ROOT-LEASE-OBSERVER-OFFLINE-FAIL-STOP.json；修正入口后的定向离线验收见ROOT-LEASE-OBSERVER-OFFLINE-PASS.json，真实状态验收仍未完成。

## 最新浏览器切片（2026-10-15 北京时间）

运行时/任务身份与用户登录/Job 提交身份已分开。真实核心运行源码为 `4c963fdef901b7c983343a930a8c54a1202bc424`；前端分轮修复源码为 `5ba25f2c775f8c04a271ea07ba9e7b8d1f786503`。保留环境现在是 `byq-dev-e8b02b5475` 的 16 个容器、端口32790及原账号/数据库卷。后台 Worker 新增运行，不带健康检查；其余15个容器有健康状态。未操作生产、推送或合并，不推进 Product Phase。

**真实核心限定 PASS：** 原浏览器通过 Gateway/Product API 提交恰好一个 SignalJob `signaljob_68060a47070f447e958efbfdba5fd987`，复用已核对的合成生命周期数据，不下载行情。Job 完成后，在原绑定会话 `conversation_d1970f74cbcb4703b8c182523db4c4f1` 自动发起一次接续，未补发用户提示、未请求单独续接许可。新 Root `d1ccf5479f5a40c390b3c5f9ced39415` 完成，回答持久化，预留已结算、权限已关闭、unknown claims 为0；Adapter、Backend 和 Gateway 的 boot/root/终态序号39/hash一致。6次模型请求、7次工具调用，用量 input173179/output4330/cache-read140672，cache-read 包含在 input 中；执行上限参数为 null。两项指定业务读取分别有 AUTO 授权和 read_ok 审计。独立 Sol 已限定通过，Root 见私有 `ROOT-REAL-CORE-PASS.json`。不据此声称独立逐项重建全部7次调用。

**真实浏览器原批次保留 FAIL_UI；修复后回放限定 PASS：** 新回答最初被前端拼到旧 assistant 气泡，数据库原标记行没有被改写。前端最小修补按规范化 run 边界合并同轮片段、隔离不同轮次，并处理 Gateway 刷新时已过滤持久 delta 的实际响应。37项定向测试和类型检查一次通过，独立 Sol→Root 离线 PASS；只更新 frontend-f6 后，原标签刷新显示旧标记独立、新回答五段同泡。其他15个容器ID不变，刷新未新增模型或 Job。独立 Sol 核对实际安装回执、库存、AX及截图后限定 PASS，私有收据为 `SOL-BROWSER-BOUNDARY-FINAL.json`；修复后的实时流只由离线测试覆盖，没有为此重跑 Job，原批次 FAIL 不覆盖。

**用户交互确认：** 维护者确认“分开了，显示正常”，并要求继续处理余项、保留当前环境和页面；没有将该确认计作一轮新的模型输入。

**残余 Backend 负例：新增7项隔离测试限定 PASS。** 修补源码 `231ab0b832037ba012cd7b2fc152ac04594ca331` 仅改变测试文件，生产实现未改。旧 `wrong_owner` 失败是非法修改既有 root 身份，被数据库 fence 正确阻断；当前个人工作区一人一个，因此将两个不合法独立错配负例合并为一个合法 `foreign_personal_scope`。隔离库中的第二用户/工作区/会话/root 的绑定逐字段核对后，结算被拒且 ledger 不变；其余新测覆盖错误 session/trace、未知证据、准确 digest/幂等、工具目标授权和取消后的授权拒绝。新批次收集7项、一次7 PASS / 0 FAIL / 0 SKIP，pytest15.84秒；Root计时含临时准备/清理126.668秒，非独立UTC起止对。Tester、独立Sol→Root限定PASS，私有收据在 `.ci-artifacts/background-residual-20261015-v1/`。模型/真实Job为0，临时资源按准确ID清理，保留16服务的ID/镜像均不变。旧20 PASS按未变依赖复用，旧1 FAIL / 7 NOT_RUN原件保留，不写成同批27/28项全通过，也不声称独立覆盖owner-only/workspace-only两分支。

**Product MCP Job 来源准入：离线限定 PASS。** 源码 `a1775f6e971442c0773ccc02687f77b2e6cc398b` 为现有 `byq_backtest_task_create` 私下传递准确 ingress、Backend proof 与签名原生身份；Job 提交事务核验当前 boot/root、绑定 AgentRun、角色、用户策略、完整参数及原 Task/Conversation，再原子写入 Job、池引用和不含凭据的 `authorized_agent` 来源，单个 MCP 请求只能认领一个 Job。既有记录的创建重试也复核当前权限与策略，未知来源不升级；人类来源与 bootstrap/null 兼容保留。这是业务创建授权核验，没有新增接续许可或 Product DSH 权限。冻结源码的 MCP 构建及5个原生脚本通过；Backend 新11项与4项共享影响回归共15项通过，pytest28.84秒，含临时准备/清理131.478秒，小于420秒。Tester、独立Sol→Root限定PASS，私有收据在 `.ci-artifacts/mcp-signal-origin-20261015-v1/`，模型/真实Product Job均为0。

**本片失败原件保留：** 首批Backend准确采集15项后，新测试误把 `task.references.research_task_id` 读为顶层字段；HTTP202后断言失败，原批为0 PASS / 1 FAIL / 14 NOT_RUN，立即停批。整11项静态合同重新核对后，只修测试一行，再经过独立审查执行新的同15项批次；没有改产品投影来迎合测试，也没有覆盖原失败。入口重名HOLD及修正、原始stdout/stderr、独立容器退出码和清理记录分别保存。两个批次均只使用隔离内网/tmpfs库，所有临时资源按准确ID清理，保留16服务ID/镜像不变。

**Agent 来源消费端：离线11项限定 PASS；已安装隔离环境，真实工具准入仍FAIL。** 当前 Git 基点为 `23764218130009c75a691eaa62c84e3ed30eb4f2`，候选 `research_continuation.py` SHA-256 为 `5b8eb11e79b83df6d39d4b26b781184c05f73611dd79c7b9fb3585770078a375`。候选只扩展现有 v3 校验：准确的历史来源 Root 必须 completed/closed，并核原 AgentRun、角色、原生绑定、已结算 ingress、冻结终态摘要、同一 Job/Task/Conversation 和 validated snapshot；不要求旧 boot 仍 current，不增加许可、调度器或 Product DSH 权限。提交前的 Python 哈希原像可能被 JSONB 数值规范化改变，因此不假装能从持久 JSONB 重算 Job 原摘要。这不代表真实接续 PASS。

**消费端两次离线批保留 FAIL，统一合同重审后另批通过。** `actual-v2` 收集11项，首项测试把首次只读 `eligible` 预览误当持久 `intent`，结果0 PASS / 1 FAIL / 10 NOT_RUN，pytest3.76秒、含准备清理169.752秒。整11项返回/状态合同复核后，`actual-v3` 再收集11项，首项在预览符合合同后把原始 SQL NULL 账本误断言为JSONB空数组，再次0 PASS / 1 FAIL / 10 NOT_RUN，pytest2.98秒、含准备清理141.569秒；均在420秒观察上限内。CLI与独立容器状态均确认exit1、无OOM，stderr为空。第二次同类错误后停止后续执行，统一重审DDL、INSERT、raw helper、内部规范化和API三层合同；没有更改Product API/数据库默认值来迎合测试，也没有继续调用模型。最终测试源 SHA-256 `11bce713ef445b96105c3333f2e3a3026c00f53c2c3bb40e063a0cfc12d018b7` 已统一保存原始账本baseline并验证预览/等待不改变它，claim后才核单项数组；修订后经独立入口审查，新 `actual-v4` 批收集11项、一次11 PASS / 0 FAIL / 0 NOT_RUN，pytest34.78秒、含准备清理129.664秒，小于420秒。完整stdout、空stderr、CLI exit0与独立容器退出0/无OOM一致，Tester、独立Sol→Root限定PASS，收据为 `ROOT-CONSUMER-OFFLINE-PASS.json`。v4初次只读预检误用了网络列表不支持的 `-a`，CLI失败原件单独保留；修正预检及逐个名称不存在检查通过后才创建临时资源。人类/child正例计划只验证到派发，root正例才覆盖accepted/closed/settled；账本比较是解码JSON值相等，不冒充原始数据库字节比对。私有完整证据在 `.ci-artifacts/agent-origin-consumer-20261015-v1/`。模型与真实Product Job均为0，准确清理临时容器/网络后，原16服务ID/镜像不变，账号/卷/原页面保留。

**两服务本地安装限定 PASS：** 本地提交 `5b6586585a963cd991e8d4ef9986c91a302137b2` 经离线构建及独立Sol→Root，隔离环境仅更新Backend-f6/MCP-f6。两份镜像为 `sha256:b9ff6e279f8335bce1f7875142accace6a632834c990620320f6fecb4b729bed`、`sha256:7b27e3cd55d64ca13d65214a17064cd6c975a61eac7ea2324113fad29afaca9f`；其余14容器ID/镜像/完整挂载字段不变，16运行、15健康检查正常，账号和数据库卷保留。安装前已完成私有备份、空闲/未知结果/准确scope检查；Mount数组无序却被Root按顺序比较的初始观察器FAIL另存，完整合同审查后v3检查通过才执行。安装后Root执行96/75源码哈希逐项相等检查，保存原生结果为计数汇总，不冒称独立逐文件原包。原Job、9条消息、3个关闭Root与ledger保持原样；用户重新登录后页面正常。

**当前浏览器真实MCP来源切片：FAIL，已停批，不重放。** 一次用户输入仅新增 `signaljob_46719b91b3d049bd9ed2051b4ac2cb86`，持久来源为authorized_agent v2；Job完成并复用既有合法合成输入，来源Root `e2fb65efed444ec38e9bb7253dfe716c` completed/closed、终态49、unknown0。系统随后无需用户补输入自动发起新Root `11b3b4854b964dd1a406e4bb4c8e8ea5`，但第一项 `byq_agent_run_start` 被MCP报 `continuation_action_not_admitted`；Backend准确authorize-tool路由返回422。因此没有实际业务读取，后台回答明确报告阻断，并分轮展示；Runtime completed/closed56、usage/ledger settled不能作为业务成功。后台观察到2模型请求/1工具调用，用量input89668/output1873/cache-read45184（cache包含于input），参数null且无limit violations。356.234秒内保留FAIL现场，小于600秒观察窗；未补发提示、重建Job或重放已settled预留，未扩大后续场景。私有完整记录见 `live-agent-origin-browser-v1/FAIL-STOP.json`。

**工具准入最小修补：源码静态审查 PASS，新增12项首批离线 FAIL 保留；修订后软件PASS，未安装。** 独立Sol确认 v3 authorize 分支查询漏取 trace_id、idempotency_key、request_hash、submission_hash；同事务复用现有完整 `_recheck_v3_source_binding`，不放松来源、身份、取消、读目标或写动作守卫。app SHA-256 `b1d90e4bb1a24ca604d88c75c723c574cc90d059a109a876b0843a86ad8a2fa4`。新增12项真实Backend HTTP路由合同经静态审查后，仅在隔离tmpfs库采集/执行；首项human-v1在准备研究任务时响应缺task_id，KeyError，尚未到authorize-tool。该批 **0 PASS / 1 FAIL / 11 NOT_RUN**，pytest2.95秒，清理/标签检查至88.866秒；保留环境复核收据保存时间距起点103.31秒（文件mtime边界，非独立命令UTC对），均小于420秒，CLI及独立State exit1、无OOM、stderr为空。准确临时资源已清理，保留16容器ID/镜像/完整挂载及15健康检查不变；模型/真实Product Job为0。当前停止实际执行，重新完整审计12项的auth、session/trace、helper顺序和HTTP响应合同；原失败 `authorize-tool-repair-v1/actual-v1/FAIL-STOP.json` 保留。独立源码定位不冒称已采获此前HTTP422的响应detail，旧11项PASS不等于新工具路由通过。

**统一夹具重审后的新12项批次：Tester、独立Sol→Root限定软件12 PASS。** 随机trace与既有固定strategy-chain正文trace不一致是测试准备错配；全12项身份/header/helper/route/Root/ledger合同重审后，仅human正例保留唯一session、固定匹配trace，并新增身份断言。test SHA-256 `b74a20a417a7830d2ca78d85442b8a87e4545c1b7ec8d867ce3e168b1f6914cf`，原11项AST保持相同，app修补不变。新隔离 `actual-v2` 精确收集12项，一次 **12 PASS / 0 FAIL / 0 NOT_RUN**，pytest26.73秒；Root计时从12:51:18.276Z至12:53:11.995Z，含清理和保留环境复核终态/保存113.719秒，小于420秒。CLI及独立容器exit0、无OOM，stdout825B/独立stderr0；3临时容器及内网按准确ID清理，保留16容器完整ID/镜像/挂载、15健康检查不变。模型/真实Product Job为0，仅证明Backend HTTP工具准入决策；不冒充MCP业务读取、浏览器或生产PASS。独立Tester、Sol核对原始收据后，Root限定软件PASS见私有 `authorize-tool-repair-v1/ROOT-OFFLINE-PASS.json`。原离线与真实FAIL均保留，不重放原已结算预留。

**后续范围仍HOLD：** “original-task permission”为旧泛化报错文案，不能据此恢复单独接续许可。当前不重放已settled预留，不继续真实模型测试。两用户真实隔离、迟到/未知结果、取消与后台竞争、进程异常、旧固定证据数量边界的执行影响等仍待分别审计/验证，远程CI/发布/生产仍HOLD/NOT_RUN。原测试环境和页面保留供当场互动；当前无需用户再提供登录或凭据。


## 此前切片（2026-10-15 北京时间；以下保留各切片当时版本）

**搜索配置和前台委派于隔离版本 `0be2f56c` 通过限定真实浏览器验收；该切片当时 ACP 两服务更新到 `0a372d18`，其余12服务当时保持原版。** 用户在“模型配置 → 搜索服务”安全保存独立 DeepSeek 官方 Key；刷新仍只显示掩码。随后同一会话完成一次搜索和一轮无工具继续输入，历史消息 8→10→12，两个 Root completed/closed、unknown claims=0；模型代理实际3次完成。搜索返回来源链接，原生搜索服务 HTTP/用量未采集，天气数值答案质量不由此通过。独立 Sol → Root 的范围见 [搜索验收收据](ROOT-OWNER-SEARCH-BROWSER-PASS.json)。系统 `.env` **模型 Key** 退役仍是后续迁移要求，未称已完成。

**当前版本单前台子 Agent：Sol → Root 限定 PASS。** 原页面一次输入、一个子 Agent、零 Job 意图；161.47秒内核对父子绑定、三条 settled 子 Agent 入口和四条 audit，当前工具 guard 的数值限制为 null，6次工具调用符合计划。8个模型代理请求均200，Root aggregate input=229231、output=1234、cache-read=169344；cache 不再加到 input，不分摊子 Agent 账单。Backend Root/两个 AgentRun 均 completed/closed，exact ACK seq53/hash 与持久化回执一致，签名进程组清理通过，11表计数前后一致。刷新后最终 ROOT_OK 显示一次；DB消息12→15，包含模型先发的绑定说明，不能写成只有一条 assistant 存储行。见 [委派验收收据](ROOT-CURRENT-FOREGROUND-CHILD-PASS.json)。原历史采集失败保留 FAIL，未被新批次覆盖。

**后台 Backend v3 原子预留：Tester → Sol → Root 限定软件 PASS。** 精确已完成 SignalJob/validated snapshot 的预留、并发去重、原会话隔离、旧未知结果与显式停止保护通过9项新测试及1项有效复用；不是一次新跑10项。原观察器字段错误和测试局部变量错误均保留 FAIL_STOP，修正后补齐22项观察器样本与8文件未定义名检查。该入口尚未接入 Gateway/dispatch，真实后台自动接续仍未验证，见 [Backend 软件验收](ROOT-BACKEND-V3-RESERVATION-SOFTWARE-PASS.json)。

**公开网页读取：Tester、独立 Sol → Root 限定真实浏览器 PASS。** 源码 `0a372d18` 的官方 fetch 已安装到保留环境的 ACP 两服务，使用同一镜像 `68c3a1eb...`；其余12服务、原账号、数据库和端口32790保持不变。原会话两次输入，消息19→21→23且历史前缀不变；首轮一个“读取公开网页”活动开始/完成对，页面显示内容及来源，第二轮准确记住标记，刷新后均保留。两个 Root completed/closed、unknown0并匹配各自终态ACK，11表计数未变；原始浏览器回执证明246.865秒内完成。3次模型代理完成及用量单独记录，不冒充原生fetch HTTP/正文、天气事实准确性或结算证据；回答偏长与AX来源主机简写也保留。此前控制入口失败原样保留，原V1/V2脚本已退役，最终采用原生 Compose 更新。见 [抓取浏览器验收](ROOT-PUBLIC-FETCH-BROWSER-PASS.json)；[原离线软件验收](ROOT-PUBLIC-FETCH-SOFTWARE-PASS.json)保留当时NOT_RUN状态。生产、后台接续和发布仍未由此通过。

**下一缺口：后台实际消费链仍走旧许可逻辑。** 合同/guard/传输的离线 PASS 不等于默认自动接续。只读确认当前采样的9类 Job/运行表计数为0，ResearchTask=1、Artifact=3；无现成 SignalJob 可复用。Backend 的精确 Job/validated snapshot → v3 原子预留与去重已完成限定软件验收，下一步接入消费链；本次尚未执行真实后台 Job。取消、进程异常、两用户、迟到/未知结果、官方固有限额和最终CI/发布/生产门禁仍未由上述切片证明，整体 NOT_READY。保留14容器测试环境、端口32790、原账号/卷和浏览器页面，不推进 Product Phase、不操作生产。

## 最新进展（2026-10-14 北京时间）

**后台续办准备：限定 Product 读回 PASS，后台执行仍 NOT_RUN。** V6 完整入口的 12 项独立替身通过；一次正常登录和七个精确 Product GET 确认 Task、不可变 Version 及股票池两成员/v1 快照投影。策略批准 UI V1 意外结果保留 FAIL_STOP；V2 一次确认后进入回测页，精确读回 validated approval、execution_outcome=not_started，未提交计算。续接许可自动 checkbox 操作及时间门禁 FAIL_STOP 保留；用户明确报告自己提交，独立只读核对既有许可的身份、版本、profile、预算和 waiting_for_event，不算自动 UI PASS。每次读回均固定 8 HTTP、无重试；Sol→Root 限定验收见 [ROOT-BUSINESS-PREPARATION-READBACK-PASS.json](ROOT-BUSINESS-PREPARATION-READBACK-PASS.json)。采集入口 [V3 SOURCE HOLD](ROOT-PRODUCT-PREPARATION-V3-SOURCE-HOLD.json)、[V4 FAIL_STOP](ROOT-PRODUCT-PREPARATION-V4-FAIL-STOP.json) 均保留。Job、Worker、自动续办与生产资格仍 NOT_RUN，整体 NOT_READY。

**当前优先修复：统一右上角审批铃铛。** 用户指出研究页应只读审批历史。审计确认铃铛仅接 AgentApproval，续接许可、策略与 ML 版本批准仍分散。当前切片将待办统一到 Bell，保留各领域权威授权事实；批准本身不启动计算。已有用户提交的许可与策略批准不重建、不撤销。FG2/后台 Job 验证暂停至该维护切片完成，测试环境和页面继续保留。

**预算停止后同一会话新输入：V4 真实浏览器限定 PASS。** 登录过期后用现有测试身份重新登录，未重置密码；准确原 CID 新增一次明确纯文字输入和唯一回答，消息数 2→4。一个新 Root/native/generation 正常 completed/closed，旧失败 Root 不变；1 次模型请求、峰值 1，已知 Task/两 Artifact 整行及时间版本不变，Job 前后采样 0。精确 ACK 与真实签名清理一致，8 条原生 Docker 回执均 rc0，整批至最终身份检查 163.83 秒 < 180 秒。批后单独刷新仍只有一份回答；guard 未读、任意工具覆盖 UNKNOWN，不等于后台业务或子 Agent 恢复。Sol → Root 限定 PASS，见 [ROOT-BUDGET-NEXT-TURN-BROWSER-V4-PASS.json](ROOT-BUDGET-NEXT-TURN-BROWSER-V4-PASS.json)。后台 Job 接续及生产仍 NOT_RUN，整体 NOT_READY。

**最新用户界面切片：** 研究提交核对的手动 GET 原已返回 200，但没有完成反馈。`d0c3bcb8` 补上“刷新核对记录”、进行中/完成状态与最近成功读取时间，5 项测试和构建及独立审查 PASS。`7d4d5757` 修正新会话 URL 保留 `?new` 的缺口，27 项定向测试及源码审查 PASS；正常首次发送的自动 CID 路由仍待真实浏览器验证。隔离前端已更新为 `35c2a90f...` 并健康，原 CID 实际手动刷新显示“核对记录已刷新”和时间；真实页面验收另记，未创建新模型/Job。

**F6 浏览器 V1：FAIL_STOP。** 第一轮实际9次模型请求均200完成，下一个候选因累计工具载荷 `959204 + 118477 > 1048576` 在发出前被拒绝；不能归因为16次调用、并发或OC配额。既有 Accepted ADR 明确重复计算目录及工具历史，未调整限额或去重。准确原键对账确认同 CID 的 Task、validated Draft/Version 均已保存，Root failed/closed、unknown claims0、Job表采样0；回答缺失，FG2/Worker/BG NOT_RUN。原 summary 定位错误已保留并更正归因。下一批将复用已核对的对象，先审查单目标流程，不能重放旧创建请求。见 ROOT-F6-BROWSER-V1-FAIL-STOP.json。

**交互验收保留：** 用户明确要求测试后保留运行环境和测试页面，邀请用户一起操作并当场修问题。当前隔离服务和浏览器保持打开；此前自动 teardown 计划不再执行。

**刷新按钮交互验收：PASS。** 用户在当前隔离页面反馈“能看到，正常”；浏览器 AX 和截图另记录成功反馈及最近成功刷新时间。独立 Sol 审查及 Root 的限定验收已完成，见 [ROOT-RECEIPT-REFRESH-INTERACTIVE-PASS.json](ROOT-RECEIPT-REFRESH-INTERACTIVE-PASS.json)。首次发送自动 CID 路由、后台 Job 接续和生产仍不由此证明。

**F6 旧轮次清理证据：只读 PASS。** 修正版采集入口完整主流程替身 5/5 后，经独立审查执行一次四调用/30 秒上限读取，实际约 0.364 秒。真实字段确认旧进程退出且清理已确认，Gateway 的 failed/seq14/hash 与签名回执精确对应；公开会话未结束。Runner 的退出 reason=cancelled 不改变 Backend Root=failed。原采集器静态失败及原 F6 FAIL_STOP 保留，下一轮尚未运行，见 [ROOT-F6-PRIOR-ROOT-CLEANUP-READ-PASS.json](ROOT-F6-PRIOR-ROOT-CLEANUP-READ-PASS.json)。

**页面停止后同一会话再次输入：V3 真实浏览器限定 PASS，Sol → Root PASS。** 原因已确认：页面“停止本轮”原来发送 hard cancel，并设置会话终态、关闭事件流；此前 API soft PASS 未覆盖页面缺陷。旧失败会话的 hard 历史保留。修补后页面使用已有 soft cancel，等待匹配轮次终止，保留 CID 和事件流，再由用户明确输入新指令。

在源码 `a0818970855cebab428e8f467cc1400272efc351`、隔离前端镜像 `378852e7...` 上，实际页面两次输入、一次停止点击，同 CID 收到唯一 `SAME_CID_OK`，刷新后仍只有一份，102036ms < 180000ms。只读补查确认对话 active、旧 Root cancelled/closed、新 Root completed/closed、各 unknown claims=0、两条精确 ACK；指定 11 表采样时全零。Provider 次数未测，计费 UNKNOWN。真实 V1 的创建 503、V2 错过停止窗口均保留 FAIL_STOP，不算成功取消。见 ROOT-UI-SOFT-CANCEL-BROWSER-V3-PASS.json。

V3 发现结算后等待文案残留，非阻断。最小修补已在 `8eb3ad3841a6c5430512e3f51ec65a9d6015e94d` 完成，40 项定向测试、构建、独立 Sol 与 Root 离线 PASS；该版本没有另作真实模型取消验收，见 ROOT-UI-SOFT-CANCEL-WAIT-TEXT-V4-PASS.json。整体仍 NOT_READY，未推送、合并或生产部署。

**F6 浏览器 V1 之前的环境与数据准备证据：** 已启动五个新增隔离应用服务且健康，端口 `32790`，三项 F6 flag 为 1；这只证明隔离启动。数据准备首次 `factor count mismatch`、rc3/无 COMMIT、8 项范围回滚全零的失败保留。随后最小修正因子哈希后置条件，离线一次生成及 Sol 审查通过；隔离 PG 原生单事务写入 193 条合成记录、三个调用均 rc0/最终 COMMIT、容器身份前后相同，1241ms < 30s，Sol → Root 限定 PASS。见 ROOT-F6-SYNTHETIC-FIXTURE-COMMIT-PASS.json；合成周末和 provider 标签不表示真实 Tushare 或数据质量。当时尚未运行 F6 模型或 Job；后续浏览器 V1 的 FAIL_STOP 及未运行范围以上面的最新记录为准。临时采集入口的解释器、回执覆盖和语法失败保留；改用原生 CLI、分开保留 stdout/stderr 与工具退出码后，替身入口和实际五服务启动均通过独立 Sol 限定审查。

**此前 API 直接 soft 的历史限定证据（63be22f6）：** 完整采集入口替身 V3 已通过；真实浏览器两次输入与一次 Gateway/Product soft 请求在同 CID 完成，唯一回答 `SAME_CID_OK` 已持久化，118961ms 未超过共享120秒。当时 UI 停止按钮仍是 hard，该历史切片显式调用 soft 接口，不能替代上面的新版页面验收。旧 Cookie/loader 夹具失败和错过取消窗口的真实 V1 均保留。

该历史 API 切片随后独立补查9次只读调用/499ms：旧Root cancelled、新Root completed，授权均closed；两条精确ACK与各自签名进程组清理关联通过Sol→Root PASS。新请求1次、并发1、跨度2984ms，usage29613/26624/39；取消请求计费用量仍UNKNOWN。11表计数全零且四个隔离容器身份未变。两份binding.closed=false、native/process close=true，清理reason=cancelled分别呈现。原子Agent映射、两用户、后台完成续办、进程丢失等剩余项不由该历史切片替代；整体仍NOT_READY。

| 项目 | 结果 | 范围 |
| --- | --- | --- |
| 完整应用闭包及定向离线回归 | PASS | 22 路径闭包、typed Artifact fixture 修补、48 MCP 合同及已记录定向检查；见 ROOT-COMBINED-OFFLINE-PASS.json |
| 已有精确 scope 的签名清理回执 | PASS | 替身34例及一次既有回执读取；不等于恢复原子 Agent；见 ROOT-EXISTING-SIGNED-CLEANUP-READ-PASS.json |
| 计数与委派预算机制旧证据 | PASS 限定复用 | 源码哈希与机制边界相同；不重复模型；见 ROOT-TOOL-COUNT-EVIDENCE-REUSE.json |
| 生产 ACP 源码版本对应 | PASS 限定 | digest150b4802通过正式部署/准入/manifest对应源码33152f65；健康不替代真实业务验收；见 ROOT-PRODUCTION-SOURCE-ATTRIBUTION-PASS.json |
| 新 MCP 镜像源码读回 | PASS | `08dcc976...`，构建/源码资格；见 ROOT-COMBINED-MCP-IMAGE-SOURCE-PASS.json |
| 隔离 MCP 服务更新 | PASS | 新容器健康，其余10个隔离服务及17个生产库存未变；见 ROOT-ISOLATED-MCP-UPDATE-PASS.json |
| 浏览器采集入口 V2 替身 | FAIL_STOP | 首例将合法重复读取误判；一次执行后停测，全面重审采集合同；见 ROOT-BROWSER-V2-OFFLINE-FAIL-STOP.json |
| 此前旧隔离Runtime的真实 Product / 浏览器 | PASS 历史限定单轮 | 旧a212运行时及此前隔离MCP修补的手动8次模型、零新Job；刷新后唯一回答、持久化/交付/Root结算一致；独立Sol及Root PASS；不替代本轮fac40候选镜像资格；见 ROOT-MANUAL-BROWSER-ONE-TURN-PASS.json |
| 两用户测试 Compose 合同 | PASS 离线限定 | 实际默认链解析，3项+6子测试，独立Tester/Sol/Root PASS；真实用户/实际挂载仍未验证；见 ROOT-TWO-USER-OFFLINE-CONTRACT-PASS.json |
| 两用户真实预检入口 | FAIL_OBSERVER_STOP | Root猜错表名；只读查询失败，零模型/Job/用户/容器变更；停止后重审查询复用方法；见 ROOT-TWO-USER-LIVE-PREFLIGHT-FAIL-STOP.json |
| 两用户预检完整性源码审计 | PASS 发现缺口 | Sol确认readyfile、无子进程、Backend roots闭合不能证明Adapter lease已释放；当前`slot_available=UNKNOWN`，真实批次保持停止，先完善只读采集合同 |
| 实际Adapter租约匿名只读计数 | PASS 定向离线限定 | 平级挂载修正后Runtime6/Gateway3通过，Tester→独立Sol→Root PASS；模型/Job0、原27容器未变。首个挂载FAIL保留，真实计数/旧进程租约仍未验证；见ROOT-LEASE-OBSERVER-OFFLINE-PASS.json |
| 最新Root读取器 | PASS 离线限定 | 按BYQ session文件名、独立native UUID校验；10用例+Sol+Root通过，原身份混同源码FAIL保留；见ROOT-LATEST-ROOT-READER-OFFLINE-PASS.json |
| 最新Root实际只读采集预检 | FAIL_OBSERVER_STOP | Docker可选Health字段导致5行渲染失败，rc1后误用部分22行；原始ps仍27 ID。6实际读取全部NOT_RUN、模型/Job0；保留日志，先完整修正入口；见ROOT-LATEST-ROOT-READ-PREFLIGHT-FAIL-STOP.json |
| 库存入口V3与完整实采入口 | PASS 库存限定 / FAIL 实采入口 | 4替身用例通过；实际前后27容器全部ID/image/start等一致。临时wrapper解析基准相对路径错误，6数据步骤仍0执行；不重试，先固定完整执行脚本并走完整替身；见ROOT-INVENTORY-ENTRY-V3-OFFLINE-PASS.json、ROOT-LATEST-ROOT-READ-V3-FAIL-STOP.json |
| 固定完整采集入口V4 | PASS 离线限定 | 一次执行6项完整流程替身；路径、失败停步、截止时间和源码漂移门禁通过Tester→独立Sol→Root；旧失败保留；见ROOT-FIXED-ENTRY-V4-OFFLINE-PASS.json |
| 最新Root实际只读采集V4 | PASS 已有Root限定 | 固定入口一次执行、6数据exec、模型/新Job0；14步骤及前后哈希PASS、27容器不变；实际签名cleanup与Backend闭合/持久化receipt一致。实际ACK/global lease/native close仍UNKNOWN；不替代新候选Runtime或浏览器资格；见ROOT-LATEST-ROOT-READ-V4-PASS.json |
| 浏览器普通续聊补缺观察 | NOT_QUALIFIED | 一次实际输入，37秒内正确回复，刷新后两轮各一次；但Root取证到190秒超过整批120秒，模型计数/Job增量/新Root结算未核验，已停后续prompt，不作为候选资格PASS；见ROOT-BROWSER-CONTINUE-OBSERVATION-STOP.json |
| 最新候选原生隔离启动 | PASS 构建/健康限定 | 原生dev-init/core；三个ACP角色同一镜像且健康，新Registry匿名计数已读回，原27容器不变。联合启动登录服务的健康等待失败保留，单独Frontend启动后完成真实网页登录；不等于模型或生产验收；见ROOT-NATIVE-ISOLATED-BOOTSTRAP.json |
| 精确Adapter ACK成功观察日志 | PASS 源码/离线限定 | 仅Gateway成功收到相等ACK后记录脱敏Engineering日志，四定向测试通过独立Sol及Root；丢日志仍UNKNOWN，不改变权限或结算。Host两次import失败保留；见ROOT-GATEWAY-ACK-OBSERVER-OFFLINE-PASS.json |
| 候选Gateway ACK镜像 | PASS 隔离镜像/健康限定 | 源码哈希读回及json-file日志驱动一致，其他35个容器库存未变；实际Root ACK仍NOT_RUN；见ROOT-GATEWAY-ACK-IMAGE-PASS.json |
| 普通双轮采集入口原始失败 | FAIL_STOP | 原始源码门禁及两次替身失败保留；分别涉及文件重复写入、阶段依赖循环、替身SQL分派和可选参数签名；均不证明Product失败；见ROOT-ORDINARY-CAPTURE-SOURCE-FAIL.json、ROOT-ORDINARY-CAPTURE-OFFLINE-FAIL.json、ROOT-ORDINARY-CAPTURE-OFFLINE-V2-FAIL.json |
| 普通双轮完整采集入口 | PASS 离线限定 | 25项一次性全入口/负向合同通过Tester→独立Sol→Root，真实登录逻辑与原生压缩投影算法保留，仅传输边界替身；原失败不覆盖；见ROOT-ORDINARY-CAPTURE-OFFLINE-PASS.json |
| 新候选真实浏览器普通双轮 | FAIL_STOP | 两次真实输入/回复正确，两条模型完成记录和精确ACK已观察；原生历史采集因默认UID错误而失败，finish和完整Job增量NOT_RUN。已证明同卷同inode、Runner默认root读取0700目录被拒；改用已有child身份仅元数据定位成功，未重发模型。见ROOT-ORDINARY-BROWSER-LIVE-V2-FAIL-STOP.json |
| 原生历史读取入口完整修补 | PASS 离线限定 | 修正UID、官方精确路径、原始命令/源码哈希关联、替身目录与各阶段路径，35项一次批次通过Tester→Sol→Root；静态与首轮替身FAIL保留；见ROOT-ORDINARY-NATIVE-READER-OFFLINE-PASS.json及ROOT-ORDINARY-NATIVE-READER-*FAIL*.json |
| 已有原生历史真实只读解析 | PASS 既有文件限定 | 20秒/2exec上限，169ms完成，10002:10002实际读取官方源码/profile与v4历史；两个人类输入哈希按原浏览器A/B顺序一致，模型/Job0。不恢复旧失败批次、不替代新双轮整体验收；见ROOT-EXISTING-NATIVE-INPUT-READ-PASS.json |
| 新候选普通连续双轮完整真实验收 | PASS 本切片限定 | 新CID f6d08，一次2提示词/2个已完成模型请求，finish及刷新证据240秒内；持久化2user2reply各一次、两Root closed/unknown0、精确ACK与结算一致、11表库存不变，Source→35离线→真实采集→独立Sol→Root PASS。租约只瞬时/非全局，旧FAIL不覆盖；见ROOT-ORDINARY-BROWSER-LIVE-V3-PASS.json |
| 单子 Agent scope 采集叶节点 | PASS 离线 / 既有普通 Root 只读限定 | 15项替身合同一次通过；冻结入口一次只读SQL、前后精确PG身份一致、277ms完成，普通Root可合法无native registration。源码审查HOLD和错误actor计划保留；不等于真实委派、子模型分账或签名cleanup。见ROOT-CHILD-SCOPE-OFFLINE-PASS.json、ROOT-CHILD-SCOPE-EXISTING-READ-PASS.json |
| 单前台子 Agent 完整采集入口 V1 | FAIL_STOP 替身 | 29项计划中22 PASS、1 FAIL、6 NOT_RUN；总时间窗负例同时违反单次时限，提前触发不同守卫。独立Sol确认fixture时间戳及负例分支核对缺口，先修整组测试再冻结；完整main正例和真实委派未执行，模型/Job0。原始回执见ROOT-FOREGROUND-CHILD-OFFLINE-V1-FAIL-STOP.json |
| 单前台子 Agent 审计集合合同重审 | HOLD → 源码修补审查通过；测试待准入 | 发现旧观察器错误要求仅一条audit。按Backend的绑定、授权和显式completed完整记录分类，并覆盖两种关闭路径；native/Backend一致的failed或unknown仍拒绝。负例返回码、守卫顺序和回执标签错配在静态审查中被拦截，未重跑或发送真实提示词；见ROOT-FOREGROUND-CHILD-AUDIT-SOURCE-HOLD.json |
| 单前台子 Agent 完整采集入口 V2 | FAIL_STOP 替身 | 18方法17 PASS/1 FAIL；两种完整main正例通过，但24项负例matrix仅1 PASS/1 FAIL/22 NOT_RUN。共享helper.Stop与采集Stop类不同，已知读取拒绝被误记internal_Stop；同类错误后立即停批，独立Sol审查全部共享异常路径，统一边界修补仅一行，未重跑或真实调用。见ROOT-FOREGROUND-CHILD-OFFLINE-V2-FAIL-STOP.json |
| 单前台子 Agent 完整采集入口 V3 | FAIL_STOP 替身 | 最小5方法4 PASS/1 FAIL；24项matrix仍1 PASS/1 FAIL/22 NOT_RUN。具体Stop原因已保留，但上一轮审查错误混同native命令rc与collector rc：UID/GID前置字符串SystemExit实际rc1，try内header拒绝rc2。停批后完整审计inline reader、替身wrapper及全部24路径，生产reader未修改；见ROOT-FOREGROUND-CHILD-OFFLINE-V3-FAIL-STOP.json |
| 单前台子 Agent 完整采集入口离线门禁 | PASS 离线限定 | V4一次新验5方法及24项停止matrix全部通过（1267ms），独立Sol原始回执及Root PASS；复用V2未影响12项预算/原生helper和1项finish正例、V1 scope16。两种完整关闭路径、raw argv/rc/bytes/SHA、首STOP与后续禁入已验证；synthetic身份/MAC不冒充实采，旧V1–V3 FAIL保留，真实委派NOT_RUN。见ROOT-FOREGROUND-CHILD-OFFLINE-PASS.json |
| 单前台子 Agent 真实浏览器 V1 | FAIL_OBSERVER_STOP | 一次提示词，实际Root completed/closed、unknown0、两个native注册、三条ingress settled及四条audit，页面显示ROOT_OK；139.9秒时原生读取报native_event_invalid后停批。完整native链、预算、MAC/ACK、Job增量及finish/reload均未验收。官方源码证明seq0合法，当前观察器过严，但实际失败行尚待单独只读形状诊断；未重发模型。见ROOT-FOREGROUND-CHILD-LIVE-V1-FAIL-STOP.json |
| 原生零序号首记录定位与统一修补 | PASS 首记录诊断 / 离线限定 | 一次独立102ms只读确认Root记录2仅因合法seq0被拒（模型/Job0）；统一producer与host各序号为非负safe integer，严格工具相对顺序保留。8项定向及29项停止场景一次通过（2654ms）经Sol→Root，修正读取器实采仍NOT_RUN；旧真实FAIL不覆盖。见ROOT-NATIVE-FIRST-EVENT-DIAGNOSIS-PASS.json、ROOT-NATIVE-SEQUENCE-OFFLINE-PASS.json |
| 已有单子 Agent 文件独立读取 caller | PASS 离线限定 | 完整caller五项一次181ms通过Sol→Root；源码两次Stop类HOLD及原始roots形状HOLD保留。只证明入口与当时reader/fixture，官方消息格式尚有缺口；见ROOT-EXISTING-CHILD-CALLER-OFFLINE-PASS.json |
| 已有单子 Agent 文件独立读取 V1 | FAIL_OBSERVER_STOP | 一次171ms读取在native_tool_result_id_mismatch停止，仅HEAD/before inspect/native exec执行，after及chain NOT_RUN，模型/Job/API/DB0。官方源码已确认观察器及fixture的嵌套工具结果格式与当前SDK不符；实际错误行未观察，不重试，先统一消息合同。见ROOT-EXISTING-CHILD-NATIVE-READ-V1-FAIL-STOP.json |
| 官方原生消息合同统一修补 V1 | FAIL_STOP 替身 | 三项pure PASS，第四fixture构造因header cwd直接用了Path而ERROR，后四项和42场景NOT_RUN；零真实IO/模型/Job。停止后完整审计JSON/路径/压缩/transport类型边界；见ROOT-NATIVE-CONTRACT-OFFLINE-V1-FAIL-STOP.json |
| 官方原生消息合同统一修补 | PASS 离线限定 | 新V2五项WholeMain及42停止场景一次3047ms通过Sol→Root，V1前三pure PASS分开复用。统一tool结果顶层ID/error、message role/source、seq/time、opaque事件及header/developer合同；不声称SDK serializer输出、完整surface folding或实采PASS。见ROOT-NATIVE-CONTRACT-OFFLINE-PASS.json |
| 已有单子 Agent 文件独立读取 V2入口 | PASS 离线限定 | V2固定current源码/HEAD，完整caller五项一次241ms通过Sol→Root；保持native/zstd/scope/chain真实算法，不冒充实际formatter结果。见ROOT-EXISTING-CHILD-CALLER-V2-OFFLINE-PASS.json |
| 已有单子 Agent 文件独立读取 V2实采 | FAIL_OBSERVER_STOP | 一次175ms，native rc2/39字节native_child_invalid；仅HEAD/before inspect/native exec，after及chain NOT_RUN。异常类型被generic catch隐藏，不能定位具体阶段。已停所有真实资格测试；先补官方AgentLoop/工具结果formatter源码，不猜改、不重发模型。见ROOT-EXISTING-CHILD-NATIVE-READ-V2-FAIL-STOP.json |
| SDK 源码采集入口合同 | PASS 离线限定 | 两轮静态 HOLD 的五处错配均在执行前拦截；修正后一次7方法335ms通过Sol→Root，真实Node解析合成SDK树，5实际Node/1传输替身日志分别保留，模型/Job/Docker0。见ROOT-SDK-SOURCE-CALLER-TEST-SOURCE-HOLD.json、ROOT-SDK-SOURCE-CALLER-OFFLINE-PASS.json |
| 已安装 SDK 公开源码读取 | PASS 源码读取限定 | 一次224ms、3Docker、5包源码及manifest合计459750字节，Runner前后身份相同；Sol→Root PASS，模型/Job/API/DB0。ToolRuntime分开保留value/content，AgentLoop持久化映射仍UNKNOWN，仅补缺失包，不重发模型。见ROOT-PUBLIC-SDK-SOURCE-READ-PASS.json、ROOT-DELEGATE-RENDER-CONTRACT-AUDIT.json |
| AgentLoop 补缺入口 | PASS 三项离线限定 / FAIL 实采入口 | 定向3方法232ms通过Sol→Root，其余4项NOT_RUN并分开复用V1未变守卫；一次实采122ms在tool锚点ESM解析失败，仅2Docker，after NOT_RUN，模型/Job0。替身模拟的依赖拓扑未证明真实插件加载入口；已停实采，不猜路径。见ROOT-AGENTLOOP-SOURCE-CALLER-OFFLINE-PASS.json、ROOT-AGENTLOOP-SOURCE-READ-V2-FAIL-STOP.json |
| 委派持久化映射检查点 | UNKNOWN / HOLD | 已确认value/content分离及观察器JSON假设缺口，完整AgentLoop写入映射及实际失败行未证明。沿原会话和注册/调用链补证，保留ACK、清理、预算、Job增量及刷新缺口；不从普通文本猜runId。见ROOT-DELEGATE-PERSISTENCE-CHECKPOINT.json |
| 原委派会话直接只读补证 | PASS 独立限定 | 复用已验helper一次235ms/6Docker，精确ACK seq12/hash、签名Root进程组清理、8提供者请求结算与并发峰值1、11表计数相同，Sol→Root PASS。清理receipt reason=cancelled与Backend completed分别保留，不等于用户取消或individual child close；不恢复旧240秒批次。见ROOT-EXISTING-CHILD-DIRECT-READ-PASS.json |
| 原会话刷新观察 | WAIT-FAIL_STOP / RECOVERED_OBSERVATION | 一次reload后文本定位器no_matches；立即停操作，随后fresh AX只读诊断显示1user1assistant原回答恢复。失败不覆盖，截图viewport仅含用户输入，不能单独证明回复；零新模型/Job。见ROOT-EXISTING-CHILD-BROWSER-REFRESH-OBSERVATION.json |
| BYQ 父子关系与工具计数直接核实 | PASS 业务注册/工具日志限定 | 原Backend raw两注册父链/共同身份一致、三settled ingress及四审计经Sol直接复核；已有工具日志一次167ms/3Docker读回六次名称/数量/顺序与计划一致，Sol→Root PASS。SDK raw ID、原生文件映射和individual child close仍UNKNOWN；本地raw/normalized字段混用KeyError单独保留，不再调模型或重跑汇总。见ROOT-EXISTING-BYQ-PARENT-CHILD-EVIDENCE-PASS.json、ROOT-LOCAL-PARENT-SUMMARY-SHAPE-FAIL-STOP.json |
| 本次停止后原会话再输入 | FAIL_STOP 模式选错及超时 | 页面按钮是hard取消，原会话已终止；按soft接续预期测试的入口选错，第二次输入NOT_RUN。184424ms超180秒，原FAIL保留，实际wire参数未捕获、不据此声称应用缺陷；见ROOT-HARD-CANCEL-UI-SCENE-FAIL-STOP.json |
| 硬取消既有状态独立补查 | PASS 只读限定 | 8Docker/440ms，cancelled/authorityclosed、ACK seq16/hash及签名进程组清理一致、11表计数相同；provider status0/outcome unknown、计费UNKNOWN、native close未确认。Sol→Root PASS，不恢复原失败批次；见ROOT-POST-HARD-CANCEL-DIRECT-READ-PASS.json |
| 硬取消后新会话浏览器 | FAIL 时限 / UI成功观察 | 同一标签新CID一次输入得到NEW_OK，选择历史后1user1reply；160600ms超120秒，保留FAIL，不称恢复旧会话。见ROOT-HARD-NEW-CONVERSATION-UI-OBSERVATION.json |
| 新会话状态独立补查 | PASS 只读限定 | 8Docker/476ms，1请求span5900ms、usage27172/24576/126，completed/closed、ACK seq7/hash、精确签名cleanup及11表计数相同。binding.closed=false、native/process close=true分别保留；Sol→Root PASS，不覆盖UI超时。见ROOT-HARD-NEW-CONVERSATION-DIRECT-READ-PASS.json |
| 软取消准确入口及批次计时重审 | PREPARATION / 真实NOT_RUN | 停止同类超时批次，先审查已有soft API合同/替身证据；把审查预检放在起表之前，每次UI操作前检查剩余时限。新请求span与UI总时长分别记录，不猜服务超时；背景库存空、完成续办NOT_RUN。见ROOT-CONTINUATION-NEXT-SLICE-PLAN.json |
| 软取消原生直接接口映射 | PASS 离线限定 | 旧V17完整替身PASS单独复用；新极小接口检查V1额外-f参数被拒，0方法/6分支NOT_RUN保留。定位系统unittest具体CLI合同后，新固定argv V2一次69ms/1方法6分支PASS、Sol→Root；不证明实际取消/原生状态。见ROOT-SOFT-DIRECT-INTERFACE-OFFLINE.json |
| 软取消原生直接真实V1 | FAIL_STOP / soft NOT_RUN | 1纯文字输入；取消前49.146s读到新Root自然completed，0取消POST、第二输入NOT_RUN，无重试。120s未超，但起表后组织控制代码错过active窗口；先冻结控制命令，不据此称服务拒绝soft。浏览器登录失效在预检中通过已有账号重登解决，密码未改。见ROOT-SOFT-DIRECT-LIVE-V1-FAIL-STOP.json |
| 上述自然完成的独立补查 | PASS 只读诊断限定 | 8Docker/448ms，1provider/span31286ms/usage27378-24576-2457，completed/closed、ACK seq15/hash/HMAC cleanup精确关联、11表计数相同；Sol→Root。binding.closedfalse/native与process close true分别保留，不覆盖软取消NOT_RUN。见ROOT-SOFT-DIRECT-POST-STOP-READ-PASS.json |
| 软取消提前冻结的一次控制入口 | PASS Source限定，历史检查点 | 复用现有helpers，输入由原生浏览器发送，后续一条固定命令；soft通知/事件源与序列/后续冲突、官方root与session cwd、bodyhash及历史边界错配均在Source gate拦截并修正，Sol→Root Source PASS。执行结果另列V1/V2 FAIL与V3 PASS；见ROOT-SOFT-CONTROL-SOURCE-PASS.json |
| 当前完整入口替身V1 | FAIL_STOP 夹具初始化 | Cookie长位置参数漏secure，rest被错置为bool，真实MozillaCookieJar.save TypeError；未进入main，六逻辑全部NOT_RUN，transport/model/Job0。一次后停止，保留原件；见ROOT-SOFT-CONTROL-OFFLINE-V1-FAIL-STOP.json |
| 上述夹具V2统一修正 | PASS Source，历史准备回执 | Cookie全显式kwargs，独立fresh路径；当时仅Source审计，随后执行结果如下，未修改历史准备结论；见ROOT-SOFT-CONTROL-OFFLINE-V2-PREPARED.json |
| 完整控制入口替身V2 | FAIL_STOP loader协议 | FixtureLoaderProxy有exec_module缺create_module，真实stdlib拒绝；首例在传输前STOP，其余NOT_RUN，87ms、零真实IO/模型/Job。审计loader完整协议后修补，旧失败保留；见ROOT-SOFT-CONTROL-OFFLINE-V2-FAIL-STOP.json |
| 完整控制入口替身V3 | PASS 离线限定 | 真实loader/helper执行，仅替身传输边界；1方法、6逻辑分支/7case一次114ms完成（1PASS/6预期STOP），冻结Controller/合同未变。Tester→Sol RAW→Root PASS；见ROOT-SOFT-CONTROL-OFFLINE-V3-PASS.json |
| 真实软取消后同会话再输入V2 | PASS UI/API限定 | 同CID76cf，旧Root4744 started16→soft cancelled19→discard21；新Root5c8 started22→result27，4个累计user、唯一SAME_CID_OK、无旧输入重放/会话误关。2原生浏览器输入/1soft POST，118961ms<120s，Sol RAW→Root PASS；ACK/清理/授权/计数在独立补查另列。见ROOT-SOFT-DIRECT-LIVE-V2-UI-API-PASS.json |
| 上述两Root独立补证 | PASS 只读限定 | 9Docker/499ms，两个Root状态/授权/terminal receipt/ACK/HMAC精确关联；新provider1次，旧provider UNKNOWN原样保留，无自动重放。两binding.closedfalse/native与process true、cleanup reason cancelled独立报告，11表计数相同、四容器身份不变。Sol RAW→Root PASS；见ROOT-SOFT-DIRECT-V2-SUPPLEMENT-PASS.json |
| 官方CLI插件加载入口补缺 | PASS 公共源码读取限定 | 复用cached CLI，只补literal引用的facade及bundle，两批各3Docker/159ms与98ms；四stamp/完整bytes/hash/Runner身份稳定。实际默认installAnchor为CLI package.json，可能有resolvedProfile覆盖；app-boot与AgentLoop实现仍未证明，不重试旧tool anchor。Sol SOURCE/RAW→Root PASS；见ROOT-CLI-PROFILE-LOADER-SOURCE-READ-PASS.json |
| 本地源码diff路径组装 | FAIL_STOP 本地预检 | Root误用上一leaf文件名，FileNotFound发生在新采集前，0Docker/模型/Job；停下后按实际inventory/CONTRACT核全argv/cwd/hash/freshout，独立Sol审查新命令后才新批只读。原失败保留，不解释为Product错误；见ROOT-LOCAL-SOURCE-DIFF-PATH-FAIL-STOP.json |
| 普通委派必需验收合同复核 | PASS 有界BYQ业务证据 | Accepted ADR0094/0100要求可信签名父链/参数digest/ingress settlement/冻结terminal cursor及ACK/执行清理；不要求从formatter提取SDKrawRunID或必须读native父文件。既有BYQ身份/只读调用/Rootaggregate预算/ACK/清理证据可限定接受。individual native close仍UNKNOWN，0096复用/0102中断业务/两用户等须另验；原实时批次FAIL不改。Sol→Root，见ROOT-BOUNDED-DELEGATE-ACCEPTANCE-CONTRACT.json |
| 两用户、自然迟到旧请求、业务结果 unknown、进程丢失 | NOT_RUN 当前补缺批次 | 保留旧限定证据，逐片补缺；不自动重放未知业务结果 |
| F6 observer 离线预检 | PASS 离线限定 | 16项 unittest、Gateway 隔离镜像测试8项通过；一份缓存 Product 样本仅作 `SAMPLE_ONLY` 观察器匹配。总耗时2313.76ms，模型/业务Job/外部API/DB均0；不证明后台续接、Root ACK或浏览器资格。见ROOT-F6-OBSERVER-PREFLIGHT-PASS.json |
| 市场数据元数据预检 | PASS 限定 / ENV_NOT_READY | V3全入口替身9项通过；一次只读检查六次Docker调用、44/44 schema列匹配、五容器前后相同；指定日期/标的范围返回0匹配行。Worker/Sandbox Image.Id与留存收据不匹配，Backend镜像对应未证明；模型/业务Job/HTTP/DB写入0，不代表数据、镜像或后台资格。见ROOT-F6-METADATA-PREFLIGHT-PASS-ENV-NOT-READY.json |
| Backend 源码字节观察 | PASS | PASS 固定93路径限定；4项离线 host/helper join 通过，1次只读采集680.066ms，容器身份前后相同；inline文件读取算法未由离线测试执行。此记录不证明额外文件缺失、loaded代码/依赖/配置或完整镜像资格。见 [ROOT-BACKEND-SOURCE-BYTES-PASS.json](ROOT-BACKEND-SOURCE-BYTES-PASS.json)。 |
| 候选镜像只读预检 V4 | PASS 限定 | 前两次真实预检均为本地观察器解析错误并保留 FAIL；V3 静态 HOLD 未执行。V4 全入口替身24场景通过，真实一次285ms、2 Git/4 Docker，两个候选标签空闲、基础镜像已存在、资源观察完成。Sol→Root PASS，仅证明预检；该预检当时未构建，后续本地构建见下行；真实后台续接仍 NOT_RUN。见 [ROOT-CANDIDATE-PREFLIGHT-V4-PASS.json](ROOT-CANDIDATE-PREFLIGHT-V4-PASS.json)。 |
| 构建脚本字节合同 V4 | PASS 离线限定 | V2静态HOLD及V3夹具错误FAIL_STOP均保留。保存驱动、固定hex、调用前全量读回确认后，实际抽取guard七例符合预期，整轮214ms、0Docker/模型/Job，Sol→Root PASS；只证明syntax/byteguard，不证明构建流水线或镜像运行。见 [ROOT-BUILD-OBSERVER-OFFLINE-V4-PASS.json](ROOT-BUILD-OBSERVER-OFFLINE-V4-PASS.json)。 |
| Signal 两候选镜像构建 | PASS 本地构建限定 | 固定f581提交的96/6路径，7次Docker/2次archive，一批78.97秒；两流水线均双rc0、两个Image.Id及source labels匹配。Sol→Root PASS；尚未启动服务，不证明runtime、image admission、后台续接或生产部署。此前观察器失败仍保留。见 [ROOT-SIGNAL-CANDIDATE-BUILD-PASS.json](ROOT-SIGNAL-CANDIDATE-BUILD-PASS.json)。 |
| Signal 候选镜像运行 Smoke | PASS 导入及纯合同限定 | 2个精确Image.Id临时容器、2.23秒，默认UID10003/10002及依赖版本符合；Worker本地URL/错误字段及Sandbox纯AST校验通过。零网络/业务DB/模型/Job，不运行策略，不证明持久服务健康或真实后台续接。Sol→Root PASS；见 [ROOT-SIGNAL-RUNTIME-SMOKE-PASS.json](ROOT-SIGNAL-RUNTIME-SMOKE-PASS.json)。 |
| 本次候选远程 CI / 推送 / 合并 / 生产部署 | NOT_RUN | 本地及浏览器片段验收不替代候选发布资格，当前仍 NOT_READY；历史生产部署成功证据单独保留。 |

## OC 工程执行事故

2026-10-14 历史补充：原会话直接浏览器输入得到 `CONTINUE_OK`，刷新后仍可见；Sol→Root 仅接受该 UI 检查，不重复完整普通续聊验收，见 [ROOT-BROWSER-NOW-UI-PASS.json](ROOT-BROWSER-NOW-UI-PASS.json)。写入之前的 F6 scoped 元数据一次只读采集33列/6 PK匹配、目标行0，启用的bar触发器及三投影副作用已记录，见 [ROOT-F6-SCOPED-METADATA-READ-PASS.json](ROOT-F6-SCOPED-METADATA-READ-PASS.json)。随后合成数据提交限定 PASS，当前状态见首节；真实后台正例仍 `NOT_RUN`。

只读源码审计 `ses_ecd98ec47ffeX0YS71U5PpA5AP` 超过工具次数且擅自检查环境，将服务认证变量带入工具输出。该批次 FAIL_STOP；含密原日志只留私有目录，不进入Git、不出站、不得续用该 session。已完成准确abort、私有日志0600、原生服务密码轮换（旧认证401、新认证200）、原固定Tester session可读。

原生 OC 服务保留，两个旧自动派发timer可逆暂停。当前7个Agent的关键工具权限配置读回为deny，经Sol核对；实际执行拒绝NOT_RUN。权限不阻止模型请求或清除旧会话上下文，新增OC工具任务仍NOT_ADMITTED。现有必要Luna源码回退继续；固定测试命令经审查后在OC外执行。无新客户端、调度框架或Agent harness。具体范围见ROOT-OC-*回执。

当前仍 NOT_READY。历史部署证据和本次新候选资格分别记录，不因当前未验收而改写旧生产部署成功记录。

## 普通接续与业务结果触发

普通会话下一轮、原生历史上下文、上下文压缩和子 Agent 生命周期由 DSH 负责。当前 ACP 接口直接调用 `session/new`、`session/resume` 和 `session/prompt`；复用原生会话时不重新注入公开历史。无需为 DSH 原生会话接续另设一项 BYQ 许可；用户身份、工作区隔离和实际业务动作审批仍按原合同核对。BYQ 不应新建通用会话或恢复管理器。

本轮后台 SignalJob 补丁处理的是可信业务完成事件：BYQ 核对准确的 Job、Artifact、会话身份、取消及去重后，将事件交给 DSH 处理后续回合。它不恢复 DSH 私有上下文或原来的子 Agent。相关所有权以 [ADR-0111](../../architecture/adr/ADR-0111-automatic-continuation-execution-parameters.md) 和 [Clean Break ADR-002](../../clean-break/adr/ADR-002-dsh-boundary.md) 为准；后台路径须另行验收，不能用普通对话已通过的证据替代。

### 2026-10-15 身份修正与当前验收边界

后台跟进测试现将运行时会话用于任务绑定、登录会话仅用于用户的 Job 提交；登录凭据不持久化为来源事实。原会话绑定校验保持。独立 Sol 已审查该修正。实际隔离 PostgreSQL 定向测试为 **20 PASS / 1 FAIL / 7 NOT_RUN**：失败负例尝试修改既有 Runtime root 的 owner，被现有数据库身份 fence 拒绝；尚未验证该用例期望的结算层拒绝。完整 Backend 资格、发布和部署仍未通过，不能用其他组件的 PASS 抵消这一失败。原失败日志保留在私有 `.ci-artifacts/background-browser-20261015-v1/identity-test/`；该定向测试没有真实模型、业务 Job 或生产操作。后续一次真实后台跟进及前端问题见本页最新浏览器切片。

## 浏览器窗口纪律

验证复用当前已核对的浏览器标签。另开测试窗口前先检查旧测试窗口，关闭已废弃的测试窗口并确认已关闭；保留无关用户标签。2026-10-13复核仅剩当前普通双轮会话标签，没有再次开窗或发送提示词。
