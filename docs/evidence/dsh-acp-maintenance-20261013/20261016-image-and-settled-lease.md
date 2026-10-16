# 2026-10-16 隔离镜像、旧接续租约与已有 Job 结果核对

本轮为 DSH / ACP 维护，不推进 Product Phase。应用提交：`6975bd18a3df48fa372def36f8fb64935978aea9`。
工作树：`/home/jefison/.codex/worktrees/dsh-acp-maintenance-candidate/BeyondQuant`。
复用原测试账号、数据库卷和浏览器会话，没有生产更新。

## 镜像与体积

以已有冻结清单核对 483 个源码映射文件和独立 SDK lock；Backend 复用原读回，Gateway/MCP/ACP 修复后原生读回通过。
权限修补只修改目录权限，没有递归复制或 chown 运行时文件。以下是 Docker 报告的存储体积增量，不是全镜像解压体积：

| 修改 | 存储增量 | 新增 RootFS 数据层 |
|---|---:|---:|
| Gateway 目录权限 | 833 字节 | 1，history 16.4 kB |
| MCP 目录权限 | 374 字节（配置） | 0 |
| 统一 ACP 目录权限 | 1,123 字节 | 1，history 73.7 kB |
| Gateway 本次租约修复 | 52,555 字节 | 1，单次 COPY，history 295 kB |

本次 Gateway 仅 COPY 已冻结的 `app/main.py` 和一个测试文件，文件 0444、目录 0555；
65 个映射文件的哈希、原始权限/属主及完整目录清单均匹配。
继承 USER/CMD 不变，revision label 指向上述提交。
新 Gateway 镜像：`sha256:67045fd75b3f9be955574fad48a38c4b4190c18f3092e7951ce769769b6cfc3c`。

先完成四份加密备份和完整认证解密/清单检查，再更新隔离环境：
先前五服务聚合更新通过；本次只替换 `gateway-f6`。
其他 15 个容器 ID、镜像和端口不变，全部 16 个容器挂载保留；15 个健康，Worker 无健康检查。
备份清单检查不等于恢复演练，也不宣称跨卷原子快照。

## 旧结算记录占用接续租约

实采发现新 SignalJob 已完成，但新预留仍 reserved/dispatch 0。
Gateway 日志先对账旧 settled 预留，随后未读取新预留的 Runtime 收据。
定向回归证明：旧 Backend settled、Runtime 明确缺失且精确 prompt reconciliation 为 unknown 时，旧本地租约仍会挡住后续不同事件。

修复仅在精确 Runtime missing-record 和官方 `prompt-receipt.v1/outcome_unknown` 形状下，
验证 Backend 已结算记录的身份、一次派发、run、typed usage、profile/limits、outcome 与 canonical 摘要，
再在锁内释放同一且无任何取消标记的租约。旧 prompt 不重放；未结算、冲突、网络错误和其他未知形状保持原保护。

补丁前单用例出现目标断言失败；原 RED 替身少 schema_version，但旧代码只读取 state，该差异不改变旧分支因果。
GREEN 替身已按官方形状修正，红绿不是相同测试字节。完整 delivery 模块 **103 PASS**；
原生退出 0、无 OOM、准确清理，局部 dev-check 通过。Tester、独立 Sol、Root 离线门通过。

## 真实结果与失败边界

原浏览器只提交一次新 Job：`signaljob_f35d7e1ff26e4ed2a2470124af041012`。
首次未自动接续的批次保留 **FAIL_STOP_REAL_BACKGROUND_NOT_DISPATCHED**。
更新 Gateway 后，原页面无需新输入便自动读取同一任务和同一 BacktestTask，并显示信号生产完成、回测尚未执行。

预留 `continuation_67ab8b63d28cbed9bba2321288648982` 只派发一次并结算；
consumer root `20f58512a06745448c0266b3625d4ce3` 完成、授权关闭、unknown 0。
Runtime terminal、Backend 和 Gateway ACK 的序号 109、boot、root 和事件摘要相同。
消息 22→23、Root 10→11，新增一条 assistant 回答；旧消息/Root/4 个 Job 行不变，Job 与预留总数均保持 4。

