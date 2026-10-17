# 活动进程丢失：故障注入前的恢复合同核对

## 维护者接受（2026-10-17）

维护者在本会话明确回复“接受 ADR-0104，继续实现并验证”，接受已审修订及其限定的隔离 A Product runner 单次故障/替换验证授权。ADR-0104 已标 Accepted，ADR-0100/0113 的对应引用同步。现有静态架构/Compose 合同 5 项通过，0 模型/Job/容器变更。实施首先限定 runner 的持久身份、事前 START 归属及状态卷排他锁；未完成源码审查和无模型资格核验前，不做故障注入。生产、推送、合并均未授权。


## R1a 源码与原生探针（2026-10-17）

源码 `ff8540d2` 实现状态卷 lifetime/admission 锁、签名实例与事前 START 归属记录；新记录仍明确 `operator_qualified=false`。没有工程 prebind、Backend 核清或围栏释放。初审两项 P2（supplied instance 签名、构造异常资源释放）和单镜像缺失 COPY 已修正，语法/diff、独立 Sol 定向复审、Root 源码限定 PASS。未新增功能测试文件。

原生批次 **FAIL，已停止且不重跑**：首次只读清单模板直接访问可选 Health 字段失败；缩为九个必备字段并经保存原件离线核对与独审后，一次只读采集确认原17容器/挂载不变。随后隔离探针仍在启动，采集先读实例、后检查 ready，记录数断言提前失败。原始断言未输出计数，不能冒充实际采集值。已停止唯一探针，没有启动 contender/successor。停后只读取证确认被审源码 hash 一致、一个实例文件和正确 ready 已写入、日志为空；时间窗口强支持启动采样竞态。确定缺陷是观察顺序缺少就绪栅栏，不是已证明的 Product 运行缺陷。

探针镜像 `sha256:1d9233a876be98f59971fa0c71d8f58238da55fdb02e941659285410e472020a` 基于现有单镜像，仅一层 COPY，无下载或递归权限 RUN；Docker 报告 Size 增加15,868字节。仅创建一个专用探针和三个专用卷，全部保留；探针退出/PID0/restart=no、原17容器及全部挂载不变已准确读回。0模型/Job/Product输入，当前A/B runner、数据库与三个页面保持不变。

已统一修正最小观察合同：有限等待准确 ready → 保存具名实际字段 → 再分类判定；无裸断言丢失计数，无新 harness。该合同仅离线语法核对，未执行，并限定全新空卷的首个探针；successor不能信任遗留的同Workspace ready，须另有与新签名实例绑定的就绪证明，仍未准入。原两个采集 FAIL 均保留；signed instance 实际MAC核验、共享状态卷冲突、successor、START归属、工程prebind/Backend终态/活动故障与浏览器恢复均 **NOT_RUN**，不能以源码 PASS 或停后文件替代。本批到此结束，继续同一ADR的既有私有CLI/受保护audit接缝审计，不扩大测试。

私有原件均位于 `.ci-artifacts/agent-origin-consumer-20261015-v1/process-loss-admission-20261017-v1/runner-foundation-v1/`：`ROOT-SOURCE-PASS.json`、`SOL-SOURCE-REVIEW-V2.json`、`OBSERVER-FAIL-STOP.json`、`NATIVE-RESULT.json`、`SOL-FAILED-PROBE-DIAGNOSIS.json`、`failed-probe-diagnosis/`、`FAILURE-SAFETY-PASS.json`、`READY-OBSERVATION-CONTRACT-V3.json`。生产/推送/合并及Product Phase均未推进。


## R1b-a：Backend 非授权准备记录（2026-10-17）

`agent_audit` 依赖AgentRun，而首START前尚无该业务记录；不伪造AgentRun。独立Sol→Root确认在Accepted ADR-0104内复用既有全局 `operations_audit` 的私有受保护记录，无需新增表、HTTP/MCP或用户审批。

源码 `3f132e0b` 新增闭合candidate合同与私有一次性 `prepare` CLI，沿用无DDL既有schema模式，准确幂等与Backend nonce；普通budget入口在查询/写入前拒绝保留namespace，管理员overview仅返回安全摘要。`prepared` 明确 `authorizes_start=false / native_facts_verified=false / runner_install_verified=false`，activate固定HOLD；不能把保存候选当作工程实例资格。初审误要求Docker启动时间等于runner实例生成时间的P2已最小删除，两个原始时间分别保留，未新增时间精度或排序假设。语法/diff与独立Sol→Root源码限定PASS，原FAIL保留。

无功能测试或live操作。本片不实现native收集验证、runner安装/读回、START锁协同、Backend激活/admission或围栏释放，以上均NOT_RUN。继续实现runner当前实例descriptor与事前started marker基础，尚未准入环境更新或故障注入。私有原件：`R1B-A-RESULT.md`、`SOL-R1B-A-SOURCE-REVIEW.json`、`SOL-R1B-A-SOURCE-REVIEW-V2.json`、`ROOT-R1B-A-SOURCE-PASS.json`，目录同上。


## R1b-b1：当前实例与事前执行标记（2026-10-17）

