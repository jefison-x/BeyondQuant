# BYQ / DSH 0.1.2rc1 升级与可维护性改造执行方案

状态：**PLANNED / 尚未实施**。编写日期：2026-09-05。

原授权是编写详细方案；2026-09-05 后续授权仅增加治理/CI 整改及本方案校正，供后续模型执行。
本文不是已通过的升级认证，也不表示已部署；ADR-0059 不授权开始 U0。
目标准确固定为 Python `0.1.2rc1`、DSH npm `0.1.2-rc.1`、Git tag `dsh-v0.1.2-rc.1`；不得自行换成更新版本。
当前 Product 完成阶段保持 Phase 97。本工作使用独立维护阶段 U0–U8，不擅自占用 Phase 98 等 Product 编号。

## 1. 阅读入口与执行顺序

交接文档：

- 本文：范围、架构目标、逐阶段任务和验收。
- [测试矩阵](DSH_012RC1_TEST_MATRIX.md)：稳定测试编号、断言、测试层次和发布门禁。
- [发布与回滚方案](../operations/DSH_012RC1_ROLLOUT.md)：隔离、切换、数据保护和回滚。
- [执行交接与进度表](DSH_012RC1_EXECUTION.md)：模型启动提示词、完成记录和授权状态。
- [ADR-0058 提案](../architecture/adr/ADR-0058-dsh-release-bundles-and-compatibility.md)：尚待 U0 证据确认的架构决策。

开始任何实施前，完整阅读 `AGENTS.md`、`ARCHITECTURE.md`、`docs/DEVELOPMENT_WORKFLOW.md`、
`docs/roadmap/STATUS.md`、`docs/roadmap/IMPLEMENTATION_PLAN.md` 和本阶段相关 Accepted ADR。
核心 ADR：0003、0009、0015、0033、0037、0038、0039、0040、0046、0051、0059。
涉及模型凭据还读 0019；涉及 ML/Feedback 行为还读 0043/0048、0049/0052。
ADR-0058 在 U0 通过前保持 Proposed，不得在运行代码中提前实现未接受的边界变化。

每阶段一工作树、一分支、一 Draft PR；前一阶段验证、审查和合并完成后才开始下一阶段。
当前请求没有要求推送、合并或部署这份方案。后续用户明确要求按方案开发时，将该授权记录到执行表，
并按会话已有授权和 ADR-0015/0059 处理合并；不要重复询问已经明确授权的动作，也不要从“规划”推断生产部署。
治理整改必须先合并，才能以它为升级基线。U0 前只读运行 GitHub preflight；自动合并配置关闭、
required checks 不可验证时停在 Draft，由维护者处理平台门禁，不临时直接 merge。
具体载体/例外必须由维护者明确接受 ADR-0058；泛化升级实施授权不能接受尚未发现的新权限需求。
U7 部署属于独立获授权 trusted operator，不是 Engineering/Product Agent 的自主部署能力。

## 2. 已核实事实与尚未证明的结论

以下是 2026-09-05 的观察。U0 必须重新核对精确 release 的 metadata，并将文件 SHA-256、时间和源 URL 留档。
GitHub 源码是接口证据；部署是否可用仍须以发布 wheel/npm artifact 内的实际内容和运行结果证明。

| 编号 | 事实 | 对执行的影响 |
|---|---|---|
| F01 | 当前 SDK/runtime-bin 是 `0.1.1rc1`，显式 npm 闭包含 71 个 DSH 包及 7 个支撑包 | 旧版是行为基线；不要机械保持新版本包数仍为 78 |
| F02 | PyPI SDK/runtime-bin 均发布了 `0.1.2rc1`，SDK 精确依赖同版 runtime-bin | 配套 Python artifact 的历史阻碍已解除；wheel hash、平台、依赖仍需验证 |
| F03 | `dsh-sdk-jsonrpc-demo` 和 `dsh-agent-spine-demo` 没有 npm `0.1.2-rc.1` | 旧启动入口和核心组合不能只替换版本号 |
| F04 | 新 `DeepSeekHarnessConfig` 不再包含 BYQ 正使用的 `cordis`、`session_root`、`launch_args_override` | 原 `_new_harness` 参数组合直接用于新版会失败；需适配公开 API |
| F05 | 新配置包含 `dsh_bin`、`profile`、`patches`、`dsh_home`、`cwd`、`runtime_cwd` | 这些是候选接口，不是与旧字段逐个同义替换；必须核验路径、加载和存储语义 |
| F06 | `sdk-app` 采用 profile/patch 组合；默认继承 coding-oriented base | 官方启动器可复用，但默认启用能力不可直接继承 |
| F07 | `sdk-minimal` 默认有持久 Shell、编辑器及 danger-full-access，缺少多项 BYQ 所需能力 | “minimal”不等于符合 BYQ 权限；禁止原样采用 |
| F08 | 新版 `dsh-subagent` peer 要求 Cordis `^4.0.2`，当前 BYQ 固定 `4.0.1` | 支撑包也要重新求解并准确锁定 |
| F09 | 新版 SDK 按 inbox receipt 对齐本次输入，随后等 root idle；子 Agent 支持新的消息方式 | 必测迟到/旧 idle、排队、root/child 归属，不能仅测 initialize |
| F10 | MCP、Backend web evidence validator 和技能示例写死 `0.1.1-rc.1` | 启动通过仍可能保存证据失败；需独立解耦 |
| F11 | BYQ 看门狗已区分私有活性与公共进度，默认 900/180/120 秒 | 保留既有语义，新的事件翻译必须重新证明，不随升级放宽上限 |
| F12 | 现有 candidate 脚本复用旧包集合、固定旧支撑包，closure 检查主要面向顶层节点 | 不能宣称它已经支持包拆分、新启动器、嵌套混版或 bundled runtime 认证 |

