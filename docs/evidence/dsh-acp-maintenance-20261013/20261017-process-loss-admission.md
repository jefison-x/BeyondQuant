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

以下保留接受之前的设计审计与当时状态，不覆盖本节接受记录。

前一项双用户普通对话及持久请求区间已限定 PASS。此片只审计与修订 Proposed ADR，没有新增模型、Job、容器操作或故障注入，不推进 Product Phase。

已通过的空闲重启、同公开会话新建子助手读取旧 SignalJob 结果继续有效。它没有证明：活动 runner 丢失、且来不及写 signed cleanup receipt 时，如何安全释放旧 Root。现有普通 Product 路径在缺证明时保留 fence；原 ADR-0104 尚为 Proposed，且“新 instance 不同”不足以证明旧进程已停止。不能先杀掉保留环境中的 runner 再猜测恢复方式。

本片将 [ADR-0104](../../architecture/adr/ADR-0104-acp-operator-process-fence-proof.md) 草案收敛到 ordinary Product：执行前固化 instance/准确容器与 scope 绑定、同一 state volume 排他锁及 consumed/tombstone；Engineering 以准确 native Docker 证据证明旧执行停止，复用私有一次性 CLI/受保护 audit seam。Backend 独立锁内重验 authority、完整 ingress/registration/claims；真正业务 unknown 仍阻塞。单独 operator interrupted 事实不能冒充旧 DSH EXIT、cleanup 或 native-close RPC；精确 ACK/proof/drain 闭合后，只能新建 native/子助手并只读已有结果，不重放旧任务。没有新增服务、HTTP/MCP 入口、调度框架或数据库表。

独立 Sol 设计 PASS：私有原件 `.ci-artifacts/agent-origin-consumer-20261015-v1/process-loss-admission-20261017-v1/SOL-ADR-0104-DESIGN-REVIEW.json`，SHA256 `e595f5207ca85805d46ff7685a00cdde90b0a2f35c7d8d9f29604c4cb2ce9b5d`；被审 ADR SHA256 `04357de411c4e42e761a6036090114d3faaaac24fd1aeb51d3c6f7a9455a9265`。Root 接受此限定设计审查，**不等于实现或故障操作授权**。

AGENTS.md 第15条及 Accepted ADR-0100/0113 要求维护者先接受这个具体例外合同。ADR 仍为 Proposed；实现、实际活动故障验证、进程丢失后的新子助手读取均 NOT_RUN。当前双用户隔离环境及三个页面继续保留。
