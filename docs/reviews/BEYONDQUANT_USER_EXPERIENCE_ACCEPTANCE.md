# BeyondQuant 真实用户交互与量化体验专项验收

日期：2026-08-26（首轮）／2026-08-27（Phase 61 整改复验）

## 1. Executive Summary

首轮测试从普通投资者目标出发，而不是逐页重复 CRUD。共聚类出 14 个问题：P0 0、P1 3、
P2 8、P3 3。Phase 58–60 已关闭 4 项、部分改善 4 项；Phase 61 依据 ADR-0034 对剩余问题
做统一闭环。

首轮结论是：BeyondQuant 已具备真实、持久、可审计的量化功能，但尚不是普通用户可以自然
连续使用的产品。主要差距不是按钮失效，而是 Agent 数据口径分裂、长任务缺少可见控制、
策略/回测由内部对象主导、数据中心不能回答“这批数据能不能用于我的任务”，以及回测完成
后缺少自然下一步。

Phase 61 的目标不是新增功能数量，而是让这些已实现能力形成一个可信的普通用户闭环。整改
期间又发现 1 个 P0 运维安全问题、2 个 P1 问题和 2 个 P2 问题，
累计 19 项（P0 1、P1 5、P2 10、P3 3）。P0/P1/P2 已完成整改和对应层级复验；正式服务已
切换到全新恢复卷，原损坏卷与备份保留。BeyondQuant 现在具备普通用户可用的首版产品闭环，
剩余 P3 与策略自动执行等产品深化项不阻断本轮接受。

## 2. Environment

- Repository：`jefison-x/BeyondQuant`
- Phase 61 base：`origin/main`（Phase 60 merge 后同步建立 isolated worktree）
- Branch：`phase/61-user-experience-closure`
- Runtime：DeepSeek Harness SDK/runtime `0.1.1rc1`，npm `0.1.1-rc.1`
- Product URL：正式 `http://127.0.0.1`；隔离复验 `http://127.0.0.1:18081`
- Browser：真实 Chromium + Playwright request/response/Console/Trace；当前 Codex 未提供稳定 Chrome MCP 会话
- Data Provider：Tushare；普通 Agent/回测只读 BYQ PostgreSQL 已同步数据
- Workspace：`/home/jefison/projects/BeyondQuant/.byq-worktrees/phase61-user-experience-closure`

Phase 61 测试中发现 Compose 把 PostgreSQL 卷名固定为全局名称，临时测试项目不安全地与
运行环境共享卷。测试在执行用例前中止；该事件、恢复证据和后续防回归作为独立环境问题记录，
不能从产品验收中隐去。

## 3. Testing Tools

最终组合：

- 真实 Chrome/DevTools：探索式用户旅程、DOM、Console、Network、截图、Back/刷新/异步状态。
- Playwright：登录语义、固定路由上下文、页面状态与 same-origin 确定性回归。
- Vitest/Vue TypeScript build：展示 helper、登录字段、Workflow run-state 和页面编译。
- Backend/Gateway/MCP/Runtime contract tests：持久行情、readiness、trusted identity、tool path、
  skill budget 与无 Provider fallback。
- PostgreSQL 只读 SQL／逻辑 dump：抽查 Provider→DB→Product→Agent/Backtest 的实际证据。

没有把 Chrome MCP 历史记录当作当前环境证明。当前可用能力中，Playwright Chromium 能稳定
读取 DOM、点击/输入、监听 Console/Network/HTTP、处理弹窗/Loading、截图和保留失败 Trace，
因此作为真实浏览器主工具；API/SQL 只用于一致性旁证。没有使用 Mock 页面做最终接受结论。

## 4. Existing Test Coverage

以下能力已有稳定 Playwright、Product API、Backend/Gateway/MCP test 或真实 Chrome Evidence，
本轮只在自然旅程中 smoke，不机械重测：

- durable login、退出、owner/workspace isolation；
- 股票池、策略草稿/版本/审批基础 CRUD；
- signal snapshot、回测运行和八类结果；
- 模拟账户、订单、T+1、结算和风险控制；
- Model/Agent Policy/资产导入导出；
- 数据源凭据、连接测试、同步 job、自动同步；
- WorkflowTrace normalized projection、secret/raw DSH boundary；
- 两用户隔离、fresh Compose Phase 48 golden Product API journey。

已有覆盖的关键局限：Phase 48 的 Agent 只验证 turn accepted/replay，业务对象随后由 Product API
直接创建；过去不存在一条“Agent 研究→池→策略→审批→回测→Agent 优化→模拟操盘”的真实
连续模型旅程。