源码 `205a55c9` 在清除旧workspace ready后、socket接受连接前，原子发布同一R1a签名实例的私有control descriptor；原始state实例记录及false字段不改。START在原admission锁内先写signed/fsynced本实例started marker，再消费scope、写归属和dispatch。marker仅表示可能接受过执行，不能证明业务结果、进程已死或实例资格。已认证marker复用前也补齐同inode文件及私有父目录fsync；初审持久化P2与原FAIL保留，修正后语法/独立Sol→Root源码限定PASS。正常关闭/初始化失败仅清理本实例inode的control pointer，state原件保留。

无新增功能测试、容器、模型或Job。Runtime读取、安装/激活、START expected binding、实际MAC/状态卷互斥/故障与浏览器恢复仍未资格。后续集成设计已独审明确：实际runner及prepare/active引用必须先原子写入既有Runtime pre-START binding，成功后才能发START；旧草案把持久化放在dispatch后的一项顺序HOLD另存，不改原件。下一片仅在相同ADR内实现闭合预绑定安装/消费链，不提前加载测试环境或恢复模型测试。原件 `R1B-B1-RESULT.md`、`SOL-R1B-B1-SOURCE-REVIEW[-V2].json`、`ROOT-R1B-B1-SOURCE-PASS.json` 与集成顺序两份独审收据均在同一私有目录。

## R1b-b2：预绑定安装与默认拒绝（2026-10-17）

源码 `4b5233eb` 增加 opt-in 出生记录及工程私有安装入口：准确匹配当前 signed instance、Backend prepared 回执与 nonce，在既有 admission 锁内确认未接受 START，持久保存非激活安装回执。新发布及准确重试均认证 canonical bytes、同 inode/nlink1，再 fsync 文件与父目录；独立 Sol 初审的持久化 P2 已修正，原 FAIL 保留。六个源码 hash、语法/diff、Sol V2 与 Root 源码限定 PASS 收据均在既有 runner-foundation-v1 私有目录。

合格模式仍拒绝 START；prepared/安装回执不是执行授权，Backend 激活及 Runtime 接入正在继续。legacy 默认行为未转换为事后工程资格。镜像只新增必要小文件 COPY，未构建或加载本片镜像。功能、原生及浏览器故障验证均 NOT_RUN，本批未恢复测试；原17容器、三页、草稿和专用停机探针保留。不能把源码通过当作恢复链路已经完成。

## R1b-c：Backend 激活锚点源码（2026-10-17）

源码 `c6b8a804` 在既有私有 CLI 与 `operations_audit` 内完成 activate：准确核对受保护 prepared 原件、签名实例/出生/安装、工程采集的容器与完整卷绑定，锁内追加唯一 immutable active 回执，准确重复返回原件，冲突拒绝。普通 budget 入口拒绝两类保留 namespace，overview 只投影安全摘要。Backend 不声称自行访问 Docker；可信本地工程执行及原始证据是 native 采集边界，Product MAC 和 UID 不会升级为工程权威。

源码审查发现固定 Mount.Mode=rw 会拒绝已有探针实际 Mode=z，已改为保留有界原值、独立核对 RW=true；原 FAIL 和第一版结果保留。其他实际字段及原始输出/解析数据摘要已分别收敛，语法/diff、独立 Sol V2→Root 源码限定 PASS。没有运行功能或原生测试，active 锚点单独仍不能执行 START。

下一步只接通现有 Runner 私有交付、Backend admission 和 Runtime pre-START 持久绑定，三处一人一写者。Runtime 写入不确定必须保留准确 lease/scope/fence，不能进入“尚未启动”的快速清理；R2 后续核清证明的关闭前快照、自身行排除、受控关闭后差异和准确幂等设计已独审修正。所有 native/活动故障/浏览器恢复均 NOT_RUN，原17容器及三页不变。

## R1b-d：Runner 交付与 START 校验源码（2026-10-17）

源码 `25229f95` 复用私有 installer 增加 activate 交付，准确匹配当前 instance/出生/安装与 Backend active 回执，锁内持久化 immutable 激活原件；START 在相同 admission 锁内核对实际实例、激活和 expected binding，再写 marker/消费 scope。保留既有 signed scope→instance 与唯一激活的关联，不新增 scope 文件，不改 R1a false/null。Runtime 独立 Backend 核验及 v2 pre-START 绑定仍是接入门槛，源码不是 native 资格。

针对重复出现的持久化边界已统一核对八类原件。两项 P2 一次修正：复用既有 state-generation 前确认同 inode 文件及 state 父目录 fsync；认证 activation 后在 marker 前确认其同 inode/原字节及 instances 父目录 fsync。原 marker 的目录 fsync 原本会在 dispatch 前覆盖 activation，因此不能宣称已发生不持久启动；其他 instance/birth/descriptor/install/marker/used/ownership 的既有覆盖或拒绝路径均留有审查说明。原 FAIL/第一版保留，Sol V2→Root 仅源码 PASS；语法/diff 通过，无测试、模型、Job、镜像构建或环境变更。

D 后续缺席判据补充：全链路核对发现 installer 的 `lexists` 会把非 ENOENT 查询错误当作缺席；其中两处直接影响 started-marker 门，另两处已有 O_EXCL 兜底。源码 `462ba0a1` 将四处统一为精确 lstat，仅 ENOENT 为缺席，其他错误拒绝；旧 PASS 与新增 HOLD 均保留，定向 Sol V2→Root 源码通过。无功能/原生测试，未声称出现过不安全执行。Runtime F 的三项独审 P2 仍在集中修正，全部 live 门保持关闭。

