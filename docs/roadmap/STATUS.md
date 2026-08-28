# BeyondQuant 状态

<!-- byq:current-completed-phase=63 -->

本文档是 Phase 状态的事实来源。它有意保持精炼，使新的 Codex session 不会从 commit
history 推断项目状态。

- 当前已完成阶段：**Phase 63**——建立受控的 DSH Plugin Registry、qualification gate、
  Agent capability mapping、确定性 Composition Builder 与 runtime identity；五类 official
  sample 均得到有证据的 QUALIFIED/ENABLED 或 BLOCKED 结论。
- 发布状态：**Beta**。维护者于 2026-08-25 明确授权顺序开发 Phase，并依据 ADR-0015
  对 CI-green PR 执行 auto-merge；该授权不包含 release candidate、tag、production
  publication 或正式发布。独立的 post-Phase 40 DSH Upgrade Lane 已将 Product Runtime
  验证到 Python `0.1.1rc1` / npm `0.1.1-rc.1`；它是维护历史，不是隐含的 Product Phase。
- 当前完成范围内没有未决架构决策。
- Phase 61 由维护者于 2026-08-27 授权并完成；规范与证据位于 ADR-0034、验收报告和
  `docs/evidence/phase-61/`。

## 生效中的 Accepted ADR

- Runtime：**ADR-0003**
- Phase 7 authentication：**ADR-0004**
- Phase 8 data provider：**ADR-0005**
- Phase 9 research entity：**ADR-0006**
- Phase 11 strategy Artifact：**ADR-0007**
- Phase 12 Backtest worker：**ADR-0008**
- Phase 13 quant research Agent：**ADR-0009**
- Phase 14 Quant Learning Loop：**ADR-0010**
- Phase 15 Engineering Plane：**ADR-0011**
- Phase 16 Product API：**ADR-0012**
- Phase 16 durable market-data storage：**ADR-0013**
- Phase 24 user authentication：**ADR-0014**
- v1.0 前 auto-merge：**ADR-0015**
- PostgreSQL single-domain-store：**ADR-0016**
- signal snapshot：**ADR-0017**
- WorkflowTrace structured card：**ADR-0018**
- encrypted credential store：**ADR-0019**
- Stock Pool snapshot/lifecycle：**ADR-0020**
- Paper Trading account/lifecycle：**ADR-0021**
- Phase 38 component ownership：**ADR-0022**
- Phase 40 isolated signal producer：**ADR-0023**
- conversation-first Product experience：**ADR-0024**
- personal-workspace tenancy：**ADR-0025**
- security-master synchronization：**ADR-0026**
- daily market automation：**ADR-0027**
- Backtest data readiness：**ADR-0028**
- adjusted research/corporate action：**ADR-0029**
- benchmark/point-in-time declared data：**ADR-0030**
- Agent domain action completion：**ADR-0031**
- Agent point-in-time market research：**ADR-0032**
- Product Agent public answer/activity projection：**ADR-0033**
- real-user journey closure：**ADR-0034**
- user-experience polish：**ADR-0035**
- trusted runtime/market time：**ADR-0037**
- DSH Product plugin registry/qualification boundary：**ADR-0038**

以上决策的规范文本位于 `docs/architecture/adr/`。ADR-0015 只在 BeyondQuant Next
v1.0 正式发布边界前有效。ADR-0026 至 ADR-0030 分别对其 Beta Phase 范围生效。

## 交付状态

- Phase 23 建立了 Product Skeleton 的 browser 与 parity baseline。其 mocked Playwright
  navigation smoke 不构成真实 Product API golden journey 的证据，也不是 v1.0 RC gate。
  Phase 23 没有完成最终 Community parity；Phase 24-31 建立了持久化产品/存储基线，
  产品深度由 Phase 32-40 完成。
- Phase 30 产出初始 V2 parity matrix 和 browser surface；原 RC 结论后来被 gap audit
  和 Phase 32-40 取代。Phase 40 已提供重新开启 RC review 所需的 real-Product-API、
  no-mock、multi-user golden journey。
- Phase 31（ADR-0016）完成：八个 domain store 均通过
  `services/backend/app/db.py`（`BYQ_DATABASE_URL`）使用 PostgreSQL；SQLite runtime
  path 与 `BYQ_DOMAIN_DB_PATH` 已移除；SQLite → PostgreSQL 逻辑迁移、幂等验证和
  `pg_dump`/`pg_restore` 演练均通过。ADR-0013 的正式 Community bulk import 仍需
  live read-only Community audit snapshot；Community PostgreSQL 保持只读且未被修改。