主要上游证据：

- [官方 release](https://github.com/deepseek-ai/deepseek-harness/releases/tag/dsh-v0.1.2-rc.1)
- [SDK 精确版本 metadata](https://pypi.org/pypi/deepseek-harness-sdk/0.1.2rc1/json)
- [runtime-bin 精确版本 metadata](https://pypi.org/pypi/deepseek-harness-runtime-bin/0.1.2rc1/json)
- [JSON-RPC demo npm metadata](https://registry.npmjs.org/@deepseek-ai%2fdsh-sdk-jsonrpc-demo)
- [agent-spine demo npm metadata](https://registry.npmjs.org/@deepseek-ai%2fdsh-agent-spine-demo)
- [subagent 精确 metadata](https://registry.npmjs.org/@deepseek-ai%2fdsh-subagent/0.1.2-rc.1)
- [Python 高层 API](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.1.2-rc.1/python/sdk/src/deepseek_harness/api.py)
- [Python client](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.1.2-rc.1/python/sdk/src/deepseek_harness/client.py)
- [bundled runtime 解析](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.1.2-rc.1/python/sdk-runtime/src/deepseek_harness_runtime/__init__.py)
- [SDK app profile](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.1.2-rc.1/packages/bundle/sdk-app/README.md)
- [SDK minimal profile](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.1.2-rc.1/packages/bundle/sdk-minimal/README.md)

未证明：bundled executable 能否加载 BYQ 本地时间插件及独立 npm 插件、完整安全 profile 是否可构造、
新版实际 role tool roster、旧 JSONL 原地恢复兼容、原生 prompt cancel 在所选 SDK 通道的能力。
不得把 ACP 的取消能力当作 Python/JSON-RPC 已支持，也不得把 tag 源码的声明当作 wheel 实测。

## 3. 必须保持的产品和架构边界

1. Frontend → Gateway/Product API → Runtime Adapter → official DSH → BYQ MCP → Domain。
2. Runtime Adapter 独占 DSH SDK/raw event；Backend/MCP 不 import DSH、不运行 npm、不控制进程。
3. Product DSH 不获得源码、Git、Docker、任意执行、Shell、编辑器、数据库、Tushare 直连能力。
4. 业务策略代码仍是 Domain Artifact，量化计算仍在现有 Worker。
5. Agent approval、领域审批、任务执行及 continuation 各自保留现有权威状态；不得用 DSH approval 代替。
6. 公开对话仍为有界最终回答/WorkflowTrace；内部活性和推理内容不进入浏览器、持久公共历史或普通日志。
7. 现有模型路由、默认 HS300、分页预算的正常结束语义、单次合理 ML 创建、任务跟踪和公开失败原因保持。
8. 不启用新交互、Spill、后台持久子 Agent、自主选模型、Web fetch、Inspector 或遥测上传等额外能力。
9. 不复制/修改 Community；若涉及领域或 UI，先读对应历史分类并按规则补查只读实现。
10. 不建立第二 Agent harness，不 fork/patch DSH，不靠 `latest`、混版、`--force` 或关闭验证推进。

## 4. 目标结构与单一权威

以下路径均为**拟新增**，U1/U2 创建前不应运行引用它们的命令。

```text
config/dsh/
  deployment.json                  # 单一默认 release_id 指针；U7 才指向新版
  releases/<release-id>.json        # 不可变 release 描述（准确版本、入口、哈希）
  release.schema.json
  provenance-policy.json           # 已认证来源版本政策，与“当前启用”分离
services/runtime-adapter/app/compat/
  base.py                          # 小型内部接口/值对象
  dsh_011.py                       # 当前协议族
  dsh_012.py                       # 新协议族；U4 才增加
scripts/dsh/
  release.py                       # 工程端 inspect/generate/check/qualify 入口
  prepare_candidate.py             # 复用/重构已有准备能力，避免重复实现
  plugin_registry.py               # 保留现有 policy/assignment/composition builder
tests/dsh_upgrade/                 # 稳定场景、fixture、报告 schema
docs/evidence/dsh-012rc1/           # 分阶段证据索引；不保存原始秘密或生产日志
```

### 4.1 release 描述最小字段

冻结字段含义后在 U1 定稿 JSON Schema，不在文档中填假 hash：

| 字段 | 含义与约束 |
|---|---|
| `schema_version`, `release_id` | BYQ 清单版本、不可变身份；不等于上游 semver |
| `upstream_tag`, `upstream_commit` | tag 指向的验证后 commit；只属于证据，不硬编码进 STATUS |
| `python_sdk`, `python_runtime_bin` | exact version、artifact hash、平台标签、依赖约束 |
| `carrier` | `bundled` 或 `official-npm-cli`；公开入口、参数结构、Node/OS 要求、SDK transport |
| `compatibility_family` | 选择内部适配模块；不得按未知版本自动回退到“最接近”模块 |
| `dependency_lock`, `sbom` | 由可信构建生成的路径及内容 hash；校验完整依赖树 |
| `composition` | template/patch、profile、插件源文件及版本 hash；可执行配置只给工程/Agent Plane |
| `capability_policy` | 引用既有 registry/profile/agent assignment 及 hash；不另造权限权威 |
| `qualification_policy` | 所需测试集合/报告 schema/门禁版本；实际通过结果放独立认证记录，不写回构建输入 |
| `persistence_policy` | 固定采用 fresh private generation + BYQ public context；命名空间版本 |

不要把 image digest 嵌入它自己参与构建的 hash 环。构建输入 release hash 与构建后 deploy receipt 分开：
receipt 关联 Git revision、release hash、image digest、composition identity、证据报告 hash。
认证结果同样是构建后的独立 attestation，绑定这些输入身份；不能把最终报告 hash 写回 release descriptor，
否则导致镜像输入变化、认证证据循环失效。生产晋升引用已认证输入和 attestation，不重新生成不同内容的 release。

依赖 manifest 和安装后的实际 metadata 必须一致。健康信息不得由硬编码字符串自证版本。
启动验证失败时不能报告新 runtime Active；采用已初始化实例或有界启动验证，禁止每次 health probe 创建一套 DSH。
面向 Product 只投影允许的版本/状态/identity；不返回路径、raw config、事件或 secret。

### 4.2 控制版本扩散

- Python/npm 版本只在 release/lock/生成物、版本专属 fixture 和历史证据中允许具体值。
- 生产业务 validator 依赖 BYQ schema 和已认证 provenance 政策，不写死 DSH 某个版本。
- npm 缺包、包改名、peer 升级通过显式 manifest mapping 解决，不自动猜替代品。
- bundled runtime 若被选中，不继续安装第二套未使用运行载体；必要外部插件闭包仍须锁定并验证。
- 当前和回滚镜像是两个独立产物，不在同一 Python 进程安装两版 SDK。
- 兼容模块只适配已验证协议族；长期保留当前/上一已认证族即可，不建设无限多版本框架。

### 4.3 候选认证不能形成循环前置条件

正式 builder 继续拒绝未 QUALIFIED 插件。工程认证 runner 需要能在**隔离测试范围**装载已核验 artifact 的
candidate 组合，才能产生首次资格证据；U1 必须显式设计这个测试入口，而不是先伪造 QUALIFIED。
该入口限固定候选清单、已核验 hash、相同 capability ceiling 和测试凭据/资源，不接 Product 请求，
不改变默认 deployment，也不提供可用于正式启动的通用 `--skip-security/--skip-qualification` 开关。
同一候选输入通过测试后由独立 attestation 授予资格；正式 activation 再检查受控记录中的 release/image/policy 身份。
这里复用工程审查记录和内容完整性校验，本方案不额外要求建设 PKI/签名服务。

## 5. 阶段总表

| 阶段 | 交付物 | 默认 DSH | 可否发布准备代码 |
|---|---|---|---|
| U0 | 上游 artifact/接口清单、载体决策、Accepted ADR、基线场景 | 旧版 | 文档/测试证据，无生产切换 |
| U1 | 单一 release 清单、生成校验、隔离镜像/CI 选择 | 旧版 | 是，必须证明旧版行为不变 |
| U2 | web evidence provenance 解耦，兼容政策及历史测试 | 旧版 | 是，按依赖顺序发布兼容准备 |
| U3 | Adapter 内部兼容接口及旧版迁移 | 旧版 | 是，旧版完整回归通过后 |
| U4 | 新版载体/SDK/组合/事件候选适配 | 旧版 | 只合并候选支持，不切默认 |
| U5 | 自动认证、故障场景及真实模型评测 | 旧版 | 测试/工具；候选单独运行 |
| U6 | 发布前完整验收、恢复/回滚演练 | 旧版 | 仅生产就绪证据和运维工具 |
| U7 | promotion PR 与生产受控切换 | 新版，必须通过门禁 | 是，仅在部署授权覆盖时 |
| U8 | 观察窗口、升级流程复用演练、收尾 | 新版或已记录回滚 | 是，最终证据和后续入口 |

U0 的可行性结果允许终止新版迁移。不能为完成时间表绕过发现的安全/兼容阻碍。
U1–U3 可以交付维护收益；U4–U6 的候选支持合并不得使默认构建或自动部署意外升级 DSH。

## 6. U0 — 冻结证据、选载体、确认架构

建议分支：`docs/dsh-u0-compatibility-decision`。复杂度：高；不修改 Product runtime。

输入：全部交接文档、当前 ADR、现有 Upgrade Lane、精确上游 release。

步骤：

1. 同步 `origin/main`，检查 dirty worktree、部署目标及发布状态；记录动态 Git 基线至 evidence，不写进 STATUS。
2. 只读核实实际运行 SDK、镜像 identity、插件组合、900/180/120 与 MCP 分页配置；不输出完整 `.env` 或 inspect Env。
3. 读取官方 exact metadata，验证 SDK/runtime 版本关系、Python/Pydantic、Node、OS/CPU wheel 和制品可用性。
4. 列出当前每个实际加载插件 → 新版包/导出/配置/public hook 的映射，标记 SAME/MIGRATE/REMOVED/UNKNOWN。
   包集合中“安装但未启用”单独记录，不把 package presence 当作 Product capability。
5. 对旧 `cordis/session_root/launch_args_override` 分别查新版 profile/patch/home/launcher 语义；
   对 SDK receipt、subagent 结果、parent relation、tool roster、time context、shutdown 查 artifact 内实现和测试。
6. 使用临时独立 venv/容器做无真实模型密钥的可行性 spike；spike 不写默认配置、不进生产镜像。
7. 按下表选择一个载体，记录实际可复现启动命令、resolved profile、有效插件/工具集合及退出结果。
8. 收集旧版最小运行基线：启动、一次只读 MCP、root/child、长推理、结束失败、公开上下文恢复。
   必须标明 scripted provider、mock 和真实模型三种证据；没有运行的项写 NOT_RUN。
9. 在新 ADR 中确定载体、版本权威、provenance 信任、内部事件接口、fresh-generation 与部署隔离决策。
   获得实施授权且证据支持后记录 Accepted 原因；不得因为创建文件就直接标为 Accepted。
10. 更新执行表：U0 完成、Next=U1；STATUS 只登记已授权维护 lane，不改变 Phase 97 完成标记。

载体决策表：

| 优先级 | 路径 | 全部必须证明 |
|---|---|---|
| A | 官方匹配 wheel 的 bundled executable + public profile/patch | 可载入 BYQ 时间插件、MCP、skills、全部所需 role；禁用危险默认工具；可固定插件解析和依赖来源；无隐式 home/discovery；生命周期可控 |
| B | 官方 npm `dsh` CLI + exact closure + public profile/patch | A 不满足时使用；确认公开 CLI 存在并能被 SDK `dsh_bin` 正确启动；完整闭包锁定，不使用旧 demo bin、不造新 Agent loop |
| STOP | A/B 均不能提供当前能力及权限边界 | 留在旧版，报告最小阻碍；不自动采用 coding profile、私有参数、fork 或改用 ACP |

允许 A 失败后依据证据选择 B，不需把这一已规划选择重新抛给用户。改变权限、持久化承诺或目标版本则更新 ADR/范围。
`_launch_args`、`_proc` 等私有成员的生产依赖必须列入清单；优先公共 API，必要例外须明确 ADR 和 contract test。

输出：`docs/evidence/dsh-012rc1/u0/{UPSTREAM,COMPATIBILITY,CARRIER,BASELINE}.md`（实施时创建）。
完成门禁：F01–F12 已复核，UNKNOWN 阻碍有明确处理；所选载体的必要能力实际可行；ADR Accepted；文档/架构检查通过。
回滚：无生产变更；只清理 spike 自有资源，保留脱敏证据。

## 7. U1 — 集中版本与保证候选构建隔离

建议分支：`refactor/dsh-u1-release-manifest`。复杂度：中；依赖 U0 已合并。

允许修改：拟新增 `config/dsh/`、`scripts/dsh/release.py`、已有 candidate/registry 工具、
Runtime Dockerfile/依赖生成、CI 图像选择、readiness 的版本来源及直接相关 tests。
禁止修改：SDK 当前默认版本、业务逻辑、tool roster、事件语义、超时参数。

步骤：

1. 将当前实际旧版完整配置形成 release 描述；`deployment.json` 只引用旧版；所有 hash 来自真实文件。
2. 实现 schema/check，再实现 generate。生成 Python 依赖段、npm manifest/lock 引用及 composition identity；
   修改依赖声明只改拥有的字段/生成区块，保留 FastAPI 等应用依赖和用户无关改动。
3. `generate` 写候选输出；`check` 只比较、不写文件。两次生成结果相同；任何手工漂移导致 check 失败。
4. 修改 registry 校验中的旧版字面量为已选择 release 一致性检查；资格证据仍按 release/包/hash 单独匹配。
5. 重构 candidate 准备：基于批准的 carrier/插件映射求解，输出完整新增/删除/变更列表。
   检查嵌套 `node_modules`、所有 DSH 节点、peer 可满足性、平台 optional dependency、install-script 执行策略。
   Python 依赖也锁定/校验；不因 `pydantic>=2.12` 范围而让每次构建结果漂移。
6. 保留当前 exact 一致性要求；如上游发布方案要求非同号组件，先明确记录官方配套证据及 ADR，不能静默混用。
7. 构建后读取 installed metadata，核对 release/lock/profile；错配不得报 Active。前端测试断言版本来自安全响应，
   历史 fixture 可以保留旧具体版本，不能把所有断言都替换为过宽 regex。
8. 复用 ADR-0059 已建立的 run-scoped build/test 镜像路径；不要重复重写通用 CI。
   本阶段新增的是候选 release 选择、installed metadata 与 image/release attestation 绑定。
   通用 CI 的构建成功不等于候选资格通过，不能仅传 `--build` 就声称运行了指定 release。
9. 完整候选栈隔离 project、network、volume、端口、凭据及镜像；未知/缺少选择必须停止，不默默回落旧镜像。

验收：T01–T07；旧版 runtime suite、registry tests、架构/CI policy tests、旧版 initialize/MCP smoke。
涉及 compose/CI 的变更执行 Integration profile；镜像 build 和 test report 均包含相同 release identity。
退出：默认依赖仍旧版；旧版启动、实际 roster、公共结果保持；所有生成物 check 通过。
回滚：恢复上一代码/镜像；不触碰业务数据和会话卷。

## 8. U2 — 解除网页研究证据与 DSH 版本的绑定

建议分支：`refactor/dsh-u2-evidence-provenance`。复杂度：中；依赖 U1 已合并。

主要位置：`services/backend/app/web_research.py`、`services/mcp/src/server.ts`、
`plugins/dsh-byq/skills/byq-market-researcher/SKILL.md`、registry 的安全生成投影及对应 tests。
实施前读 ADR-0039 与 Community 原分类；这是现有证据契约维护，不新增研究功能。

步骤：

1. 先添加失败测试：旧证据可读且 hash 不变；新来源版本不因字面量被拒；未知/伪造来源不能被静默接受。
2. 保留持久 `web-research-evidence.v1`、source/claim/time/usage policy、atomic save 和现有 idempotency。
3. 将“当前 active 插件版本”和“历史已认证可识别来源版本”分离，生成只读、有限的 provenance policy。
   Backend/MCP 只加载该安全投影，不读 Cordis、不 import DSH，不接任意用户版本/URL。
4. 首选去掉模型构造内部 plugin version 的责任，由可信部署/MCP 上下文附加实际来源版本；
   若为兼容保留旧 command 字段，校验其与可信上下文一致，不能依赖模型声明作为执行证明。
   trusted context 来自 release/role 授权链，用户请求头不能覆盖；若新增 header，必须通过 MCP token/既有信任边界。
5. 容忍发布时旧/新运行版本并存：旧版合法写入与新候选写入各自带准确 provenance；旧历史证据不重写。
   新版未 QUALIFIED 前不能把它登记成正式可信来源；候选使用隔离环境的 candidate policy，U7 原子晋升。
6. 更新技能以使用稳定业务字段；删除“让模型猜运行时版本”的示例。MCP schema 与 Backend schema 做正反向一致性测试。
7. 保持 read/history/export 的 schema 兼容；domain schema 不因 DSH 升级而增加迁移。

验收：T08–T11，Backend web research/agent tests、MCP 完整 suite、Gateway 安全投影、真实旧版保存流程。
退出：旧版仍正常运行和保存；新版本支持仅在受控候选政策启用；历史 evidence identity 不变。
停止：需要降低 provenance 校验、修改 immutable 历史、扩大角色权限或不能证明 trusted producer identity。

## 9. U3 — 先在旧版提取兼容接口

建议分支：`refactor/dsh-u3-runtime-compatibility-seam`。复杂度：中高；依赖 U2 已合并。

主要位置：`services/runtime-adapter/app/{runtime,normalization}.py`、新增 `compat/`、Runtime tests。
保持当前 SDK/configuration/实际 DSH 版本，不同时引入新版适配。

内部接口最小职责：

- 创建使用公开 SDK 的 session-owned runtime handle；start/prompt/close 的实际行为可验证。
- 将一条原始 notification 转为内部有界 Observation：本回合归属、活性类别、规范化终态、
  允许公开的候选文本/领域活动、用量、可信 parent/child 关系。
- 只在 Adapter 内存在该结构；不得为了抽象新增跨服务 DSH 中间协议或通用工具路由器。
- 事件只解析一次；public projector、watchdog、usage 各取允许字段；内部 Observation 不持久化推理正文。

步骤：

1. 先用旧版 fixture 锁定现有公开输出与私有活动行为，包括 child active、unknown/error 结束和 response loss。
2. 将 raw schema、SDK configuration、私有访问（如有）集中到 `dsh_011.py`，逐项迁移，不重写整个 runtime.py。
3. RuntimeAdapter 继续持有线程/锁、单活跃 prompt、run idempotency、owned-process cleanup、超时边界。
4. 新的 Observation 按当前 run/private generation/已验证 lineage 归属；晚到消息不能延长下一回合生命周期。
5. 不修改 900/180/120，不恢复“只看公开进度”的算法，不把任意 heartbeat/未知 event 当活性。
6. Gateway/Frontend public contracts 保持；必要 mock 调整必须对应真实 SDK adapter contract，不能只改 FakeHarness 让测试通过。

验收：T12–T22；Runtime 完整 suite、Gateway 相关完整 suite、旧版真实进程 smoke。
退出：旧版行为与 U0 基线一致；DSH import/raw parsing 只存在于 Adapter 的允许模块；所有进程能收口。
停止：需要新调度器、绕过 DSH 结果交付、无界缓存或更改业务审批 state machine。

## 10. U4 — 新版候选载体、插件组合与 SDK 适配

建议分支：`feat/dsh-u4-012rc1-candidate`。复杂度：最高；依赖 U3 已合并，U0 载体方案未失效。

主要位置：candidate release/locks、`compat/dsh_012.py`、版本化 profile/patch/templates、
BYQ 本地 time plugin 的兼容部分、Runtime Dockerfile 的 candidate build 入口及对应 tests。
默认 deployment 指针和默认 compose 行为仍旧版。

严格按序执行，每步通过再继续：

1. 用 U1 工具生成候选 artifact/lock/SBOM，验证所选载体、平台、SDK 参数存在；运行 `pip check` 和 npm peer/audit。
2. 用公开 `dsh_bin/profile/patches/dsh_home/cwd/runtime_cwd` 构建 SDK config；参数值来自受控配置。
   不将 `cordis` 文件直接当 patch 文件，不把旧 session root 原样充当新版 DSH home，不用 `_launch_args` 偷渡旧入口。
3. 确定新 home 下 profile/settings/persistence 和模块解析路径；只读 profile 与可写 Agent 数据分开。
   运行时 UID/权限、contained path、symlink escape、并发 session home 不冲突；不扫描宿主 `.dsh`/项目插件。
4. 生成最小 BYQ 所需组合。移除旧 demo/spine 行必须补齐其原来提供的安全核心服务，并用实际 initialize 证明。
   不原样复制 sdk/sdk-minimal。对所有生效 tools、providers、MCP servers、subagent targets 做实际清单比对。
5. 验证 BYQ time plugin 使用的 public hook；每轮时间动态刷新。Guard/Compaction/Web 必须重新资格验证，
   `verify-qualified-plugins.mjs` 的旧导出断言应由对应真实新行为替代，不能删除测试绕过。
6. 实际检查每个 delegate 的 toolName、persona、foreground 模式、maxDepth、provider capability、toolFilter。
   保留当前五个 `byq_delegate_*` 名称和 BYQ role ceiling；禁止后台持续 child 和新的外部 Agent provider。
7. 精确适配新版 root/child/inbox/turn/step/assistant/tool/usage 结构。旧 idle、receipt 前事件、重复输出、
   child-only failure、max-token/unknown terminal 均按测试矩阵处理；不能把 SDK `final_response` 绕过公开过滤直接转发。
8. 测试进程启动失败、MCP auth/startup failure、无凭据、LLM 失败、shutdown/terminate/kill 与取消。
   新版有原生 cancel 也先保留旧 BYQ policy；如需采用，另作已接受的语义变更与测试，不顺手开启。
9. 保持 ADR-0046 的 fresh generation/public context。新版本获得 native resume 不构成本阶段采用理由。
10. 测试所有当前部署允许的 provider 协议与 credential resolution；缺真实凭据的 route 仍需 deterministic 协议覆盖。
    不将 Responses/Chat/Messages 路由混为一种，不擅改模型档案或默认模型。
11. 明确关闭新 session 日志上传；对默认插件版本上报等遥测行为作显式配置与出站测试，按 U0 ADR 决策执行。
12. 构建 candidate immutable image，旧版和新版分别在独立进程/容器跑同一 suite；记录 installed metadata。

验收：T01–T30 中 Runtime 相关项；新版 package/startup/roster/SDK/lifecycle/normalization/MCP 真实进程测试通过。
退出：候选可运行而默认仍旧版；没有权限扩张、公开事件变更和假 qualified flag。
停止：真实 root/child 归属不可证明、bundle 不能禁止危险工具、必须 patch DSH、SDK 活性不能可靠观察。

## 11. U5 — 自动认证与小巴故障回归

建议分支：`test/dsh-u5-qualification-journeys`。复杂度：高；依赖 U4 已合并。

主要位置：`tests/dsh_upgrade/`、已有 runtime/MCP/Gateway/Backend tests、
`scripts/dsh/release.py` qualify/report、CI change classifier/isolated runner；按需扩展现有 browser journeys。

步骤：

1. 按测试矩阵实现稳定 T 编号，不以文件存在或测试数量充当完成；每项关联真实测试名称和证据。
2. 增加仅测试用 scripted provider，用真实 DSH SDK/插件/MCP 调用走稳定场景。
   它是测试 fixture，不是新的生产 LLM gateway，也不替代真实模型评测。
3. 给现有发生过的问题构造回归：连续推理无公开输出、child 晚到、六次分页耗尽正常返回、
   repeated ML create、approval response loss/restart、web save、idle release 后追问。
4. 报告清楚区分 mock、real-process/scripted-provider、真实 Product API/worker、live-model。
   required keyless CI 不依赖真实密钥；本次生产升级必须有额外 credentialed 报告，缺凭据不可伪报通过。
5. 选实际生产默认 provider/model 和至少一个已启用不同协议 route 做真实 smoke（没有第二 route 就如实注明）。
   使用专门测试用户、最小固定数据与有限费用/总时间预算，provider secret 只经既有凭据链注入，不进入日志/fixture。
6. 同一 fixture、模型和参数分别运行旧/新版本；以任务状态、数量、授权、结束和证据一致性判定，
   不比较回答逐字一致。首次失败保留诊断，最多一次有理由的复测，不反复重跑挑一个成功结果。
7. `qualify` 输出结构化报告，包含每个 T 的 PASS/FAIL/BLOCKED/NOT_RUN、release/image/git identity、
   依赖与 capability diff、耗时/资源统计、cleanup 结果；不能将缺项默认 PASS。
8. CI 对 release/compat/profile/lock/time-plugin 的改动触发 Runtime/MCP/Gateway/相关 Backend 和 Integration。
   新增流程复用现有 resource scope、heavy lock、memory preflight、always cleanup，确保候选镜像实际被测试。

验收：T01–T37 中全部适用项；旧/新比较报告、live-model 报告、全链路 Product API、无密钥 CI 通过。
T38/T39 属于 U6 演练，T40 属于 U7/U8 实际生产，必须在报告中保留 NOT_RUN，不能作为 U5 循环前置条件。
退出：允许将 candidate 标记工程认证通过；尚不宣称生产已升级或观察完成。

## 12. U6 — 发布前验收与回滚演练

建议分支：`ops/dsh-u6-rollout-rehearsal`。复杂度：中高；依赖 U5 已合并。

步骤：

1. 按发布文档实现最小 operator 工具/手册；Product 页面不增加部署按钮。
2. 验证隔离新栈完整用户流程；涉及 UI/公开体验必须完成 Chrome MCP review 与现有 Community checklist。
3. 用旧版生成测试会话和审批，再切新版，完成 reopen/follow-up、pending approval 续接；
   再切回上一已验证旧 runtime，证明对话与领域对象可用，重复点击/响应丢失不新增重复执行。
4. 验证 fresh generation 的版本命名空间，旧/新不会同时写同一 home；不承诺恢复 hidden state。
5. 演练服务排空/停止接受新 turn：先识别现有可用入口；如不存在，实施并测试最小运维 admission gate，
   或使用有界聊天维护窗口。不得只查一次 active=0 就假定下一刻不会有新请求。
6. 新 turn 拒绝不能丢用户输入；approval continuation 应保留待续接状态；pending approval 不要求用户全部批准后才能部署。
7. 按测试矩阵记录资源/耗时；若新版明显退化，先定位 dependency/组合/事件问题，不能删功能换速度。
8. 冻结 promotion candidate 的 Git、release、镜像及 profile hash；生成 readiness/rollback checklist。
   gate 完成后有代码/配置/锁变化，受影响证据失效并重跑，不无限重复无变化测试。

退出：T01–T39 的适用发布前门禁通过；BACKUP/RESTORE/ROLLBACK/CHROME/LIVE_MODEL 证据齐全；候选可发布。
T40 此时明确 NOT_RUN，只有 U7/U8 能执行；不能要求“先生产通过才允许首次发布”。
回滚：仅隔离演练栈；正式环境尚未升级。

## 13. U7 — 默认版本晋升与正式切换

建议分支：`chore/dsh-u7-promote-012rc1`。复杂度：操作风险高，代码量应小。

前置：U6 已合并；部署授权明确且仍有效；精确 promotion 内容与已认证候选一致。

1. 将 `deployment.json` 默认指向已认证新版；同步由其生成的生产 manifests/composition/registry 资格和 provenance policy。
2. 更新当前兼容矩阵/Upgrade Lane/readiness 预期，旧 evidence 保留历史标识；不机械改写过去所有版本记录。
3. 检查后端镜像内 registry、MCP provenance 投影、Runtime profile 和插件中心 active identity 的整体一致性。
   它们可能需要协调部署；不能笼统承诺本次仅重启 Runtime。
4. promotion PR 对最终 diff 跑 required CI，并执行指定 candidate 实际构建/身份复核；不得在 PR 里顺手修新功能。
   “候选/已认证”状态放外部 attestation；只改变部署选择时可复用同一镜像。若晋升时生成的 policy/profile
   内容或打包镜像改变，必须先验证新 hash 对应的制品，不能把旧候选的通过记录贴到新镜像上。
5. 按 runbook 保存当前镜像、配置、会话备份，验证可恢复；部署准备版本，再阻止新 turn、等待活动执行收口。
6. 仅重建/切换本次变更的服务，使用 `--no-deps`；正式 PostgreSQL 与 ML/行情 Worker 不因 runtime 升级重启。
7. 核对实际 SDK/载体/image/profile identity；执行无副作用生产 smoke 和已有真实用户会话的有界恢复检查。
8. 如出现发布文档红线，按既定旧版镜像和兼容准备版本回滚，保留故障证据，不尝试自动重放 mutation。

退出：目标版本真实在生产运行、依赖服务健康、关键行为 smoke 通过、回滚可用；进入 U8 观察。
若部署失败且已回滚，记录 U7 ROLLED_BACK，不能标记整个升级完成。

## 14. U8 — 观察、复用演练与收尾

建议分支：`docs/dsh-u8-qualification-closeout`；必要工具小修可同阶段，禁止扩展新 DSH 功能。

1. 观察至少一个正常使用周期（目标 24 小时，真实流量不足时明确样本不足）；发布后先做 30 分钟初检。
   不用单次长 sleep 代替监控；报告生产切换完成与观察完成两个独立状态。
2. 比较超时原因、失败回合、未终止 child、重复任务、continuation backlog、错误 profile、CPU/RSS 与磁盘增量。
3. 核查完整升级结果与实际用户反馈；原始生产日志只在受控环境诊断，证据提交摘要。
4. 对同一已认证 release 做一次 dry-run 重生成/复验：零人工版本字符串修改、无运行代码 diff、旧/新可精确定位。
   不通过虚构 `0.1.2rc2` 或冒充未来版本来证明自动升级能力。
5. 更新 Upgrade Lane 为日常流程：观察 → 分类 → 候选 → 验证 → PR → 授权部署 → 观察。
   定期发现可复用既有 CI/manual dispatch；自动向 GitHub 写 PR/Issue 或新增定时任务须有相应授权。
6. 维护当前和上一已认证 release，清理仅本任务拥有的临时资源；回滚镜像/备份按明确保留期处理，不自动删除。

最终完成：全部门禁和观察达到要求；STATUS 仍保留正确 Product Phase，记录维护 lane COMPLETE、运行版和回滚基线。

## 15. 执行命令的使用约定

以下**当前已存在**，在各自隔离 worktree 根目录运行：

```bash
git status --short
git rev-parse origin/main
python3 scripts/ci/check-docs.py --base origin/main
python3 -m unittest discover -s tests/architecture -p 'test_*.py'
python3 -m unittest discover -s tests -p 'test_dsh_*.py'
python3 scripts/dsh/plugin_registry.py validate
python3 scripts/dsh/plugin_registry.py build --check
git diff --check
scripts/ci/local-ci.sh --base=origin/main --with-e2e --auto-smoke --plan-only
```

按阶段选择实际检查；需要依赖先按 lock 安装，不以缺依赖跳过 gate。
治理整改后的 local-ci 默认构建本次 run-scoped 镜像，构建失败停止且不复用正式 tag。
但它仍测试当前 checkout 的默认 release；U1 必须增加明确候选选择和认证身份，不能把普通 CI 当新版认证。
候选参数名与具体调用在 U1 evidence 定稿；禁止提前使用尚未实现的参数。

当前全量 CI 入口（U1 后先核对镜像选择，再运行）：

```bash
scripts/ci/local-ci.sh --base=origin/main --all --build --with-e2e --with-smoke
```

以下为**U1/U5 待实现的 CLI 合同**，不是现在可执行的工具；实现后必须提供 `--help` 和失败测试：

```text
python3 scripts/dsh/release.py inspect --release <exact-release-id> --output <new-directory>
python3 scripts/dsh/release.py generate --release <exact-release-id> --output <new-directory>
python3 scripts/dsh/release.py check --release <exact-release-id>
python3 scripts/dsh/release.py qualify --release <exact-release-id> --baseline <qualified-release-id> --output <new-directory>
```

`inspect` 读取已登记目标，不接受任意执行 URL；网络失败与版本不存在分开报告。
`qualify` 不执行生产部署、不修改默认指针；缺真实模型证据时只能报告 keyless-qualified。
未知 release、非空输出目录、任意 source、哈希错配、平台不支持或 cleanup 失败都返回非零。

## 16. 常见错误与明确禁止的捷径

| 错误做法 | 正确处理 |
|---|---|
| 全仓替换 `0.1.1` 为 `0.1.2` | 通过 release 生成，仅修改当前配置与对应测试；保留历史记录 |
| 把 sdk-minimal 当安全最小组合 | 从实际 enabled capabilities 验证，默认 Shell/editor 不允许 |
| 将新版配置 `dsh_home` 当旧 `session_root` 的别名 | 分离配置与数据、逐 session/generation 验证路径和写入 |
| 复用旧 npm package 名单或强制 peer 安装 | 依 artifact 映射新增/删除，重新锁定并检查全树 |
| 候选支持合并就让默认镜像升级 | U7 前默认 release 保持旧版；CI 分开测默认和候选 |
| initialize/healthz 通过就 qualified | 实际 MCP、child、tool roster、turn 和用户流程都需通过 |
| 将 SDK 响应/未知事件直接公开或当活性 | 内部归属校验、allowlist 和安全终态，不读推理含义 |
| 增大 timeout 或取消分页限制解决不结束 | 检查事件/结果/预算正常结束语义，保留现有上限 |
| 把旧 JSONL 喂给新版再要求旧版接着读 | 默认 fresh generation；先隔离演练，保留 BYQ durable context |
| 丢响应就重试创建 ML/审批/回测 | 先读 BYQ 权威对象，使用原幂等键，不自动重放副作用 |
| 重建全栈来“确保更新” | 精确服务/镜像部署，PostgreSQL/Worker 保持独立 |
| 用真实生产用户数据做候选重放 | 使用专用测试用户、最小隔离 fixture；不重复提交生产任务 |
| 缺密钥/浏览器/上游 artifact 就写 PASS | 明确 BLOCKED/NOT_RUN，继续可独立完成的工作 |

## 17. 最终验收目标

- 本次 0.1.2rc1 真实模型、业务链路、生产切换和观察完成，或诚实记录阻碍/回滚。
- 下一次无协议变化的普通升级只改 release/生成配置与资格证据，不改 Backend 业务逻辑、MCP 业务格式或 Vue 页面。
- 有破坏性变化时可定位到 carrier/compat/profile；有稳定失败测试，无权限放宽和隐式降级。
- 保留准确锁定、可重复构建、真实运行身份、已演练回滚和旧证据可读性。
- 不承诺未来 DSH 任意版本“自动兼容”；减少重复劳动，保留实际变化所需的判断。