## R1b-e：现有 Backend admission 的只读资格分支（2026-10-17）

源码 `b00d8fc0` 扩展既有 authenticated agent-admission，不带资格参数的 v1 行为原样保留；v2 严格要求两类 JSON、四个唯一 query、准确 header 与八项 scope。锁内核对当前 authority/epoch/boot receipt、owner/Workspace、准确 Root（首次 prospective 可无记录）和其他未闭合 Root；从唯一受保护 prepare/install/active 链派生 closed START binding，不采信请求自报 native 状态，不读 Product key/Docker、不签发 activation。缺失、重复或冲突均拒绝，不选 latest。

两源 hash、实际语法/diff、独立 Sol→Root 仅源码 PASS。DB/HTTP/qualified START/浏览器实际均 NOT_RUN。Runtime 四文件仍在接入，环境、页面和原失败全部保留。

## R1b-f：Runtime 事前绑定与准确退休源码（2026-10-17）

源码 `8e80c0ce` 仅修改既有 Runtime 四文件：从确认的 producer 权限读取签名 descriptor，在 socket connect/START 前独立核对 Backend v2 admission 并持久化完整 scope/active 引用。新 Root base 在同锁内 CAS 准确前驱，使用明确的新 generation/cwd 和未执行事实；旧终态字节与内存快照单独保留。正向未启动或已认证 prelaunch 拒绝必须先完成代理关闭、guard 退休、准确 binding 恢复/删除及文件/父目录 fsync，再通过 typed receipt 释放 lease；未知写入、权限、authority、CAS 或退休失败继续保留 fence。没有新增服务、表、HTTP/MCP 或通用 harness。

已闭合 qualified v2 在跨 Adapter boot 补保存 settlement 时，准确 CAS 只补回执，保留原执行 scope/boot/epoch，后续普通持久化也不混写新身份；未结算 v2 恢复仍 HOLD，不能称恢复原子 Agent。legacy 分支原调用保持。初审三项 P2 与 V2 的一项新 Root 旧终态污染均有原件，修正后 V3 独立 Sol→Root 仅源码 PASS，Root 实际语法/diff exit0、四源 hash 与冻结快照一致。原编译及两次源码 FAIL 不覆盖。

私有原件：`R1B-F-RUNTIME-IMPLEMENTATION-v1/`、`-v2/`、`-v3/`、`SOL-R1B-F-SOURCE-REVIEW[-V2|-V3].json`、`R1B-F-ROOT-V3-SYNTAX-NATIVE.json`、`ROOT-R1B-F-SOURCE-PASS.json`，均在既有 runner-foundation-v1 目录。原失败原生批次仍停止；新的无模型原生命令/观察合同待准入。实际 DB/HTTP、qualified START、活动故障、浏览器恢复、生产及推送合并均 NOT_RUN。原17容器、三页和草稿未变。

## R1b 候选镜像构建及观察入口（2026-10-17）

源码审查完成后，仅准备两份 FROM 准确本地 image ID + 单 COPY 的上下文：ACP 10文件/612793字节，Backend 6文件/655149字节，无 RUN、依赖下载或递归 chown。首 build-only 预检实际 FAIL：Go 模板直接访问镜像可省略的 Cmd/Entrypoint，exit1、只有1字节换行而无完整 JSON 行，0构建。Root 与独立审查均误判该可选字段类别，原 GO 和 FAIL 保留。统一 Cmd/Entrypoint/User 为 index，明确缺省/null 规范化但保留空数组/空串；单独一条两 base 只读命令实际 exit0、7202字节、stderr0，经 Sol 限定 metadata PASS。Go 替身因本机无 Go 仍 NOT_RUN，没有安装新工具。

随后独立新构建批次预检确认原17容器/完整挂载不变，两个实际 build 均 exit0；候选 ACP 为 `sha256:5401edd1c741aab92021c8cf12621fc8941dab29c3fc09ae091b8959de9df8bd`，Backend 为 `sha256:ab83d14bd78c14d2c64cea44048861ebb9207ea37faab86166503fe3c3030c30`。但 Root 将两个各71字节、无换行的合法 IID 文件用 cat 拼接，host 按空白拆分后误判一个值，整批立即 FAIL_STOP；未派发候选 metadata 或后清单命令，不能声称层数/体积/启动配置已验收。该故障属于工程观察入口，不是已证明的 Product 缺陷。

两镜像和全部原件保留，不再构建；仅在现有原件上核对完整读取/判定链，将准确 IID 固定进后续只读命令，单独审查收尾。0容器、卷、DB、模型、Job、浏览器和环境更新。私有原件：`image-qualification-r1b-v1/`、`image-metadata-command-qualification-v1/`、`image-build-r1b-v2/`、`image-closeout-r1b-v1/` 及对应 Sol failure/metadata/admission 收据，均在 runner-foundation-v1；实际 image 文件字节/权限、prebind、START、活动故障和浏览器恢复仍 NOT_RUN。不能以原生构建退出0覆盖两个原批 FAIL。