最后采集误用了普通回合的 provider journal 文件名，原生命令在 terminal GET 200 后断言失败。
此批单独保留 **FAIL_OBSERVER_STOP**，没有重跑模型。
静态审计后，另批只读一次官方 Runtime continuation receipt：0 新模型/Job/输入，原生 0，
其 exact run、known usage（7 次 provider attempts）、profile/limits 和 canonical 结算摘要与已存 Backend 记录一致。
限定已有 Job 恢复的组合证据经 Tester → 独立 Sol → Root 通过，原失败批次不改标。
不为逐次 HTTP 状态额外追日志：该项 **NOT_RUN**。后台读取有准确授权和成功审计，不冒充独立 native domain-result 读取。

Gateway 重启会清除本地内存占用，因此上述组合仅证明**已有 Job 的限定恢复完成**；
连续运行时“旧 Runtime 终态缺失→下一个事件”的真实回归仍 **NOT_RUN**，软件因果由定向回归证明。
不宣称恢复原子 Agent。真实新版本取消/进程异常/两用户与迟到请求等未覆盖项目仍分别保留。
推送、远程 CI、合并和生产部署 **NOT_RUN**；当前环境与原页面保持打开。

## 当前镜像单子 Agent 只读委派

原页面在 `2026-10-15T23:19:09.063Z` 提交一次输入，限制为一个子助手、零新 Job、最多12次模型请求、300秒。
采集入口已先用现有已完成 Root 和官方 recovery-binding 核对；没有新建验证框架。
本轮 Root 从新增 Backend 行确定为 `c5ce0d9d9b864a7eab414f7a2d6a0097`。
quant_orchestrator 父运行与 market_researcher 子运行使用独立 AgentRun/native session，签名父子链一致。
子运行只发生 authorize → byq_research_get → audit 三条 settled MCP 入口，授权与成功审计指向原研究任务。
浏览器活动显示委派步骤完成，父回答转述实际 `planned` 状态及子助手标记。

普通回合 journal 记录8次请求，均HTTP 200、聚合峰值并发1；provider跨度35,693毫秒。
input 295,958、cache-read 253,184、output 3,370 tokens；这是Root聚合，不能作子助手费用拆分。
两个业务 AgentRun 均 completed/authority closed，Root unknown 0；terminal、Gateway ACK、持久化行同序号118和事件摘要。
官方 recovery-binding 返回同一 Root/boot/epoch 的 settled 收据，证明 Adapter 已确认其所拥有的 Root 进程退出。
消息23→25（一个用户输入和一个回答），Root11→12；旧消息/Root、4个Job及4笔预留逐行不变。
不宣称单独 native child closed、旧子进程恢复、多子助手或生产资格。
Tester → 独立 Sol → Root 限定 PASS；准确命令、raw 与三门收据见私有 `current-delegation-v1/`。

## 当前镜像取消后再输入：已存结果补查与登录提示缺陷

同页发两条纯文字输入、中间只点一次停止，没有工具、委派或新Job。
取消 Root `ba6d11218fff45d5925e93491d87bb88` 已 cancelled/closed、unknown claims 0，终态与ACK序号122；
在第二次输入前已读取其 settled recovery-binding，外层游标124与内层结算收据122含义不同。
页面等待提示消失、迟到结果未采纳，最终未持久化取消轮的assistant答案。
新 Root `19dad0526ba24721a4a4dfc739c51cf9` completed/closed，终态与ACK130，实际短回答正常持久化。
消息25→28（两user、一assistant）、Root12→14，旧消息/Root、4个Job和4笔预留不变。
取消轮1次provider请求用量未知，不能记成零费用；新轮1次HTTP200，input/cache/output为37,546/26,752/14。

Root复用命令时全局替换目录，误改固定SQL输入路径，导致两项采集在Docker/SQL前重定向失败。
原批保留 **FAIL_STOP**，停止后续真实测试。纠正方式是固定已验证SQL的绝对输入路径，执行前检查文件哈希与输出路径；
不构建新观察器。独立Sol准入另一批零模型/Job只读核对：已完成Root预检及两条准确Root查询均原生0。
Tester → 独立Sol → Root限定已存在结果补查PASS；不追认原批为PASS。