## 5. New Test Scope

- 连续自然对话与指代：价格、估值、基本面、候选股、策略、旧/新回测引用。
- 简单追问是否无必要地创建 ResearchTask/Experiment/Artifact。
- Agent 日线是否与估值、回测使用同一持久数据口径。
- 长模型运行期间阶段、已用时、停止与恢复。
- Strategy/Backtest/Data Center 的首次用户信息层级和术语。
- 回测结果到 Agent 分析、优化草案、再次回测和手工模拟操盘的上下文交接。
- 指定股票/日期/用途的 task readiness 与缺口下一步。
- 最近 N 个交易日的窗口起止、实际行数、最新日和结论截止日一致性。
- 失败恢复、数据不足、不存在股票和未同步区间。

## 6. User Journey Findings

### Journey 1：想法到回测

首轮能分别完成研究、建池、策略和回测，但 Agent 可能产生过多中间资产，策略页要求理解
Artifact，回测后缺少直接优化动作。Phase 61 将策略名称/说明/审批/下一步提升到首屏，内部
JSON/源码/ID 降级为技术详情；批准版本可直接进入预选回测。

### Journey 2：研究到模拟交易

模拟交易领域真实可用，但与回测没有自动策略执行关系。Phase 61 只携带已授权股票池上下文，
并明确提示“模拟账户独立、不会自动执行策略”。任何自动 signal→order 能力需要新的 Domain
ADR，不能用一个前端按钮伪装。

### Journey 3：失败恢复

数据不足时 Agent 已能拒绝填值并指向数据中心，但过去数据中心只显示全库 observed count。
Phase 61 新增按股票、日期和研究/回测用途的只读检查，返回可以使用／部分受限／暂不可用、
缺失数据类型、影响和同步下一步，不自动触发下载。

## 7. Quant Agent Findings

- Phase 58 关闭建池 403 和策略 422 重试风暴。
- Phase 59 关闭估值/基本面幻觉风险：exact-session、announcement-aware、缺失不填充。
- Phase 60 关闭英文内部前言、authorize/audit/raw coverage 的公共泄漏。
- Phase 61 将 `byq_market_daily` 从实时 Provider 请求迁移到
  `/v1/data/research/daily` 持久读取，保留 cutoff、完整性和缺失事实。
- Phase 61 DSH skill 明确三类意图预算：已有证据追问零写入；临时研究只做必要 read；只有
  用户明确要求保存/创建/比较持久资产或执行时才创建最少实体。
- “最近 N 个交易日”必须说明实际起止和行数、日期降序、最新列表日与结论截止日一致；不足
  N 行必须披露。

维护者明确授权有限公开 A 股行情和测试提示词发送至已配置 DeepSeek 后，真实连续 Agent 场景
完成。Agent 正确保留招商银行／兴业银行指代、披露数据截止日与实际行数，且简单追问前后
ResearchTask/Experiment/Artifact 数量不变。首轮模型回答暴露一个新的收益口径问题：文字将
“首日收盘→末日收盘”的箭头与“首日前收盘→末日收盘”的累计收益混用。规则修正后复验得到
招商银行五个交易时段累计 `+1.66%`、首末收盘变化 `38.86→39.80，+2.42%`；兴业银行分别为
`-0.16%` 与 `18.17→18.21，+0.22%`，结论与持久行情一致，无 Provider 实时调用或臆测。

## 8. UX / Interaction Findings

- Agent 长任务主界面显示当前公共阶段和真实已用时，不伪造 ETA；固定“停止本轮”采用 hard
  cancel 后恢复持久会话，避免 soft cancel 仍后台运行却宣称停止。
- Strategy 以名称、说明、状态、版本、审批、回测数和下一步为主，技术对象折叠保留。
- Backtest 指标统一为累计收益、基准收益、超额收益、最大回撤、成交笔数、被拦截交易、
  期末资产；Preflight 改为输入就绪检查。
- Login 增加 label/id/name、`autocomplete=username/current-password`、提交 busy 状态。
- 回测的 Agent draft 只预填并让用户审阅，不因导航自动提交模型或执行优化。

## 9. Data Sync Findings

全局 coverage 的 `observed` 不能证明任务可用。Phase 61 新接口复用 ADR-0028
MarketReadinessStore，以最新 Security Master、交易日历、生命周期、日线、停复牌、涨跌停、
复权、公司行动和声明数据评估任务。最多 20 个显式代码，结果最多公开 50 条问题，不把 raw
dataset token 暴露到普通 UI。