之后只在本地已保存原件上修正完整判定入口：具名严格 IID、闭合 JSON/字段/类型、base 层顺序及增量、启动缺省语义、完整挂载和源码/上下文均离线检查。独审准入固定两条只读命令，准确 IID 写入计划，不再临时拼接。实际2命令/2分类器均 exit0、stderr0，共23.298秒；独立 Sol→Root 限定 image metadata/host source/environment preservation PASS：ACP 807191646字节、比 base +114591、50→51层；Backend 90451023字节、+110380、42→43层，两者完整 base 前缀、启动配置一致，原17容器九字段及全部 unique-Destination 完整挂载一致。原两个 build-only FAIL 和原 GO 原件不改，未重建镜像。收据 `SOL-R1B-IMAGE-CLOSEOUT-ACTUAL-REVIEW.json` SHA256 `f4571806274a65171dceb7bd6c608befd5f78980f2351adc4ef62dd9d151572c`、`ROOT-R1B-IMAGE-CLOSEOUT-PASS.json`。

这项 PASS 不证明 image 内文件的实际字节/权限、runner 出生/锁/私有 prebind、qualified START、活动故障或浏览器恢复；这些仍 NOT_RUN。没有更新原测试服务、页面、账号或数据库，Product Phase 未推进。

## R1b fresh 原生验证：权限名观察合同失败（2026-10-17）

精确源码 `8e80c0ce`、文档 HEAD `f5ce82c5`，候选镜像沿用上一项已核对 IID，没有重建或更新现有服务。v2/v3 命令与观察入口的静态阻断均保留；独立 Sol 准入 v4 与 Root 准入后，仅执行一次固定无业务批次。计划 SHA256 `b4dd19dec65df478c88efcaa1165db10e3a8802e52dff5a76bcce7292b73b92c`，v4 SHA256 `34f5c91fca1821ca733a54da4b88ab4f2f59d6b0db9be60e97f68abade8e5ff4`。

**原批 FAIL，实际测试已停止，不重跑或扩大。** 共 7.876 秒、19 条 native 命令，全部 exit0/stderr0；固定脚本退出2，失败点为 `runner-inspect`。Docker 将请求中的 `CHOWN/KILL/SETGID/SETUID` 在 inspect 中规范化为 `CAP_CHOWN/CAP_KILL/CAP_SETGID/CAP_SETUID`；Root 的观察代码按裸名集合比较，误报 security config mismatch。实际原始字段已先保存。这是工程观察合同缺陷；Root 和前次独审均漏判，不是已证明的 Product 权限缺陷。

创建并保留两个无网络/只读检查容器和三个新建专用卷。两容器均通过准确 CID 停止及停后 inspect 确认 exited/PID0/not paused/not restarting；原17容器九字段及完整挂载与前清单、既有 PASS 基线一致。Backend 六个镜像文件实际 SHA/字节/uid0/gid0/0444 读回通过，但不提升原批为 PASS。ACP 文件读回、ready、PID namespace 内部读回、签名实例/出生/锁/noSTART 核验尚未执行；Backend prepare/activate、Runtime START/ACK、R2、活动 A 故障和浏览器恢复仍 NOT_RUN。0 DB/API/模型/Job/START/浏览器输入，无生产、推送、合并或 Product Phase 推进。

本轮只用已保存原件全面审计字段合同：准确区分 CLI 请求表示与 Docker 输出表示、限定四项 capability 的已知别名、拒绝重复/额外权限/畸形类型、拒绝未知 PID mode、额外 security options、冲突 tmpfs 与不明确空值；挂载与卷读回准确绑定，不猜 `Mode` 或目录前缀。后续修正只允许 saved-only 观察判定和独立审查，不构成 native 重跑准入。Backend helper 的历史 stopped 投影缺少 tmpfs，保持 NOT_OBSERVED；runner stopped 已采集该字段且与 running 一致。现有测试环境和三个页面继续保留。

原件位于上述 runner-foundation-v1：`R1B-FRESH-INSTANCE-QUALIFICATION-v1/native-run-fresh-20261017-v1/`、`ROOT-R1B-FRESH-NATIVE-FAIL-STOP.json`、`SOL-R1B-FRESH-INSTANCE-FAILURE-ANALYSIS.json`。独立失败分析 SHA256 `92c94a066b44ea4a067b7a45b6234f4185174c8896c47db95695c7e183f78a68`；19 条原生命令和全部 raw 原件不覆盖。

保存原件上的观察合同随后完成源码/离线限定收口：已闭合有限 capability 等价与去重、准确阶段字段/类型、tmpfs token、卷读回绑定与挂载按 Destination 比较；停止投影不把 `RW=1/1.0` 当作布尔 true。v5/v6 的静态 HOLD 原件保留，v7 经独立 Sol→Root 仅 saved-contract PASS，source SHA256 `692d456cbd0ff853e0fadeec9dd18a86afeaa466c249d345afbe07c333c26785`，独审 SHA256 `a4bab4926c7d39d429577263238dc61ee766e7ed9f4f0f785d18baf77327dac9`。入口固定 `NOT_ADMITTED_SAVED_ONLY`；没有重新运行 Docker 或真实模型，没有新 native GO。原生资格 FAIL 与缺失项保持；私有收据 `ROOT-R1B-SAVED-CONTRACT-PASS.json`。

