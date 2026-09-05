# DSH 0.1.2rc1 升级测试矩阵

状态：PLANNED。所有 T 编号目前均未据此完成新版认证。与[主方案](DSH_012RC1_UPGRADE_PLAN.md)共同使用。

## 1. 证据层次

| 层次 | 环境 | 能证明什么 | 不能代替什么 |
|---|---|---|---|
| L0 | 静态/纯函数/假 SDK | schema、生成、状态和边界规则 | 真实 DSH 插件/SDK 执行 |
| L1 | 发布 artifact 的真实 DSH + scripted provider + 测试 MCP | 启动、实际工具执行、通知、子 Agent、生命周期 | 真实模型是否遵守任务和正确选择工具 |
| L2 | 隔离完整 BYQ Compose + PostgreSQL/Worker + Product API/浏览器 | 权威业务状态、审批、结果、持久化、用户隔离 | 如果模型被 scripted 替换，不能宣称 live-model 通过 |
| L3 | 隔离 BYQ + 真实部署允许的模型/凭据 | 小巴真实编排、收尾、回答和关键回归 | 无法保证任意未来输入都成功 |
| L4 | 授权生产发布后的有界检查/观察 | 真实部署版本、依赖状态、生产回归表现 | 不替代发布前隔离测试 |

测试可以组合层次；报告必须明确具体用到哪一层。L0/L1/L2 进入 required keyless CI。
本次升级的 L3 是生产晋升门禁，独立于无密钥 CI；没有真实密钥时该项 BLOCKED，不能靠 mock 通过。
全部测试检查 release/image/profile identity，防止测到宿主旧 SDK、错误镜像或默认旧 composition。

## 2. 测试编号及必要断言

### 制品和版本权威（U1）

治理前置（ADR-0059）：先通过通用 CI 的风险分类、run-scoped 镜像、取消清理与实际执行 gate。
这些证据只证明 CI 可用，不替代下列 release identity、候选兼容性或真实模型资格。U1 复用现有
隔离 CI 并新增 release selector/attestation；不得重复改回固定 `beyondquant-*` 测试镜像。

| ID | 场景与必须断言 | 最低层次 |
|---|---|---|
| T01 | 官方 exact artifact 可下载且 hash/版本/平台一致；SDK 依赖配对；无 unknown release/自动 latest | L0 + 下载验证 |
| T02 | release schema 拒绝缺字段、非法路径、未知 carrier/compat；部署指针仅指已登记 release；不存在时失败 | L0 |
| T03 | 同输入生成两次结果逐字节一致；check 不写文件；手改生成物、锁或 profile 任一项立即失败 | L0 |
| T04 | 全依赖树不混 DSH prerelease；特意在嵌套 node_modules 植入混版必须失败；缺包/peer 冲突不可 force | L0 + 实际安装 |
| T05 | wheel/SBOM/lock/installed metadata 对应；Python `pip check`、npm peer 检查、审计有结果；不能只核对顶层版本 | L1 |
| T06 | registry qualified evidence 绑定 exact release/package/hash；不能复制旧版 qualified flag；未启用包不进入实际工具集合 | L0/L1 |
| T07 | 默认仍旧版；候选镜像/volume/network/port/DSH home 与生产隔离；错误镜像或 identity 不能显示 Active；所有退出路径零遗留测试资源 | L1/L2 |

T04 的 supporting Cordis 等包按审核后的 manifest 准确固定，不强求其版本号与 DSH 一样。
bundled executable 的内置组件需要官方构建 metadata/SBOM 或等效可验证证据；外部插件不能与内置服务混出两套实例。
安装阶段 `--ignore-scripts` 与必须的原生构建依赖不能含糊：需要脚本时逐项审核并固定，在隔离构建中运行。

### 网页证据 provenance（U2）

| ID | 场景与必须断言 | 最低层次 |
|---|---|---|
| T08 | 旧证据 read/list/export 与原 content hash 一致；旧合法 save 在旧版政策下正常 | L0/L2 |
| T09 | 新候选受控来源可保存相同 v1 业务格式；来源版本来自可信运行身份；未知/伪造/跨实例声明被拒；不能任选已认证版本冒充本次 producer | L0/L1/L2 |
| T10 | 旧/新 policy 的滚动兼容；旧 Runtime 与新 Backend/MCP 同用仍可写；撤回候选后历史证据仍可读 | L2 |
| T11 | future/unknown time、AUXILIARY-only、重复 source/query、secret/local URL、跨 owner 与 atomic save rollback 仍有效 | L0/L2 |