本轮新发现研究核对面板把登录失效403错误显示为“暂时无法读取核对状态”。
收据GET与认证GET此前200，`23:26:18Z`开始403；最小只读登录时间查询确认账号active，最近一次登录恰于
`2026-10-15T23:26:15.205464Z`正常满12小时过期。没有读取session ID、密码或密钥，没有重置账号。
当前修补范围仅为准确识别会话认证错误、保留已有结果并提供回到同CID的登录入口；不改变登录期限或权限。
该UI缺陷与SQL采集错误分开记录，整体UI验收仍未关闭。私有证据见 `current-soft-cancel-v1/`。

最小修补已完成：只认401/403及已知会话认证错误码，保留已有记录/成功时间，停止此类自动轮询，并提供同源登录返回链接。
其他403、服务错误和网络异常保持原处理；旧CID迟到错误不能污染新CID。
四个前端文件的源码与测试哈希冻结一致，两个spec共18 PASS，vue-tsc/Vite构建原生0，两stderr为空。
Tester → 独立Sol → Root离线门通过。该门不代表镜像已更新或新提示已通过真实浏览器；后续单独记录。
证据：`receipt-auth-expiry-v1/ROOT-OFFLINE-PASS.json`。

前端修补提交 `1979031e1deba233eafc3a8f997a857e99437fbb`，从固定Nginx基础镜像重建静态层，单次COPY，未叠加旧前端资源。
新镜像 `sha256:f83da9e65fdfd7879da2cfb93995a9afb13ea6d88bd44c72e9bfcfa779bdecd2`：
95文件哈希及93个assets路径均吻合，nginx用户/断网/只读校验原生0、无OOM，准确临时容器已移除。
Docker同口径Size为21,767,715→21,767,826字节，**仅+111字节**；RootFS层数10→9。
Tester → 独立Sol → Root镜像门通过。

隔离环境仅替换 `frontend-f6`，原生Compose调用有120秒外层超时、终态0；新CID `a4dc49220d2d3b963ef6bd12d2303a023b3cb6ff18b022d89fd283d590834a6e`。
后置比较错误地把无序Mounts数组按顺序比较，触发断言：原批保留 **FAIL_STOP**。
同一执行单元未检查该返回值又发出一次只读SQL，此执行纪律缺口也保留记录。
独立审查确认仅三个未改容器的挂载数组重排；另批先用六组纯内存反例核对“按唯一Destination比较完整挂载对象”，
再仅复核已有快照，不新查询、不重新部署/调用模型。
其余15容器ID、镜像、端口和状态一致，所有挂载完整字段不变；16运行、15健康、1无健康检查。
后置数据库元数据与此前28消息/14Root/4Job/4预留快照字节相同。
独立Sol/Tester与Root限定后置对账通过，原失败不翻标。

避免再次出现同类采集错误的执行规则：固定已验证输入路径，不对整条命令全局替换；执行前核输入存在/哈希与输出位置；
每个有依赖的命令先检查原生返回再继续；无序集合按唯一业务键比较完整对象，拒绝重复、增删及字段变化。
这些是原生命令的简短核对规则，没有新增客户端、调度器或Agent harness。

同一浏览器标签刷新后已进入正常登录页，完整保留原CID的redirect，等待用户重新登录。
新面板认证分支目前为离线测试证据；真实浏览器已证明更新后页面加载与过期登录跳转，未冒称登录后全部通过。
环境、原页面和账号均保留，未改密码或登录期限，未清理业务数据库或卷，也未操作生产。
准确证据：`receipt-auth-expiry-v1/image-v1/`、`receipt-auth-expiry-v1/local-frontend-update-v1/`。

## 准确私有证据入口

### 重新登录与连续Gateway后台接续（V2）