- Phase 32 完成 Backtest workspace 深化：wizard 使用不可变 `signal_snapshot`；结果页
  的八个 detail tab、删除、比较和 mobile flow 均接入真实数据并有 Chrome MCP 证据。
  D-0001 关闭；D-0002/D-0003 转交 Phase 40，后者最终因触发条件不成立而 DROPPED。
- Phase 33 完成 Strategy workspace 深化：持久化 `strategy_draft` save、soft-supersede
  delete、version history 和真实 Backtest count 均贯通 Backend/MCP/Product API/UI。
  D-0009 至 D-0012 交由 Phase 40 并已全部关闭。
- Phase 34 完成 Stock Pool：owner-scoped catalog/detail、五种 persisted projection、
  immutable membership snapshot、weight validation、Tushare provenance、
  no-look-ahead lookup、lifecycle/tombstone，以及跨 Paper Trading/research/Backtest 的
  frozen reference 均可审计。Backend、Product API、`byq_pool_*` MCP、frontend 和
  desktop/mobile evidence 完成。
- Phase 35 完成 Paper Trading：owner-scoped account、ledger/settlement snapshot、手工
  immutable settlement、T+1 quantity partition、order audit、versioned risk control、
  frozen Stock Pool binding 和 canonical asset-bundle transfer 均持久化。六个 Product
  UI tab、只读 MCP projection、真实 Product API E2E 和 browser evidence 完成；未引入
  live broker 或 Community runtime/storage path。
- Phase 36 完成 Agent workbench：ADR-0018 的封闭 WorkflowTrace card/activity vocabulary
  在 MCP、Runtime Adapter、Gateway、Product API 与 frontend 边界强制执行；公开内容
  不含 raw DSH schema、hidden reasoning、tool argument 或 secret。D-0005 已关闭，证据
  位于 `docs/evidence/phase-36/`。
- Phase 37 完成 My Space：user-scoped write-only model credential 使用 AES-256-GCM
  envelope encryption；model profile/Product Agent binding、workspace asset v2
  export/import 和 Agent Policy 均持久化并受 owner/audit 约束。D-0006 已关闭，证据位于
  `docs/evidence/phase-37/`。
- Phase 38 完成 Operations workbench：九个 admin route 使用有界 `operations.v1`
  Product API projection；monitoring-threshold write 只允许 admin，且 versioned、
  idempotent、audited。Browser boundary 不暴露 secret、raw DSH event、Redis control、
  arbitrary SQL 或 direct runtime control。D-0007 已关闭。
- Phase 39 完成 Data Center / Data Sync：仅 Tushare、write-only credential lifecycle、
  有界 connection test、持久化 async job、per-symbol outcome、canonical daily bar import
  和诚实 coverage。Browser 只访问 Product API；D-0008 已关闭。
- Phase 40 完成 shared component 与最终 parity closure：ADR-0023 的 trusted coordinator
  和无凭证 Pandas sandbox 将 approved immutable StrategyVersion 与 frozen canonical
  bar/Stock Pool snapshot 转换为 `signal_snapshot`。真实 strategy → approval → signal →
  Backtest golden flow、two-user isolation、accessibility 100 分和 evidence 已完成；
  D-0002、D-0009 至 D-0012 关闭，D-0003 因测得触发条件为假而 DROPPED。
- Phase 41 接受 conversation-first Product 方向并推迟 v1.0 RC review；确定 BYQ durable
  conversation catalog 与 private DSH Session 的边界、单层 navigation、settings 整合、
  semantic theme Contract、Community classification 和 Phase 42-48 顺序。本 Phase 未改
  Product runtime。
- Phase 42 实现 ADR-0024 conversation-first shell：`/` 进入 Xiaoba；desktop 和 mobile
  navigation、recent Product session、user menu 及 protected deep link 均可用；browser
  只观察到 same-origin Product API traffic。
- Phase 43 实现持久化 conversation boundary：PostgreSQL 持有 owner-scoped metadata 和
  user turn；Gateway 组合 restart-safe replay，只暴露 normalized WorkflowTrace，并将
  DSH runtime session 隐藏在 browser response 之外。title、search、pagination、rename、
  pin、archive/restore 均持久化。