新来源版本的认证与启用分开。U2 只测试受控 candidate policy，正式来源注册在 U7 引入已验证的 identity。
不能因为“字段在白名单”就宣称已证明本轮实际执行插件；报告分别描述来源绑定与行为证据。

### 运行生命周期、私有活动与公开投影（U3/U4）

| ID | 场景与必须断言 | 最低层次 |
|---|---|---|
| T12 | SDK start/initialize/prompt/close 成功；构造参数确实由发布 SDK 接受，不能只 fake config；stdio 无普通日志污染 | L1 |
| T13 | 同 session 只允许一个 active prompt；同幂等键同内容返回原 run；不同内容拒绝；keyless 阶段就覆盖 running/completed 两种状态 | L0/L1 |
| T14 | root 连续合法 reasoning/step/text chunk 超过 quiet window，没有公共输出也不误杀；无 reasoning 正文进入公共事件 | L0/L1 |
| T15 | 完全静默达到 no-progress 上限，只有所属进程被关闭；另一用户 session 正常；公开终态说明真实失败 | L0/L1 |
| T16 | child 正在运行时使用 delegated 边界；child 结果返回后 root 可继续；child 超时只影响所属会话；重复 tool completion 不扰乱计时 | L0/L1 |
| T17 | 过期 private generation、无关 session、未知/畸形 notification、无意义 heartbeat 不延长本 run；可信 descendant 才计入 | L0/L1 |
| T18 | 持续活性仍受 whole-run 上限；900/180/120 默认不变；terminal 与 timeout 竞态只产生一次终态，迟到答案不复活会话 | L0/L1 |
| T19 | root text-only 最终回答可见；tool-call 混合文本、child 原文、raw args/results、reasoning、密钥不公开；schema 和 bounded output 不变 | L0/L1/L2 |
| T20 | error/unknown 结束不能映成 success；max-token 截断要按实际 SDK/DSH 策略测试；有答案但失败不得变成“任务完成” | L0/L1 |
| T21 | prompt receipt 前旧事件/旧 idle 不结束新 run；root/child attribution、queued message、重连、重复通知不丢/重放输出，用量不重复计数 | L0/L1 |
| T22 | soft/hard cancel、MCP 断连、SDK crash、startup failure、terminate/kill 都能 bounded cleanup；无僵尸、悬挂线程/订阅/等待队列 | L0/L1 |

L0 中用受控 monotonic clock/同步事件，禁止为了测超时每次真实等待 900 秒。
L1 可用测试配置缩短超时，必须另测 production 默认解析；缩短值不写正式配置。
不要删掉“迟到消息”测试以掩盖异步不确定性；用 barrier/可控 provider 构造先后顺序。

### 真实 profile、角色和安全边界（U4/U5）

| ID | 场景与必须断言 | 最低层次 |
|---|---|---|
| T23 | 实际已加载的根/child tool roster 与批准清单一致；Shell/editor/Git/任意代码/浏览器/DB/外部 Agent provider 不可见且不可执行 | L1 |
| T24 | 每个 `byq_delegate_*` 都能调用本角色允许的实际 `mcp__byq__*` 工具；不靠 YAML 字符串相似；跨角色动作被拒；maxDepth 与 foreground 生效 | L1/L2 |
| T25 | MCP 启动认证失败阻止正常初始化；不能绕过 MCP；owner/workspace/actor/approval header 不被模型参数或 browser header 覆盖 | L1/L2 |
| T26 | Guard/Compaction/Web 的实际 public hook 生效；web fetch 禁用；重复提醒不改业务结果；context 压缩后可收尾且不多执行 mutation | L1 |
| T27 | trusted time 每轮刷新，Asia/Shanghai 正确；自然日不当交易日；market context 使用 BYQ 数据；技能只从固定只读目录加载 | L0/L1/L3 |
| T28 | 生产允许模型协议 route 分别初始化/发出正确请求；不同用户凭据隔离；无效/缺凭据安全失败，不能回落到另一用户或意外 provider | L1/L2/L3 |
| T29 | 每个 session/generation 的 home 路径 contained；非法 ID/symlink 拒绝；不发现宿主插件/设置；无源码挂载；产品 runtime 没有在线安装路径 | L0/L1/L2 |
| T30 | 关闭 session 日志上传及未批准遥测；出站目的地符合实际 provider/MCP 需求；SDK stderr、报告、错误和公共响应均不含 sentinel secret | L1/L2 |