用户重新登录后回到原CID，核对记录刷新正常，旧28条消息未变；未改密码或登录期限。
源码验收点 `85aad7f7e30e1541dbbf00015c7289a069693ba0`，Gateway应用仍为上述6975bd18、前端1979031e。
`2026-10-16T00:13:50.291Z`仅从原浏览器提交一次已有批准合成输入，创建一个新SignalJob，未委派、下载行情或执行回测。

- Job `signaljob_82d0b0be6ea74a4cb51642b543921289` 一次完成；预留 `continuation_3d79b88a5a2875644df86c1d1ce955e8` 只派发一次并settled。
- 源Root `f149b866112b423e941b97696cf07ef1` 与自动Root `cada1c0324534c9382b6baf65542cc6e` 均completed/closed、unknown claims为0；终态与Gateway ACK分别为143、158。
- 源轮5次HTTP200；后台官方收据为5次请求、7次工具调用、峰值并发1，known/provider_response用量input218408/cache-read196736/output2924。后台逐次HTTP状态未采集，不冒称通过。
- Runtime与Backend canonical结算摘要同为 `0066618aa837c3049f16ee054a3262ab4d5443589c3d634482da225ff7d7b46c`；可选执行限制仍null。
- Gateway前后CID、StartedAt、RestartCount=0及镜像逐字节相同。后置16容器快照与此前保留基线按服务及唯一挂载目标比较一致，15健康、1无健康检查；该全量快照的原生命令包未单独保存，不冒充V2批内全16项原生前后验收。
- 消息28→39、Root14→16、Job4→5、预留4→5；旧消息、Root和Job行精确不变，旧预留仅全账本摘要随新增项变化。ResearchTask仍planned/version1，但其预算字段随预留增加，不宣称整行未变。

原计划误把两个可见assistant气泡当成两条耐久消息。实际每个Root各保存5条非空文本delta，连同1条user共新增11条；新段哈希各异，无旧历史重放。
原PLAN保留，另行澄清存储与UI分组合同，没有为此重跑模型。
刷新原页后自动回答仍在，准确说明同一BacktestTask信号完成、回测未执行；刷新前后元数据快照字节相同。
观察窗600秒、最多1输入/1Job/0子助手、请求观察阈值16，实际10次；阈值是测试停止线，不是Product配额。

Tester → 独立Sol → Root **限定PASS**，私有入口 `continuous-background-v2/ROOT-PASS.json`。
它证明连续Gateway中的新Job自动接续；未独立注入“旧Runtime终态缺失”内部条件，该分支仍以103项离线因果证据为准。
旧V1失败原件不改标。进程异常、空闲释放、两用户/迟到/未知结果剩余范围另行验证；生产/推送/合并NOT_RUN。
原环境和浏览器页面保持打开。

### 空闲Adapter异常退出：原批采集失败，停止扩大测试

源码 `726ba6b5`；独立Sol准入前完成只读预检：私有PID命名空间、restart=no、仅Uvicorn进程，
active prompt及执行槽为0；所有未闭合Root/AgentRun、待绑定、未知入口/claim、进行中Job、未结算预留和待处理取消均为0。
原39消息/16Root/5Job/5预留与V2结束快照字节相同。

`2026-10-16T00:38:58Z`开始，仅对原隔离Adapter准确CID执行一次SIGKILL，再start同一CID。
原生结果为exited/137、Gateway503，随后ready200；新boot `488d00f535f263b1390318772c82469e`，epoch9→10。
原页随后一次输入委派只读子助手，返回原SignalJob82的completed、相同快照和“回测尚未执行”，显示RESTART_READ_OK。
保存的provider journal含11次完整HTTP200、峰值并发1；input359166/cache-read310912/output6020，provider跨度64513毫秒。
这不证明子助手或Root已闭合，更不表示恢复原子助手。