- Phase 44 将 Profile、Appearance、Assets、Paper Trading、Models、Agent Policy 和
  research/approval 入口统一到 user center。Appearance preference 持久化且 versioned；
  browser cache 仅是非权威 paint hint。restart、owner isolation 和 accessibility evidence
  完成。
- Phase 45 将 System Overview、Data、Sources、Cache、Database、Models、Agents、Budget、
  Runtime、Workflow、Access 和 Audit 整合为 route-backed administrator dialog。RBAC、
  append-only audit 和 destructive-action limit 不变，browser 仍只访问 Gateway/Product
  API。
- Phase 46 统一 Stock Pool、Strategy 和 Backtest 的 responsive catalog/detail hierarchy，
  保留不可变 snapshot/reference、draft/version/approval/signal lineage 和全部八个
  Backtest result tab。Workflow card 通过封闭 route table 映射，真实 persisted data 的
  desktop/mobile review 通过。
- Phase 47 标准化 loading/empty/retry、pagination、localized label、form state 与 unsaved
  change protection；route focus、recoverable unknown route、ECharts semantic theme、
  reduced motion 和全部十种 mode/accent contrast matrix 完成，desktop/mobile
  Lighthouse Accessibility 均为 100。
- Phase 48 建立 fresh-Compose CI journey，覆盖 durable login、conversation restore、
  Stock Pool、strategy validation/version/approval、isolated signal、Backtest、profile、
  appearance、encrypted model binding、asset transfer 和 admin settings。第二个用户看不
  到 owner resource 且无法访问 admin projection；最终 Community reconciliation 无未解释
  的 `PARTIAL`/`MISSING`。v1.0 RC review 仍由人工决定。
- Phase 49 接受 ADR-0025：每个 durable user 拥有一个 private personal workspace 和唯一
  owner membership；workspace resource 以 trusted `workspace_id` 授权，user/platform/
  Engineering scope 保持分离。Phase 49 不改变 runtime/schema，授权 Phase 50 实现。
- Phase 50 创建并修复 personal workspace/membership，为 31 个 workspace table 增加
  nullable indexed `workspace_id`。migration CLI 执行精确 mapping、propagation、manifest
  hash、relationship check、transactional dry-run 和 quarantine，不猜测 unmatched owner；
  authorization 尚未提前 cutover。
- Phase 51 在 Product/Agent authorization boundary 强制 durable session 的 active
  personal workspace。Gateway 忽略 browser identity header；Runtime Adapter、Product
  DSH、MCP 只传播 trusted context；Backend 验证 membership。31 个 table 在零
  quarantine、22 项 relationship check 后强制 `NOT NULL`。
- Phase 52 只向 durable login/session bootstrap 暴露有界 workspace summary，并在 shell
  与 asset transfer UX 中明确 personal scope，不增加 team affordance。two-workspace
  journey、spoof rejection、backup/restore、restart 和 forward repair 均通过；修复了
  Paper-account existence oracle。
- Phase 53 依据 ADR-0026 闭合 fresh-install Data Center bootstrap：Tushare
  `stock_basic` 生成 atomic immutable `L/P/D` snapshot 和 searchable catalogue；daily
  job 冻结明确的 symbol selection，incremental mode 从每个 symbol 最新 bar 之后开始。
- Phase 54 依据 ADR-0027 用 exchange-calendar-driven Data Plane 取代 per-symbol nightly
  orchestration：每个 open session 一份 exact-date Tushare snapshot，具备 content-
  addressed completeness、catch-up/retry/lease recovery、可选 atomic security-master
  refresh 和独立 trusted `data-worker`。
- Phase 55 依据 ADR-0028 冻结 typed market-data requirement，按 SSE session 与 security
  lifecycle 分类 coverage，持久化 daily suspension/status/limit，并只向 trusted Data
  Worker 发送有界 missing range。Signal job 在 provider-free coordinator 冻结完整输入前
  保持 `waiting_for_data` 且不可 claim。
- Phase 56 依据 ADR-0029 同步 exact-date adjustment factor 和 implemented corporate
  action；为研究构建 content-addressed adjusted view，同时保留 raw execution price；
  input 被冻结，entitlement/cash/share 在明确日期结算。