另：R2 的 global operations_audit 独立 proof + ACK-confirm、全部 reset 入口锁序/保留/安全投影方案仅通过有限设计审查，未实施。收据 `SOL-R2-RETAINED-PROOF-DESIGN-REVIEW.json` SHA256 `c825dbf762632798f97c5546eebaa51fd47c8a8ba8da90ab7f326206ebb632d6`；不能把此设计 GO 当作恢复资格。

以下保留接受之前的设计审计与当时状态，不覆盖本节接受记录。

前一项双用户普通对话及持久请求区间已限定 PASS。此片只审计与修订 Proposed ADR，没有新增模型、Job、容器操作或故障注入，不推进 Product Phase。

已通过的空闲重启、同公开会话新建子助手读取旧 SignalJob 结果继续有效。它没有证明：活动 runner 丢失、且来不及写 signed cleanup receipt 时，如何安全释放旧 Root。现有普通 Product 路径在缺证明时保留 fence；原 ADR-0104 尚为 Proposed，且“新 instance 不同”不足以证明旧进程已停止。不能先杀掉保留环境中的 runner 再猜测恢复方式。

本片将 [ADR-0104](../../architecture/adr/ADR-0104-acp-operator-process-fence-proof.md) 草案收敛到 ordinary Product：执行前固化 instance/准确容器与 scope 绑定、同一 state volume 排他锁及 consumed/tombstone；Engineering 以准确 native Docker 证据证明旧执行停止，复用私有一次性 CLI/受保护 audit seam。Backend 独立锁内重验 authority、完整 ingress/registration/claims；真正业务 unknown 仍阻塞。单独 operator interrupted 事实不能冒充旧 DSH EXIT、cleanup 或 native-close RPC；精确 ACK/proof/drain 闭合后，只能新建 native/子助手并只读已有结果，不重放旧任务。没有新增服务、HTTP/MCP 入口、调度框架或数据库表。

独立 Sol 设计 PASS：私有原件 `.ci-artifacts/agent-origin-consumer-20261015-v1/process-loss-admission-20261017-v1/SOL-ADR-0104-DESIGN-REVIEW.json`，SHA256 `e595f5207ca85805d46ff7685a00cdde90b0a2f35c7d8d9f29604c4cb2ce9b5d`；被审 ADR SHA256 `04357de411c4e42e761a6036090114d3faaaac24fd1aeb51d3c6f7a9455a9265`。Root 接受此限定设计审查，**不等于实现或故障操作授权**。

AGENTS.md 第15条及 Accepted ADR-0100/0113 要求维护者先接受这个具体例外合同。ADR 仍为 Proposed；实现、实际活动故障验证、进程丢失后的新子助手读取均 NOT_RUN。当前双用户隔离环境及三个页面继续保留。

## 重新准入：停止探针的两条只读采集（2026-10-17）

本节是前述失败之后的新证据。准确 HEAD `631f80b9ce0a39299b9c85a32bc00c3851922024`，未修改功能源码。独立 Sol 准入固定两条 stopped inspect；每条先独占保存 stdout/stderr、退出码和起止 UTC，再运行已审纯判定。非空 stderr、非零退出、超时、类型或语义不符立即停止，不派发后续工作。原19命令 FAIL 和所有静态 HOLD 保留。

实际两条原生命令均 exit0/stderr0，合计0.051秒，精确旧 helper/runner CID、停止状态和全部已采集字段匹配。runner 的挂载输出顺序实际变化，按准确 Destination 的完整对象比较通过；runner tmpfs 已观察且匹配，helper 原 stopped 投影缺少该字段，仍为 NOT_OBSERVED。独立 Sol→Root 仅 **stopped metadata 采集合同 PASS**，不是 fresh runner、START 或恢复资格。0资源变更、0模型/Job/DB/API/浏览器输入；没有重启旧探针。

私有原件位于 `R1B-FRESH-INSTANCE-QUALIFICATION-v1/native-stopped-readback-v1/`：计划 `PLAN-v2.json` SHA256 `6168f213e6f252a5d2f881f724c66dc436c88d6ecc311abe4ab6a1a7a335d6ef`，采集入口 `capture-classify-v2.py` SHA256 `a714acca95eaca5a542dbfb0fbaa38b3037c74c3493b50f319b84eac0d89b7eb`，实际结果 SHA256 `ed7e053334d278f56fcc6bcfd16c07f03d517d7330eb8c59b81583b0ed5c4fc0`，独审 SHA256 `2170411030564b2d760c2f529432c7ecd63e0067b2195a30342f29d1540d87bd`，`ROOT-PASS.json` SHA256 `4f8bc2472c1d777ec42cf836bac12c21895a61e963bd1c6cfc01c4f4beb4c4ed`。

下一片单独准入真正 fresh ACP runner：只补 ACP10文件、ready 后 PID namespace、签名出生/锁/noSTART；复用已通过的 Backend6文件证据。上限1新runner/3新卷/32原生命令/300秒，无 Backend helper、安装/激活、START、模型、Job或DB。当前尚未准入或创建资源，R2与活动故障/浏览器恢复均 NOT_RUN。原17容器和三个当前浏览器页签保留。

## Fresh ACP-only 原生片限定通过（2026-10-17）