Agent 日线现在只接受 `data_source=tushare` 的持久行；readiness 的 bar/status 也对不可信来源
fail closed。这使“来源问题”与“回测却判 ready”的旧不一致收口。

真实抽查 `002737.SZ`：DB 与 MCP 的 `20260826` 收盘价均为 `13.22`，23 个交易日与 Product
readiness 的 23 required/ready sessions 一致，且 MCP 明确 `live_provider_called=false`。

## 10. Technical Browser Findings

真实浏览器复验持续记录：Console error/warning、HTTP 4xx/5xx、SSE、重复请求、Loading、刷新、
Back、路由 query 和 same-origin。P0/P1/重要 P2 必须保留截图、URL、时间和相关 session/job。

数据库环境事件：误启动的临时 PostgreSQL 在测试用例执行前被停止，但因共享卷并发导致原
WAL 检查点损坏。已经完成：

- 原卷完整只读归档：`/tmp/byq-postgres-pre-recovery-20260827T0817.tar.gz`，111MB，
  SHA-256 `c612497f7d80ab0854f688519ff98d7fb83c939decdf069924f94480637b9e02`；
- 独立恢复卷启动成功，业务库 `pg_dump -Fc` 成功；
- 逻辑备份：`/tmp/byq_domain_recovered_20260827.dump`，40MB，SHA-256
  `4f62aaf6a808f072b817322df19961cfa000bd118482c4239ebb0a7ba173828f`；
- 核心只读数量：127,326 日线、4 用户、34 会话、5 回测、8 模拟账户；
- 原损坏卷保持未重置 WAL，恢复副本只连接隔离测试网络。

维护者授权后，正式 `beyondquant` 项目已切换到全新恢复卷
`byq-postgres-production-recovered-20260827`；该卷声明为 external，避免 `down -v` 删除。
九个正式服务/worker 全部健康，原损坏卷 `byq_postgres_data` 未挂载、未重置、未删除。

另完成全新卷逻辑 restore drill，五项业务数量与恢复源一致；并确认 PostgreSQL dump 不包含
不可变回测结果对象。Domain 对象卷已另行只读归档（16KB，SHA-256
`e02bc60f8418c68757fb80d1afbef13ea9f75f7bc42d56c22f7f7d543c049285`），只读挂载后历史回测
result 从 503 恢复为 200。这是恢复集合边界，不是修改历史结果。

正式切换复验：前端 HTTP 200、Gateway health 200、Product Token health 200；无 Cookie 管理
请求由错误的 500 修正为 401。既有有效 admin 会话经正式 Frontend→Gateway 路径读取运维投影
200、历史回测结果 200；结果对象 SHA 与 DB 引用一致。真实 Chromium 打开数据库页无 Console
error 或 HTTP 5xx，证据见 `screenshots/07-production-recovery.png`。

## 11. Defect List

| ID | 类型 | 初始级别 | 首轮结果 | Phase 61 整改／复验状态 |
|---|---|---:|---|---|
| BQ-UX-001 | Agent Tool/股票池 | P1 | 创建池 403 | Phase 58 已关闭 |
| BQ-UX-002 | Agent Strategy | P1 | 同类 422 重复修复 | Phase 58 已关闭 |
| BQ-UX-003 | Quant/Data | P0 风险按 P1 管理 | 估值工具缺失，可能臆测 | Phase 59 已关闭，无填值 |
| BQ-UX-004 | UX/Agent projection | P2 | 内部英文/授权叙述泄漏 | Phase 60 已关闭 |
| BQ-UX-005 | Interaction | P2 | 长任务无耗时、停止隐藏 | 真实模型运行中阶段和耗时可见，已关闭 |
| BQ-UX-006 | Tool Calling/Product Design | P2 | 简单追问产生过多资产 | 真实连续场景资源 delta=0，已关闭 |
| BQ-UX-007 | UX/Strategy | P2 | Artifact/JSON/源码主导 | 真实浏览器关闭；技术详情默认折叠 |
| BQ-UX-008 | Data Sync UX | P2 | 问题计数不说明影响/下一步 | 真实数据与浏览器关闭；23/23 sessions usable |
| BQ-UX-009 | Data consistency | P1 | Agent 日线实时、回测持久 | 真实 DB→Backend→MCP 关闭，close=13.22 |
| BQ-UX-010 | Cross-workflow | P2 | 回测后无法自然分析/优化/模拟 | 真实浏览器关闭；四动作与 reviewable draft 通过 |
| BQ-UX-011 | Product Design/Data | P2 | 固定前 100，无任务查询 | 已提供 bounded 显式查询；股票池快捷选择留 P3 |
| BQ-UX-012 | UX/Terminology | P3 | 中英文和工程术语混杂 | 核心 Strategy/Backtest/Data/Agent 已收口，待扫描 |
| BQ-UX-013 | Accessibility/Login | P3 | 无 label/name/autocomplete | 单测关闭 |
| BQ-UX-014 | Quant communication | P3 | 最近窗口与最新日表达含混 | 真实模型披露起止、5 行和截止日，已关闭 |
| BQ-UX-015 | Functional/Asset Import | P2 | Browser JSON round-trip 把 `10.0` 写为 `10`，manifest digest 失配，真实资产导入 422 | 已使用带算法标识的数值语义 digest 修复；legacy 无标识 bundle 保持旧校验；Gateway suite + 真实浏览器关闭 |
| BQ-UX-016 | Interaction/Cross-workflow | P1 | 未批准策略的批准按钮在主题下白底白字，用户看不到进入回测的必要下一步 | 按钮改为可见次级动作；真实“批准→开始回测→预选对话框”关闭 |
| BQ-UX-017 | Quant Agent Bug | P1 | 模型把首末收盘箭头与首日前收盘口径的累计收益混用，数值标签会误导投资判断 | skill 明确两种公式和标签、禁止混用；静态契约和真实 DeepSeek 连续场景关闭 |
| BQ-UX-018 | Error Handling | P2 | 无 Cookie 访问管理员 Product API 时认证异常未映射，返回 HTTP 500 而非 401 | Gateway 增加统一 ProductAuthError 投影；Gateway 61 tests + 正式 API 401 复验关闭 |

