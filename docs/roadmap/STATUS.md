# BeyondQuant 状态

研究流程连续性维护：见[下一阶段整改目标](RESEARCH_HANDOFF_PLAN.md)，先完成审批后原目标交接，再补持久交接与授权续接连接；不推进 Product Phase。

<!-- byq:current-completed-phase=97 -->

本文档顶部是当前 Phase 状态的事实来源，使新的 Codex session 不会从 commit history 推断状态。
下方交付历史保留当时配置与验收事实，不作为当前运行参数或通用合并/部署授权；后续具名修订可能已替代它。

浏览器验收现行规则：依据 ADR-0059 的 2026-09-09 维护者授权修订，取消 Chrome MCP
专属要求，使用测试框架管理的真实浏览器即可；不依赖系统 Chrome 或个人浏览器调试连接。
真实 Product API、业务断言及按影响要求的浏览器证据仍必须满足。以下历史工具记录不改写。

## 权威当前状态（唯一权威条目，2026-09-20）

本节是 Product、维护与依赖资格三条轨道“当前步骤 / 下一步 / 授权来源 / 停止条件”的唯一权威条目；
下方同名历史段落只保留当时事实，不再独立表达授权。顶部机器 marker
（`byq:current-completed-phase=97`）只表示最近完成的 **Product Phase**，不表示独立数据/资格轨道
状态，也不表示下一 Product Phase 已授权。

| 轨道 | 当前步骤 | 下一步 | 授权来源 | 停止条件 |
|---|---|---|---|---|
| Product | 最近完成 Phase 97（marker 97） | 未授权任何新的 Product Phase | 维护者阶段性授权 + 本文件 next phase | 一阶段一 worktree/Draft PR；Human Merge Gate；不得自授新 Phase |
| 数据/资格 | Phase 98 资格与基准冻结已授权（#282，2026-09-17）；Phase 99 `COMPLETE`（#283）；Phase 100 `IN_PROGRESS`（维护者 #285 于 2026-09-17 开启，冻结 Tushare 6000 数据集范围；P100-A 基金 provider 合同已并入 #286）；Phase 101 `COMPLETE` | 继续 Phase 100 切片 P100-B..E（`index_dailybasic`、申万行业、同花顺概念、Product 呈现），每切片独立 worktree/Draft PR | 维护者开启 Phase 100（#285）+ [V1_DATA_BASELINE_CONTRACT](V1_DATA_BASELINE_CONTRACT.md)「6000 积分可接入的数据集（Phase 100 实施范围）」；ADR-0074 为边界 ADR；Phase 98 授权只覆盖前置资格，**不**覆盖 Phase 100 实施范围 | 仅 Tushare、不用 Community；不支持分钟/实时/港股/特色数据；不得以“接口可调用/单次拉取成功”代替覆盖/时点/单位/许可证据；不改生产状态（除非另有部署授权）；HIST/THS 概念在证明历史可见性前保持 blocked |
| 维护（当前） | D15-G architecture Go/No-Go 维护（独立 worktree/分支 `codex/phase-d15-g`，不推进 Product Phase）；交付结论 `NO_GO`（NOT-PASS） | 被委托实现者停在 Draft；合并由原会话既有授权按 ADR-0015/0059 预发布 Gate 按次执行（不写成永久规则） | 本次任务委托 develop/push/Draft；**合并授权属原会话既有授权，非本次新授予** | 被委托实现者不得 merge/deploy/release/tag/付费/重启主机；不得接受或实现 Proposed ADR-0082/0083；不得覆盖历史证据；`R3_RESUME = NO`、生产 selector 不变 |
| 依赖资格（D15） | D15-0/1/2/3/3R 完成（D15-2 格式层、D15-3 原生持久层、D15-3R 隔离 runtime 连续性均 `PASS`）；D15-4 `PARTIAL/BLOCKED`（原生 subagent/fork seam 6 项 + 1 支撑项通过；`child-crash`/BYQ `adapter-restart` `BLOCKED`；host reboot `NOT_RUN`）；D15-5 `PARTIAL/BLOCKED`（真实隔离原生 persistent terminal：page refresh/browser disconnect/frontend restart/gateway restart 四行 `PASS`，跨进程唯一 marker 无重放/丢失、权限不可绕过、错误 terminal 拒绝、stale generation/epoch fenced、清理无孤儿；`adapter-restart` 与 `dsh-runtime-restart` 必需项 `BLOCKED`，host reboot `NOT_RUN`）；D15-G `NO_GO`（NOT-PASS，decision contract + fail-able observer；部分 PASS 不得聚合为 GO；child-crash/BYQ adapter restart/terminal adapter restart/DSH runtime restart 四项必需项未过，host reboot `NOT_RUN`；证据 `docs/evidence/d15/d15-g/`）；R3 冻结、`R3_RESUME=NO` | 无：D15-G 已给出 NO_GO，未授权任何后续 D15/R3/生产切换；R3 解冻需 GO 加 R3/R6 原生连续性证据 | 维护者 D15 目标决策（2026-09-19）+ 专项 D15 计划 | 不改生产 selector；候选隔离；NO_GO 后不恢复 R3；不接受/不实现 Proposed ADR-0082/0083 |

**授权缺口（已解决）**：`ADR-0081` 曾为 `Proposed`，其文本写明“路线重排须在接受之后”，而专项 D15
计划已实际实现该重排（D15 插在 R2 之后、R3 之前）。维护者已于 2026-09-19 接受 ADR-0081
（Accepted，见 #328），该缺口已关闭：D15 插在 R2 之后、R3 之前的重排现为已授权顺序。D15-2/D15-3
的 `PASS` 仍是隔离资格证据，不据此推断 R3 解冻或生产切换授权。

## 维护收口：ADR-0047 聚合边界、运行连续性、数据就绪续接与可逆归档（2026-09-19，历史叙述）

本批次为维护，不推进 Product Phase。顶部机器 marker 仍保持最近完成的 Product Phase 97；
Phase 98/100 为独立的数据/资格轨道，Phase 99 已完成，因此该 marker 相对本文当前叙述是滞后的——
本次据实说明而不伪造 marker 迁移，也不把维护写成一个新 Product Phase。

- **ADR-0047 五层数据/容量边界修复（构建修订 .129–.132）**：共享确定性分片规划器接入
  signal/backtest 准备路径并持久化 `requirement_plan_json`；delist-date 边界改为
  `trade_date >= delist_date` 非适用（对齐 ADR-0028 生命周期语义）；signal sandbox 输入去重并
  改用列式 `bars_frame.v1`（100.24→24.10 MiB，`AGGREGATE_ROW_LIMIT=2_000_001`，`packages/contracts/bars_frame.py`
  为单一事实来源）；不可变 snapshot 改用列式 `signal-snapshot-v2`（41.30→13.68 MiB），
  `snapshot_bars` 兼容解码 v1/v2；`backtest.py` 的 `MAX_BARS`/`MAX_SIGNALS` 与 ADR-0047 聚合上限对齐。
  全部 32 MiB transport/object envelope（`MAX_JOB_BYTES`/`MAX_REQUEST_BYTES`/`MAX_RESULT_BYTES`/`MAX_SNAPSHOT_BYTES`）
  保持不变，未改任何 Accepted ADR 文本。
- **信号生产完整性（构建修订 .134，PR #303）**：ready bars 现携带持久化绝对 `adjustment_factor`，
  使合法除权除息的 `prev_close` 跳变不再被误判为不一致；`source.data_readiness` 接受
  `requirement_plan_sha256`；signal worker/coordinator 以结构化 traceback 记录失败（不含 secrets 或完整 payload）。
- **运行连续性（构建修订 .133/.135，PR #302/#304）**：runtime-adapter 重启后按需、幂等地从 BYQ lifecycle
  journal 重建会话记录，Gateway 以持久 WorkflowTrace 的 last sequence 作为 append authority 续写；
  reboot 导致的陈旧 lease 现显式映射为 HTTP `409` + `stale_session_lease`（区别于 404/503）。
  新增可逆、audit-first、只读数据库的 `scripts/ops/archive_stale_sessions.py`；生产已归档 15 个陈旧会话，
  未删除任何文件或 domain row。
- **数据就绪自动续接（ADR-0077，Accepted；构建修订 .136/.137，PRs #305/#306）**：在既有任务绑定续接
  合同内新增数据就绪事件，signal job `completed` 且产出 `validated signal_snapshot` 时经既有预算账本
  生成至多一个有界续接回合。ADR-0077 仅对 ADR-0045 §3「默认下一回合投递」增加具名例外，已于
  2026-09-19 获维护者接受并成为当前规范；生产当前已运行该实现。后续修复使 continuation guard 与 Backend 权威
  `RUNTIME_MODEL_ALLOWLIST` 对齐（`deepseek-official` 及六个 `opencode-*` 路由），并以架构/Backend drift 测试守门。