后置两项只读SQL并行采集时，Root把`-v root=…`追加在`sh -c`脚本之外，psql未收到变量，scope查询退出3。
另一查询原生0：消息41/Root17/Job5/预留5，旧39消息/16Root/5Job/5预留逐行不变；新Root当时仍active、终态尚空。
本批保留 **FAIL_OBSERVER_STOP**，立即停止后续采集/模型/故障测试，无输入重发或新Job。
当时已确认Root采集命令错误，产品原因尚未定位；UI答案不能替代终态ACK。
后续仅允许先离线验证完整字面命令的参数合同，经独立审查后另批零模型只读核对同一已存在结果。
准确入口 `process-loss-v1/FAIL-STOP.json`、`NATIVE-RESULTS.json`、`NATIVE-STOP-SUPPLEMENT.json`。
隔离Adapter已恢复，测试环境与原页面保留；活动child异常、两用户/迟到/未知结果不扩测，仍NOT_RUN。

离线shell参数正反例与Tester/Sol准入后，另批零模型只读执行准确scope查询，原生0；
父/子AgentRun仍active且authority active，child的两条`byq_agent_audit`入口（seq5/6）为unknown，其他六条入口已settled。
官方recovery-binding首个GET返回409，立即停止本批后续终态/快照/日志读取；原生stderr保存，未重发模型。
故已有结果收尾为 **HOLD_REAL_ROOT_NOT_CLOSED**，不能把界面回答当作流程闭合。
409端点把多种不满足恢复条件的情况映射为同一状态，不能据此认定具体清理根因；两条success audit也不能证明旧unknown入口已结算。
另经独立Sol准入仅读取原运行时间窗内三服务既有日志：Adapter显示同Root终态查询200被持续重试，Gateway/MCP无精确关联行；无响应正文，不证明ACK成功。
随后按准确路径、唯一普通文件及16MiB上界核对，仅复制本Root与child的两份既有原生会话记录，SHA一致并以0600保存。
精确child记录显示：两次audit的run_id正确，但detail含公开字段`authorization_decision`；原生工具返回均为`agent_request_invalid`/422。
Backend在INSERT前的密钥字段过滤中将该字段名归一化为含`authorization`而拒绝；MCP将无精确负回执的422保守记为unknown，根关闭守卫继续阻断。
后续省去detail/resource的两次audit成功，不能替代前两次unknown结算；会话身份并未混用。
当前仅实现切片A：审计detail顶层精确字段及封闭枚举的最小校验修补，保持其他密钥与ACP控制过滤。
切片B的确定性无副作用私有拒绝回执另行处理；不能把普通422、超时、5xx或丢响应全部判为无副作用。
不扩大真实测试、不自动清除旧unknown、不重放业务；旧Root和失败批次不能因后续软件修补改为PASS。

### 审计公开权限判断字段（切片A）：限定离线软件PASS

应用提交 `f6a1c51f0e065cde341677e53b2fbca928341953`，仅修改Backend审计校验及一个新测试模块。
只在audit detail对象顶层允许精确键`authorization_decision`，值必须为`allowed`、`denied`、`approval_required`之一。
一般JSON校验不放宽；相似键、嵌套凭据、非法类型、不可序列化/非有限数值、16KiB字节边界和保留ACP-control拒绝仍在。
两个实际失败输入形状分别通过`record_audit`两层校验进入替身execute边界，不能称为真实数据库写入。

冻结应用/测试SHA分别为`860e4b52a2f3c7f8b471b16b2e958d48e18b26d2f8e68eb199455aa2cc7020a6`、
`eafbd3196f1f898428851f62c830d396a9fb9804df0bc1afe52bc11dd16c9fdc`，前后不变。
单次19项全部PASS、0失败/跳过、schema resets和store bootstraps均0；pytest0.03秒，整批含采集清理138秒，小于180秒。
缓存镜像断网、容器和源码挂载只读、空数据库URL；准确测试容器原生及State退出0、OOMKilled=false，并按准确CID移除。
原44条运行容器清单前后字节相同；未调用数据库、模型或Product Job，未更新保留服务。
Tester → 独立Sol → Root限定PASS，私有入口`audit-detail-public-decision-v1/ROOT-OFFLINE-PASS.json`。

当前镜像安装、真实浏览器重验、切片B私有负回执、旧unknown核对及生产均NOT_RUN；本片不能解除旧Root的HOLD。