上述下一片随后完成独立准入与一次实际执行。v1 命令顺序与固定 Workspace、v2 的清单计数缺陷均在执行前 HOLD，保留原件；10个镜像路径来自8个源文件，两个合同各复制到两个准确目的地，不能要求10个不同源路径。v3 复用原始 source/readback/capture 与纯判定，仅修正这些固定接缝；完整 `load_static()` 实际输入预检 exit0/stderr0，未访问 Docker 或凭据。随后 Sol→Root 只准入该冻结批次，未扩展通用工具。

实际 host exit0，18条原生命令全部 exit0/stderr0、无超时，15工作/3收尾、5.76秒。只新建1个无网络/只读 runner 和3个独立卷；ACP 镜像沿用 `sha256:5401edd1c741aab92021c8cf12621fc8941dab29c3fc09ae091b8959de9df8bd`，未重建镜像。镜像内10个准确路径、612793字节的 SHA/uid0/gid0/0444读回匹配；ready 后核对 PID1/PID namespace，签名 descriptor/instance/birth一致、require_prebind=true、lifetime lock忙、admission lock可取得，准确当前 started marker 缺席且 install/activation均无记录。停止本次准确 CID 后确认 exited/PID0/not running/not paused/not restarting，原17容器九字段及完整 Destination挂载图前后同基线。

源码仍 `8e80c0ce`，执行时 HEAD `29055725c2c14721dbcb878a7e30362c0cf754b9`。原件 `R1B-FRESH-ACP-ONLY-v3/`：计划 SHA256 `e2b8f433112b6f6dac106bfd91ece3dc108b32a644a9e0047089c375e28792b7`，固定入口 `fa5823d4f6b30a070436f570e99f4bb689b87342b895d1c168c768c8f6172062`，准入独审 `69396382d35ac59112e622c02df6fe967275d1ea6faafd1e92f8eaa9c6d55423`，实际结果 `6dcdb21771a594337cc03f87f41d04a6876840c49bd894e310a89599726e9b3d`，实际独审 `d8a0c1e89ea754c34b335b1150b1d088efa659b8f919bddfbef1890f556ffc9a`，`ROOT-PASS.json` 为 `62a83ed3629f16edc11fb1a530edf4e343c1592d6205d7d26a9d676066c13883`，包含全部 raw/exit/UTC摘要。stop stdout包含 Docker旧参数弃用提示，exit0/stderr0及准确停后状态另有原件，没有忽略失败。PLAN内历史 native-v2 标签不作执行依据，实际目录固定为 native-v3。

**Sol→Root 仅 fresh ACP 镜像读回/出生/noSTART PASS。** 原批 FAIL及静态HOLD不升级；Backend6实际读回证据复用，0新Backend helper、DB/API/模型/Job/START/浏览器输入。探针停后不称同instance接续；Backend prepare/install/activate、Runtime qualified admission/START/ACK、R2、活动 A 故障和浏览器恢复均 NOT_RUN。下一步只读核对现有私有 prebind CLI 的最小验证片，未经单独准入不操作。原测试环境、三个浏览器页签、草稿、全部卷/镜像及原探针保持；无生产、推送、合并或 Product Phase 推进。

## 停止并取消多余的 reader 采集（2026-10-17）

prebind 写入前须先确保现有 Backend reader 具备对应保护。工程侧为此另备两条只读采集，但入口错误复用了 fresh v3→v7 的生命周期 helper；其返回的新旧 plan 形状和局部变量发生混淆。静态审阅发现 KeyError 接缝后，唯一一次纯输入预检实际 exit1/NameError（`old` 与 `_old`），未进入 Batch/native。Root随即停止该入口及重试；原 stdout/stderr/exit 保留，未见第二次预检、native输出目录不存在。失败时入口SHA与UTC没有完整记录，明确 NOT_CAPTURED，不把事后hash或mtime当作失败时事实。另一次 Root 源配置审计使用普通 PyYAML 读取 Compose `!override` 标签失败，未取得DB同异结论，未重试或据此操作。这些均属工程审计入口缺陷，不是已证明的 Product 缺陷。

全面复核后不再修此入口或新增替代采集：已保存的 `explicit-revoke-fence-20261016-v1/exact-cancel-receipt-fix-v1/install-v1/RUNNING-READBACK-RESULT.json` 准确绑定当前 Backend CID `274826fbc7365f8bf794c00fff595dcc14ec5b3cb947f850aa648a808096de24`、IID `sha256:37434d44043a80e3aea448d28c4e66606887b546876e0971d06800efa74aea49`、源码 `7e5779f0` 及两关键 reader 的实际字节；Git语义确认缺少本轮 qualified v2 admission/active-anchor reader。fresh18又证明同CID/IID和无source挂载保持。无需再读第三文件来决定是否升级；这些证据只关闭“需要更新”的决策门，不声明泄漏或旧版安全PASS。

独立 Sol→Root 接受复用并取消整个额外 reader 采集。原件在 `R1B-PREBIND-QUALIFICATION-v1/READER-VERSION-READBACK-v1/`：`ROOT-FAIL-STOP.json`、`CAUSE-AND-MINIMAL-REDESIGN.md`、`EVIDENCE-REUSE-DECISION.json`（独审SHA256 `9736b335542430f3dfb776b95002941ad5a43b49b363efdcadc2e1847ee1de4e`）与 `ROOT-REUSE-DECISION.json`。失败、未执行的替代草稿和已通过的fresh18原件都保留。此后0新Docker/DB/API/模型/Job/START/浏览器输入，不重跑镜像/出生资格。