- **生产结果**：round-1 HS300 momentum+Kelly 回测完成——job `backtest_83cab36af0ec486d98b0a002c671b5da`、
  result `artifact_c62ab34ffd61405d85bac30ea3ca08ed`，收益 +25.49% vs 基准 +19.65%，最大回撤 33.83%；
  round-2 等待 `agent_approval_4e2ecb61eca74ec1a5c6721b5204f4f5`。
- **本轮只新增只读/可逆运维产物，不改 domain 数据**：
  [终态 signal job 归档审计](../operations/TERMINAL_SIGNAL_JOB_ARCHIVE.md) 与
  `scripts/ops/archive_terminal_signal_jobs.py`（audit-first，`--apply` 仅落盘可逆 manifest，
  绝不写业务表；终态 job 归档需新增具名 ADR/domain action）；
  [重复沪深300股票池清单](../operations/HS300_DUPLICATE_POOLS.md)（仅提议，整合须经 owner 授权的
  Product/`byq_pool_lifecycle` domain 路径，建议 `inactive` 而非不可逆 tombstone）。
  详见 [实现计划](IMPLEMENTATION_PLAN.md) 本轮维护小节。

## Runtime Continuity D15：DSH 0.1.5-rc.1 原生连续性资格（2026-09-19，维护，历史叙述）

> 当前权威状态以上方“权威当前状态”条目为准；本段保留 D15 的详细历史事实。D15-2 为格式层证据、
> D15-3 为原生持久层证据，均不构成 runtime 语义恢复或 R3/生产切换授权。

本批为维护，不推进 Product Phase。维护者要求重排 Runtime Continuity（R-series）路线并推进 D15：
完成 D15-0 升级 recon、确定资格目标、构建/启动 D15-1 隔离候选、完成 D15-2 Session V3 迁移资格，
并完成 D15-3 原生会话恢复资格，冻结 R3。依
[ADR-0081](../architecture/adr/ADR-0081-dsh-native-continuity-and-d15-stage.md)（Accepted，2026-09-19）：

- **R3 冻结（非回滚）**：状态 `PAUSED_PENDING_DSH_015_NATIVE_CONTINUITY_QUALIFICATION`。保留
  既有 R3 代码/测试/文档与框架中立合同，不回滚 R1/R2；暂停自建 DSH 进程重启编排、会话重建、
  原生会话持久化替代、subagent 持久化与持久 PTY/shell。R3 分支相对 `main` 无任何提交，从未实现。
- **目标决策（维护者）**：资格目标为 coherent 配对 `dsh-v0.1.5-rc.1`/Python `0.1.5rc1`/npm
  `0.1.5-rc.1`（`docs/evidence/d15/target-decision.v1.json`）。请求的 npm
  `@deepseek-ai/dsh-*@0.1.5-rc.2` 无匹配 PyPI Python `0.1.5rc2`；rc.2 保留为
  not-a-coherent-pairing。D15-0-F1 据此解决。
- **D15-0（DONE）**：机器可读台账 `docs/evidence/d15/compatibility-ledger.v1.json` 与
  `upgrade-recon.v1.json`，按字节级 npm `.d.ts` diff 与 bundled Python runtime 检查，覆盖
  27 个 BYQ 依赖接口。D15-1 探测后：changed 12/new 5/compatible 8/unknown 0/unchanged 2。确认
  0.1.5 原生 Session V2/V3 迁移、`SessionHandle` 持久化、跨进程写租约、continuable subagent、
  persistent terminal；Python SDK 公共文件与 0.1.2rc1 逐字节相同。
- **D15-1（隔离 build/start/probe DONE）**：独立候选声明
  `config/dsh/candidates/dsh-0.1.5rc1/`、校验/selector `scripts/dsh/candidate_registry.py`、
  compat 边界 `services/runtime-adapter/app/compat/dsh_015.py`；候选镜像
  `byq-d15-1-0.1.5rc1-candidate:local`（`sha256:96bf6327...`）由候选 Dockerfile/requirements 锁
  构建，以 `--network none` keyless 启动并跑通 scripted turn + tool call（事件序列连续，含
  `tool/call`/`tool/result`，BYQ profile patch 加载成功）。证据
  `docs/evidence/d15/d15-1/`。候选在不可变 `config/dsh/releases` 注册表之外，未 push；
  生产默认 `dsh-0.1.2rc1`、`compose.yml`、既有 0.1.2 制品/证据不变，回滚目标 `dsh-0.1.2rc1`，
  无 DB/Worker 变更。`tool_event_schema` 与 `profile_schema` 由 unknown 转为 probed/compatible。
- **D15-2（Session V3 迁移资格 PASS，格式层）**：提交 9 个不可变 fixtures
  （`docs/evidence/d15/fixtures/sessions/index.v1.json`，含 sha256），其中 `f-normal`
  为隔离运行官方 0.1.2-rc.1 bundled runtime 产生的真实 v0 会话（keyless 合成 loopback
  provider/MCP，多帧 zstd 无损解压），其余为用官方 0.1.5-rc.1 released-v2 codec 确定性构造的
  历史 v2 fixtures，`f-continuable` 为经真实 catalog 迁移后再编码的 v3 当前格式 child，
  `f-old-lifecycle` 附带合成 BYQ lifecycle 证据 sibling。Node harness
  `scripts/d15/harness/migration_harness.mjs` 仅读原始文件、复制到 scratch 后经第一方
  `@deepseek-ai/dsh-session-format-catalog`（`sessionFormatV2ToV3`）执行
  `read → resume → append → close → reopen`：9/9 全阶段 pass、0 blocker、
  序列连续、message id 保留、system prompt/provider context 保留；`f-forked` 的
  `isSeeded`/inherited cut（源标记 seq 7 → 目标 inherited count 9）保留。迁移后 v3 store
  **不可降级**（9/9 记录：0.1.2-rc.1 无 `dsh-session-format` 且按 `session.vN.jsonl` 选代）。
  **这是格式层证据，不是 runtime 恢复**：`resume`= `Session.fromRestore`、`append`= 手工构造/
  编码事件、`close`/`reopen`= 文件/codec 操作。verdict v2 显式要求全部不变量、全部拒绝用例与
  全部 blocker 通过，否则进程非零退出；`negative-controls.v2.json` 证明注入的
  sequence/id/context/reopen/blocker/fail-closed 破坏都会失败，而修复前的“仅看阶段状态”门禁会
  误报 PASS。fail-closed v2：future-version / unclassified-event / malformed-header /
  refused-surface 均返回文档化拒绝，`treated_as_new_session=false`、
  `successor_generation_written=false`。台账 `session_format_v2_v3` 增加
  `observed_status=compatible` 并移出 `not_yet_probed`；`acceptance-matrix` D15-2 置 PASS，
  D15-3..D15-G 仍 NOT_RUN。D15-2 仅新增测试/证据/文档，但 `scripts/` 与 `tests/` 属于 BYQ
  build-input inventory，故按仓库规则构建修订推进 `post-u8.147 → post-u8.148`
  （仅重建身份，不改 selector/deployment）。
- **D15-3（Native Session Resume Qualification PASS）**：隔离 Node harness
  `scripts/d15/harness/native_resume_harness.mjs` 以真实 0.1.5-rc.1
  session-persistence seam（`SessionPersistence.create/open`、`SessionHandle`
  read/append/flush/close、跨进程 `SessionWriteLease` flock、`readColdSessionLog`）
  驱动，**每个 runtime generation 一个 OS 进程**；`scripts/d15/native_resume_qualification.py`
  经 `packages/contracts/runtime_continuity.py::classify_generation_transition`
  对全部 8 个 failure-matrix 行分类。结果：8/8 持久化行均可被新 generation 原生恢复同一
  session（同 id、事件日志保留、序列连续）：browser/frontend/gateway 为 `reattached`（generation
  存活），adapter restart/generation replacement/host reboot/executor takeover 为 `rehydrated`
  原生恢复，DSH crash 为 `interrupted`（丢失 run 如实标记且同 session 仍可原生恢复）；
  native 不可用对照（未过 `flush()` 屏障的未物化 session）正确不可恢复并需 BYQ fallback。
  **证明边界**：D15-3 证明原生持久层可恢复性（新 OS 进程重开同一 session），未运行
  browser/frontend/Gateway/runtime-adapter 服务，也不证明 runtime 语义恢复——原目标保持、
  domain action 不重复、approval 仍有效、结果可追溯仍需一次真实隔离 runtime 资格，属必需下一步
  且尚未完成。结论：原生 session resume 可用，**R3 不得重复实现**；R3 仅保留调用原生 attach/resume、
  epoch fencing、native 不可用时走 BYQ fallback、生命周期观察与清理。公开
  `fresh/reattached/rehydrated/interrupted` 合同不变，native/fallback 机制仅存于内部
  evidence-only 诊断字段（`native_resume_used`/`byq_fallback_used`/`previous_generation_state`/
  `native_session_present`），DSH session id 不成为 BYQ AgentSession 身份。台账
  `native_session_resume` 置 compatible 并移入 probed；acceptance-matrix D15-3 置 PASS；
  证据 `docs/evidence/d15/d15-3/`。R3 冻结与 `R3_RESUME = NO` 不变，直至 D15-G。