新增环境问题：

| ID | 类型 | 级别 | 实际结果 | 建议修复方向 |
|---|---|---:|---|---|
| BQ-OPS-001 | Deployment/Data Safety | P0 | 多 Compose project 复用固定 PostgreSQL 卷名，可导致两个 postgres 进程并发挂载和 WAL 损坏 | project-scoped 默认、external 恢复卷、DB + Domain 联合备份/恢复演练和正式切换全部通过；原卷封存，已关闭。 |

## 12. Product-Level Findings

本轮多数问题不是“代码不能运行”，而是产品没有告诉用户发生了什么、数据能否使用、下一步
在哪里。关键设计原则已经固化：聚合状态不能替代任务 readiness；审计 ID 不能主导普通任务；
导航只携带受控上下文且不自动执行；Paper Trading 不伪装策略自动化；没有可靠 telemetry 时
只显示已用时，不显示虚假剩余时间。

## 13. Recommended Fix Order

1. P0：修复 Compose/PostgreSQL 卷隔离并完成业务库干净恢复、备份/恢复演练。
2. 数据可信：持久 Agent daily + readiness + source fail-closed。
3. Agent 连续性：长任务控制、工具预算、最近窗口规则。
4. 跨模块：Strategy/Backtest 下一步和上下文交接。
5. 术语、登录语义和次要可发现性。

## 14. Regression Automation Recommendations

- Backend：持久 daily 无 Provider call、missing/no-fill、source fail closed、readiness 三态。
- Gateway：trusted owner/workspace propagation、Browser spoof ignored、公开 label 无 raw token。
- MCP：`byq_market_daily` 只 POST persisted endpoint。
- Runtime/skill：回答/临时读取/持久资产三级预算和最近窗口规则。
- Frontend：run state、取消、Login autocomplete、Strategy 技术详情、Backtest context draft、
  Paper 手工边界、Data Center readiness。
- Playwright real Product：seed 真实 persisted resource 后验证四个深链、same-origin 和刷新/Back。
- Key-gated model evidence：简单追问资源 delta=0；完整黄金旅程不作为脆弱的无模型 CI。
- Deployment：任何临时 Compose project 若解析到已有非 external 数据卷必须在启动前失败。

## 15. Final Acceptance Assessment

首轮：不建议宣称“普通用户可用”，建议进入整改。

Phase 61 最终接受。已通过 Architecture 50、Backend 169、Gateway 61、MCP 全套与真实持久行情、
Runtime 34、Frontend 83/build、Mock Playwright 15、真实 Product 3 条，以及 Phase 61 浏览器 3 条
（其中一条为真实模型连续对话）。正式恢复后又通过九服务健康、业务数量、结果对象 SHA、
Product API、既有历史回测与真实 Chromium 管理页复验。

结论：BeyondQuant 已不只是“功能已经实现”，而是具备普通投资者可使用的首版量化研究产品
体验。仍建议进入下一轮 P3 优化和更完整的研究→策略→模拟执行产品设计，但这些不再是本轮
普通用户可用性的接受阻断。