当前下一门：核对所有同逻辑DB reader，再对必要的隔离Backend更新给出准确命令、独审和Root操作准入；更新后才做候选source读回/新容器基线与私有prebind。不能拿一份候选helper镜像代替已部署reader，不能预先写入资格审计行。R2、活动故障和浏览器恢复仍 NOT_RUN；环境、页面、账号、数据库及卷均保持。


## 两条只读数据库身份采集通过（2026-10-17）

沿用隔离工作树，准确源码/文档起点 `c12dfc24d6d97e5623ddf27d86bf3bba42baf0ab`，未修改功能源码。保存配置无法证明保留的 base Backend 与当前页面的 F6 Backend 分库；因此先单独审查两条固定 CID 的只读身份查询，不重启服务、不复活已取消的 reader-source 采集。

独立 Sol 完整静审准入后，Root 各执行一次 `docker exec -i <exact CID> python3 -`，输入已冻结的26行 SQLAlchemy payload。只在容器内使用现有连接 URL，不输出/哈希凭据；PostgreSQL 启动选项强制默认只读、statement5秒/connect3秒，只选择当前库名及只读状态，不 import App/Store，不查询业务表或写入/DDL。驱动初始化可能包含其他元数据读取，不将总SQL数伪称为一条。每次独占持久化 raw stdout/stderr、native exit、UTC并fsync。第一条实际 Root 验收并保存标志后才派发第二条；总上限120秒、每个CID一次，错误停止且不重试。

实际两条 native/host均exit0、stderr0，strict JSON均为 `{"database":"byq_domain","read_only":true}`；各0.985774/0.941225秒，完整UTC跨度15.235307秒。独立 Sol→Root仅 **只读身份采集合同 PASS**。同库名只能要求将两者按潜在共享 reader 处理，不能声称已经证明同一服务器/完整拓扑；只更新F6不足以关闭共享reader门。第一PASS标志没有issuanceUTC，不冒充独立测得其创建时刻，实际派发顺序由Root执行记录及两个窗口支持。

私有证据 `runner-foundation-v1/R1B-DB-IDENTITY-v1/`：payload SHA256 `997efef49fc9c8e93c9fe1514d754ca53b787e531ccae800a805a566e21cb8b7`，实际结果 `17f77770a36bf3e535f7f86cbe6accc71adf139c93af42affcff4c5e91c20bd3`，Sol实际独审 `141ef42bd4b790b7ede27b6b3ef0da4a196397956db643e6e9644e9a52021d61`，Root PASS `79ea46917d9d534c3d50b8e1c93b84af1aa34f573e2f4cb23d9107127f023b89`。原FAIL/HOLD与fresh18限定PASS不变。0模型/Job/START/API/业务写入/资源变更。三个页面保持打开，只读观察当前B会话历史正常，不将它记为新的恢复测试PASS。

下一门为两处潜在共享 Backend reader 的准确隔离更新准入；正常Backend重启有现有Store schema bootstrap、管理员幂等检查及retention生命周期，不能将部署本身伪称只读或仅两条审计写入。私有prebind、R2、活动故障和浏览器恢复仍 NOT_RUN；当前未给服务更新或受保护审计写入GO。


## Backend 配置预览在静审阶段停止（2026-10-17）

两处潜在共享reader的更新准备没有进入实际操作。`R1B-BACKEND-UPDATE-v1/` 的完整独立Sol静审发现两个确定问题：采集入口切换到artifact目录，而继承的命令仍使用相对wrapper路径；其次原生调用超时/启动异常在追加安全调用摘要前抛出，导致该次尝试缺失。Sol收据SHA256 `7ac0b854074ca16f104f37c98d25e23249f5f88e15dae1d7f3c89129f0b3dadd`，Root以 `ROOT-HOLD.json` 接受HOLD。

这是验证入口准备缺陷，不能归因于Product。两项均在执行前发现：0预检、0配置预览原生调用、0服务更新、0模型/Job/故障。按维护者“同类问题再出现先停下来重新思考”的要求，停止该批次，保留v1，先统一核对命令实际工作目录/绝对入口及全部异常路径，实施最小源码修正后再独立审查；不扩大工具或测试范围，不重启已取消的reader-source采集。前述DB身份合同PASS及fresh18限定PASS不受影响。页面、账号和环境保持；活动故障/浏览器恢复仍NOT_RUN。


## 配置预览采集通过，端口比较 HOLD 原样保留（2026-10-17）

v1在静审阶段的两处入口缺陷修正后，v2完整独审通过；实际只运行一次三条只读配置命令，均native exit0/stderr0，无超时/启动失败，外层exit3/`HOLD_CONFIG_DIFFERENCE`。环境变量完整内存比较、命令/入口/用户/工作目录、挂载子集、健康、项目、重启策略与候选镜像均匹配；只有base端口比较为false。含凭据的原生配置stdout/stderr明确不保存、不哈希，只保留脱敏调用摘要，不冒充完整raw。

独立复核确认判据混用了新计划发布端口和旧 `HostConfig.PortBindings` 创建请求，不能从false声称实际发布端口漂移或猜测旧请求为0。Root停止该批次、不重跑或修补预览；复用同CID历史 `NetworkSettings.Ports` 的32769事实选择固定端口计划，由实际更新必要的即时before/post补当前发布事实。独立Sol实际审查 `90c7a2ff67f2bfaae4e42ea44f3e00a325604cb34f2ffb1bb6be816f29e37f49`；Root限定采集合同PASS，配置HOLD不改写。