- **D15-3R（真实隔离 runtime 连续性 PASS）**：在独立 compose 项目 `byq-d15-runtime`
  （独立网络/卷、全新 PostgreSQL、仅 loopback 端口）启动真实 Gateway + 重建的
  `dsh-0.1.5rc1` 候选 runtime-adapter + Backend + MCP，以 keyless scripted provider
  驱动。5/5 行 PASS：adapter 进程 SIGKILL+重启、DSH 子进程中断、Gateway 重启重连、
  generation 替换、executor takeover；逐行记录 before/after session/goal/approval/
  action-receipts/result 与 pid/generation/epoch，原目标保留、重复投递去重（单一副作用）、
  approval 未被绕过、结果可追溯；takeover epoch `1→2` 且不写任何数据库行。observer
  可失败且区分**格式有效（`format_valid`）与资格通过（`all_pass`）**：REQUIRED 场景
  `NOT_RUN`/`BLOCKED` 一律使 verdict 非零并保留状态/原因；OPTIONAL（`host-reboot`）单独声明、
  不 gate 必需覆盖；`allowed/forbidden continuity` 仅来自合同（观察不得放宽）；PASS 需真实
  PID/generation/epoch 关系与 receipt/trace 链接。27 个负例控制全部非零退出，且对
  `all-required-not-run`/`single-required-blocked`/`reasoned-not-executed`/放宽 allowed/清空
  forbidden 五例，重建的旧算法 `all_pass=true` 而修复后为 false（真实执行对比，非硬编码）。
  本修订还发现并修复隔离栈复用陈旧生产镜像导致 pool 幂等失效的问题，改为从本分支重建
  Backend/Gateway/MCP。capture 层复核修订（v3）进一步移除成功默认：缺失 journal receipt/
  replay 错误/非目标 run 一律 `capture_ok=false` + 场景 FAIL，不伪造 receipt 也不回退原 run id；
  approval 的 `state`/`decided_by` 取自持久化响应，并真实执行 REJECT 与 invalid-reuse 拒绝试验
  （`side_effect_created=false`）；`trace_contiguous` 按完整持久序列计算并把结果归因到目标 run
  （`terminal_kind`/`attributed_message_sequence`）；`side_effect_count` 必须实测、action `origin`
  必须标注；手工 Product 动作与 Agent→MCP 执行显式区分（`agent_mcp_tool_calls=0`）。**v1/v2
  证据保留但不构成资格通过**。**这是 scripted keyless provider 的服务边界证据，非真实 LLM 语义
  证据；host reboot 为 OPTIONAL `NOT_RUN`，不等同容器重启**。D15-4/D15-5/D15-G 与 R3 不在本批，
  不主张完整 D15。scope/approval/Agent-MCP 复核修订（v4）补齐两项必需业务：scripted provider
  发出真实 tool call `mcp__byq__byq_research_task_create` 经真实 MCP→Backend 创建任务，adapter
  重启后同 idempotency key 重投返回同一 task id、实测副作用为 1（`agent-mcp-domain-at-most-once`
  为必需场景）；approval 拒绝不再由任意 error 推断，而是记录 HTTP 状态/域错误码并**真实尝试受保护
  操作**（用被拒 approval 创建回测），前后权威计数不变（invalid-reuse 409 / protected 422，
  `product_domain_rejected`）。capture 层负例新增 `500/timeout 不算拒绝` 与
  `拒绝响应但副作用已存在`。**文档明确区分「有限服务边界观测通过」与「完整原任务资格」：v4 是
  scripted keyless provider 的有限服务边界通过，不是真实 LLM 语义/完整原任务资格；v1/v2/v3 为
  保留历史且不构成资格通过**。v5 复核修订修正 Agent→MCP 重放证据：分别持有第一次/第二次
  run 与 message，等待第二次自身的 tool call/terminal/assistant，并按 run id、tool_call_id 与
  同一 task id（实测副作用=1）关联两个真实 MCP tool 结果；provider 记录真实 tool-call/result
  历史，`agent-mcp-second-no-tool`/`agent-mcp-second-mcp-failed`/`agent-mcp-only-first-run`
  负例必须失败。approval 试验区分 `pre-fault`/`post-fault`：每个恢复场景的 after 在故障后
  真实重试 invalid-reuse 与受保护回测操作并测量权威前后计数。资格证据
  `docs/evidence/d15/d15-runtime/*.v5.json`。
- **D15-4（PARTIAL/BLOCKED，历史）**：原生 subagent/fork seam 6 个必需项加 1 个支撑项
  `PASS`，`child-crash` 与 BYQ `adapter-restart` 必需项 `BLOCKED`，host reboot `NOT_RUN`；
  证据 `docs/evidence/d15/d15-4/`。BYQ continuable hookup 边界以 Proposed ADR-0082 记录，未实现。
- **D15-5（PARTIAL/BLOCKED）**：真实隔离原生 persistent terminal（PTY）资格。以候选
  `@deepseek-ai/dsh-terminal` 的 owner-scoped `TerminalSessionService` + `dsh-terminal-bash`
  `shell` backend（`bwrap --die-with-parent`）在独立 runtime OS 进程运行，客户端为独立 OS
  进程，并用 evidence-only BYQ `TerminalAttachment` gate（身份/状态/授权/reconnect，无 PTY/IO）。
  显式区分四件事：PTY/进程存在、attachment 存在、I/O rebind、稳定 terminal 身份；BYQ 拥有
  attachment，DSH 拥有 PTY/shell/IO，不构建 PTY runtime，terminal 生命周期不定义 conversation/job。
  page refresh / browser disconnect / frontend restart / gateway restart 四行 `PASS`：另一客户端
  OS 进程重绑同一 attachment/session/pid，唯一 marker 跨进程无重放（send delta 不含旧 marker）
  且无丢失（scrollback 各一次），权限不可绕过（`FOREIGN_SESSION`/`UNAUTHORIZED_PRINCIPAL`），
  错误 terminal 拒绝（`NO_SESSION`），stale generation/epoch fenced，清理无孤儿。adapter restart
  与 DSH runtime restart 必需项 `BLOCKED`（native sessions 文档为 process-local，提交的 BYQ 树未
  compose terminal、未持久化 TerminalAttachment，真实拒绝而非伪造 reattach）；host reboot
  `NOT_RUN`。`interface-probe.v1.json` 证实 BYQ 无 terminal wiring；跨进程 reattach 边界以
  Proposed、未实现的 ADR-0083 记录。observer 因必需项未覆盖而非零退出，不主张完整 D15-5。
- **D15-G（NO_GO / NOT-PASS）**：architecture Go/No-Go 已执行。fail-able decision
  contract（`scripts/d15/go_no_go/contract.v1.json`）与 observer（`observer.py`）从已提交
  D15-2..D15-5 证据独立推导每个必需 capability 状态并验证 provenance sha256；只有全部必需
  capability 为 `PASS` 才给 GO，任一必需项非 PASS 即强制 NO_GO 且必须具名 actionable blocker。
  只有 atomic required capability 可作 blocker；aggregate capability 为 display-only（由其
  atomic 成员推导，不得重复计为独立 blocker）；optional capability 为 limitation，不 gate GO、
  不作 blocker。observer 拒绝把部分 PASS 聚合为 GO、拒绝 claimed 与 derived 不一致、拒绝缺失
  blocker/证据/自声明字段、拒绝把 aggregate/optional 列为 blocker。`negative-controls.v1.json`
  19 项控制全部被拒（18 项 defect-targeting，修复前 result-trusting 门禁会误报），已知“全部必需
  PASS 且 optional host-reboot NOT_RUN”的合成 fixture 得到诚实 GO 并通过。推导结果：
  root-session-persistence/process-restart-resume/fork-continuity/terminal-client-reattach
  `PASS`；四个 atomic 必需项 subagent-child-crash、subagent-byq-adapter-restart、
  terminal-adapter-restart、terminal-dsh-runtime-restart `BLOCKED`；aggregate
  subagent-resume/terminal-persistence 因成员 `BLOCKED` 而 display `BLOCKED`；optional
  host-reboot-resume 为 `NOT_RUN` limitation。**NO_GO 仅由四个 atomic 必需 blocker 决定。**
  证据 `docs/evidence/d15/d15-g/`。GO 不隐含生产切换；Proposed ADR-0082/0083 未接受、未实现；
  `R3_RESUME = NO`。
