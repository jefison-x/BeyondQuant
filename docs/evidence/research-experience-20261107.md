# 投研体验维护 — 2026-11-07

## 范围与基线

维护者请求“请研究项目代码解决体验测试问题”，依据会话
`6aeecc9b-c21c-83e8-ad83-b45a36158c66` 的体验记录处理明确缺陷。
本次授权为代码维护和必要验证，不推断 push/PR、合并、发布或部署授权。
不推进 Product Phase，不修改用户模型配置、历史回执或数据卷。

- 起点：fetched `origin/main` / `e7c488d800a2e61f1aae6226d80cfc41a21af77b`。
- 分支：`codex/research-experience-20261107`。
- 隔离工作树：`/home/jefison/.codex/worktrees/research-experience/BeyondQuant`。
- 工作树校验通过，使用专用 `BYQ_ENGINEERING_WORKTREE_ROOT=/home/jefison/.codex/worktrees`。
- 主工作区仅 fast-forward 同步；实现变更只在隔离工作树。

## 原始失败事实

Engineering 只读核对运行环境的持久会话、WorkflowTrace、provider gate journal
和 DSH 原生日志。生产测试镜像标签对应起点提交、Release Images `42334849363`。

原体验会话 `conversation_4d08951130e14140a33a56209949f79f`：

| Root | 时间（UTC） | 事实 |
| --- | --- | --- |
| `c563b48e23ba4156b90f5ced6d8908e4` | 07:04:44–07:05:00 | provider attempt 1，admitted/completed，HTTP 500，forwarded=true |
| `290161774b4c497ea46101d7c1912043` | 07:05:40–07:05:56 | provider attempt 1，admitted/completed，HTTP 500，forwarded=true |

两次 admission reason 均为 `within_request_budget`，Backend Root 均为 failed、
terminal_unknown_claim_count=0。不能据此把实际 token 用量 unknown 改成0。
第一轮原生错误为 `SERVER / Internal Server Error`，上游 request id
`e9c45254-49e8-4908-84a6-eb8e1cf0c60a`。公开失败事件仅有 `AcpRpcError`，
没有 code，因此前端退回“本轮运行未能完成”。未发现支持额度或并发拒绝的证据。
HTTP 500 的服务端内部根因未知，不以错误分类修复冒充模型服务修复。

## 最小修复

Runtime 复用已有请求回执，在精确 generation 的 proxy 已关闭、gate 已封闭且
所有请求已成对结算时，将最后一次 HTTP 错误归类为服务不可用、限流、鉴权或
请求拒绝。公开投影不含上游正文、凭据或原生身份。保留 FAILED、retryable=false、
原有 Backend ACK、未知结果保护和下一轮准入，不重试或重放旧输入。
前端使用固定中文说明和现有 trace/sequence 诊断编号。

- 股票池复用 Product 证券目录按中文名/代码搜索、多选。目录不完整时保留规范代码
  手录；中文查询不生成假候选。按百分比填写权重，空值明确显示“未设置”。创建与
  编辑共用全部留空或全部为正且合计100%的校验；不合法输入保留，不发请求。
  百分比换算规范到合同的12位小数，避免20.01%产生二进制除法尾数而被后端拒绝。
- 原股票池可一键进入比较研究草稿，携带当前 pool/snapshot ID；不从分页成员猜全池，
  不自动创建会话、调用模型或发送消息。策略页亦可先描述投资想法。
- 回测缺已批准策略或可用股票池时提供对应管理入口，去掉 ADR 和内部运行术语。
- 模型训练/验证/预测日期不再预填旧样例，要求填写完整且顺序不重叠的区间；
  不把样例日期或本机时间冒充市场数据覆盖。

未扩展拼音搜索、一键等权、行业/估值/股息筛选、自动推荐数据区间或导航重构。

## 真实验证（运行中的原基线，不是新代码部署验收）

开发测试使用正常账号，通过 Gateway/Product API 登录、创建并读取会话
`conversation_231598efc95d4acea9cf1e572495e946`。

1. 基础对话：一次明确输入、不调用工具或业务操作，Root
   `7fc19cfa38b843fbb8e3998c27cfa21e` completed，回答持久化。**PASS**。
2. 招商银行只读研究：一次输入，要求来源/日期，禁止下载行情、创建策略、任务、
   股票池或订单；Root `892dcc815bb24d56b526d43b87295182` failed。
   gate attempt 1、admitted/completed、HTTP 500、forwarded=true，业务 unknown=0。
   **FAIL**，停止此批，不重发。上一轮成功回答不充当本轮研究结果。

两轮观察分别限制120/180秒，均提前得到终态。没有修改运行栈、模型配置或额度。
该结果证明基础对话本次可用，同时研究链仍受模型上游错误阻塞；不证明研究结论
质量、行情数据覆盖或完整“研究→保存观察池→比较”旅程通过。

## 交付门禁

### 本地源码验证

- Workflow 中文错误分类/诊断引用：18 tests **PASS**。
- Worker 的 StockPool、MLResearchWorkbench、Backtest、Strategy、AgentView 五文件：
  57 tests **PASS**。最后权重校验/精度修正后仅重跑 StockPool：9 tests **PASS**，
  其他未受影响测试保留其证据；前端最终类型检查与生产构建 **PASS**。