证据根：`.ci-artifacts/agent-origin-consumer-20261015-v1/`。

- `native-image-readback-v1/ROOT-LOCAL-IMAGE-PASS.json`：原生哈希/权限/目录与体积；首轮权限及观察器失败均保留。
- `aggregate-local-apply-v1/ROOT-LOCAL-APPLY-PASS.json`：先前五服务更新及备份。
- `current-image-browser-ordinary-v1/ROOT-ACTUAL-PASS.json`：新聚合镜像普通对话、持久化和 ACK 通过。
- `current-image-browser-background-v1/ACTUAL-RESULT.json`：首次后台停滞。
- `settled-continuation-lease-v1/ROOT-OFFLINE-PASS.json`、`GREEN-ENTRY.json`：准确源码哈希、命令、原生红绿日志与独立审查。未采集的 RED/GREEN UTC 起止明示 NOT_RECORDED。
- `settled-continuation-lease-v1/image-v1/ACTUAL-RESULT.json`：精确镜像、原生命令、65 文件核对与体积。
- `settled-continuation-lease-v1/local-gateway-update-v1/`：完整 preflight/rollback、备份、容器前后快照、失败原件、单次后置只读收据、浏览器截图和独立审查。

### 切片B：确定性审计拒绝回执，源码及镜像差量限定PASS

应用提交 `3f87d3f24edbdf4efe6524ffc056b9d05c81b6d8`，冻结六文件diff
SHA-256 `36a3b3dd0bd7957819fb0b342f1a2cffb70ea165a32893108738a91e170553d2`。
Accepted ADR-0112 已实现：Backend 在精确活动Root/AgentRun及锁定ingress上验证输入，
只有写入前的确定性校验拒绝才保存私有标记；MCP精确核对并以denied结算，模型看不到证明。
普通422/超时/5xx/丢响应仍unknown；旧unknown不升级，拒绝标记不能被observe重复派发或abort覆盖。
跨AgentRun权限检查先于detail拒绝；ACP私有入口不能退回普通接口，普通SDK共享boot/root头保持兼容。

按维护者最新要求，没有新增或执行功能测试代码。初次静态记录缺原生退出码，保留原收据；
Root只补一次必要的AST、指定Ruff规则、diff检查和MCP TypeScript构建，各原生0、四份stderr为空。
独立Sol源码及实际静态回执审查通过，Root限定PASS。
准确命令、源码及raw/native入口为 `audit-validation-refusal-v1/ROOT-SOURCE-PASS.json`。

仅构建两份候选镜像，没有安装：Backend `sha256:5e8ddc836cd92ef55c91477cdeabdd4ddf5041e453195b0683ce92b3c07a3c70`，
MCP `sha256:13486c17984f91c15e487f12241228d4c089f25e29f36ecffc6687d547f2d884`。
各在精确原镜像上单次COPY，USER/CMD/工作目录不变；RootFS各增加一层，存储增量分别100502/59910字节。
通过从未启动的两个临时容器读回三份Python及三份TS/三份JS，九文件SHA/字节/UID/GID/0444均匹配。
准确临时CID已删除、批次标签查询为空；无模型/Job/服务更新。
独立Sol→Root的镜像差量限定PASS入口为 `audit-validation-refusal-v1/images-v1/ROOT-IMAGE-PASS.json`。
各构建120秒timeout生效并退出0；全批UTC起止未留存，不声称300秒总墙钟验收。
这不是完整image admission、浏览器或生产PASS。

当前原Workspace仍被Root7537的两条历史unknown封锁；镜像修补不解除旧责任。
Accepted ADR-0100/0109/0111要求保留该门槛，不能仅靠轮换Adapter内存/boot在同组新建Root。
普通DSH由独立Product runner持有，前述空闲Adapter退出不能证明它或活动child退出。
Proposed ADR-0113提出单独的普通审计unknown人工核对合同；未接受、未实现、未执行，ADR-0104仍Proposed。
新版本安装、浏览器/真实模型验收、Full CI、推送/合并及生产均NOT_RUN；原环境和页面保持打开。