- **路线重排**：`R0 → R1 → R2 → D15 → R3 Thin Runtime Supervisor → R4 TerminalAttachment →
  R5 DurableJob independence → R6 Full Runtime Continuity Qualification → 独立 Production
  Go/No-Go`；R6 完成不隐含生产切换，“兼容 0.1.5-rc.1”与“生产默认 = 0.1.5-rc.1”为独立决策。
- **构建修订**：D15 改变 runtime build inputs，`.145→.146`，D15-1 新增候选 Dockerfile/锁/探测后
  推进 `post-u8.146 → post-u8.147`；D15-2 新增 `scripts/`/`tests/` 下的 harness 与 fixtures 后推进
  `post-u8.147 → post-u8.148`；D15-3 新增 `scripts/d15/` harness、`tests/`、`packages/contracts`
  分类逻辑与证据后推进 `post-u8.148 → post-u8.149`；本轮 D15 资格完整性/验收措辞整改新增
  `scripts/d15/harness`、`tests/` 与证据后先推进 `post-u8.150 → post-u8.151`，CI-A `#326`
  并入 `main`（`.154`）后合并 `origin/main` 并改用未使用 id `post-u8.155`（仅重建身份；
  历史清单与全部证据保留，不修改任何既有 immutable manifest）。D15-3R 及 observer v2/v3/v4
  复核修订各新增 `scripts/d15/runtime_continuity`/`tests`/证据后依次推进
   `post-u8.159 → .160 → .161 → .162 → .163 → .164`（仅重建身份，历史 manifest 与证据全部保留）。
    D15-4 新增 `scripts/d15/subagent/`（原生 harness/合同/observer/reachability probe）、
    `tests/test_dsh_d15_4_subagent.py` 与 `docs/evidence/d15/d15-4/` 后推进
    `post-u8.164 → .165`（仅重建身份）。D15-4 评审修订 v2 再次修改同一批 build inputs
    （harness 精确 fork cut/全日志哈希、child-run-fault 场景、`finally` 清理；observer fork 校验/负例；
    tests），推进 `post-u8.165 → .166`（仅重建身份，v1 证据保留）。D15-4 路由/进程边界调查新增
    `scripts/d15/subagent/routing_probe.mjs`、更新 `tests/test_dsh_d15_candidate.py`（D15-4
    `BLOCKED` 仅在带具名 `uncovered_items` 时被接受；D15-G/R3 未开启）与
    `tests/test_dsh_d15_4_subagent.py`，推进 `post-u8.166 → .167`；routing probe 清理修订
    （每 trial 独立 OS 进程 + `finally` 重试删除，`runtime_root_cleaned=true`）再推进 `.167 → .168`
    （均仅重建身份）。真实路由试验确认：
    提交的 `byq_delegate_*` 配置走 foreground `subagents.start`（`startContinuable=0`）；
    `backgroundMode: continuable` 仅在 in-process `spawn` provider 可达；无 `prepareContinuable`
    的 out-of-process provider（dsh-sdk/ACP/Codex/Claude Code）被拒绝，故 0.1.5rc1 **无独立进程
    continuable child provider**。BYQ hookup 属产品语义变更、超出本 PR 资格范围且仍不能解决
    child-crash/adapter restart，D15-4 保持 `PARTIAL/BLOCKED`：原生 subagent/fork seam 6 个必需项
    `PASS` 加 1 个支撑项 `child-run-fault` `PASS`（真实每代一 OS 进程、scripted keyless provider），
     `child-crash` 与 BYQ `adapter-restart` 必需项保持 `BLOCKED`（不以删除或 owning-process SIGKILL
     冒充），host reboot `NOT_RUN`；observer 因必需项未覆盖而非零退出，不主张完整 D15-4。D15-4
     continuable wiring 再推进 `.168 → .169`。D15-5 新增 `scripts/d15/terminal/`（原生 harness、
     contract、observer、interface probe）、`tests/test_dsh_d15_5_terminal.py`、
     `packages/contracts/terminal_attachment.py` 与 `docs/evidence/d15/d15-5/` 后推进
     `post-u8.169 → .170`（仅重建身份，历史 manifest 与全部证据保留）。D15-G 新增
     `scripts/d15/go_no_go/`（decision contract、fail-able observer、provenance builder）、
     `tests/test_dsh_d15_g_go_no_go.py` 与 `docs/evidence/d15/d15-g/` 后推进
     `post-u8.170 → .171`（仅重建身份，历史 manifest 与全部证据保留）。不部署、
     不自动合并。D15-G 结论为 `NO_GO`（NOT-PASS）；`R3_RESUME = NO`，仅 GO 加 R3/R6 原生
     连续性证据才可重新评估。

- 当前已完成阶段：**Phase 97**——回测任务拥有 Backend 权威、持久化的可读名称；名称与稳定 Backtest ID 在 Product 目录、
  技术详情和小巴任务投影中分离。名称搜索保持服务端分页，缺省名称来自已验证策略，历史任务由 PostgreSQL 前向修复补齐，
  且名称不进入 immutable input/result identity 或 idempotency identity。
- 发布状态：**Beta**。维护者于 2026-08-25 明确授权顺序开发 Phase，并依据 ADR-0015
  对 CI-green PR 执行 auto-merge；该授权不包含 release candidate、tag、production
  publication 或正式发布。独立的 post-Phase 40 DSH Upgrade Lane 已将 Product Runtime
  验证到 Python `0.1.1rc1` / npm `0.1.1-rc.1`；它是维护历史，不是隐含的 Product Phase。
- 当前完成范围内没有未决架构决策。
- 长研究维护：维护者已接受[ADR-0072](../architecture/adr/ADR-0072-long-running-research-checkpoints.md)，
  取消根/子默认总时长硬终止，新增15分钟检查，新后台期限随许可最长24小时；旧许可/预算/取消保留。
  [执行与验收记录](LONG_RESEARCH_EXECUTION_CHANGE.md)独立记录本地验证，生产不由此自动更新。
- H 系列研究连续性整改：H1–H5 全部完成并合并（PR #280/#281）；H4 逐接口台账 `complete=true`，
  H5 真实三轮研究在隔离栈通过 `verify_completion`；生产已部署 `dsh-0.1.2rc1-post-u8.115`。
  见[研究交接计划](RESEARCH_HANDOFF_PLAN.md)与[H5 记录](../evidence/research-handoff-h5/LIVE-RESEARCH.md)。
  这是维护，不是新的 Product Phase；Phase 97 仍为当前已完成 Product 阶段。
- 下一 Product 阶段：**Phase 98（0.10 前置资格与数据基准合同）已授权**（维护者 2026-09-17）。
  依据 [ADR-0074](../architecture/adr/ADR-0074-data-baseline-and-qualification-boundaries.md)，交付
  [数据基准合同](V1_DATA_BASELINE_CONTRACT.md)、[HIST 历史关系资格调查](V1_HIST_DATA_QUALIFICATION.md) 与
  [深度学习环境资格调查](V1_DEEP_LEARNING_ENVIRONMENT_QUALIFICATION.md)；不实现数据扩容、不引入 HIST、
  不授权 GPU/有限调参/新 Worker 拓扑。继续遵守一阶段一工作树/Draft PR 的合并门禁。
- Phase 99（0.10 资格调查执行）已完成：深度学习 CPU profile 实测（`torch 2.14.0+cpu`，MLP/LSTM
  训练与推理耗时、峰值 RSS 352.8 MB、torch 安装 773 MB，GPU/故障矩阵/容差 `not_measured`）；
  HIST 历史关系来源只读核对确认本机无可用来源，维持 `blocked`。见
  [资格执行证据](../evidence/phase-99/QUALIFICATION-EXECUTION.md)。不实现数据扩容、不引入 HIST。
- Phase 101（凭据驱动动态模型目录与后台续接资格）已完成：依据 [ADR-0075](../architecture/adr/ADR-0075-dynamic-model-catalogue-and-credential-discovery.md)，
  Backend 发现接口、已发现模型的档案创建/解析、后台续接封闭 provider 路由、Gateway 转发与前端“选中凭据→刷新模型”均已实现；
  真实浏览器经 Gateway/Product API 验收（真实 DeepSeek 凭据发现成功、不可用凭据闭合失败并保留已审阅静态目录）。
  验收证据位于 [docs/evidence/phase-101d](../evidence/phase-101d/README.md)。Phase 100 数据基准仍在进行中。
- 版本规划：维护者已接受 [ADR-0071](../architecture/adr/ADR-0071-v1-machine-learning-release-plan.md) 与
  [0.9.x → 1.0 路线](VERSION_PLAN.md)。1.0 须在约定主流机器学习模块及研究闭环开发、运行稳定后发布，
  包括 HIST 的历史关系资格和最终候选至少14天观察；仅当前整改完成不足以发布1.0。
  本次仅规划，不开启新 Product Phase，不改现有版本号或运行能力。