- 独立 Tester 的 Runtime 分类8组及预算/未知结果/存储/未关闭proxy保护：12 tests
  **PASS**；补充领域安全停止优先级后，重新执行分类矩阵9组 **PASS**。
  使用现有固定镜像 `sha256:9ac6186f5c5402403cb17b563a74ac95664130d82668d58d9c2f88360b031f5b`，
  单仓库只读挂载、显式 PYTHONPATH、network none，不安装依赖或调用模型。
  两次测试准备失败保留：首次缺 packages import path，第二次只读根下缺嵌套挂载点；
  均未执行测试，最终以单挂载修正，未扩大测试范围。
- `dev-check.py --base e7c488d800a2e61f1aae6226d80cfc41a21af77b`、diff检查 **PASS**。
- 独立 Sol Reviewer：Functional / Tests / Clean Break Architecture **PASS**。
  审查发现的领域停止优先级、权重部分填写/总和问题已修复并定向复验。

### 真实浏览器（候选前端 + 已运行 Gateway/Product API）

使用正常账号登录、Playwright Chromium；所有业务请求经过 Gateway。
本地预览 `http://127.0.0.1:5175` 指向开发测试，`http://127.0.0.1:5176`
指向生产测试 Gateway。只是本地候选前端预览，不替换运行栈镜像或正式入口。

- 开发目录只有两条明确标识 Synthetic Fixture 的证券记录，不当作真实行情证据。
  新建 `体验回归_银行观察_20261107`（`stock_pool_5ea9df5c4b084eb28ab851ec7c6594aa`），
  手录600036.SH、601398.SH，初始权重“未设置”；60%/40%保存、刷新回读 **PASS**。
  无效合计保持表单且零 POST；20.01%/79.99%保存后，Product成员回读
  `0.200100000000` / `0.799900000000` **PASS**。这些是表单/持久化验收，不是行情或投资质量验收。
- 策略想法入口只生成编辑草稿，零 session/turn POST **PASS**。
- 模型六个日期输入为空且有填写说明 **PASS**；回测表单去除ADR术语 **PASS**。
  当前开发环境有前置资产，缺项引导仅单元测试覆盖，不冒称真实空资产流程通过。
- 原生产体验池只读核对：平安银行/招商银行/工商银行中文成员、未设置权重 **PASS**；
  中文搜索最终仅返回真实候选“招商银行（600036.SH）” **PASS**；比较草稿准确携带
  `stock_pool_5dbb5369172f43f88b571938bc3967ae` 和原 current snapshot ID **PASS**。
  生产浏览器唯一 POST 为正常登录，零业务写入、零新模型输入。
- 真实旧失败历史显示诊断编号，390px无横向溢出 **PASS**；旧事件没有新 code，
  继续如实显示泛化说明，不改写历史或声称新 Runtime 已运行。
- 浏览器检查曾因等待开发目录不存在的招商银行候选超时；只读API确认空结果后停止
  原批，改为手录验证与生产目录只读验证。另一表单点击被展开下拉遮挡，保留表单、
  关闭下拉后继续，没有重复提交。开发页面无 pageerror。

截图保存在本机 `~/.local/state/byq-maintenance/research-experience-20261107/stock-pool-desktop.png`。
本地预览、浏览器页面、原会话、测试数据、运行环境和失败证据保留。

**Root：本地限定源码修复 PASS；研究可用性整体仍 FAIL。**
新代码镜像、远端 CI、发布、部署和修复后真实模型验收均 **NOT_RUN**。
模型500的服务端根因仍未知；不切换用户模型、绕过保护或反复重发来制造成功。
本次不推进 Product Phase。

## 继续定位（2026-11-07 15:46–15:53 UTC）

用户要求“那继续查”。以下与上午07时的失败相隔约8小时，运行镜像、模型、
额度和密钥均未修改；不是新源码部署后的验证。

### 模型500与本次请求

对比原成功基础对话和失败研究的原生记录：两者均为 `deepseek-official` /
`deepseek-flash`、maxTokens 256000、reasoningEffort high；101个工具定义完全相同
（SHA256 `04fed60490117b7388449bacfc1ac0b4852499b0b865bd343cbe28d03d5c2bbf`），
全部通过本机 JSON Schema 定义校验。失败请求约15.3秒返回上游500，原基础对话
约1.5秒返回200。请求代理原样转发请求正文；本地连接超时为10秒，未配置固定15秒
读取截止，连接失败路径产生502，而非此次带上游 request id 的500。