- Phase 57 依据 ADR-0030 同步 benchmark/index membership、daily valuation 和 declared
  financial indicator；冻结 point-in-time membership 和 announcement-aware research
  input，拒绝 non-member signal，并报告 frozen benchmark/excess performance。
- Phase 58 依据 ADR-0031 为协调角色增加 bounded custom Stock Pool list/get/create，
  为策略研究角色增加 planned ResearchTask create 前置能力；统一 MCP/Backend strategy
  schema、有界 422 单次修复和逐动作授权/审计，并通过真实 Chrome 连续旅程验收。
- Phase 59 依据 ADR-0032 增加持久化 `daily_basic` exact-session 估值和公告后次日可见的
  financial-indicator Agent reads；完整性、缺失值、报告/公告/生效日期均显式，且没有
  Provider call、自动同步或数据填充。
- Phase 60 依据 ADR-0033 只投影 DSH text-only 最终回答，封闭本地化公开研究术语，隐藏
  authorize/audit/unknown control activity，并让公开活动以用户可理解的中文状态正确终止；
  真实无工具和估值工具旅程均未暴露 raw DSH/MCP/coverage token，且未改变 Domain result。
- Phase 61 依据 ADR-0034 完成真实用户验收闭环：累计 19 项中的 P0/P1/P2 全部关闭，
  Agent 日线统一为持久化口径，任务 readiness、连续追问和跨模块下一步通过真实浏览器；
  正式 PostgreSQL 与结果对象完成联合恢复，原损坏卷保持封存。
- Phase 62 依据 ADR-0035 关闭剩余 P3：股票池 snapshot 可直接选择至多 20 只执行任务
  readiness；普通工作台移除工程标签；ECharts 模块化与 Vite 8 分包消除默认大包告警，
  并通过真实 Chromium 的 readiness 和回测图表复验。

Community Parity Delivery Plan Phase 1-8 恢复 Product shell 和 Chrome MCP browser
evidence。`docs/roadmap/COMMUNITY_FEATURE_PARITY_GAP.md` 中的历史缺口已由 Phase 32-40
分类并解决；parity-only RC 结论已被 Phase 41 的 Product experience program 取代。

Post-Phase 40 DSH Upgrade Lane 已完成：Product Runtime 准确固定 Python
`deepseek-harness-sdk` / `deepseek-harness-runtime-bin` `0.1.1rc1`，以及一致的 78 个
`@deepseek-ai/*` npm package closure（其中 71 个 DSH package 为 `0.1.1-rc.1`）。由于
缺少匹配的 Python artifact，GitHub/npm rc.2 不合格；rc.6 保持 rollback baseline。
Product capability 和 Gateway → Runtime Adapter → DSH → MCP 边界不变。

Phase 63 依据 ADR-0038 建立 Git-managed Plugin Registry、状态/风险/capability contract、
qualification checker、静态 Product profiles、独立 Agent assignment 和 deterministic
Cordis composition/hash。Guard、Compaction、search-only Web Search 已 QUALIFIED + ENABLED；
Spill 因 rc.1 本地文件/cleanup 边界 BLOCKED，Interaction 因当前 SDK/JSON-RPC 缺少已验证
的 Product 问答 lifecycle 而 BLOCKED_BY_RUNTIME_VERSION。DSH baseline 未升级。

Post-Phase 62 Trusted Time Maintenance 依据 ADR-0037 将服务器权威自然时间作为 DSH
逐轮动态 runtime context，并通过 BYQ MCP 暴露已有 SSE calendar 与 persisted market
snapshot 的有界只读截止语义。它是维护修复，不改变 Phase 62 完成状态，也不定义下一
Product Phase。

## 当前授权边界

- Phase 49-63 与相应 Accepted ADR/计划均已完成。
- Next phase 尚未定义。研究→策略→模拟执行自动化属于新产品能力，必须先明确 domain
  invariant、Accepted ADR 和验收标准；本轮授权不扩大为 release-candidate 评审、tag 或
  production publication。
- BeyondQuant Next v1.0 正式发布时必须禁用 GitHub auto-merge，并恢复单维护者 Human
  Merge Gate。

Git SHA 不是 Phase state。干净基线始终通过 `git fetch origin` 后执行
`git rev-parse origin/main` 动态取得；本文档不得硬编码 SHA，也不得描述临时 PR/merge
状态。