- 维护执行：[DSH 0.1.2rc1 升级方案](DSH_012RC1_UPGRADE_PLAN.md) 的 U0 已 `VERIFIED`，维护者于
  2026-09-06 接受 ADR-0058 和官方 matching wheel bundled executable 路线；U0 已通过 PR #250
  按 ADR-0015 squash auto-merge。U1 的集中 release identity、候选物料与隔离验证已完成；U2 的可信
  evidence provenance 解耦已由 PR #253 合并；U3 的旧版 Runtime compatibility seam 已由 PR #254 合并；
  U4 的 0.1.2rc1 候选适配已由 PR #255 合并。U5 的真实候选进程/五角色委派、old/new 20-cycle
  benchmark、完整本地 CI 和模型场景内部断言已通过。授权只读核查确认一条历史 G6 合成反馈误发到正式 Hub，
  当时为 received、无发布队列或 GitHub Issue；记录保持不变，原认证已撤回并归档。
  U5 已完成封闭测试栈/假 Hub 隔离整改、old/new G6 重跑和候选 Chrome MCP 桌面/手机审查；
  最终本地 CI 26/26 通过，T01–T37 PASS，修复后预发布认证恢复，U5 已通过远端 CI 和合并门禁。
  U6 发布与回滚演练已验证：最小排空门禁、跨版本审批续接、逻辑备份/实际恢复及隔离 old→new→old 通过；
  维护者已明确授权保留历史 release 描述、报告和失败测试不变，新增 U6 独立构建身份并重新认证；
  ADR-0061 已记录该决定；独立 U6.3 构建的完整本地 CI 26/26、179项架构测试和最终模型/Chrome 演练通过。
  新 v2 认证为 T01–T39 PASS，保留 RSS 明确例外及原 G2 语义失败/独立补测；T40 留给 U7-U8。
  当前维护阶段为 U8（CLOSED_EARLY_REMEDIATION_REQUIRED）：U7 已合并并完成生产部署；维护者已明确授权恢复停止的正式服务、在
  `/home/jefison/backups/byq-dsh-u7` 私有备份、部署 0.1.2rc1 并持续观察24小时完成 U8。
  逻辑备份和隔离实际恢复已通过，U7 本地全量 CI、经明确澄清的 G3 及 G4/证据回滚验收通过；原失败保留。
  新版生产安装身份、旧版 G1→新版同公开会话 G5、Chrome 桌面/手机和 Product Plugin Center 核查通过。
  观察于 2026-09-06 23:02:43 UTC 开始；2026-09-07 维护者明确要求提前停止并先行整改。
  已停止观察器并完成最终盘点：78次采样、4小时25分钟，基础设施告警为零，但业务语义验收未通过；
  不能标记24小时完成或稳定性PASS。原始采样与失败历史保留，当前DSH不回退。
  观察中确认真实基金研究在子 Agent 超时后以“继续”恢复时丢失未回答主题，并误选同工作区既有 ML/回测对象；
  该基金事故窗口未发生新训练/预测/回测写入或跨租户读取，但持久 Agent run 未随超时收口。
  后续ML研究出现迟到训练成功但无预测/回测续接；最终盘点4条Agent仍active。维护者决定 U8 提前诚实收尾后，
  在独立 maintenance worktree 统一实施[可靠性修复需求](POST_U8_AGENT_RELIABILITY_REMEDIATION.md)；U8 不得声称该缺陷已解决或语义稳定。
  下一维护任务：已授权开展R1–R5、S1–S3、F1–F10审计及修复；保持DSH 0.1.2rc1，
  数据中心Tushare数据扩容暂缓。开发授权不自动扩大为生产部署或新架构边界授权。
  维护者已明确接受[ADR-0062](../architecture/adr/ADR-0062-post-u8-reliability-boundaries.md)，
  同步修订ADR-0045/0046；按[审计执行记录](POST_U8_RELIABILITY_AUDIT.md)先合并收尾与规范，
  再从更新主线分批修复。架构接受不代表实现完成，也不自动续跑历史研究。
  实际部署与观察证据见 [U8 记录](../evidence/dsh-012rc1/u8/OBSERVATION.md)。
  维护者已授权 U1–U8 串行开发、自动 push/Draft PR，并在 CI-green 后按
  ADR-0015 自动合并和进入下一阶段。维护者另行授权在当前本地环境使用既有凭据链执行必要的
  付费模型测试，并精确限制为合成测试用户、固定提示和 BYQ 测试上下文，不含生产数据、真实对话或密钥。
  本次 U7 生产部署授权已另行取得，不授权数据库回退、数据删除或正式 release/tag。
  默认选择器及实际生产均为 0.1.2rc1；0.1.1rc1 按 ADR-0069 仅保留历史回滚制品，不再持续维护；Product Phase 97 不变。
- Phase 82 已依据 ADR-0047 完成；验收证据位于 `docs/evidence/phase-82/`。
- Phase 90 已依据 ADR-0049 完成；验收证据位于 `docs/evidence/phase-90/`。
- Phase 91 已依据 ADR-0051 完成；验收证据位于 `docs/evidence/phase-91/`。
- Phase 92 已依据 ADR-0052 完成；验收证据位于 `docs/evidence/phase-92/`。
- Phase 93 已依据 ADR-0053 完成；验收证据位于 `docs/evidence/phase-93/`。Cloudflare 账号资源、域名和 GitHub App secret
  仍按运维 runbook 由维护者一次性配置，不属于普通安装配置。
- Phase 94 已依据 ADR-0054 完成；验收证据位于 `docs/evidence/phase-94/`。Cloudflare Git source、两个 Worker 的 runtime
  secrets 和首次生产部署仍按运维 runbook 由维护者一次性配置。
- Phase 95 已依据 ADR-0055 完成；验收证据位于 `docs/evidence/phase-95/`。其 Cloudflare Access 强制要求已由 ADR-0056
  替代；普通 intake/status/health 路径保持公开。
- Phase 96 已依据 ADR-0056 完成；验收证据位于 `docs/evidence/phase-96/`。管理员密码直登为默认路径，Cloudflare Access
  仅在需要 MFA/IdP 时作为可选外层；旧 v1 管理会话在部署后失效。
- Phase 97 已依据 ADR-0057 完成；验收证据位于 `docs/evidence/phase-97/`。GitHub Issue #240 的名称/ID 分离已贯通 Backend、
  Product API、MCP/任务投影和真实浏览器，历史回测计算身份保持不变。
- Phase 61 由维护者于 2026-08-27 授权并完成；规范与证据位于 ADR-0034、验收报告和
  `docs/evidence/phase-61/`。

当前整改批次（2026-09-09）：维护者已要求开始剩余项目；首批全接口清单及 F2 非ML
反馈发布分页核对见[本批审计](../evidence/post-u8-interface-audit/AUDIT.md)。
[ADR-0068](../architecture/adr/ADR-0068-post-u8-community-inspection-waiver.md) 已按维护者
明确指示接受：当前及之后所有开发步骤免除 Community 原实现检查；真实数据迁移验证不豁免。
本批不推进 Product Phase，不代表 F2/F6/S3 或全接口审计完成。
后续归属切片已复现并修复Factor/Signal写入口及Snapshot读取的身份/owner/workspace/kind缺口，
定向30项及独立`.19`完整CI26/26通过，独立清理通过，尚未部署；具名范围见[领域输入验收](../evidence/post-u8-interface-audit/DOMAIN-INPUT-OWNERSHIP.md)。

非 ML 原键核对维护：ResearchTask/Experiment/Artifact 精确只读接口及 MCP 扩展已实现，
定向26项与独立`.20`完整CI26/26通过，资源清理通过，尚未部署；完整 F2 仍未关闭。见[回执核对记录](../evidence/post-u8-interface-audit/RESEARCH-RECEIPTS.md)。

Backtest 原键只读核对已完成，定向15项及独立`.21`完整CI26/26通过，资源清理通过；尚未部署，范围见[Backtest 回执记录](../evidence/post-u8-interface-audit/BACKTEST-RECEIPTS.md)。

高层 backtest-task 原键核对已完成，定向16项及独立`.23`完整CI26/26通过；`.22`测试同步失败记录保留，资源清理通过，尚未部署。见[任务回执记录](../evidence/post-u8-interface-audit/BACKTEST-TASK-RECEIPTS.md)。

信号任务幂等认领、job/引用原子提交及 Worker 补数已完成，定向25项与独立`.24`完整CI26/26通过，资源清理通过，尚未部署；见[提交验收记录](../evidence/post-u8-interface-audit/SIGNAL-SUBMISSION.md)。