[DeepSeek错误码说明](https://api-docs.deepseek.com/quick_start/error_codes/)
将500定义为服务端内部错误；[官方兼容接口说明](https://api-docs.deepseek.com/guides/anthropic_api/)
支持当前模型与 max_tokens 字段。这些只能排查明显配置不符，不能证明上游内部根因。
检查时官方状态页正常，不能以11月3日的历史事件解释11月7日的失败。

只新增两次明确的开发 Product 输入，无自动重发、无切换模型：

| 输入 | Root | 结果 |
| --- | --- | --- |
| 仅调用一次 byq_health | `3f7246a3e1c74f939d90aae25a099fde` | Backend completed，unknown=0；实际 byq_health ingress settled；2次成对模型请求均200 |
| 与上午相同的招商银行只读研究 | `f6dc48f8c4e446c6912eed772a47493f` | 12次成对模型请求均200；15:48:07生成并持久化回答；业务终态未通过，见下文 |

对应会话为 `conversation_b2f27ed85c3e4f95bfaa82aa137a1866` 和
`conversation_5ecc68a5555c4de2a6fc975a6682c6bd`。后者 trace 为
`byq-trace-06a38817a2bc4a34839fd1111795f387`。
本次500未复现，不能据此宣称此前500被代码修复或永久恢复。

### 新定位：只读查询错误被误记为未知结果

研究原生记录 seq54/55：`byq_market_daily({ts_code:"600036.SH"})` 缺日期，
Backend明确返回422；MCP返回 `isError=true` 和 `research_data_unavailable`。
精确请求 `d654db9604d2a0631a6db5ba5e77412c` 的 Backend ingress seq8却被记为
unknown。原Root仍为active、terminal_unknown_claim_count未结算。Product回放已有
session.result和回答，containment显示completed；这些投影不等于权威业务终态。
不把此研究记为PASS，不改写旧收据、不解除旧会话保护、不重放请求。

代码原因：`classifyAcpToolCompletion` 对已审核只读工具的已知错误允许settled，
但四个持久化行情读取工具未在其显式名单中，因此普通422落到unknown。
修复限定为核对只读调用链后补充名单，沿用原有分类机制；错误仍返回给模型，
不会变成成功行情。显式unknown、无法解析的结果、凭据/身份收据缺失与业务写入
错误继续保留保护。具体本地验证结果补记于下文。

审核路径：MCP `market-data.ts` → Backend `main.py` 四条
`/v1/data/research/{daily,session-context,valuation,fundamentals}` →
`market_data.py`、`market_automation.py`、`market_readiness.py` 的只读查询。
日线缺日期在 `DailyRequest.normalized()` 中于任何数据查询之前被拒绝。

### 开发数据与搜索配置不能外推到原体验环境

- 开发库实际查询：招商银行日线、估值及财务均未返回数据，日历登记止于20260330，
  当前交易会话未知；其证券目录先前已确认只有Synthetic Fixture。模型关于“全库
  财务为空”的泛化推论未通过全库审计，不作为本报告事实。
- 本次唯一网页搜索原生结果为HTTP401，request id
  `143c3177-ecf8-4f4d-b282-d80a1a9829fd`，上游明确拒绝搜索密钥。
  只读核对确认拒绝的遮罩尾码与开发账号的独立搜索凭据记录一致；该记录创建于
  2026-10-15且仍标active。active仅是本地启用状态，不能证明上游凭据有效。
  不复制模型密钥、不改搜索端点、不输出真实密钥。
- 原体验环境的搜索凭据创建于2026-11-02，遮罩尾码不同；其搜索实际可用性本轮
  **NOT_RUN**，不能从开发401推断它同样失效。
- 原体验环境经正常登录读取 Product 数据覆盖：133589条、5579个证券，观察日期
  20260928–20261106；该接口明确不声称整体完整。另一次现有只读 readiness 请求
  对600036.SH/20261106返回 usable、ready_items=1、missing_items=0、日历完整。
  这只证明该日研究行情准备度，不证明估值、盈利、分红数据或完整研究质量。

定位采集限制保留：原生日志存在无seq元数据，首次筛选KeyError后改用get；
从上层目录递归未能遍历挂载工作区，核对实际挂载后直接读取已知工作区；
宿主未安装dotenv，首次只读Product检查在登录前退出，随后用标准库读取指定变量。
均未因此新增模型输入、安装依赖、改动运行环境或重放业务。

### 本次补充修复验收

- 业务源码仅在 `services/mcp/src/server.ts` 的已审核只读名单增加四个工具名。
  现有 ingress 集成测试新增四种422错误保持isError、单次请求及精确收据settled断言，
  另验证同一日线工具的显式outcome_unknown仍为unknown且不重放。
  原有可变写入409、超时、错误观察/结算收据保护仍执行；同时修正旧测试中错误的
  `/v1/market/daily` 断言路径为实际 `/v1/data/research/daily`。
- 独立Tester：一次临时容器中 `npm run build`、
  `node dist/tests/acp-ingress-test.js`、`node dist/tests/market-data-test.js` 全部
  **PASS**，exit0，无准备失败。固定镜像
  `sha256:134ab67dff08eadcdb71234abce3830823619f0bc400dcc296aa377bae414bf0`，
  Node24.22.2/npm11.19.1/TypeScript7.0.2，network none，UID1000，
  源码/测试/配置只读挂载，dist与tmp仅临时内存目录；不安装依赖或更改运行栈。
- `dev-check.py --base e01d5bae519a94d91995c92613d4e9d718575ca6` 和diff检查 **PASS**。
- 独立Sol审查 Functional / Tests / Clean Break Architecture **PASS**，
  核实四端点为只读、分类器和写入保护未改；源码与定向测试证据不代替
  部署后的真实Product流程。

**Root：补充缺陷的本地源码与定向验证 PASS；研究流程整体仍未通过。**
500上游内部根因未取得，开发搜索401未修复，原unknown收据保持不变。
新代码部署及部署后真实研究验收 **NOT_RUN**；未推送、合并、部署或推进Product Phase。

## 生产原问题对照复测（2026-11-08，北京时间）

用户要求测试定位具体原因，不能把“上游恢复”当作未经验证的根因。
本节区分确定的故障位置、复测结果及仍缺失的服务端证据。

### 保留的故障与对照

| 时间（北京时间） | 输入 / Root | 实际结果 |
| --- | --- | --- |
| 11-07 15:04:44 | 原招商银行研究，`c563b48e23ba4156b90f5ced6d8908e4` | 首次模型请求187628 bytes、工具83382 bytes，15305ms后500；尚无工具调用；Backend failed/closed、unknown=0 |
| 11-07 15:05:40 | 原基础介绍，`290161774b4c497ea46101d7c1912043` | 首次模型请求186854 bytes、工具83382 bytes，15248ms后500；尚无工具调用；Backend failed/closed、unknown=0 |
| 11-08 08:32:50 | 用户原会话再次提交相同基础介绍，`2ddff72f8d6d44c282fc06cff0649a52` | 首次请求186854 bytes、工具83382 bytes、7930ms返回200；该轮两次模型请求均200，Backend completed/closed、unknown=0 |
| 11-08 08:39:00–08:41:23 | 本轮新增独立生产测试会话，原文重测研究，`4e0541c4d8524c609a71935a44c68984` | 首次请求187628 bytes、工具83382 bytes、5117ms返回200；17次请求均成对且全部200；最长35938ms；Backend completed/closed、unknown=0 |

新测试会话 `conversation_44966845f83544a0a9a007c908d800e8`，trace
`byq-trace-b3a1e02fb30f439baebbafe83ce1e75b`，使用正常登录与Gateway/Product API。
仅新增这一条原文输入，无自动重发、修改配置或替换模型。原会话及失败收据保留。
本轮调用了市场研究子助手，其15条MCP ingress均settled；生成回答并持久化。
这证明本轮生产研究能够完成，不是新源码部署验收，也不代表已逐项核验研究数字与来源。

### 已核对的变量

- 原基础介绍失败/用户成功，以及原研究失败/本轮研究成功，两组各自的用户输入均
  逐项相等。原生request/header中的config、adapterDefaults和101个工具定义相等。
  系统提示内容去掉运行身份标识后相等。模型均为deepseek-official/deepseek-flash，
  maxTokens256000、reasoningEffort high。
- Runtime及Product Runner镜像均仍为`9ac6186f…`，Runner从11-07 12:33:28起运行，
  Runtime从12:33:35起运行；Gateway与MCP也未重启或替换。此次两个源码提交均未部署。
- 模型凭据、模型profile及用户绑定均为版本1，最后更新时间为11-02，早于两次失败。
  仅读取元数据，不输出密钥。官方ordinary请求上游由当前合同固定为
  `https://api.deepseek.com/anthropic`；当前Runtime的六种大小写HTTP代理环境变量均未启用。
- 初次读取新测试原生日志时通配符混入了子助手文件，不能用于主请求对照；已停止
  该比较，按 `.byq-acp-root-binding.json` 的精确native root
  `bb1212e0-03b8-4122-9697-e7df46b77cdd`重新核对，以上相等结论来自精确主会话。
- 运行时钟、运行标识与服务端状态不是固定变量；没有保存原始线上HTTP请求头与完整
  原始请求字节，因此不能称为历史请求逐字节重放或严格控制服务端状态的实验。

### 确定结论与根因边界

两次原故障的确定位置是**首个模型HTTP请求收到500**，早于市场/搜索工具执行。
请求闸门记录admitted、forwarded、completed，未发生本地预算拒绝。
本轮存在17.247秒及35.938秒的成功模型请求，不能把约15秒的原失败归因于BYQ固定15秒超时。
开发环境搜索401、日线422误分类与这两次生产首请求500处于不同阶段，不能作为它们的原因。

原生失败记录只提供 `SERVER / Internal Server Error`，没有更深层错误详情：

| 请求 | 上游 request_id |
| --- | --- |
| 11-07 07:04:44 UTC研究请求 | `e9c45254-49e8-4908-84a6-eb8e1cf0c60a` |
| 11-07 07:05:40 UTC基础介绍请求 | `4bcaa388-85de-4b28-951a-0f7464e3390c` |

**具体服务端内部根因仍未查明。** 当前证据不支持把拥堵、限流、额度、模型参数或
部署变化中的任一项指定为根因。要进一步区分，需要上游按以上request_id与UTC时间
查询服务端日志；本地对相同业务输入的再次成功不能补出历史服务端内部原因。
本轮未联系外部支持、未更换凭据、未改写历史终态，不再为已成功的同类输入反复调用模型。

## 用户授权生产全栈重启及复测（2026-11-08）

授权原文：“你帮我全面重启一下生产byq容器，然后再测试看看有没有问题。”
范围为现有Compose project `beyondquant` 的17个生产容器，不包含开发环境，
不等同于部署本分支源码。使用operator目录的原compose.json/operator.env，先检查
无active对话、无运行中的业务Job，保存容器与关键会话记录，再执行
`compose stop --timeout 45`；PostgreSQL先启动并确认pg_isready，随后
`compose start`按既有健康依赖启动其余服务。未执行up/recreate/build/pull/down或删除资源。

- 北京时间10:43:27，最后一个容器Frontend已启动；17个容器均running，12个已配置
  健康探针均healthy，其他5个Worker无健康探针。它们只取得运行/启动日志检查证据，
  不代表新增回测、训练、因子、信号、数据同步Job功能验收。
- 重启前后逐ID比较：17个生产容器ID、镜像digest和按目的路径匹配的挂载均不变，
  StartedAt全部更新；10个开发容器StartedAt、镜像和挂载均不变。未自动重启循环。
- 需保留的问题：feedback-hub-relay、acp-product-runner、acp-judgment-runner在
  45秒停止等待后退出码137、OOMKilled=false；其余容器退出码0。这三个服务重启后
  健康探针通过，但正常退出的问题尚未单独修复，不将其记为“全部平滑停机”。
- Frontend入口HTTP200，正常账号重新登录成功。重启前的3个会话数量保持不变；
  原体验会话与重启前研究会话共7条历史消息的ID、角色和正文SHA256完全一致。
  招商银行20261106现有Product readiness查询仍为usable、missing_items=0。
- 实际旧会话接续：在`conversation_44966845f83544a0a9a007c908d800e8`中要求仅复述
  上次研究截止日及两项缺口。Root `5ae9ceb1f6bb49588cbaf5ac125ec227`在10:44:41
  得到回答，正确引用原摘要；1次模型请求200，零MCP ingress，Backend
  completed/closed、unknown=0。**PASS**。
- 新研究会话`conversation_496cc68fffcf482aa7646a0656623624`，trace
  `byq-trace-92bca7d382814af7aae4f0479354ff00`，Root
  `1b9e48fd370e4a0188ab6bbbcb8c4f31`于10:45:33提交原始招商银行研究原文一次。
  180秒观察窗口结束时仍active，未自动重发；继续只读观察，10:54:51自行完成，
  耗时约9分18秒，未达到声明的10分钟停止上限，因此未发送取消请求。
  49次模型请求全部成对且返回200，单次最长81537ms；Backend completed/closed、
  unknown=0，19条MCP ingress全部settled，包含日线、估值、财务和交易会话读取。
  最终3163字回答持久化，包含数据日期、缺口和5个外部链接。
  **运行链路PASS，但简要研究响应时间偏长**；不以成功终态证明金融数字全部正确。
- 约5分钟时实际观察到研究子助手已执行11次web_search和29次web_fetch，仍在继续
  取证；不是已完成结果因前端显示延迟而丢失，也没有本轮500证据。此为该次采样的
  实际路径与耗时，不将其直接归因为重启，也不据此修改用户的模型/额度配置。
- 最终生产17个容器仍运行，12个探针健康，无active Root；completed由9增至11，
  failed保持原来的3条。所选10个服务最近150行启动后日志未见ERROR/Traceback/FATAL，
  此为限定日志抽查，不等于全日志或所有Worker业务功能验收。

私有操作记录保存在既有本机证据目录下的
`production-restart-20261108-before.json`、`production-restart-20261108-after.json`、
`production-restart-20261108-messages-before.json`，不含密钥或原始消息正文。
首次挂载比较因Docker返回顺序不同误报，改为按Destination比较后证实无变化。
一次消息数量查询使用错误表名在只读事务中失败，后经information_schema确认实际表名。
Chrome调试连接不可用、宿主未发现Playwright包，因此本轮使用现有Product API验证，
不声称新增真实浏览器交互验收。未安装浏览器或测试依赖。

**本轮结论：授权重启完成，基础服务、数据回读、旧会话接续和新研究运行链路通过；
未复现500。保留两项问题：三个服务停止退出不及时、简要研究耗时约9分18秒。**
没有删除数据、升级镜像、部署未发布源码，或为测试创建策略、订单与计算Job。

### 该次9分18秒研究的耗时拆分

按用户后续要求，只读取已有回执与两个精确native会话，不新增模型调用。
Backend Root起止为02:45:33.821157–02:54:51.551220 UTC，总计557.730秒。
49条provider completed回执与49条原生assistant/message按完成时间逐一对应，
最大事件时间偏差513ms。工具按同一native session内callId配对，71次调用全部有结果。
剔除父级delegate等待区间后，各类别时间区间无交叠，避免把子助手耗时重复计入。

| 类别 | 实测时间 | 占比 |
| --- | --- | --- |
| 49次模型请求（admitted至completed） | 383.456秒 | 68.8% |
| 12次web_search，含40个不同查询 | 142.362秒 | 25.5% |
| 33次web_fetch | 26.201秒 | 4.7% |
| 本站MCP与skill调用 | 1.717秒 | 0.3% |
| 区间外的启动、事件转交及收尾等差额 | 3.994秒 | 0.7% |

模型回执elapsed_ms合计383.312秒，与admission时间戳到完成时间相差144ms，
属于两个计时口径的微小差额；上表使用可对齐的区间口径。模型请求时间包括
服务端处理、传输与输出，现有记录无法进一步拆出纯排队、纯推理或首token等待时间。

主助手10:45:48.989委派，等待496.839秒（8分16.8秒，约89.1%）才收到子助手回报。
这是包含关系，不与上表相加。子助手34次模型请求的elapsed_ms合计325.013秒，
主助手15次合计58.299秒。子助手最后一次回报生成81.537秒（15572 output tokens），
另两次中间调用48.122秒、40.319秒；主助手最终生成又用22.100秒（3231 output tokens）。
tokens使用上游统计口径，不能等同于用户可见字数或纯推理字数。

40个搜索查询均不完全重复，33个网页读取参数也各不相同；不能说是同一请求机械重试。
3次web_fetch报错合计10.873秒：跨域重定向未自动跟随、一次fetch failed、一次不支持的
重复PDF MIME类型。它们不是主要耗时来源；此前49个模型HTTP200不代表所有网页抓取成功。

主助手在子助手返回之后才补读本站数据：10:54:11.879读估值，10:54:17.614读财务，
10:54:23.912读日线。父子合计6次交易会话/行情/估值/财务读取总耗时仅0.382秒。
本轮主要成本在串行的长链网页取证、多轮模型调用和两次报告整理；现有证据不指向
数据库读取慢。可优先评估“简要研究”先读本站数据、仅为缺失事实补查公开来源，
在证据足够时收束范围并缩短子助手交付；本次只定位，不修改模型设置或产品实现。

## 继续体验整改：研究入口与股票池权重（2026-11-08）

维护者要求“暂时不做MCP，继续优化之前我们体验测试遗留的问题”。本切片
从 `ecf3beea` 起在原隔离工作树继续维护；暂停外部 Tushare MCP 接入，不改
生产配置，不推进 Product Phase。此前的取数顺序维护见
[数据路径记录](research-data-path-20261108.md)。

### 本切片行为

- 对话首页从三个点击即发送的泛化问题，改成研究个股、寻找股票、验证想法、
  比较股票四种具体任务。示例只填入输入框，可修改标的、条件和范围，用户明确
  发送后才创建会话并运行。已有草稿时禁用示例，避免覆盖从股票池带来的问题。
  同时提供已有股票池入口。示例不预填行情或承诺完成未支持的自动筛选/回测。
- 自建股票池的创建和成员编辑支持“设为等权”“清空权重”。以整数基点分配
  两位小数：3只为33.34/33.33/33.33%，7只为14.29%四只、14.28%三只。
  余量按列表顺序分配、合计100%；只改草稿，保存才写入，成员变化不静默重分配。
  保存进行中禁用这两个操作；保留现有权重合法性、完整成员读取和快照并发校验。
- 区分尚无股票池与筛选无结果，分别提供新建、清除筛选入口；将动态池的
  内部白名单/非权威术语换成当前支持条件和创建时重新核验的业务说明。

### 验证与限制

- AgentView 定向测试：**PASS，36项**。包括四个入口均不创建/提交，修改草稿后
  显式发送一次，已有草稿不覆盖、清空后可重新选择。
- StockPoolView 定向测试：**PASS，12项**。包括3/7只等权、清空、增添成员保留
  已有权重、不自动提交以及创建/编辑提交的精确权重与原快照引用。
- `npm run build`：类型检查与前端生产构建 **PASS**。
- `git diff --check` **PASS**；`dev-check.py --base ecf3beea` **PASS**，但该命令
  对本切片报告0个本地语法检查文件，不能代替以上Vue定向测试和类型检查。
- 独立 Sol 审查：Functional / Clean Break Architecture **PASS**，无阻塞项。
- 真实浏览器 **NOT_RUN**：Chrome工具无法连接；复用现有候选入口5175，已在
  可用的应用内浏览器打开正常登录页并请求维护者登录，未索取或回显密码。
  登录后的草稿点击、等权持久化、空态与窄屏验收仍待完成。
- 本轮未提交模型输入、创建业务资产、修改数据或重启服务。现有5175/5176候选
  预览进程保留；构建更新本工作树的本地前端产物，不是生产镜像部署。
- 远端CI、发布、部署 **NOT_RUN**。本切片是本地候选，不宣称完整体验旅程通过。

剩余包括真实研究结论/分红口径核验、新取数顺序的耗时对比、拼音搜索、动态
筛选条件扩展、回测完整分步引导、模型日期按数据覆盖推荐，以及登录后上述
真实浏览器验证。原模型500内部根因仍未知；不因本次UI整改关闭该事件。

## 登录后真实页面补验（2026-11-09）

维护者在保留的 `http://127.0.0.1:5175/agent` 页面完成登录后要求继续。
使用该已登录应用内浏览器、候选前端 `f588335f` 和原开发 Gateway/Product API；
不替换任何运行镜像。本节补充上一节的浏览器证据，不覆盖未运行项目。

| 检查 | 实际结果 |
| --- | --- |
| 个股研究示例 | 点击后输入框出现草稿，仍显示发送后保存；未点发送。修改草稿成功；已有输入时4个示例禁用，清空后恢复。PASS |
| 创建池等权 | 3个规范代码按选择顺序分配33.34/33.33/33.33%，清空后DOM输入值均为空、placeholder为未设置；再次等权后创建成功。PASS |
| 编辑清空并保存 | 点击清空仅显示未保存更改；保存后v2成员权重全部显示未设置。PASS |
| 编辑等权并保存 | 完整成员按代码排序后重新等权，v3为000001.SZ 33.34%、600036.SH与601398.SH各33.33%；整页刷新回读一致。PASS |
| 筛选空态 | 搜索不存在名称后显示没有符合条件的股票池和清除筛选入口；点击恢复列表。PASS |
| 股票池到研究草稿 | 比较入口携带精确池ID和v3快照ID；仍为未发送新草稿，不覆盖成已有会话。PASS |
| 390px窄屏 | 研究草稿页和加载后的股票池页 document.scrollWidth 均为390，等于viewport width；恢复原桌面尺寸。PASS（无页面级横向溢出） |

本次新增并保留测试池 `体验回归_等权与草稿_20261109`：

- pool: `stock_pool_944367de0d5f49fbad35c36a574d181d`。
- v3: `stock_pool_snapshot_273e5517f562d4a0cceaa68851a968696784529433e058c802b53d80bfa59b42`。
- Gateway/Product API只读交叉检查：三个快照；当前三项权重分别为
  `0.333400000000`、`0.333300000000`、`0.333300000000`，Decimal合计
  `1.000000000000`，当前快照与浏览器草稿引用一致。
- 目录中的000001.SZ明确标注Synthetic Fixture，另两个代码目录缺失并按页面
  说明手录。这里验证表单与持久化，不把目录或“数据就绪度”提示当行情质量证据。

截图已在本次会话中展示（桌面保存结果、窄屏研究草稿）；当前已登录页面与
未发送的比较草稿保留。限定浏览器error日志查询返回空数组，并非全链路日志审计。
没有点击发送、提交新的模型输入或启动回测/训练/下单；新增业务数据仅上述
测试池及其三个版本。未清理原数据或页面，未推送、发布、部署。

采集限制：一次窄屏定位误选隐藏的桌面表格文本而超时；重新读取实际可见
无障碍树确认移动卡片存在，不将该定位失败记为产品失败。恢复视口后紧接的
一次定位点击意外打开旧会话；重新读取页面、通过可见导航回到测试池后，比较
入口再次正确生成草稿。未改写旧会话、未发送输入，也不据此推断产品根因。

真实“完全没有股票池”的空态仍NOT_RUN（保留现有池，不为测试删除数据）；
其余三个首页示例保留本地行为测试证据，本轮仅个股示例实点。
金融结论质量、新取数指导的真实耗时和部署后研究整链仍NOT_RUN。

## 2026-11-09 当前测试会话 409：工作区历史未结算保护

用户在候选前端 `5175` 提交股票池比较后，新会话
`conversation_555d234c6cf64527bd4114b711dd2b2c` 显示
`runtime session is not available for this operation`。本轮没有重发输入或
重启容器，先以现有访问日志、Product 回读和数据库只读事务定位。

- 当前 Runtime 为 `byq-session-5bbe82898c8044a5b7cc9e3125548ed1`，
  trace 为 `byq-trace-e679576c066d4cdf89d54608d0f43769`。
  2026-11-09 06:57:51（北京时间）会话创建返回201，发送返回409。
  持久消息只有一条用户输入，无助手回答；事件只有 `session.ready`，
  Product containment 为 `submission=not_performed`。
- 同一时间 Backend 收到该 session 的工作区 admission 读取，候选 Root
  `40dde542820a4746a64cc9992d1b0174`，随后 Runtime prompt 返回409；没有
  新 Root admission POST。数据库没有这个候选 Root 的记录。
- 工作区 `workspace_4c5b803209d549019b7804976f6930c6` 旧 Root
  `f6dc48f8c4e446c6912eed772a47493f` 仍为 `active/active`，它正是前文
  11月7日日线缺日期返回422却被误记为unknown的研究；ingress seq8
  `byq_market_daily` 仍为unknown，`terminal_unknown_claim_count=NULL`，不能当作0。
  旧ACP binding仍为 `closed=false/process_exit_confirmed=false` 且无settlement
  receipt。没有把Runner中的node进程精确归属到该Root，因此其当前是否还执行
  模型未证实；完整active Jobs盘点NOT_RUN。旧页面出现回答没有结清该业务执行。
- Backend `AgentResearchStore.workspace_agent_admission` 对同工作区其他
  `status=active` 或 `authority_status!=closed` 的Root返回 `can_start=false`；
  Runtime `_require_group_admission` 将其映射为
  `workspace has an unsettled Agent turn`，Gateway `_adapter_post` 再隐藏为
  上述通用英文提示。日志顺序、持久状态与源码共同定位到准入保护；没有保留
  当时409响应正文，不把源码还原的原因冒充已采集的响应body。

所以本次不是模型慢、模型500或新会话不存在；新输入在模型执行前已被拒绝。
旧会话 `/release` 也有409，但那是并发出现的另一个请求，不能代替上述因果链。
新建同工作区会话仍受相同保护。候选 `d57904f8` 只防止未来已审核只读工具的
明确错误再被误记为unknown，不会自动修改这条历史收据。

现有 local-validation prepare/finalize 恢复仅支持精确的
`byq_strategy_validate` 回执，不能用于行情读取。普通恢复也需要已结算的
Backend证明，不能把 `byq_market_daily` 的unknown直接改成settled、清空数据库、
重放原请求或通过重启宣称恢复。历史执行的安全结算路径和可理解的工作区
阻塞提示仍是未完成整改项。

用户已授权仅测试环境更新。更新前检查发现上述未结算Root，因此尚未切换
运行容器；候选ACP统一镜像、MCP与Frontend按当前源码开始构建，保留原配置
和镜像。生产无变更。部署后同题研究、金融质量及耗时对比仍为NOT_RUN，
不能用候选构建成功替代验收。

独立Reviewer复核上述guard与现有恢复分支，确认当前会话功能FAIL、保护门禁
符合架构约束。Root复核27个现有容器（生产17、测试10）的ID、镜像和StartedAt
均与本轮开始相同，测试operator Compose字节一致。私有构建日志和只含容器
元数据的前后对照位于 `~/.local/state/byq-maintenance/research-candidate-20261109/`。
MCP与Frontend候选构建exit0；这仅是镜像构建证据。

### 2026-11-09 安全恢复授权与设计准备

维护者明确要求：先修好历史未结算记录的安全恢复，再更新测试环境，用同一
研究问题验证结论质量和耗时，生产不动。独立设计审查确认：ADR-0113排除
非审计工具，ADR-0114仅覆盖策略校验；此日线读取需具名的新恢复合同，不能
将上述任务授权自行记成Accepted。已形成
[ADR-0117 Accepted](../architecture/adr/ADR-0117-exact-readonly-error-reconciliation.md)，
维护者明确回复“接受 ADR-0117，继续实现和测试”。实现进展见后文；历史恢复、候选部署、同题验证尚未进行。

只读准备：测试Backend实际文件与当前源码SHA256一致：

| 文件 | SHA256 |
| --- | --- |
| `app/main.py` | `84e3923d2b24bb9b50cafe91923a178f7077b0ffa1537c2ee7e4ec151791e830` |
| `app/market_data.py` | `72e511f206e3ddd8edf6d40a26ef1462ccdbcd99fd2cef4beaf5708dbc32cc54` |
| `app/data_provider.py` | `0fdf9de31724ed53ccb53c35ed1a069a696cc0fa6e3843048cfc047a967b7662` |

`research_daily`先调用`DailyRequest.normalized()`，只给`ts_code`且没有日期时
抛出ValueError，入口映为422；正常读取只执行已有行情/交易日/停牌状态SELECT，
没有Provider调用。候选与已部署基线这三个文件无源码差异。这证明源码性质，
不冒充当时完整HTTP请求/响应配对证明；ADR采用保留读取结果unknown的语义。

先前启动的ACP候选构建现已结束；本地三镜像均具有源码
`62c0363ff51ae7ada3210f0cd19759e9b658e4ff`标记，尚不含新的恢复实现：
ACP `sha256:24affa33aef864012cb526b41a25a5ce39a75c2fc963a057c81e8c36d2600e5a`；
MCP `sha256:fce67cc302c85c0bed201060081033652ba7d4889c085208b14ac7aaff995552`；
Frontend `sha256:fa2b06698a515878d11070d425e0aa7dc814857ad35dd53cf6373da32f5055b6`。
元数据留在同一私有目录`candidate-images.json`。未变更operator配置、容器、
数据库、凭据或当前页面，未发新模型请求。


### ADR-0117 实现和隔离验证（2026-11-09）

Backend 增加无 HTTP 入口的受限 prepare/finalize CLI；保留原 unknown，附加
固定审计证明并消费原始 seq38 terminal。检查原控制 Key 信任锚、签名 cleanup、
完整冻结快照及身份；terminal guard/hash 和 Workspace reset 均保护此证明。
Runtime helper 7 项测试 PASS；Backend 14 项定向测试 PASS。独立源码审查
正路径和架构 PASS。仅在新增 tmpfs PostgreSQL 内恢复测试环境备份做实际 SQL
检查：prepare/finalize/exact repeat PASS；改变 operator 拒绝；22 条 ingress
整行未变，Root completed/closed、terminal sequence38、unknown domain claims0。
这是合成控制 Key 的隔离 SQL 证据，不是原 Runner 清理或 Product 验收。

隔离负例：额外 unknown、pending registration、改 settlement、删 proof、改 proof、
未决 domain claim 均拒绝。Reset 初次命中前置 ADR-0113 保护；在回滚事务内
排除该前置保护后，ADR-0117 保护也拒绝，原数据未变。首次 CLI 因容器普通用户
不能读取0700私有证据而 HOLD；核对用户/路径后以一次性 Engineering 身份成功。

旧 MCP image 134ab67d… 的实际 src/server.ts 与 src/market-data.ts 均匹配
Git e7c488d8；分别 SHA256 2dd1139f13438b859a1e12f42b2c390f5e4de9586bd4904257778dfadddb6b05
和 eda1210e91803659708139f9e1b68b03cb73b7ad9279fbc3c3b4c2ea49f2c4d7。
编译产物 SHA 及原 Runtime seq38 event/readback/arguments 文件 SHA 已封存在
私有 readonly-operation-evidence.json。MCP handler 仅加身份头并调用上述 Backend
读取入口；外围写入仅为已保留的 ingress 生命周期记录，不执行行情更新/业务写入。

经维护者允许，仅测试 admin 将现有模型 Key 复用于搜索 credential；Product API
版本1→2，重新解析保存后的 Key 鉴权200（原401）。未调用模型/搜索来替代研究验收。
生产未变更。真实旧 Runner 签名清理、实际恢复、候选部署及同题研究仍 NOT_RUN。

### 实际恢复与第二个收尾阻塞

实际原 Runner cleanup MAC 校验 PASS，reason=cancelled、code0、cleanup=proven，
receipt SHA f4cd19a79c0ef350f4480ce9429316d2b67bc5d3d0768031f53d6921cac61795。
Helper 只补 process_exit_confirmed；Backend finalize exit0，proof SHA
c917f101ad5f8d02dc8a769c99cbc25ab4e99cbdc933209a492551cd96732f53。
旧 Root completed/closed、原seq38 receipt落库，原unknown不改。

测试 Backend 已更新本地镜像5655da84…，两MCP更新fce67cc3…，生产不动。
旧会话GET仍保留2条消息与原seq38 terminal；事件订阅实际409。根因是原binding
sequence1与Gateway tail38不等，阻塞正常closed-before-ACK恢复。经独立审查，
在ADR0117原终态ACK范围内只允许完整原binding摘要+原receipt+已证明进程退出+
initial/tail38的唯一组合。35项Runtime测试PASS，包括真实恢复函数写38、生成39
并ACK39，且不创建旧native harness；其他binding字段/receipt/cursor偏差均拒绝，
原通用gap拒绝测试仍PASS。此补充尚未部署时不宣称旧会话接续已PASS。

构建首次错误：Dockerfile FROM image ID被BuildKit当作registry路径；停止该批，
保留失败说明，给已核对image ID打本地base tag后成功派生镜像。未改依赖或热补丁。
Runtime新增测试因宿主缺httpx未收集；改用既有运行镜像依赖。普通10002用户运行
Engineering manifest夹具会被owner保护拒绝；明确root Engineering测试身份后35PASS。