如果官方没有公开工具枚举 API，优先通过 scripted provider 接收到的工具 schema 加实际禁止调用证明。
可以在测试中插入只观测、不提供工具的探针；不得把探针或 raw tool list 作为新的 Product API。
测试过程可以读取合成消息，不采集/提交真实用户推理。

### 核心产品流程和发布（U5/U6/U7/U8）

| ID | 场景与必须断言 | 最低层次 |
|---|---|---|
| T31 | 正常回测分析先读 bounded summary，再按需少量 detail；六次预算耗尽为非工具错误的正常结束；不给浏览器加载 raw series | L1/L2/L3 |
| T32 | 单个 ML 请求只生成意图所需的一组对象；重试不额外创建四套研究；training/prediction/job ID 稳定；状态来自持久权威结果 | L1/L2/L3 |
| T33 | Agent 只到全局中心审批；批准回原对话且执行一次，拒绝不执行；resource/user/session 不匹配被拒；等待中重启与响应丢失可恢复 | L1/L2/L3 |
| T34 | 旧会话 idle release/restart → 新版 fresh generation → 有上下文的追问；最后未回答用户消息不重复回灌；稳定 BYQ ID 和序号不倒退 | L1/L2/L3 |
| T35 | 小巴搜索→显式保存研究证据；小巴反馈→预览→一次审批→内部提交；外部发布只用隔离 fake Hub/GitHub，绝不重复生产 Issue | L1/L2/L3 |
| T36 | 真实浏览器登录、桌面/移动小巴与审批/插件中心；只走 Product API；公开状态真实、无灰色假完成；列表仍服务端分页/懒加载 | L2 + Chrome MCP |
| T37 | 同模型/数据/配置旧新对比：启动/首次公开活动/答案时延、quiet failure、子任务收尾、CPU/RSS、日志磁盘增长；保留失败样本 | L1/L3 |
| T38 | admission/drain 竞态：门禁后新 turn 不启动、既有 SSE/回合能收尾；pending continuation 不丢；关闭维护后可续接 | L2 |
| T39 | 隔离完整 old→new→old 演练、备份恢复验证；新旧 private home 不相互改写；BYQ 数据/审批/作业与幂等性完整；无 mutation 自动重放 | L2 |
| T40 | 正式实际版本与候选一致、依赖服务健康、只读 smoke、观察窗口；确认无重复任务/静默失败/资源泄漏；回滚 receipt 可执行 | L4 |

## 3. 真实模型固定场景

U0 冻结输入，U5 用相同 fixture 运行旧/新版本。使用测试用户持有的小数据，不重下载历史市场数据。
隔离 fixture 必须明确标为 TEST，不把合成行情/模型指标展示为生产事实。

| 场景 | 输入意图 | 客观成功条件 |
|---|---|---|
| G1 | 询问今天日期并区分最近完整交易日 | 自然时钟正确；行情不足明确说明；没有无关领域写 |
| G2 | 分析已有小型回测，指出风险与证据不足 | 使用实际结果；分页有界；root 给出答案或明确原因；无训练/重跑 |
| G3 | 请求一项小型 ML 研究，审批后推进并查询进度 | 只创建必要对象；全局批准后续接；状态一致；不为了测试等待整个大型训练 |
| G4 | 公开背景搜索并保存来源 | 实际来源可追溯；持久证据保存成功或 provider 不可用时明确失败；不能虚构保存成功 |
| G5 | 完成首轮、释放进程、重新进入追问 | 能引用已完成公开上下文；无重复尾部提问或新建业务任务 |
| G6 | 在会话反馈一个测试问题，预览后批准 | 一次准确审批和一次内部反馈；外部边界连接 fake Hub，不发布真实 GitHub Issue |

每场景旧/新各先运行 1 次；G2/G3/G5 在预算内各增加 2 次，记录全部结果。
费用预算由维护者已有测试授权或 U0 指定限额约束；缺明确付费测试授权不自行大量调用。
预先固定最大场景次数/每 run 上限/总时间与 token 上限；工具执行失败不能无限复测。
真实模型回答不逐字匹配，以授权、对象数量、状态、证据来源、终态和上下文保持为判据。
不以“成功率大于某百分比”豁免任何重复 mutation、越权或泄漏失败。

## 4. 性能与运行资源门禁