F2 三类研究创建持久核对维护（本地验收完成）：ResearchTask/Experiment/Artifact 的 MCP 写前登记、
有限次数原键核对、重启保持预算及 Product 只读投影已实现；独立 `.30`
完整本地 CI 30/30、真实 HTTP 超时/Gateway 重启及 Product API 桌面/手机验收通过。见[本切片记录](../evidence/post-u8-f2-research-watch/AUDIT.md)。
不将本切片计作完整 F2、S3 或全接口审计完成；F6 已交付结论不变。

DSH 旧基线退役维护：维护者已接受 [ADR-0069](../architecture/adr/ADR-0069-retire-dsh-011-build-lane.md)。
日常构建和运行仅支持 0.1.2rc1，0.1.1rc1 仅保留历史制品、来源与验收证据；
不再持续升级旧 npm 依赖。MCP Hono 4.13.7 与当前运行时整栈资格见
[退役验收记录](../evidence/dsh-011-retirement/AUDIT.md)。
本任务不推进 Product Phase，不关闭剩余 F2/S3 或 U8 长期稳定性观察。

## 生效中的 Accepted ADR

Post-U8 交付授权（2026-09-08）：维护者明确允许新增独立构建身份、重新认证，并将当前
修复分支推送至 `jefison-x/BeyondQuant` 创建 Draft PR；不合并、不部署。ADR-0061 已补充
本次范围，构建验证见[独立认证记录](../evidence/post-u8-r1/BUILD-REQUALIFICATION.md)。
这不代表剩余整改全部完成，不改变 U8 提前结束结论或 Product Phase 97。

2026-09-10 F6 实现与功能验收已完成：独立 `.29` 构建全量本地 CI 29/29、
真实 Product API 桌面/手机许可及完成状态、Gateway 重启后的三回合领域链路通过；
固定合成目标的真实模型已完成训练后预测、冻结信号、原生回测及 validated 对比报告。
任务绑定许可、24小时/8回合/900秒/累计额度、逐工具范围检查、未知预留保留及持久结算均已验收。
仅资格支持官方 `deepseek-v4-flash` 的保守 token 额度，后台搜索关闭；普通分发默认开关仍为 0，
部署使用本任务明确授权及 ADR-0015/0059 精确门禁，不追溯授权历史研究。
见 [F6 验收](../evidence/post-u8-interface-audit/F6-CONTINUATION.md)。
此结论不关闭完整 F2/S3/全接口审计，不改变 Product Phase 97 或 U8 提前结束结论。

F6 前期维护决策（以下保留历史事实）：[ADR-0065](../architecture/adr/ADR-0065-task-continuation-budget-admission.md)
已于 2026-09-08 获维护者明确批准，状态为 Accepted。已证实 SDK 单次 max_tokens 不等于
任务累计预算；预算账本合同及官方接口资格核查继续进行。接口全调用覆盖尚未通过资格验证，
后台执行保持关闭，不将 ADR 接受或合同存在计作 F6 完成，不改变 Product Phase 97。

2026-09-10 F6 接口复核：准确 `0.1.2-rc.1` npm 包公开了 `llm/stream` 调用前
拦截接口，已记录制品摘要与静态调用位置；不能再把 SDK 参数缺失推定为所有官方接口缺失。
既有两项无网络预算反例复测通过；bundled runtime 加载、全调用覆盖与预算执行仍未合格。
下一步为该公开接口的隔离加载和发出前拒绝资格验证，见
[F6 接口复核](../evidence/post-u8-r1/F6-STREAM-INTERFACE.md)。不启用后台续接。

F7 当前维护决策：[ADR-0066](../architecture/adr/ADR-0066-domain-validation-call-admission.md)
已于 2026-09-08 获维护者回复“批准。”接受，状态为 Accepted；先隔离验证，再接入首批两工具。
仅 AgentRun 引用/进程 generation 不足以作为该凭证；首批两工具的持久准入已本地验证，
该首轮证据当时未关闭全部矩阵；最新 F7 完成范围见下方具名结论。

后续真实 HTTP 资格核查确认官方 MCP 请求缺少 Adapter 可关联的逐调用根身份，输入摘要
匹配不能单独关闭此门禁。[ADR-0067](../architecture/adr/ADR-0067-root-scoped-runtime-call-identity.md)
提出每根回合独立进程与可信根 header，已于 2026-09-08 获维护者批准，状态为 Accepted；
隔离实现已通过下述本地验证，未改变生产拓扑；首轮不计作 F7 全项完成。

F7 当前完成结论：ADR-0066/0067 首批普通/ML 策略的安全字段诊断、持久一次修正、
无进展原生停止、根归属、迟到请求、取消/提交竞争及真实断连回执已完成具名验收；
新增 `.15` 独立源身份、完整本地26/26与清理核验通过。见
[F7 最终矩阵](../evidence/post-u8-r1/F7-ACCEPTANCE-MATRIX.md)。
不推广为所有工具接入同一账本、付费模型自主研究质量或生产验收通过；
F6 后台续接仍关闭，S3 与全流程/接口剩余审计继续独立推进，数据扩容仍暂缓。

当前已接入逐根进程、公开上下文恢复、私有调用证据投递与两工具持久纠错准入，
两工具真实 native stop 首次失败已定位并通过定向重测。独立 post-u8.10 构建的本地 CI
26/26 项通过；真实 Chrome desktop/mobile、两工具跨服务 schema-stop、持久纠错回执及
Backend/Gateway 重启恢复验证通过，未调用付费 Provider。完整自然语言研究语义及
multi-child/迟到 HTTP/撤销矩阵仍有仅组件级证据的项目；不得部署或关闭 F7。
具体通过/失败边界见[纠错台账实现切片](../evidence/post-u8-r1/F7-CORRECTION-LEDGER.md)。

S3 历史成分准备继续隔离整改：明确日期的封闭准备范围及指数入库防错、旧覆盖防丢失、
同日冲突保护已通过合成定向测试。真实 Community 缓存尚缺只读来源，未认证历史覆盖，
专用 data-demand/Worker/Product 闭环尚未接入；不计作 S3 完成，不进行数据扩容。
详见[历史成分准备记录](../evidence/post-u8-r1/S3-HISTORICAL-PREPARATION.md)。

原会话任务发现缺口已补只读 Backend/MCP 上下文，禁止工作区最新任务回退和隐式重建。
独立 `.12` 构建的架构 224 项、MCP 全套及 Backend 490 项（1 skipped）通过；三根真实
Product/官方进程的合成恢复探针通过：原目标保留、经 MCP 找回原任务、明确新指令送达。
该脚本不代替真实模型研究语义验收，F7/S3/F6 仍未全部关闭；未部署。
见[原任务发现证据](../evidence/post-u8-r1/ORIGINAL-TASK-DISCOVERY.md)。

- [ADR-0064](../architecture/adr/ADR-0064-runtime-crash-recovery-evidence.md)：已接受并完成首版本地崩溃证据恢复；仅原本地卷、同次主机启动且原排他锁身份可证时收尾，不续跑模型。主机重启/复制卷/无日志保留不可判定。验证见 `docs/evidence/post-u8-r1/ADR-0064-VERIFICATION.md`，未部署，其他 Post-U8 整改未全部关闭。

- [ADR-0063](../architecture/adr/ADR-0063-disabled-owner-terminal-cleanup.md)：维护者已接受禁用身份后既有 AgentRun 的受限终态清理；本地实现及 Backend 完整回归已通过，未部署。历史未绑定记录及其他 Post-U8 流程整改仍未关闭。

- Post-U8 reliability maintenance：**ADR-0062**，具名修订ADR-0045/0046；不授权生产部署或数据扩容。

- Development governance / CI integrity maintenance：**ADR-0059**。本次只授权治理、CI 与 DSH 方案修正；
  不推进 Product Phase，不授权 DSH 实施或生产部署。

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
- Market Research Web Search evidence boundary：**ADR-0039**
- Plugin Center deployment control plane：**ADR-0040**
- trusted stock-pool producers：**ADR-0041**
- trusted multi-index catalogue：**ADR-0042**
- auditable machine-learning research pipeline：**ADR-0043**
- Product Agent 产品能力目录与任务化接入：**ADR-0044**
- Agent 按需数据准备与通知：**ADR-0045**
- Durable conversation runtime rehydration：**ADR-0046**
- Provider-budget-aware data preparation：**ADR-0047**
- Extensible machine-learning components and regime routing：**ADR-0048**
- Product Feedback and trusted GitHub Issue publisher：**ADR-0049**
- ML study archive and unified management actions：**ADR-0050**
- Agent approval center and conversation continuation：**ADR-0051**
- Central Feedback Hub and conversation submission：**ADR-0052**
- Cloudflare-native Central Feedback Hub：**ADR-0053**
- Cloudflare GitHub automatic deployment：**ADR-0054**
- Central Feedback moderation console：**ADR-0055**
- Central Feedback direct admin password and login throttling：**ADR-0056**
- Backtest readable name and catalog identity：**ADR-0057**

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

