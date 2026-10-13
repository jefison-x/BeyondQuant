# DSH / ACP 专项维护当前验收（2026-10-13）

不推进 Product Phase。应用闭包基线为 `55033eb0937665bf1d19f848de1f185353f7dbc0`，基于同步后的 `origin/main=ad5f7df1ad18e54dd0d9860d424241297187eef8`。新增租约观察切片的五文件源码 SHA 单独记录于 ROOT-LEASE-OBSERVER-OFFLINE-FAIL-STOP.json；修正入口后的定向离线验收见ROOT-LEASE-OBSERVER-OFFLINE-PASS.json，真实状态验收仍未完成。

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
| 两用户、自然迟到旧请求、业务结果 unknown、进程丢失 | NOT_RUN 当前补缺批次 | 保留旧限定证据，逐片补缺；不自动重放未知业务结果 |
| 远程 CI / 推送 / 合并 / 生产部署 | NOT_RUN | 不以本地、合成或隔离更新证明生产资格 |

## OC 工程执行事故

只读源码审计 `ses_ecd98ec47ffeX0YS71U5PpA5AP` 超过工具次数且擅自检查环境，将服务认证变量带入工具输出。该批次 FAIL_STOP；含密原日志只留私有目录，不进入Git、不出站、不得续用该 session。已完成准确abort、私有日志0600、原生服务密码轮换（旧认证401、新认证200）、原固定Tester session可读。

原生 OC 服务保留，两个旧自动派发timer可逆暂停。当前7个Agent的关键工具权限配置读回为deny，经Sol核对；实际执行拒绝NOT_RUN。权限不阻止模型请求或清除旧会话上下文，新增OC工具任务仍NOT_ADMITTED。现有必要Luna源码回退继续；固定测试命令经审查后在OC外执行。无新客户端、调度框架或Agent harness。具体范围见ROOT-OC-*回执。

当前仍 NOT_READY。历史部署证据和本次新候选资格分别记录，不因当前未验收而改写旧生产部署成功记录。

## 浏览器窗口纪律

验证复用当前已核对的浏览器标签。另开测试窗口前先检查旧测试窗口，关闭已废弃的测试窗口并确认已关闭；保留无关用户标签。2026-10-13复核仅剩当前普通双轮会话标签，没有再次开窗或发送提示词。