- L1 相同固定输出场景每版本至少 10 次，记录每次耗时与 peak RSS；冷启动/暖进程分别计数。
- 参考阈值在 U0 基线后、候选结果前冻结：中位数时延不高于基线的 1.2 倍 + 1 秒，
  peak RSS 不高于基线的 1.2 倍 + 32 MiB；超出须定位并给出明确接受理由，否则阻止 promotion。
- 基线同机、同资源限额、同 fixture；构建/镜像拉取耗时不混入模型运行耗时。
- L3 样本少，不用其 p95 证明性能；记录 provider 抖动、model/token、错误分类，按成对场景比较。
- 连续 20 次 create/prompt/release 后无 owned 子进程/订阅残留，已释放 session 不无限增长；
  session 磁盘增长有解释，未采用 Spill 时也不能突然产生无界日志或上传。
- 候选评测时基础业务目录的首屏请求数量/响应体大小不得增加到全量；不混入新的前端性能重构。

## 5. 现有测试落点与命令

优先扩展现有测试，不复制另一套相同 suite：

- `tests/test_dsh_upgrade.py`：T01–T07；新增未来目录用于 release/报告/候选完整流程。
- `tests/test_dsh_plugin_registry.py`、`services/runtime-adapter/tests/test_plugin_identity.py`：资格与 identity。
- `services/runtime-adapter/tests/test_sdk_compatibility.py`：真实发布 SDK 接口；旧版私有 client 测试只算局部契约证据。
- `services/runtime-adapter/tests/test_process_cleanup.py`：T13–T18/T22/T34 的故障和幂等测试。
- `services/runtime-adapter/tests/test_normalization.py`、`test_sse_delivery.py`：T19–T21、事件投递。
- `services/backend/tests/test_web_research.py`、`test_web_research_api.py`：T08–T11。
- `services/backend/tests/test_agent_api.py`、`test_agent_research.py`、`test_ml_api.py`：审批/ML 权威状态。
- `services/gateway/tests/test_product_agent.py`、`test_plugin_center_projection.py`：续接、版本/公开投影。
- `services/mcp/tests/` 对应 contract suite：真实 Agent-to-Domain 注册名、预算、角色和 provenance。
- `apps/frontend/tests/e2e/real-product.spec.ts`：真实登录/领域/API；明确哪些用例含真实模型，不能混淆。
- `tests/smoke/run.sh`、`scripts/ci/local-ci.sh`：隔离 Compose、restart、two-user、cleanup。

从隔离 worktree 运行既有根目录检查：

```bash
python3 -m unittest discover -s tests/architecture -p 'test_*.py'
python3 -m unittest discover -s tests -p 'test_dsh_*.py'
python3 scripts/dsh/plugin_registry.py validate
python3 scripts/dsh/plugin_registry.py build --check
```

服务 suite 由修正后、明确 image identity 的 local-ci 运行。不要在生产容器中执行测试或安装候选依赖。
服务目录下 `python -m pytest -q` 只在该服务对应已安装依赖的隔离容器内执行，避免同名 `app` 包互相污染。
MCP `npm test` 需要编译及测试 Backend/MCP server，直接裸跑失败不等于版本不兼容；使用现有 CI 启动依赖。

## 6. 报告合同与失效规则

U5 生成的 JSON 报告至少包含：

```text
schema_version, release_id, baseline_release_id
git_commit, image_digest, artifact_hashes, composition_hash, policy_hash
started_at, finished_at, platform, provider_model_metadata_without_secrets
checks[]: id, layer, result, test_name, evidence_reference, failure_category
metrics: raw_sample_counts, timing_summary, peak_rss, cleanup_counts
capability_diff, dependency_diff, limitations, qualification_scope
```

结果枚举：PASS/FAIL/BLOCKED/NOT_RUN；不适用须写适用性理由，不能删行。
缺项、身份不一致、未完成清理均拒绝生成完整 QUALIFIED 结论。
报告必须携带 `qualification_scope`：keyless、preproduction、production-observed 分开。
发布前 scope 要求其适用 T01–T39，T40 保留 NOT_RUN 且不阻止发布前认证；生产观察完成后才允许 T40 PASS。
基础建置阶段只报告自身已运行项，不能因为未运行后续阶段而伪造通过或绕过阶段顺序。
报告不得包含 secret、原始生产对话、hidden reasoning、完整工具结果或本机敏感路径。
构建输入/锁/适配代码/profile/技能变动后，只复用可证明不受影响的证据；最终 promotion 必须关联最终构建。
文档更正可保留代码证据但重新做链接/身份引用检查；不要求对纯拼写变更重跑真实模型。