Phase 64 依据 ADR-0039 建立 `web-research-evidence.v1` 与专用
`byq_web_evidence_create` promotion boundary；Market Research 最多四条有目的的 query，按
PRIMARY/SECONDARY/AUXILIARY/UNKNOWN 治理来源，并显式区分 publication、retrieval、research
as-of、trading session 与 persisted cutoff。Web evidence 永远是 research-only，不能成为
Factor/Strategy/signal/Backtest deterministic input。Factor、Strategy、Backtest 仍无 Web
capability；credentialed Product journey 已通过，DSH baseline 未升级。

Phase 65 依据 ADR-0040 建立 admin-only Plugin Center、PostgreSQL desired policy/request/audit、
有界 Product API projection 与 immutable desired-policy snapshot。trusted deployment lane 使用
Phase 63 deterministic builder 生成 composition/profile/hash，经正常 image build/restart 后只在
Runtime Adapter readiness identity 匹配时显示 Active。真实浏览器 journey、普通用户 403、
restart recovery、desktop/mobile accessibility 100 和 same-origin Network review 已通过；没有
runtime install、Browser direct DSH、source write、secret projection 或 DSH baseline 升级。

Phase 66 依据 ADR-0041 接受指数型/动态股票池生产边界：owner-scoped versioned definition、持久化
materialization run 与 ADR-0020 immutable snapshot 分离；指数只消费 ADR-0030 canonical data 并
禁止 look-ahead，动态只允许 closed declarative point-in-time rule。Product 只提交意图，trusted Data
Worker 原子物化，失败不推进 current pointer。Community 指数语义分类为 `PORT_LOGIC`/`PORT_UX`，
动态占位和 sample data 为 `DROP`；本阶段无 runtime implementation。

Phase 67 依据 ADR-0041 交付指数型股票池：validated index catalog 只投影完整 canonical coverage；
Product 创建 owner/workspace-scoped definition 与幂等任务，trusted Data Worker 选择不晚于请求日期的
最新完整权重、转换 percent 单位并原子追加不可变 snapshot。失败与晚到旧任务不回退 current pointer；
API/UI 展示 definition、物化状态、成员和历史。PostgreSQL、Gateway、frontend、真实 Chromium 与
Chrome DevTools MCP desktop/mobile journey、same-origin Network review 均通过，未调用 Provider 或
暴露 worker internal。

Post-Phase 62 Trusted Time Maintenance 依据 ADR-0037 将服务器权威自然时间作为 DSH
逐轮动态 runtime context，并通过 BYQ MCP 暴露已有 SSE calendar 与 persisted market
snapshot 的有界只读截止语义。它是维护修复，不改变 Phase 62 完成状态，也不定义下一
Product Phase。

Post-Phase 65 Web Evidence Persistence UX Maintenance 依据 ADR-0039 clarification，将网页来源
内部 ID 改为 BYQ 根据已验证 URL 生成，以单一 PostgreSQL transaction 创建 ResearchTask 与
Evidence Artifact，并把 MCP 结果收敛为中文 saved/not-saved 状态与来源数。旧保存失败不再在
无关对话中主动重播；该修复不改变 Phase 65 完成状态，也不定义下一 Product Phase。

Post-Phase 65 Paper Trading Navigation Maintenance 将模拟操盘从 User Center 移回主业务导航，
固定在回测管理之后，并复用 Phase 46 `ManagementWorkspace` 的目录/详情层级。旧
`/user/paper-trading` 深链保留为兼容重定向；Paper Trading 的 Product API、授权、持久化和
仅模拟交易边界均未改变。该修复不改变 Phase 65 完成状态，也不定义下一 Product Phase。

Phase 68 Dynamic Stock Pools 已完成 ADR-0041 的封闭 `dynamic-stock-pool-rule.v1`、时间点
非权威 preview、确定性 evaluator、trusted Data Worker 物化与交易日历 cadence。规则仅允许
白名单字段、运算符、bounded filters/top_n 和显式 missing/weight policy；Browser、DSH、插件、
Python、SQL 与 URL 均不能成为 evaluator。definition/run 状态、waiting/stale/failure recovery、
不可变 snapshot/current pointer、Product API 与 responsive UI 均已实现。真实 PostgreSQL、完整
Compose smoke、Product Chromium desktop/mobile 和独立 Chrome DevTools MCP same-origin/Console/
Lighthouse review 均通过；Community dynamic placeholder 已按 inventory 分类为 `DROP`。

Phase 69 Integration and Product Closure 已统一 custom/index/dynamic catalog，并提供封闭
`stock-pool-readiness.v1` 状态和确定性的 `stock-pool-snapshot-diff.v1`。生产者资产导出只携带
portable intent；导入后强制 `inactive` pool 与 `draft` definition，必须重新验证和物化，历史快照及
权威状态不会跨 workspace 信任。Operations 仅暴露有界 definition/run 摘要，不暴露 worker payload。
完整 PostgreSQL、Gateway、Runtime、MCP、frontend、mock/real E2E、Compose smoke、two-user isolation、
Backend/Gateway restart recovery，以及 Chrome DevTools MCP desktop/mobile/same-origin/Console/
Lighthouse 验收均通过；证据位于 `docs/evidence/phase-69/`。

Phase 70 Index Catalogue Coverage Closure 已建立六个 canonical 候选的 BYQ-owned 封闭目录，
由 trusted Data Worker 以 62 日窗口逐指数同步并隔离失败。`market-index-weights-v2` 使用精确
`(index_symbol,snapshot_date)` evidence 验证成员、权重和与内容哈希；旧月度数据只在重新验证后
进入目录。Product API、Data Center 和股票池创建界面展示可用/等待状态，只有 verified snapshot
可创建。Backend/Gateway/frontend、PostgreSQL forward repair、完整 Compose、真实 Product API 和
Chrome desktop/mobile 验收证据位于 `docs/evidence/phase-70/`。

Post-Phase 70 Conversation Completion Presentation Maintenance 使用 ADR-0033 已有的 text-only
最终回答锚点收起独立公开进度气泡，避免答案显示后短暂闪回“正在思考”。Runtime lifecycle、
停止入口、WorkflowTrace、公开活动 allowlist 与 hidden-reasoning 边界不变；该维护修复不改变
Phase 70 完成状态，也不定义下一 Product Phase。

Phase 71 Auditable Machine Learning Contract Baseline 依据 ADR-0043 完成只读 Community ML
实现分类，并冻结 `ml-strategy-version.v1`、`ml-training-run.v1`、
`ml-feature-snapshot.v1`、`ml-model-artifact.v1` 和 `ml-prediction-snapshot.v1`。首版只允许
独立 trusted CPU Worker 中的 LightGBM 4.7.0、封闭价格/成交量特征、chronological split、原生
文本模型和现有 ADR-0017 冻结信号。Community 的 Backtest 内 `fit/predict`、任意用户 source、
pickle/joblib、Provider/DSH/Browser 训练路径均为 `REPLACE`/`DROP`。本阶段没有修改运行时。

Phase 72 Trusted Training and Model Artifact 实现封闭 ML StrategyVersion validation/approval，
持久化 `waiting_for_data → queued → running → completed/failed/cancelled` 训练任务和数据库
claim/lease/retry/attempt fencing。FeatureSnapshot 使用冻结股票池、canonical session、前复权
research bars 与历史指数 membership，严格隔离 chronological split 且 prediction rows 不含 target。
独立非 root `ml-worker` 固定 Python 3.13 / LightGBM 4.7.0 / NumPy 2.3.3、单线程 CPU 和有限参数，
在无 Provider/模型凭证环境生成 native text 模型对象、SHA-256、validation metrics、runtime/image
identity 与完整 lineage。模型对象使用独立 volume；Worker runtime 健康必须等待 Store 初始化完成。
Backend 不引入 LightGBM 依赖；本阶段不提供 Product API/UI，也不生成预测、信号或 Backtest。

Phase 73 Out-of-sample Prediction and Signal Closure 实现持久化 `ml-prediction-run.v1`、claim/lease/
retry/attempt fencing，重新验证 model object size/hash、runtime、feature order 与完整 lineage 后，只对
无 target/label 的 prediction split 推理。PredictionSnapshot 按 `(score DESC, symbol ASC)` 排名；
approved `top_n_equal_weight` policy 使用冻结 capital、当日可见 close 和 lot size 生成仅包含进入/退出
的明确数量信号。标准 SignalSnapshot 保存 Strategy Approval、Model、Feature、Prediction、Pool 与
policy identity；现有 Backtest 只消费冻结 manifest，不加载 LightGBM、不重新排名或训练。本阶段没有
Product API/UI，也没有引入 HIST。