## 两处隔离 Backend reader 更新通过（2026-10-17）

实际更新准备的v1完整静审拦住可选Health、完整Compose标签及替换后网络动态字段三处合同问题；v2又拦住人工复制的截断CID，均0操作命令。v3从冻结argv唯一权威纯生成五份字面shell并逐项验证全数组一致，不增加运行调度器、验证框架或测试套件。保留全部HOLD，不用实机或真实模型试观察器。原生Health通过安全index读取，缺席为null；两目标配置标签按实际24个-f输入精确匹配；网络固定NetworkID/名称及稳定别名，允许已声明的EndpointID/MAC/CID派生DNS变化。

条件Sol→Root准入后，实际7条命令全exit0，134.480346秒：即时原17基线全匹配、Runtime ready/active0/slot占用0，Root持久前提PASS后，仅 `backend`、`backend-f6` 使用已构建镜像 `sha256:ab83d14bd78c14d2c64cea44048861ebb9207ea37faab86166503fe3c3030c30` 正常重建，无build/pull/新凭据。即时数据确认旧base创建请求0、实际发布32769；替换后请求固定32769，实际仍127.0.0.1:32769。两目标健康、完整挂载/安全及资源设置保持，其余15容器所有采集字段保持。两新CID各6个实际源码路径、655149字节、SHA/uid0/gid0/0444及HTTP200通过，最终Runtime完整operations JSON与前值相同。没有发起Product输入、Job、START、私有prebind写入或故障操作。正常Backend启动的既有DDL/provision/retention不能声称只读；原数据库、卷、镜像及页面保留。

F6新CID `a6783f714f3a1df8b0db16a1349eb06d4fae245f1bbc1e9f149fe5a0b79b44e3`，base新CID `de34580c076d5aa55d0aa743dd8af8938e77a3937de5fc04ef8f5cfc4b740daf`。功能源仍 `8e80c0ceff799774da3923b74e298751e981ef33`，本片文档起点 `16e6d8af`。私有证据 `runner-foundation-v1/R1B-TWO-BACKEND-APPLY-v3/`：实际结果 `c2f1112faa3e5f3df37c80e817e2564972ff7efcd91469d6bd97a7e6610e4e4e`；Sol实际独审 `a6f2451a01780b4edc60d350f3ae46744fa4782f57f1355191b35c048e807f67`；Root限定更新PASS `a26b5af071e4b903e453c2b7b3ec415b0885c450df0e304f59bd0487272f656e`。由实际after原件派生的新17容器九字段基线SHA256 `ffa16d605a76f4d8b281ecbdf1fe47d392a041f7763532bc3367c3af79a91e51`，不是第二次测量；旧两个Backend CID后续不得再作当前目标。

边界：环境值后验未独立采集，复用完整预览匹配及相同冻结配置；一次过早读取进行中捕获的exit/end文件尚不存在，不作为原生命令重试或成功依据。实际Root前置断言均成功，但宿主文本未set-e的失败反事实未验证、不保证；后续依赖操作改为先独立验工具exit0再单独派发。未用重复执行改变这些边界。

## 更新后当前浏览器普通接续通过（2026-10-17）

更新Root PASS后，单独准入当前browser2/tab4的B原会话 `conversation_4e1a48c747ee422886e9783de1115453`：1次UI提交、2次刷新、120秒窗口。输入要求为不调用业务工具/子助手、不请求Job，只回复准确标记。实际准入至持久性观察84.114784秒；原2篇对话变4篇，新增用户消息及准确回复 `BYQ-BACKEND-UPDATE-20261017-可以继续。`，刷新后新旧助手回复各一次，回复出现后与刷新后完整DOM相同，B身份/会话与可用输入框正常。截图和DOM/facts保存，三个页签均标记保留；A和B新对话页面没有导航/输入。

证据 `runner-foundation-v1/BACKEND-UPDATE-BROWSER-v1/`：实际结果SHA256 `b8cd50b5c7e2eaa6b1bdb33fe97a4691127b0ced5d5baac8b7b9b8335932692b`，Sol独审 `684530c2765a0566a0df574df09342722b7745ce54f3d46c223b272d01a49e6b`，Root限定普通接续/持久性PASS `82ee8f760fa3b114d5331033fb9f7f43750b3f7746a0eacada5300685b75455f`。真实provider请求次数、原始HTTP状态未观察；未独立测量业务DB中Job实际零，不将“1次UI提交/无业务请求或界面步骤”冒充严格模型/DB计数。另保留页的当前输入为空，历史summary的123没有本轮before测量，故123保留NOT_PROVEN；未赋予清空原因或覆盖内容。

本片未推进Product Phase，未push/merge/生产部署。双Backend reader及当前普通浏览器兼容通过，不等于私有prepare/install/activate、Runtime qualified START/ACK、R2或活动进程故障恢复。下一片仅准备最小fresh-fixture私有prebind资格，不重复已合格镜像/出生/普通对话，不重启旧探针，不声称恢复原子Agent。测试环境和三个页面保持打开。