Phase 74 Product Closure 实现 owner/workspace-scoped Gateway/Product API 安全投影、typed client 和
真实模型研究工作台。用户可从冻结股票池与时间窗口创建不可变 ML StrategyVersion，经人工批准后查看
持久化训练状态、模型指标、确定性样本外排名、冻结信号并提交现有 native Backtest。模型对象路径、
FeatureSnapshot/raw rows 和 raw Backtest manifest 不进入浏览器。完整 PostgreSQL/Compose journey、
Worker restart identity、two-user isolation、六条真实 Product API 浏览器旅程，以及 Chrome DevTools MCP
desktop/mobile Accessibility/Best Practices 100、same-origin Network 和空 Console 验收均通过；证据位于
`docs/evidence/phase-74/`。

Phase 75 Product Capability Contract Baseline 依据 ADR-0044 建立 BYQ-owned、版本化的产品能力目录，
统一稳定路由、普通/管理员受众、前置条件、产品用途、Agent 支持等级、MCP 映射和真实限制。CI 验证
目录 identity、固定 route 和已登记 MCP tool；Community 的帮助/Agent UX 只作 `PORT_UX` 证据，旧
Agent API/runtime/direct internal path 保持 `DROP`/`REPLACE`。本阶段未增加 Product DSH tool、领域写、
第二工作流或 UI。

Phase 76 Xiaoba Product Guide 交付自动发现的 `byq-product-guide`，以精简 SKILL 路由到市场研究、股票池/
策略、模型研究/回测、模拟操盘、用户设置和管理员六类 reference。只读 MCP 对目录做有界搜索，返回
`product-help-result.v1` 与固定 route；管理员结果默认隐藏，显式说明也不授予权限。模型配置与量化模型
研究被明确区分，Product DSH 仍不挂载源码，说明请求零领域 mutation。

Phase 77 Backtest Task Facade 将 Community 的预检、幂等、进度与取消 UX 分类为 `PORT_UX`，旧
Agent API/VectorBT 分类为 `DROP`。`backtest-task.v1` 使用 SignalProducerJob 稳定身份并从既有组件派生阶段，
prepare 不触发补数或领域写；create 可请求现有数据修复并排队可信信号生成，execute 只消费完成后的不可变
signal snapshot，BacktestJob 继续负责重试、结果对象和 lineage。

Phase 78 ML Agent Create/Training 将 Community 的“先确认可用模型能力再配置研究”意图分类为
`PORT_UX`；任意 sklearn/scipy/statsmodels/XGBoost/LightGBM import、在回测内 fit/predict 与旧 Agent
工具策略分类为 `DROP`/`REPLACE`。新能力只接受 ADR-0043 的封闭 LightGBM 合同，通过 BYQ MCP
操作领域对象，并把策略人工批准、Agent action approval、训练执行状态明确分离。

Phase 79 ML Prediction/Backtest Conversation Closure 增加 `byq_ml_prediction_create/get`，并为
PredictionRun 派生稳定的 `backtesttask_ml_*` 身份，复用 Phase 77 的 get/execute/cancel 投影和既有
BacktestJob。真实 PostgreSQL、六条 no-mock Product API 旅程、Worker restart identity、双用户隔离、
desktop/mobile Chrome MCP 和说明/准备/执行行为评测均通过；证据位于 `docs/evidence/phase-79/`。

Phase 80 Xiaoba Data Demand and Automation-channel Repair 依据生产会话证据，将 DSH 子智能体
`toolFilter` 改为实际注册的 `mcp__byq__*` 名称并增加漂移测试。`data-demand.v1` 在管理员个人工作区内
接受最多 500 只冻结股票和五年日期范围，按 readiness 上限分片并复用既有 durable repair/session job；
`ready` 仅由当前完整性验证产生。小巴通过 create/get 与下一回合 context 通知恢复研究，数据中心通过
Product API 展示同一状态；未引入第二同步引擎、Provider 直连或 Backend 主动模型执行。验收证据位于
`docs/evidence/phase-80/`。

Phase 81 Durable Conversation Runtime Rehydration 依据生产故障证据，将稳定 BYQ session/trace 与
每次新建 DSH process 的私有 generation identity 分离。Gateway 只回灌最近、已完成且用户可见的
有界 Product 消息，尾部未回答 user turn 不重复注入；Runtime Adapter 二次验证合同，并将 DSH
`error`/未知结束原因安全投影为 failed。真实生产 Chrome 旅程证明首轮完成、30 秒 idle release、重开
同一会话和上下文追问闭环；桌面/移动端、同源网络、空 Console 和临时会话清理均通过。证据位于
`docs/evidence/phase-81/`。

Post-Phase 74 Model Research Navigation Maintenance 将量化模型研究从个人“模型配置”提升为
“策略管理”与“回测管理”之间的一级业务工作台；个人模型设置继续只管理 LLM 凭据、档案与 Agent
绑定。策略编辑器为研究任务、策略身份、说明、参数、数据依赖和 Python 脚本提供持久可见标题与
accessible name。该维护不改变 Product API、ML lineage、策略生命周期、授权或 runtime 边界。

Post-Phase 74 CI Reliability Maintenance 将 PR 检查改为 change-impact selective profile，
保留 Nightly/manual Full；以 run ID + attempt 隔离 Docker 资源，并以 signal trap、workflow
always-cleanup、重型任务锁、内存 preflight 和 zero-resource verification 保证取消/失败后收口。
该维护不改变 Product、Domain、DSH、MCP 或持久化边界。

Post-Phase 82 Product Agent Runtime Reliability Maintenance 为每个 prompt 增加五分钟总墙钟、
三分钟子 Agent 和两分钟无公开进度看门狗；超限只关闭该会话独占 DSH process，并保留既有
fresh-generation resume。回测分析 MCP 对同一会话/任务的五分钟分页读取限制为六次，超过后
不再访问 Backend。后续生产会话证明将预算耗尽标记为工具错误会使子 Agent 失败且父 Agent
无法收口；维护修复改为在每次成功读取中返回剩余次数，并将耗尽投影为非错误的有界结束信号，
要求立即使用已有证据回答。该维护不创建第二 Agent loop，不改变 Domain 数据或当前 Phase 状态。

Post-Phase 82 Benchmark UX Maintenance 将新 Product 策略草稿和小巴策略提案在用户未指定时的
默认对比基准设为沪深300（`000300.SH`），并在回测向导展示已批准版本实际声明的冻结基准。
历史无基准版本保持不变。Community 策略/回测页仅作为通用布局参考，分类为 `REFERENCE_ONLY`；
本维护沿用 ADR-0030 的 declared-data 与 immutable-input 边界，不复制 Community 执行架构。

Post-Phase 90 Management Action Consistency Maintenance 依据 ADR-0050 将股票池、策略、模型研究和回测
详情的删除、归档、停用、恢复与取消集中到统一管理操作区，同时保持各自领域状态机。模型研究未执行时仅
可软删除，产生运行证据后仅可在全部运行终态时归档，并支持恢复；默认目录隐藏归档项，但训练、模型、预测、
信号和回测证据保持可读、不可变。Browser 只消费 Gateway/Product API 返回的权威 action projection。

## 当前授权边界

- Product Phase 49-97 与相应 Accepted ADR/计划均已完成；**下一 Product Phase 尚未授权**。
  独立数据/资格轨道 Phase 98 已授权、99/101 完成、100 进行中；当前维护为 D15 整改；完整权威状态
  见顶部“权威当前状态”。
- 2026-09-19 维护收口（ADR-0047 聚合边界、运行/续接连续性与只读归档审计）已完成并记入本文与
  [实现计划](IMPLEMENTATION_PLAN.md)；它是维护，不推进 Product Phase，也不改变上一条授权状态。
- ADR-0077（数据就绪自动续接）已于 2026-09-19 获维护者接受（Accepted）；生产当前运行其实现。
- ADR-0078/0079/0080/0081 已于 2026-09-19 获维护者接受（Accepted）。
- Phase 82 与 ADR-0047 已完成；50,000 保持原子 readiness 分片上限，不是 Tushare
  额度或完整数据任务上限。
- ADR-0044 授权的 Phase 75–79、ADR-0045 授权的 Phase 80、ADR-0046 授权的 Phase 81、
  ADR-0047 授权的 Phase 82 已完成。ADR-0048 的 Phase 83–86 已完成。ADR-0049 的 Phase 87–90 已完成；
  当前完成范围不包含 HIST、实盘券商、AutoML、GPU、
  强化学习或在线学习。
- BeyondQuant Next v1.0 正式发布时必须禁用 GitHub auto-merge，并恢复单维护者 Human
  Merge Gate。

Git SHA 不是 Phase state。干净基线始终通过 `git fetch origin` 后执行
`git rev-parse origin/main` 动态取得；本文档不得硬编码 SHA，也不得描述临时 PR/merge
状态。
