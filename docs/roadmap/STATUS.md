# BeyondQuant 状态

研究流程连续性维护：见[下一阶段整改目标](RESEARCH_HANDOFF_PLAN.md)，先完成审批后原目标交接，再补持久交接与授权续接连接；不推进 Product Phase。

<!-- byq:current-completed-phase=97 -->

本文档顶部是当前 Phase 状态的事实来源，使新的 Codex session 不会从 commit history 推断状态。
下方交付历史保留当时配置与验收事实，不作为当前运行参数或通用合并/部署授权；后续具名修订可能已替代它。

浏览器验收现行规则：依据 ADR-0059 的 2026-09-09 维护者授权修订，取消 Chrome MCP
专属要求，使用测试框架管理的真实浏览器即可；不依赖系统 Chrome 或个人浏览器调试连接。
真实 Product API、业务断言及按影响要求的浏览器证据仍必须满足。以下历史工具记录不改写。

## 权威当前状态（唯一权威条目，2026-09-21）

本节是 Product、维护与依赖资格三条轨道“当前步骤 / 下一步 / 授权来源 / 停止条件”的唯一权威条目；
下方同名历史段落只保留当时事实，不再独立表达授权。顶部机器 marker
（`byq:current-completed-phase=97`）只表示最近完成的 **Product Phase**，不表示独立数据/资格轨道
状态，也不表示下一 Product Phase 已授权。

<!-- byq:v090-closeout-audit=complete -->
<!-- byq:v090-full-interface-rebaseline=complete -->
<!-- byq:v090-composite-research=complete -->
<!-- byq:v090-adr-decisions=complete -->
<!-- byq:v090-step5-b1-subagent-child-crash=blocked-external -->
<!-- byq:v090-step5-gsplit-decision=complete -->
<!-- byq:v090-step5-b2-adapter-restart=blocked-external -->
<!-- byq:v090-session-containment=containment-classification-delivered -->
<!-- byq:v090-step-safety-design=inventory-design-delivered -->
<!-- byq:v090-step5-b3-terminal-adapter-restart=complete -->
<!-- byq:v090-step5-b4-terminal-dsh-runtime-restart=complete -->
<!-- byq:v090-dsh-provider-qualification=blocked-external -->
<!-- byq:adr-0084=accepted -->
<!-- byq:session-failure-containment=in-progress-blocked-internal -->
<!-- byq:v090-business-recovery=implementation-delivered -->
<!-- byq:v090-business-recovery-acceptance=real-passes -->
<!-- byq:session-failure-containment-next=real-recovery-acceptance-then-coherent-dsh-0.1.5rc1-upgrade -->
<!-- byq:phase-100-slices-frozen=P100-C,P100-D,P100-E -->
<!-- byq:phase-100-p100-c=paused-not-delivery -->
<!-- byq:v090-dsh-default-upgrade=promoted -->
<!-- byq:v090-d15-superseding-assessment=established -->
<!-- byq:build-revision=dsh-0.1.5rc1-post-u8.201 -->

| 轨道 | 当前步骤 | 下一步 | 授权来源 | 停止条件 |
|---|---|---|---|---|
| Product | 最近完成 Phase 97（marker 97） | 未授权任何新的 Product Phase | 维护者阶段性授权 + 本文件 next phase | 一阶段一 worktree/Draft PR；Human Merge Gate；不得自授新 Phase |
| 数据/资格 | Phase 98/99 `COMPLETE`；Phase 100 `PAUSED`：P100-A/P100-B 已并入 `main`，P100-C 只存在于暂停且未交付的 Draft #338，P100-D/P100-E 冻结；Phase 101 `COMPLETE`。S3/历史成分准备属于 0.10.0，不是 0.9 gate。 | 等待 0.9 的**完整** BYQ failure-containment gate 收口（当前 `IN_PROGRESS / BLOCKED_INTERNAL`；本 PR 只交付 containment + 只读分类，不生成 superseding assessment）；之后仅在维护者恢复 Phase 100 时继续 P100-C/D/E，并在 0.10 资格结束后执行 1.0 `core`/`extended`/`deferred` 范围复核 | Phase 100 原授权 + ADR-0074/0084 | 仅 Tushare；不得从未审查分支推断完成；数据来源、时点、单位、许可与完整性失败继续 fail closed；不因外部可选能力冻结无关调查 |
| 维护（当前） | **ADR-0084 门禁合理化与 0.9 收口治理**：维护者已于 2026-09-21 明确接受完整决定；B3 `terminal-adapter-restart` 与 B4 `terminal-dsh-runtime-restart` 保持候选/资格层 PASS；B1 `subagent-child-crash` 与 B2 `subagent-byq-adapter-restart` 继续保持真实 `BLOCKED_EXTERNAL`，历史 D15-G 继续为 `NO_GO` 且不改写，但这些外部能力不再是 0.9 收口、候选兼容判断、受限 R3 失败隔离或无关 0.10 工作的全局硬前置。另已完成独立监控切片 `v090-dsh-provider-qualification`：DSH rc.2 与 alpha.2 均无进程外 continuable provider，保持 **`BLOCKED_EXTERNAL`**，**未升级依赖**（证据 `docs/evidence/v090-dsh-provider-qualification/`）。**本 PR（`codex/v090-session-failure-containment`）只交付 containment + fail-closed 只读恢复分类**（marker `v090-session-containment=containment-classification-delivered`）：执行者失联检测、未完成 run→`interrupted`（仅在 fenced containment 匹配同一 session/trace 与精确 run 时）、旧 generation/epoch 与迟到终态 fencing、真实 before/after 业务状态观测、未知副作用与未验证 authority 一律 `paused`。**完整 business-recovery gate（权威服务端 step-safety + budget binding + safe rescheduling）仍为 `IN_PROGRESS / BLOCKED_INTERNAL`**，本 PR 不据此声明门禁完成，也不进入 D15 superseding assessment。 | **本 PR（`codex/v090-business-recovery-impl`）交付 #351 最小设计的真实垂直切片实现**（marker `v090-business-recovery=implementation-delivered`，证据 `docs/evidence/v090-business-recovery/`）：Backend 在既有 `research_tasks.continuation_budget` 行内权威分配/复用 `recovery_attempt`（`FOR UPDATE` + trigger-key 去重，cap 3，无新 store/migration）；封闭 carrier `{attempt_key, ordinal, trigger_key, interrupted_run_id, interrupted_generation, containment_attempt, interrupted_executor_epoch, snapshot_tail_sequence, snapshot_digest}` 由 Backend 铸造；Gateway 只转发封闭 authority；Adapter 在 `record.lock` 内先校验 digest/containment 再重算并原子比较当前 snapshot 与 `idle=true`，之后才创建/安装 target generation 并返回 accepted receipt（target epoch/generation/run）；recovery-mode envelope 仅允许只读或精确复用原安全调用五元组；未知副作用/成本、预算/floor、snapshot 变化、旧 epoch/generation、`ordinal > 3` 一律 fail closed。**本 PR（`codex/v090-business-recovery-acceptance`）已完成真实隔离服务组合验收**（marker `v090-business-recovery-acceptance=real-passes`，证据 `docs/evidence/v090-business-recovery-acceptance/`）：真实 Adapter OS 进程终止→containment 把精确未完成 run 记为 `interrupted`→真实 Gateway consumer→Backend 铸造 carrier→Adapter 安装新 target generation，9/9 场景 PASS；并发现并最小修复一个真实 #352 缺陷（丢失 run 的原始 prompt 被 `reconcile_prompt` 误报 `accepted`，导致 Gateway 在 recovery seam 之前短路）。**以下 0.9 收口顺序保留**：本 gate → 真实 recovery 验收（本 PR 已交付）→ 正式把仓库默认 dependency/selector 升级到 coherent DSH `0.1.5-rc.1`（含 rollback/业务验证）→ D15 superseding assessment → 0.9 收口。**本 PR 不把既有候选资格写成正式升级完成，不生成 superseding assessment，不启动 0.10**（superseding assessment **尚未生成**）。**2026-09-22 具名 D15 superseding assessment 已建立**（marker `v090-d15-superseding-assessment=established`，证据 `docs/evidence/d15/d15-superseding/`）：该评估独立派生实际采用范围的候选兼容（PASS）与晋升（仅仓库默认）、确立 bounded R3 范围且 `R3_RESUME = NO`、保持 B1/B2 `BLOCKED_EXTERNAL` 与历史 D15 verdict 不改写、且不把原生独立 child resume 写成已实现；**本 PR 不执行最终 0.9 收口，不部署、不 tag/release、不启动 0.10**。 | 维护者明确接受 ADR-0084；ADR-0081/0082/0058/0071/0074 的 superseding 修订 | 不改写历史 verdict；不实现 DSH 进程外 provider 或第二通用 harness；不自动解冻 R3；不切换生产 selector；不部署；不创建/移动 tag/release；不恢复 Phase 100；每个实现切片使用独立 worktree/PR |
| 依赖资格（D15） | **当前资格状态（B4 之后，2026-09-21）**；ADR-0084 已接受：`terminal-adapter-restart` = **PASS**、`terminal-dsh-runtime-restart` = **PASS**（均为候选/资格层）；B1 `subagent-child-crash` 与 B2 `subagent-byq-adapter-restart` 为 `BLOCKED_EXTERNAL`；独立监控切片确认 DSH rc.2/alpha.2 provider 资格仍 `BLOCKED_EXTERNAL`（无 out-of-process provider，未升级依赖）；ADR-0083 仅候选/资格层最小实现完成；R4 / production wiring NOT implemented。D15-G **未重跑**，按当前 B1/B2 状态即使重跑仍为 `NO_GO`；**历史已提交快照（不改写）**：D15-4/D15-5/D15-G committed evidence 保持原样。外部 blocker 只阻塞原生独立 child 恢复声明，不再形成全局停止。2026-09-22 具名 D15 superseding assessment 已建立（`docs/evidence/d15/d15-superseding/`）：B1/B2 仍 `BLOCKED_EXTERNAL`、B3/B4 候选 PASS、实际采用范围候选兼容 PASS 且晋升仅仓库默认、bounded R3 范围确立且 `R3_RESUME = NO`、原生独立 child resume 未实现。 | **已生成具名 D15 superseding assessment**（marker `v090-d15-superseding-assessment=established`）；完整 failure-containment gate 已通过真实隔离验收，按实际采用范围判断候选兼容与晋升已完成；下一步为**独立** 0.9 收口（维护者门禁，本 PR 不执行，且不启动 0.10） | ADR-0084 + ADR-0081/0082；历史证据与 B3/B4 current overlay | `R3_RESUME` 不因文档决定自动变为 YES；不得把 B1/B2 标为 PASS；不得改写历史 D15 verdict；生产切换、部署和 release 独立授权 |

## 0.9 closeout governance & gap ledger audit（2026-09-20，历史审计快照）

> **历史快照说明（state-consistency）：** 本节与 `docs/evidence/v090-closeout/` 的机器可读字段
> （`gap-ledger.v1.json`、`acceptance-matrix.v1.json`、`DSH-015RC1-CLOSEOUT-SLICES.md`）是
> base `.174` 的**审计时快照**，保留当时事实，**不是**当前 D15/slice 状态的唯一权威。当前
> 资格状态以本文件顶部“维护（当前）”、B3 权威段、以及 closeout JSON 内的
> `current_state_after_b3` overlay 为准；`docs/evidence/d15/d15-5/` 与 `docs/evidence/d15/d15-g/`
> 的 committed verdict 保持不改写。审计时“两 terminal 切片未开始 / ADR-0083 未实现”的表述是
> 历史快照，已由 2026-09-21 B3 执行与 ADR-0083 候选/资格层最小实现取代，但 D15-G **未重跑**、
> 仍为 `NO_GO`（即使重跑仍为 `NO_GO`，因 B1/B2 非 PASS）。

本批是**审计/治理**，不推进 Product Phase，不实现 Proposed ADR-0082/0083，不切换生产 selector，
不 deploy，不创建/移动 tag/release。base 为动态取得的 `origin/main`（不在本文硬编码 SHA）。
机器可读交付见 `docs/evidence/v090-closeout/`：gap ledger、acceptance matrix、beta-vs-formal、
DSH slices、ADR-0082/0083 sufficiency；一致性由 `tests/test_v090_closeout_governance.py` 断言。

Phase 100 冻结：P100-A（#286）与 P100-B（#337，已并入 base）为已完成事实；P100-C 仅在隔离分支
`codex/phase-100c`（Draft PR #338）存在**未审查实现提交**，**paused、not delivered、未审查、不并入 `main`**；
不得从该分支推断业务完成。P100-D/P100-E 冻结。Phase 100 不因此关闭；维护者未授权恢复前不得继续。

**版本范围（关键）**：S3 / 历史成分准备属于 **0.10.0**（`VERSION_PLAN` 的 0.10.0 行），**不属于 0.9
closeout gate**。历史 Post-U8 S3 调查保持 `blocked` 事实，但在 ADR-0068/AGENTS 规则 21 下缺失
Community 来源不是开发阻塞；它移交冻结的 Phase 100（用 Tushare P100-C/P100-D 时点证据解决，不申请
Community 豁免、不用当前关系回填）。**0.9 严格顺序不以 S3 开头，也不被 S3 阻塞。**

0.9 严格串行顺序与每切片停止条件：

1. 本审计（本分支）→ Draft PR，停在 Human Merge Gate。
2. full-interface 逐接口台账在候选 base commit 重新达到 `complete=true`。
3. 复合研究故障回归（改进策略→审批→训练→预测→回测→新旧比较 + R1–R5 故障矩阵）。
4. ADR-0082 维护者决定（Proposed→accept/modify/reject）；ADR-0083 同。**已于 2026-09-21 执行**：
   ADR-0082 modified accept（只选 Option 1，Option 2 被拒）、ADR-0083 as-proposed accept；见本文件
   “0.9 ADR-0082/0083 maintainer decision”段，决定记录 `docs/evidence/v090-adr-decisions/`。
5. D15 pre-gate 修复切片：
   - `subagent-child-crash`（owner `d15-4-child-provider-remediation`；若 0.1.5-rc.1 无进程外
     continuable provider 则为 **external blocker**，不得指派给 post-GO R6）。**已于 2026-09-21
     执行首切片并确认 external blocker**（`docs/evidence/v090-d15-child-provider-remediation/`：
     真实原生 gate 证明唯一 continuable provider 为 in-process，进程外 provider 全部
     `UNSUPPORTED_CAPABILITY`）；**需维护者 gate-order 决定**后才可继续；
   - `subagent-byq-adapter-restart`（owner `d15-4-candidate-composition-hookup`）——**已于
     2026-09-21 在 G-split 内执行**（真实隔离候选镜像 composition/restart 探针 + fail-able
     observer）：generation A 真实 `startContinuable` 并持久 child/委派/goal 链接，generation B
     全新 OS 进程无法经 committed BYQ composition 重绑 child；**保持 BLOCKED（external/dependency）**；
     证据 `docs/evidence/v090-step5-b2-adapter-restart/`；
   - `terminal-adapter-restart`（owner `d15-5-candidate-attachment-layer`，非 post-GO R4）——**已于
     2026-09-21 执行**：候选/资格层最小 `TerminalAttachment` 生命周期实现并验证 **PASS**（native
     可达分支重绑同一 durable attachment，native 丢失分支诚实 `lost`/`interrupted`，fail-able
     observer 区分正确 lost 与 not-implemented/label PASS）；证据
     `docs/evidence/v090-step5-b3-terminal-adapter-restart/`。**当前资格状态 = `terminal-adapter-restart` PASS**。
   - `terminal-dsh-runtime-restart`（owner `d15-5-candidate-attachment-layer`，非 post-GO R4）——**已于
     2026-09-21 执行**：候选/资格层在**真正终止并重启 DSH runtime OS 进程**后记录 truthful
     `lost`/`interrupted`、reconcile surviving PTY without attachment 为 `lost`（never silently reused）、
     并证明 terminal lifetime 不定义 conversation/durable-job lifetime（fail-able observer 区分正确
     lost 与 not-implemented/label PASS）；证据
     `docs/evidence/v090-step5-b4-terminal-dsh-runtime-restart/`。
     **当前资格状态 = `terminal-dsh-runtime-restart` PASS**。
   每项独立 Draft PR；owner 必须在 D15-G gate 之前，未 PASS 不进入下一项。
6. D15-G 重跑；仅当全部必须 atomic 项 PASS 才可 GO。若 B1 仍为 external blocker，维护者必须显式
   选择 gate-order 选项（`G-keep` / `G-split` / `G-reorder` / `G-reclassify`），不得同时声称严格串行且可执行。
7. GO 之后：R3 thin supervisor → R4 TerminalAttachment → R5 DurableJob independence →
   R6 full runtime continuity → 独立 production Go/No-Go（维护者决定）。

每项停止条件：一 worktree/分支/Draft PR；停在 Draft；不 push `main`；不得删除或降级 blocker；
不得以“升级依赖”等同“切换生产默认”；不得覆盖历史证据或旧 tag；不得让 S3/0.10 项阻塞 0.9。

**授权缺口（已解决）**：`ADR-0081` 曾为 `Proposed`，其文本写明“路线重排须在接受之后”，而专项 D15
计划已实际实现该重排（D15 插在 R2 之后、R3 之前）。维护者已于 2026-09-19 接受 ADR-0081
（Accepted，见 #328），该缺口已关闭：D15 插在 R2 之后、R3 之前的重排现为已授权顺序。D15-2/D15-3
的 `PASS` 仍是隔离资格证据，不据此推断 R3 解冻或生产切换授权。

## 0.9 full-interface re-baseline（2026-09-21，权威维护条目）

本批执行 0.9 严格顺序第 2 步：在候选 `origin/main`（`21c1812`）上把 H4 逐接口可靠性台账重做到
**真实、机器可读的 `complete=true`**。这是维护/审计，不推进 Product Phase，不实现 Proposed
ADR-0082/0083，不切换生产 selector，不 deploy，不创建/移动 tag/release，不恢复 Phase 100，
不触碰 `codex/phase-100c`/PR #338，不做 Community 检查或复制。

H4 台账在其自身提交记录 560 行；当前源码发现 **566**。缺失的 6 行全部是 Phase 101 凭据驱动模型目录
接口（Backend 发现接口 + profile disable/enable 及其 Gateway/Product API 代理）。**20 个文件漂移**：
17 个在 H4 提交后变更，另有 3 个记录哈希从未匹配已提交的 H4 树（MCP `server.ts`、`backtest.ts`、
Gateway `main.py` 的假基线）。`scripts/ci/check-reliability-review.py` 已改为**fail-closed 审计器**：
缺行、过期 source/dependency 哈希、fake PASS 任一都非零退出；当前结果 `discovered=reviewed=566`、
`missing=0`、`stale=0`、`fake_pass=0`、`complete=true`。逐接口重新核对结果、漂移分解与复现见
`docs/evidence/v090-full-interface-rebaseline/`，由 `tests/test_reliability_review_audit.py` 断言。

构建身份推进到未使用 id `post-u8.177 → post-u8.178`（`scripts/`、`tests/` 属 build inputs）；历史
`.177` manifest 与全部证据保持不变，仅重建身份，不改 selector/`compose.yml`/`deployment.json`/制品。

## 0.9 composite research fault regression（2026-09-21，权威维护条目）

本批执行 0.9 严格顺序第 3 步：在隔离栈上真实跑通**改进策略复合研究旅程**
（改进策略→需审批动作→用原键在批准后执行→训练→样本外预测→冻结信号→原生回测→新旧比较→
原任务终态），并注入 R1–R5 故障矩阵。这是维护/审计，不推进 Product Phase，不实现 Proposed
ADR-0082/0083，不切换生产 selector，不 deploy，不创建/移动 tag/release，不恢复 Phase 100，
不触碰 `codex/phase-100c`/PR #338，不做 Community 检查或复制。

**v1 证据已 `superseded` 且不构成资格通过**：v1 故障行硬编码 generation/epoch、把同一 trace/run
复用于无关故障动作，并用单一拒绝冒充“拒绝/撤销/陈旧复用”、用普通排队冒充“数据等待续接”。
v1 保留仅供溯源，不得读作 9/9 PASS。

**v2 为当前整改证据**（P1-1..P1-8）：验收矩阵在**执行前冻结**为
`docs/evidence/v090-composite-research/acceptance-matrix.v2.json`，关闭合同
`scripts/v090/composite_research/contract.v2.json` 是观察器唯一事实来源。每个 PASS 场景标注真实
`boundary` 并携带 `provenance`：trace 取自权威 `ml_training_runs.trace_id` 且与该场景 receipt 关联，
run/generation/epoch 在 ML 边界为显式 `not_applicable`+原因（不再伪造 1→2），pid 按被重启服务实测；
观察器拒绝缺失 provenance、无合同允许 source 的数值、无原因的 not_applicable、无关 trace、重启无
pid 变化。场景已拆分：`approval-rejected`、`approval-stale-reuse`、`approval-revoked`（无 revoke
路径，BLOCKED）；`cancel-terminal` 必须权威终态为 `cancelled` 且 worker 恢复后不反转；`late-success`
要求下游 delta 严格为 0；`queue-worker-resume` 为真实队列恢复，ADR-0077 `data-ready-continuation`
单独列为 BLOCKED；`bounded-continuation-exactly-once` 由旅程权威 continuation ledger 派生。
`process-restart-backend/gateway/ml-worker` 分别验证三个边界；`runtime-adapter-tool-boundary` 列为
BLOCKED（属 D15 tool-call 故障注入范围）。真实结果：旅程 PASS；13 个可执行必需行为 PASS；4 个必需行
诚实 BLOCKED（`approval-revoked`、`timeout-terminal`、`data-ready-continuation`、
`runtime-adapter-tool-boundary`），故观察器 `format_valid=true`、`all_pass=false`（exit 1），**不再
宣称 9/9 PASS**。可失败观察器 `--selfcheck` 58 项负例全部非零（含 21 项 defect-targeting），
capture negatives 12 项 post-fix 全失败、pre-fix 全通过。P1-1：已从 `.gitleaks.toml` 移除整目录
allowlist，`.gitleaks.toml/.gitleaksignore` 相对 `main` 无改动；触发在源头消除（高熵 idempotency key 已 redact 为短 sha256 摘要、变量改名），CI 同版本/config 对 `origin/main..HEAD` 报 0 findings。
cleanup 后 containers/networks/volumes 均为 0 且生产栈未被触碰。证据见
`docs/evidence/v090-composite-research/`，由 `tests/test_v090_composite_research.py` 断言。provider 为
scripted keyless（非真实 LLM 语义）。未复现 0.9 范围缺陷，故无实现修复；本批不部署、不合并。
构建身份推进 `post-u8.178 → post-u8.179`。

## 0.9 ADR-0082/0083 maintainer decision（2026-09-21，权威维护条目）

本批执行 0.9 严格顺序第 4 步：记录维护者对 ADR-0082/ADR-0083 的人工决定。这是**决定记录/治理**，
不推进 Product Phase，**不实现任何组件**，不切换生产 selector，不 deploy，不创建/移动 tag/release，
不恢复 Phase 100，不触碰 `codex/phase-100c`/PR #338，不做 Community 检查或复制。决定来源是维护者
2026-09-21 的步骤 4 指令；本文件不伪造 GitHub approval，接受证据记录在
`docs/evidence/v090-adr-decisions/`（`README.md` + `decision-record.v1.json`）。

- **ADR-0082（Accepted，modified）**：**只选 Option 1**——未来由 DSH 提供独立进程 continuable
  provider / `prepareContinuable`，通用子会话恢复与独立子崩溃恢复归 DSH。**Option 2（BYQ
  runtime-adapter child-resume bridge）被拒**为当前架构方向；BYQ 不建第二个 session store、不建
  通用 harness。接受不等于实现；`subagent-child-crash` 等 blocker 保持 `BLOCKED`，直到合格进程外
  provider 出现并通过资格。回退/逃生路径：若 provider 不出现，保持前台委派、不启用原生
  continuable seam，候选 wiring 仍可逆。
- **ADR-0083（Accepted，as proposed）**：BYQ 只持久化有界 `TerminalAttachment`
  identity/permission/generation/epoch/state，并经 Gateway/Product API 暴露有界接口；DSH 继续拥有
  PTY/shell/IO；原生 process-local 状态丢失时 MUST 真实 `lost`/`interrupted`，绝不伪造
  `reattached`；**不承诺**跨 runtime restart 的 PTY 连续性。接受只授权候选级、可逆的 D15-G 资格
  路径，不切换生产 selector。
- **未解决/未关闭**：四项 D15-G atomic BLOCKED（`subagent-child-crash`、
  `subagent-byq-adapter-restart`、`terminal-adapter-restart`、`terminal-dsh-runtime-restart`）**仍未
  解决**；D15-G 仍 `NO_GO`；**0.9 未关闭**。D15-4/D15-5 状态不变；R3 继续冻结、`R3_RESUME = NO`。
- 一致性由 `tests/test_v090_closeout_governance.py`（更新/新增的治理断言）守门。
- 构建身份推进 `post-u8.179 → post-u8.180`（`tests/` 属 build inputs，仅重建身份，历史 manifest 与
  全部证据保留）。

## 0.9 step-5 B1 `subagent-child-crash`（2026-09-21，权威维护条目）

本批执行 0.9 严格顺序**第 5 步的首个且唯一首切片**：B1 `subagent-child-crash`，owner
`d15-4-child-provider-remediation`（独立 worktree/分支 `codex/v090-d15-child-provider-remediation`，
基于动态 `origin/main`）。这是维护/资格，不推进 Product Phase，不实现 ADR-0082 Option 1（属上游 DSH），
**不**建 BYQ child-resume bridge，不切换生产 selector，不 deploy，不创建/移动 tag/release，不恢复
Phase 100，不触碰 `codex/phase-100c`/PR #338，不做 Community 检查或复制。

- **只读能力发现 + 隔离资格（真实）**：`scripts/d15/subagent/child_provider_discovery.mjs` 启动真实
  候选 cordis 上下文 + 真实 `SubagentRuntime`，注册真实候选 provider，并调用真实
  `SubagentRuntime.prepareContinuable` gate。结论：**不存在**进程外 `prepareContinuable` provider。
  唯一 continuable provider 为 in-process `spawn`/`fork`（gate 接受）；`acp`/`codex`/`claude-code`
  （候选打包）与 `dsh-sdk`（未打包）均无 `prepareContinuable`，被 gate 以
  `UNSUPPORTED_CAPABILITY` 拒绝。候选源码归档 sha256
  `23af26a7…8262c`（commit `183f08e9…`）经校验与声明一致；上游源码扫描同样只在 spawn/fork 找到
  `prepareContinuable`。按 ADR-0082，Option 2 的 BYQ child-resume bridge **被拒**，本批不建第二个
  session store/generic harness，唯一路径是未来上游 DSH 进程外 provider。
- **结果 = external BLOCKED**：in-process continuable child 与父执行器共享 OS 进程，无法在父存活时
  被独立 SIGKILL；且 **未** 用 same-process provider / owning-process SIGKILL / label-only PASS 替代。
  `subagent-child-crash` 保持 **BLOCKED**，D15-G 仍 `NO_GO`。
- **未开始**：`subagent-byq-adapter-restart`、terminal 两切片、D15-G 重跑、R3/R4/R5/R6。
- **需要维护者 gate-order 决定**：`G-keep` / `G-split` / `G-reorder` / `G-reclassify`（见
  `docs/evidence/v090-closeout/DSH-015RC1-CLOSEOUT-SLICES.md`）。在决定前，严格串行既诚实又不可执行。
- 证据 `docs/evidence/v090-d15-child-provider-remediation/`（capability discovery、fail-able observer
  verdict、external-blocked、21 项 focused negatives），由
  `tests/test_v090_d15_child_provider_remediation.py` 断言。构建身份推进
  `post-u8.180 → post-u8.181`（`scripts/`、`tests/` 属 build inputs，仅重建身份）。
- **0.9 未关闭**；`R3_RESUME = NO`；D15/R3 保持冻结。

## 0.9 step-5 G-split gate-order decision（2026-09-21，权威维护条目）

本批记录维护者对 0.9 严格顺序第 5 步 B1 external blocker 的 **gate-order 决定**：**`G-split`**。
这是决定记录/治理，不推进 Product Phase，**不实现 B2**，无任何 runtime/provider/child-bridge/
TerminalAttachment 代码，不切换生产 selector，不 deploy，不创建/移动 tag/release，不恢复 Phase 100，
不触碰 `codex/phase-100c`/PR #338，不做 Community 检查或复制。决定来源是维护者 2026-09-21 的
G-split 指令；本记录不伪造 GitHub approval。

- **B1 `subagent-child-crash` 保持 MANDATORY external blocker**：**不**降级、**不**删除、**不**改为
  optional；D15-G 的必需 atomic 条件不变。
- **G-split 决定**：把 external B1 与可独立执行的 **internal** pre-gate 修复分离，按**严格内部顺序**
  继续：**B2 `subagent-byq-adapter-restart` → `terminal-adapter-restart` →
  `terminal-dsh-runtime-restart`**。
- **D15-G 保持 `NO_GO` 直到 B1 真正 PASS**；B2/B3/B4 的 PASS 不会在 B1 BLOCKED 时把 D15-G 变为 GO。
- **`R3_RESUME = NO`**；D15/R3 保持冻结；**0.9 未关闭**。
- **下一唯一任务**：B2 `subagent-byq-adapter-restart`，owner `d15-4-candidate-composition-hookup`
  （pre-gate，非 post-GO R6）。**本批未开始 B2**。
- 机器可读决定记录 `docs/evidence/v090-closeout/gsplit-decision.v1.json`；一致性由
  `tests/test_v090_gsplit_decision.py` 与 `tests/test_v090_closeout_governance.py` 守门。
- 构建身份推进 `post-u8.181 → post-u8.182`（`tests/` 属 build inputs，仅重建身份；历史 manifest
  与全部证据保留）。

## 0.9 step-5 B2 `subagent-byq-adapter-restart`（2026-09-21，权威维护条目）

本批在 G-split 严格内部顺序内执行 **B2 `subagent-byq-adapter-restart`**，owner
`d15-4-candidate-composition-hookup`（独立 worktree/分支 `codex/v090-step5-b2-adapter-restart`，
基于动态 `origin/main`）。这是维护/资格，不推进 Product Phase，**不实现** ADR-0082 的
Option 2（BYQ child-resume bridge **被拒**），不建第二个 session store/generic harness，
不切换生产 selector，不 deploy，不创建/移动 tag/release，不恢复 Phase 100，不触碰
`codex/phase-100c`/PR #338，不做 Community 检查或复制，不 fork/patch DSH。

- **真实隔离 composition/restart 探针**：`scripts/d15/subagent/byq_adapter_restart_probe.py`
  在真实 `byq-d15-4-continuable-candidate:local`（candidate 0.1.5-rc.1 + 真实
  `RuntimeAdapter` + candidate continuable composition；`--network none`、keyless scripted
  provider）中把 generation A 与 generation B 作为**独立容器/OS 进程**运行，共享同一 durable
  session root。
- **结果 = external/dependency BLOCKED**：generation A 真实到达 `startContinuable`
  （`byq_delegate_market_research` 返回 `{kind: continuable, subagentId}`、child 持久且
  `subagent.started` 链接到 root、精确 delegation call id、恰好 1 个 child）；generation B
  是全新 OS 进程/容器且 child 文件同 id 持久，但 **committed BYQ composition 无任何
  child rebind/message/resume 表面**：adapter 仅暴露 root `resume_session`，`0.1.5` Python SDK
  与 `0.1.2` 逐字节相同、无 child 操作，且 composition 自身 `forbidden_tools` 禁用
  `subagent`/`subagent_fork`/`send_message`/`list_agents`。`resume_session(child_id)` 真实
  fail-closed（`KeyError: unknown BYQ session`）。无第二 session store、无额外 child、无孤儿。
- **observer 可失败**：`byq_adapter_restart_observer.py --selfcheck` 27 项控制全部对修复后门禁
  非零（25 项 defect-targeting，修复前 result-trusting 门禁会误报）；提交的 `verdict.v1.json`
  `format_valid=true`、`all_pass=false`、`external_blocked=true`、exit 1。
- **未开始**：`terminal-adapter-restart`、`terminal-dsh-runtime-restart`、D15-G 重跑、
  R3/R4/R5/R6。**`R3_RESUME = NO`**；D15/R3 保持冻结；**0.9 未关闭**。
- **下一唯一任务**：`terminal-adapter-restart`（owner `d15-5-candidate-attachment-layer`，
  pre-gate，非 post-GO R4），按 G-split 严格内部顺序继续。
- 证据 `docs/evidence/v090-step5-b2-adapter-restart/`（composition observation、probe
  provenance、fail-able observer verdict、external-blocked、27 项 focused negatives），由
  `tests/test_v090_step5_b2_adapter_restart.py` 断言。构建身份推进
  `post-u8.182 → post-u8.183`（`scripts/`、`tests/` 属 build inputs，仅重建身份；历史
  manifest 与全部证据保留）。

## 0.9 step-5 B3 `terminal-adapter-restart`（2026-09-21，权威维护条目）

本批在 G-split 严格内部顺序内执行 **B3 `terminal-adapter-restart`**，owner
`d15-5-candidate-attachment-layer`（独立 worktree/分支
`codex/v090-step5-b3-terminal-adapter-restart`，基于动态 `origin/main`）。这是维护/资格，
不推进 Product Phase，不实现生产 wiring/R4 productization，不切换生产 selector，不 deploy，
不创建/移动 tag/release，不恢复 Phase 100，不触碰 `codex/phase-100c`/PR #338，不做 Community
检查或复制，不 fork/patch DSH。按 ADR-0083，在**候选/资格层**实现并验证**最小
`TerminalAttachment` 生命周期**：BYQ 只拥有有界 attachment id（BYQ-minted，绝不是 DSH session
id/pid）、owner principal/授权、runtime generation、executor epoch、state 与 audit linkage；
**DSH 继续拥有 PTY/shell/process/IO**；BYQ 不建 PTY runtime、不复制 DSH terminal、不建第二
generic harness、不持久化或伪造 native PTY。

- **真实隔离 native 探针**：`scripts/d15/terminal/adapter_restart_harness.mjs` 在真实
  DSH 0.1.5-rc.1 候选闭包（`@deepseek-ai/dsh-terminal` owner-scoped registry +
  `@deepseek-ai/dsh-terminal-bash` shell backend）内，以**独立 OS 进程**运行 native runtime
  generation、BYQ adapter generation 与每个 client action；BYQ adapter 只持久化自己的
  attachment store，native runtime 拥有 PTY。
- **generation A → abort BYQ adapter → generation B（真实结果）**：
  - **native 可达分支 `PASS`**：generation A 建立真实 native persistent terminal + durable
    BYQ attachment；abort BYQ adapter OS 进程后，全新 adapter generation B 重载**同一**
    durable attachment，做 owner/principal 授权与 generation/epoch 校验，native 状态仍可达时
    重绑**同一** attachment / native session / PTY pid，唯一 marker 跨进程无重放（第二次 send
    delta 不含第一个 marker）且无丢失（scrollback 各一次）。
  - **native 丢失分支 `PASS`（ADR-0083 诚实契约）**：committed topology 下 adapter 重启随附
    native runtime 终止；全新 adapter generation 重载同一 durable attachment、授权与
    generation 校验后，发现旧 pid 已死、native session 不在、runtime generation 已变，确定性
    返回 `lost` 并拒绝 fake reattach（不返回旧 session/pid、不声称 identity stable）。
- **fail-able observer（区分“正确 lost/interrupted”与“not implemented / label PASS”）**：
  `scripts/d15/terminal/adapter_restart_observer.py --selfcheck` 32 项控制全部对修复后门禁非零
  （29 项 defect-targeting，修复前 result-trusting 门禁会误报）；控制显式包含
  `label-only-pass-positive`、`not-implemented-label-pass`、`not-implemented-positive-missing`、
  `lost-without-native-failure`、`lost-status-not-lost`、`fake-reattach-accepted`、
  `durable-not-loaded`。正分支必须以 fresh adapter 真正重载并重绑 durable attachment 才能通过，
  故纯 label-only/未实现不能以 `lost` 冒充验收。提交的 `verdict.v1.json` `format_valid=true`、
  `all_pass=true`、exit 0。
- **附加验收（真实）**：foreign principal `UNAUTHORIZED_PRINCIPAL`、foreign owner send/read
  `FOREIGN_SESSION`；stale generation `STALE_GENERATION`、stale epoch `STALE_EPOCH`；未知
  attachment `UNKNOWN_ATTACHMENT`、错误 terminal `NO_SESSION`；reattach/close 幂等；cleanup 无孤儿。
- **范围强制**：`adapter_restart_scope_probe.py` 证实本批只落在候选/资格层；runtime-adapter 的
  persistent-terminal/PTY/attachment 路由数 0（唯一 terminal 路由为 AgentRun terminal-state
  receipt 证据）；`apps/frontend/src` 对 raw DSH schema 引用 0；生产 selector 仍
  `dsh-0.1.2rc1`；无 R4 productization。历史 D15-5 证据与 D15-G 证据**不改写**。
- **未开始/未改变**：`terminal-dsh-runtime-restart`（B4）、D15-G 重跑、R3/R4/R5/R6、
  生产 selector/deploy/tag/release。B1 保持 mandatory external blocker，B2 保持
  BLOCKED-external，D15-G 仍 `NO_GO`（本轮未重跑，需 B1 真正 PASS）；**`R3_RESUME = NO`**；
  D15/R3 保持冻结；**0.9 未关闭**。
- 证据 `docs/evidence/v090-step5-b3-terminal-adapter-restart/`（native observations、fail-able
  observer verdict、32 项 negative controls、scope probe、provenance），由
  `tests/test_v090_step5_b3_terminal_adapter_restart.py` 断言。构建身份推进
  `post-u8.183 → post-u8.184`（`scripts/`、`tests/` 属 build inputs，仅重建身份；历史
  manifest 与全部证据保留）。

## 0.9 step-5 B4 `terminal-dsh-runtime-restart`（2026-09-21，权威维护条目）

本批在 G-split 严格内部顺序内执行 **B4 `terminal-dsh-runtime-restart`**，owner
`d15-5-candidate-attachment-layer`（独立 worktree/分支
`codex/v090-step5-b4-terminal-dsh-runtime-restart`，基于动态 `origin/main`）。这是维护/资格，
不推进 Product Phase，不实现生产 wiring/R4 productization，不切换生产 selector，不 deploy，
不创建/移动 tag/release，不恢复 Phase 100，不触碰 `codex/phase-100c`/PR #338，不做 Community
检查或复制，不 fork/patch DSH。复用 B3 的 native runtime role 与最小 `TerminalAttachment`
store schema（**不建第二 generic harness**）；BYQ 仍只拥有有界 attachment/reconcile，DSH 继续
拥有 PTY/shell/process/IO。

- **真实隔离 native 探针**：`scripts/d15/terminal/dsh_runtime_restart_harness.mjs` 复用 committed
  B3 runtime role（真实 `@deepseek-ai/dsh-terminal` + `@deepseek-ai/dsh-terminal-bash`），以独立
  OS 进程运行 DSH runtime generation、BYQ adapter generation 与每个 client action。
- **generation A → 真正终止 DSH runtime OS 进程 → generation B（真实结果）**：
  - **`dsh-runtime-restart-terminal-lost` PASS**：generation A 建立真实 native persistent terminal
    （唯一 marker 经真实 PTY 回显）+ durable BYQ attachment；`SIGKILL` DSH runtime OS 进程并以
    **全新 OS 进程**启动 runtime generation B（runtime pid 改变、generation `1→2`、旧 PTY pid 死亡、
    新 runtime 0 session）；fresh adapter generation B 重载同一 durable attachment，做 owner/
    generation/epoch 校验后确定性返回 `lost`（`NATIVE_SESSION_UNAVAILABLE`），**不返回旧
    session/pid、不声称 identity stable**，重试保持同一 lost。
  - **`surviving-pty-without-attachment-lost` PASS**：native PTY **真实存活**而 BYQ durable
    attachment record 丢失；fresh adapter generation B reconcile native sessions 与 attachments，
    把该 surviving PTY 识别为 **orphan** 并分类 `lost`，拒绝 orphan-reuse（`ORPHAN_NOT_REUSABLE`）
    与陈旧 attachment id（`UNKNOWN_ATTACHMENT`），**绝不**为 orphan 创建 attachment；cleanup 杀掉
    orphan PTY（0 orphans、0 sessions）。
- **terminal lifetime 独立性**：BYQ conversation / durable-job 身份（与 attachment 一同由 BYQ
  铸造并持久化）在 DSH runtime 重启与 orphan loss 前后保持 `active` 且不变；terminal loss 不得终止
  conversation/job。
- **fail-able observer**：`scripts/d15/terminal/dsh_runtime_restart_observer.py --selfcheck` 48 项
  控制全部对修复后门禁非零（45 项 defect-targeting，修复前 result-trusting 门禁会误报）；控制显式
  包含 `runtime-not-restarted`、`runtime-generation-not-advanced`、`lost-without-native-failure`、
  `fake-reattach-accepted`、`label-only-pass-positive`、`not-implemented-label-pass`、
  `conversation-terminated-on-terminal-loss`、`orphan-reused`、`orphan-adopted-as-attachment`、
  `orphan-cleanup-left-alive`、`permission-bypass`、`stale-not-fenced`、
  `orphan-dimensions-hide-surviving-pty`。提交的 `verdict.v1.json` `format_valid=true`、
  `all_pass=true`、exit 0。
- **附加验收（真实）**：owner principal `UNAUTHORIZED_PRINCIPAL`；runtime generation 真实验证；
  stale generation `STALE_GENERATION`、stale epoch `STALE_EPOCH`；wrong terminal `UNKNOWN_ATTACHMENT`/
  `NO_SESSION`；foreign send/read `FOREIGN_SESSION`；reattach retry / orphan reconcile / close 幂等；
  cleanup 无孤儿。
- **范围强制**：`dsh_runtime_restart_scope_probe.py` 证实本批只落在候选/资格层，且
  `reuses_b3_native_runtime_role=true`、`reuses_b3_attachment_store_schema=true`、
  `second_generic_harness=false`；runtime-adapter 的 persistent-terminal/PTY/attachment 路由数 0
  （唯一 terminal 路由为 AgentRun terminal-state receipt 证据）；`apps/frontend/src` 对 raw DSH
  schema 引用 0；生产 selector 仍 `dsh-0.1.2rc1`；无 R4 productization。
- **历史快照与当前 overlay 区分**：`docs/evidence/d15/d15-5/`、`docs/evidence/d15/d15-g/`
  committed verdict **不改写**（D15-5 `dsh-runtime-restart` 当时为 `BLOCKED`；D15-G 仍 `NO_GO`）；
  B4 当前 overlay 记录在
  `docs/evidence/v090-step5-b4-terminal-dsh-runtime-restart/current-overlay.v1.json`。
- **未开始/未改变**：D15-G 重跑（因 B1 external BLOCKED 不得重跑）、R3/R4/R5/R6、生产
  selector/deploy/tag/release。B1 保持 mandatory external blocker，B2 保持 BLOCKED-external，
  D15-G 仍 `NO_GO`；**`R3_RESUME = NO`**；D15/R3 保持冻结；**0.9 未关闭**。
- 证据 `docs/evidence/v090-step5-b4-terminal-dsh-runtime-restart/`（native observations、fail-able
  observer verdict、48 项 negative controls、scope probe、provenance、current overlay），由
  `tests/test_v090_step5_b4_terminal_dsh_runtime_restart.py` 断言。构建身份推进
  `post-u8.184 → post-u8.185`（`scripts/`、`tests/` 属 build inputs，仅重建身份；历史
  manifest 与全部证据保留）。

## 独立 DSH provider 资格监控切片 `v090-dsh-provider-qualification`（2026-09-21，权威维护条目）

本批执行**独立维护/依赖资格监控切片**（独立 worktree/分支 `codex/v090-dsh-provider-qualification`，
基于动态 `origin/main`），回答一个问题：**未来哪个 DSH 发布能解锁 ADR-0082 Option 1 blocker**。
这是监控/资格，不推进 Product Phase，不实现 ADR-0082 Option 1（属上游 DSH），不建 BYQ provider /
child-resume bridge / 第二 session store，不切换生产 selector/default，**不升级依赖**，不 deploy，
不创建/移动 tag/release，不恢复 Phase 100，不触碰 `codex/phase-100c`/PR #338，不 fork/patch DSH，
**不向外部仓库提交 issue/PR**。**B1/B2/D15-G/R3 状态不变**：B1 `subagent-child-crash` 保持
**BLOCKED（external）**，B2 `subagent-byq-adapter-restart` 保持 **BLOCKED（external/dependency）**，
D15-G 保持 **`NO_GO`** 且**未重跑**，**`R3_RESUME = NO`**，0.9 未关闭。

- **版本/包来源 + 完整闭包**：`scripts/d15/provider_qualification/version_provenance.py` 只读记录
  npm dist-tags、发布时间、根 tarball integrity、完整解析闭包（rc.2 = 594 包，alpha.2 = 650 包，
  含 canonical sha256）与 6 个 subagent provider 闭包；PyPI `deepseek-harness-sdk` /
  `deepseek-harness-runtime-bin` **均无** `0.1.5rc2`/`0.1.6a2`，故两个发布都**不是 coherent pairing**。
- **原生能力清单 + 探针**：`scripts/d15/provider_qualification/capability_inventory.mjs` 在隔离安装中
  启动真实 cordis 上下文 + 真实 `SubagentRuntime`，注册真实 provider 并调用真实
  `SubagentRuntime.prepareContinuable` gate。结果：rc.2 与 alpha.2 的 in-process `spawn`/`fork`
  gate `PASS`，而 out-of-process `acp`/`codex`/`claude-code`/`dsh-sdk` 全部
  `UNSUPPORTED_CAPABILITY`；两个发布的 README 仍声明 **Process-local residency**（跨进程续接需要
  **未来的 durable mailbox + cross-process lease protocol**）、**No durable parent mailbox**、
  **ACP children remain one-shot**。`out-of-process.d.ts`/`subprocessRunHandle` 等
  **one-shot helper 符号存在但不算 capability**。
- **结果 = 两个版本均 BLOCKED（external）**：机器可读 verdict 分版本记录
  `verdict.rc2.v1.json` / `verdict.alpha2.v1.json`（`format_valid=true`、`all_pass=false`、
  `external_blocked=true`、exit 1）；`cross_process_continuation_qualification = null`，因为不存在
  可运行的 out-of-process continuable provider。最小具体缺口 = DSH 无 out-of-process
  `prepareContinuable` provider，且无 durable mailbox / cross-process lease protocol。
- **显式资格开关**：原生探针**不进入日常 CI**，仅在 `BYQ_DSH_PROVIDER_QUALIFICATION=1` 时经
  `scripts/d15/provider_qualification/run_provider_qualification.sh` 运行；能力缺失时**稳定输出
  BLOCKED 且非零退出**，不造成日常 CI 误报。
- **上游需求包**：`docs/evidence/v090-dsh-provider-qualification/upstream-requirement.md` 给出最小接口
  契约（`SubagentProvider.prepareContinuable`、durable mailbox、cross-process lease）、10 条生命周期/
  安全不变式、可复现 B1/B2 场景与上游验收清单。**未向外部仓库发送任何 issue/PR**。
- **可失败 observer**：`provider_qualification_observer.py --selfcheck` 33 项控制全部非零（31 项
  defect-targeting），显式覆盖 **fake provider / in-process provider / one-shot provider /
  no-mailbox / double-lease / duplicate-settlement** 六类必需失败。
- 证据 `docs/evidence/v090-dsh-provider-qualification/`，由
  `tests/test_v090_dsh_provider_qualification.py` 断言。构建身份推进
  `post-u8.185 → post-u8.186`（`scripts/`、`tests/` 属 build inputs，仅重建身份；历史 manifest 与
  全部证据保留）。
- **结论**：ADR-0082 Option 1 **仍 BLOCKED（external）**；**未执行任何依赖升级**；下一个上游合格
  provider 出现时本监控切片可重跑。
- **追加：PR #348 CI 运行域镜像引用加固（2026-09-21，同 PR）**：backend lane 出现一次运行域
  `:latest` tag 丢失（后续 `docker run` 误走 registry pull）与一次 26% 处非确定性 pytest 失败。经
  诊断：二者**不可本地复现**（本机同镜像 backend 全绿；attempt 1 在同一 26% 位置无失败；`main`
  backend lane 绿），且 #348 **不触碰任何 backend 代码**，故**非 #348 引入**。加固
  `scripts/ci/local-ci.sh`：run-scoped 镜像构建后立即捕获 immutable image id，backend/mcp 容器运行
  改用该 id 并加 `--pull=never`，缺失时 **fail-closed、绝不回退 registry/陈旧镜像**；identity 与
  cleanup gate **不变**。回归测试 `tests/test_ci_run_scoped_image_reference.py`。构建身份推进
  `post-u8.186 → post-u8.187`（`scripts/`、`tests/` 属 build inputs，仅重建身份；历史 manifest 与
  全部证据保留）。**未改历史 verdict、未改生产 selector/compose/deployment、未 deploy/tag/release、
  未运行 Full CI、未触碰 `codex/adr-gate-rationalization`。**
- **追加：cleanup image-id 收口（2026-09-21，同 PR）**：维护者指出运行侧 immutable-id 修复未闭合其
  启用的清理场景——tag 丢失而 ID 仍在时，旧 cleanup 只按 tag 校验，会留下 dangling image 却误报成功。
  现 `local-ci.sh` 在构建后把本次实际捕获的 `service=sha256:<64hex>` 列表原子写入按
  `BYQ_CI_SCOPE` 严格隔离的 manifest（`.ci-artifacts/$BYQ_CI_SCOPE/image-ids.env`）；独立
  `always-cleanup` 进程读取同一路径，**校验后才**对精确 ID 执行 `docker image rm`（仅当该 ID 无其他
  scope 的 tag），清理后**同时验证 tag 与精确 ID 均消失**。缺失 manifest 保持向后兼容；内容非法
  一律 fail-closed 且**绝不**把文件内容交给 `docker image rm`。**无 global prune、不删除其他 scope/
  共享镜像**；identity/backend/schema/cleanup gate 均未放宽。行为测试
  `tests/test_ci_cleanup_image_ids.py`（strict fake docker：tag 丢失 ID 仍在被移除、tag+ID 双移除、
  shared foreign-tag 不删除、foreign-scope manifest 不读取、非法/畸形 manifest fail-closed、缺失
  manifest 向后兼容、重复 ID 去重）。构建身份推进
  `post-u8.187 → post-u8.188`（`scripts/`、`tests/` 属 build inputs，仅重建身份；历史 manifest 与
  全部证据保留）。**未改历史 verdict、未改生产 selector/compose/deployment、未 deploy/tag/release、
  未运行 Full CI、未取消或重跑当前 CI、未触碰 PR #349。**
- **追加：manifest 边界两处窄修（2026-09-21，同 PR）**：(1) scope 现在显式拒绝 `.`/`..`，且
  manifest 目录经规范化必须严格等于 `.ci-artifacts/<scope>`，杜绝 `..` 把 `image-ids.env` 解析到
  `.ci-artifacts` 之外；`local-ci.sh` 的 scope 校验同步拒绝 `.`/`..`。(2) manifest 的 `service`
  必须是本次 `image_resources` 精确白名单成员，**未知或重复 service 一律 fail-closed**，其 ID
  **绝不**交给 `docker image rm`。行为测试新增：`.`/`..` scope 拒绝且不读取/不删除越界 manifest、
  unknown service 与 duplicate service fail-closed 且 ID 不被删除。既有 foreign-tag 共享保护、
  缺失 manifest 向后兼容、无 global prune 全部保留。构建身份推进
  `post-u8.188 → post-u8.189`（`scripts/`、`tests/` 属 build inputs，仅重建身份；历史 manifest 与
  全部证据保留）。**未改历史 verdict、未改生产 selector/compose/deployment、未 deploy/tag/release、
  未运行 Full CI、未取消或重跑当前 CI、未触碰 PR #349、未引入镜像签名或第二框架。**

## ADR-0084 BYQ session failure containment and business recovery（2026-09-21，权威维护条目）

本批实现 ADR-0084 取代 B1/B2 全局阻塞作用的**当前必需门禁**：`BYQ session failure containment
and business recovery`。独立 worktree/分支 `codex/v090-session-failure-containment`，基于动态
`origin/main`。这是维护/资格，**不推进 Product Phase**，不切换生产 selector，不 deploy，不创建/移动
tag/release，不恢复 Phase 100，不触碰 `codex/phase-100c`/PR #338，不做 Community 检查或复制，
不 fork/patch DSH，**不实现** ADR-0082 Option 2 或任何原生 child resume。

- **实现范围（可逆、合同优先，只读）**：新增 BYQ 自有框架中立合同
  `packages/contracts/session_failure_containment.py`（closed loss cause / `interrupted` 终态 /
  generation-epoch-attempt fence / 终态重开与重复结算拒绝 / **tri-state fail-closed 恢复分类** /
  boundary assertion 与真实 preservation 证据分离）；Runtime Adapter `app/containment.py` 持久化
  **有界、受 epoch 与 attempt fence 保护**的 containment 证据（`byq-lifecycle-evidence/containment/`），
  记录**框架中立 trace/run 绑定**，并在 `_rehydrate` 检测到丢失的 open root 时如实记录 `executor-loss`、
  在 `_run_prompt` 终态结算前校验 generation fence；Gateway `app/session_containment.py` **只读**，仅当
  **fenced containment 记录匹配同一 session/trace 与精确 run** 时才投影 `interrupted`，并提供 Product API
  投影（`GET /v1/agent/sessions/{id}/containment`、`GET /v1/agent/sessions/{id}/recovery` 只读分类、
  `GET /v1/agent/sessions/{id}` 的 `containment` 字段）。前端**不**读取 DSH 私有事件。
- **恢复分类（fail-closed，无自动重试路径）**：取消/预算耗尽/授权撤销/owner-workspace 不匹配一律
  `blocked`；已存在精确成功回执一律 `settled`（绝不重放）；非幂等或结果不可核对的副作用一律 `paused`
  （用户可见原因）。authority 每项为 tri-state：未知/不可达一律 `paused`，**绝不默认允许**；owner/workspace
  来自 owner-scoped catalog 与 durable Backend auth session，任意未答复回合的预算无权威绑定故为未知。
  **无权威步骤安全元数据，故不存在自动 resubmit 路径**：`GET .../recovery` 只读分类、`"submitted": false`，
  不提交任何 prompt，也不存在 attempt ledger。
- **五处 Safety/Integrity 修复**：(1) 删除客户端 `step` 自证字段，安全声明只能来自服务端权威元数据，
  缺失即 paused；(2) `_recovery_authority` 接入现有权威组件逐项校验，未验证不提交；
  (3) 删除 `/tmp/byq-recovery-attempts` authority ledger，收缩为只读分类，无第二 store；
  (4) `loss_from_evidence` 仅在 fenced containment 匹配 session/trace 与精确 run 时投影 `interrupted`，
  普通 `failed`/`cancelled`/`discarded` 保持原语义；(5) 移除常量 preservation 声明，改为
  `boundary_verified=false` + 仅由权威 catalog/trace 读取证明的 `preserved`，其余 `unknown`/`unavailable`。
- **可失败验收（真实、可破坏）**：`scripts/v090/session_containment/`（contract、fail-able observer、
  real capture）；真实 Runtime Adapter 合成兼容 harness 复现执行者丢失→`interrupted` 且**真实
  before/after journal 状态（会话事件与回执计数）不变**，以及旧 generation 迟到成功不覆盖新 generation；
  纯合同函数复现 stale generation/迟到/重复/重开拒绝与全部分类（含 authority 未知 paused、预算/授权/
  owner-workspace 拒绝）；`loss_from_evidence` 复现三项 interruption 负例；`no_submit` 静态守卫证明
  恢复端点不含 `_adapter_post`/`/prompt`/`_runtime_recovery_payload`。observer 区分 `format_valid` 与
  `all_pass`，`--selfcheck` 27 项控制全部被拒（27 项 defect-targeting，修复前 result-trusting 门禁会误报），
  提交 verdict `format_valid=true`、`all_pass=true`、exit 0，且对 committed observations 的变异会使其失败。
  证据 `docs/evidence/v090-session-containment/`，由 `tests/test_v090_session_containment.py` 断言。
- **交付范围 ≠ 门禁完成**：本 PR 交付 **containment + fail-closed 只读恢复分类**（marker
  `v090-session-containment=containment-classification-delivered`）。**完整 business-recovery gate
  仍为 `IN_PROGRESS / BLOCKED_INTERNAL`**：缺少权威服务端 step-safety 与 budget binding，故不存在自动
  resubmit 路径。**下一唯一任务**：为该权威元数据与 safe rescheduling 做 inventory + minimal design；
  若需要新的持久化权威、信任主体或跨 Plane 调用，必须先提出 ADR 决定。
- **边界事实不变**：B1 `subagent-child-crash` 与 B2 `subagent-byq-adapter-restart` 保持
  `BLOCKED_EXTERNAL`；历史 D15-G 保持 `NO_GO`（历史 verdict/JSON 不改写）；`R3_RESUME = NO`；
  0.9 未关闭。本 PR **不生成也不声称**任何 D15 superseding assessment 通过；原生子进程续接仍
  **未实现**，未知副作用**暂停**，未授权项（生产 selector 切换、deploy、release/tag、Phase 100
  恢复、B1/B2 降级）一律未做。
- 构建身份推进 `post-u8.189 → post-u8.190`（`scripts/`、`tests/` 属 build inputs，仅重建身份；
  历史 `.189` manifest 与全部证据保留，不改 selector/`compose.yml`/`deployment.json`/制品）。

## 0.9 authoritative step-safety + budget binding + safe rescheduling inventory/design（2026-09-21，权威维护条目）

本批执行“完整 business-recovery gate”的唯一后续设计切片：为
**authoritative server-side step-safety + budget binding + safe rescheduling**
做 **inventory + minimal design**。独立
worktree/分支 `codex/v090-step-safety-design`，基于动态 `origin/main`。这是**设计/证据**，
**不实现任何 runtime 代码**，不推进 Product Phase，不切换生产 selector，不 deploy，不创建/移动
tag/release，不恢复 Phase 100，不触碰 `codex/phase-100c`/PR #338，不做 Community 检查或复制，
不 fork/patch DSH。证据 `docs/evidence/v090-step-safety-design/`（`README.md` +
`inventory.v1.json` + `design.v1.json`），由 `tests/test_v090_step_safety_design_governance.py`
守门。

- **Inventory（现有 vs 缺失）**：step-safety 现有 `agent_domain_call_evidence`（有序 occurred-call
  集，PK `(owner,workspace,session,sequence)`，绑定 root-run/generation/agent-run）与
  `agent_domain_call_claims`（精确 per-call receipt，UNIQUE
  `(root_run_id,task_id,action,idempotency_key)`）、`domain_call_admission.ACTIONS`（closed action
  + idempotency identity）、`research_receipts`、adapter prompt receipt；budget 现有 Backend
  `research_tasks.continuation_permission`/`continuation_budget`（**权威**；并发保证是 task 行
  `SELECT ... FOR UPDATE` + 事务内 event_key 扫描去重，**没有** per-event-key DB 唯一约束，也
  **没有**该路径上的 advisory lock）与 adapter guard 镜像；safe-rescheduling 现有
  `classify_recovery`/fence/containment ledger 与 `dispatch_attempts`（**传输重试，不是业务恢复
  尝试**）。缺失三项：closed per-step idempotent/result_verifiable registry；失联 run 到原
  reservation 行与按 sequence 闭合的 occurred-call 集的绑定；有界、按 ordinal 恰一次、
  receipt-first 的原行 rearm。MCP 工具描述、客户端 step 字段、prompt 文本与“最后一次调用”
  启发式均**不是**权威。
- **Minimal design**：contract mapping 保留 `session_failure_containment`。**身份分离（P1-F/O）**：
  budget 权威身份仍是原 `reservation_id`；每次恢复提交身份是 Backend 原子签发/持久化的
  `recovery_attempt_key`（作为 prompt idempotency key，避免 Adapter 因同 key 的旧 accepted
  receipt 直接返回旧 run；`runtime.py:780-789`/`806-809`）。carrier
  `task-continuation-reservation.v1` 增加 **closed** `recovery_attempt` 子记录
  `{attempt_key, ordinal, trigger_key, interrupted_run_id, interrupted_generation,
  containment_attempt, interrupted_executor_epoch, snapshot_tail_sequence,
  snapshot_digest}`（P1-L/P1-R）。**两个 epoch 分离（P1-O）**：
  `interrupted_executor_epoch` 来自 durable containment（`record_loss` 写入失败 epoch），参与
  SOURCE `trigger_key`，且**永不要求等于 live epoch**；`target_executor_epoch`/`target_generation`
  由 Adapter 在 admission 的 `record.lock` 下读取 **live** epoch 并创建/绑定新 generation，经
  accepted receipt 返回、由 Backend 聚合持久化（Backend **不**假装知道 Adapter 的 live epoch）。
  Adapter **重算并校验** `trigger_key`/`attempt_key`，要求 containment 字段一致、prompt key ==
  attempt key 且 reservation 一致；缺字段/篡改/把 interrupted epoch 当 live/stale target receipt/
  target epoch 或 generation 不符一律 fail closed；**合法正例**：interrupted=1、live target=2。
  **每 attempt 独立 receipt（P1-G）**：prompt/guard/settlement 以 `attempt_key.json` 为身份、
  不可覆盖，绑定 `{reservation_id, ordinal, run_id, charged_tokens, settlement_sha256}`；Backend
  行内 `recovery_attempts`（含 target epoch/generation）为最终聚合；累计精确费用 ≤
  `R.token_limit`；未知费用→`paused`。**trigger-key 去重后分配 ordinal（P1-H）**：
  `trigger_key=sha256(reservation_id+interrupted_run_id+interrupted_generation+containment_attempt+interrupted_executor_epoch)`；
  同一 trigger 在 task 行 `FOR UPDATE` 下返回既有 attempt，仅新的 fenced loss 才分配下一 ordinal
  （cap 3，`dispatch_attempts` 仍只是传输重试）。step-safety 改为 **snapshot-anchored
  session-global closure（P1-I/N/P）**：`domain_call_evidence` 仅单请求持 `record.lock`
  （`runtime.py:1143-1146`），**不假设跨 HTTP 页持锁**；`idle=true` 时 Adapter 发出固定
  `{snapshot_tail_sequence, snapshot_digest}`，digest 的**规范化输入**为
  `{"schema_version":"recovery-snapshot.v1","session_id","trace_id","tail_sequence","calls":[有序
  closed call 行]}`（sorted keys + compact，绑定 session_id + trace_id + tail + 有序调用行），
  分页锚定该 tail，与 persisted `agent_domain_call_evidence` **逐项对账**并验证全局 `1..N`
  连续，再按 root 过滤（子集只须严格递增、**不必从 1 开始**）；carrier 的 closed
  `recovery_attempt` 显式携带 `snapshot_tail_sequence`/`snapshot_digest`（P1-R），Backend 聚合
  存**同一** snapshot 身份；`submit_prompt` 先校验 snapshot 字段形状与 digest，再在**同一
  `record.lock`（`777-877`）内、创建新 root 之前**重算并原子比较当前 tail/digest 未变且
  `idle=true` 才安装 target generation（闭合 check-then-start TOCTOU）；
  append-between-pages/append-after-final-page/idle 翻转/digest 篡改/竞态→`paused`；**同一
  trigger + 同一 snapshot 重试不增加 ordinal**，snapshot 变化**不得**静默改写既有 attempt 或
  消耗另一 ordinal（须新的权威 loss trigger 或 fail closed）。**recovery-mode admission envelope（P1-K/N）**：
  仅允许只读操作，或精确复用原 `(action,task_id,idempotency_key,request_sha256,input_sha256)`；
  模型不得选择/铸造新 key；`may_produce_new_key=true` 仅作保守分类，**永远 ineligible/blocked**，
  不得据此授权铸造新 key（若要允许新 key，须另立 **Proposed** ADR，本 PR 不开启/不暗示）；
  越界的新写/改 key/发布/下单/付费/不可逆→`blocked`/`paused`；无法预先确定的 replay 不得
  `eligible`。budget 决策为**自洽 tri-state（P1-J/M/Q）**：先验
  `other_settled + other_unresolved + R.token_limit ≤ P.token_limit`（违反→blocked），再算
  `R_available = R.token_limit − cum_exact`（任一未知→`R_available=None`→**None/paused**）；
  revoked/expired/blocked reason/ordinal cap/权威证据冲突→**blocked**；**任何创建新 recovery
  model run 的资格都必须满足已知 `R_available ≥ model_call_floor`（P1-Q：只读仅约束副作用，
  **不豁免 token 预算**）；只有纯 controller receipt/evidence 对账（无模型调用、无 recovery
  attempt/run）可在 floor 之下继续观察，且不得称为 eligible reschedule**。原行 rearm 不是新 turn，
  `max_turns` 只校验未越权。**数值例**：P.token_limit=100、other settled=30、R ceiling=60、
  R 累计精确费用=20 → 不变量 `30+60≤100`，`R_available=60−20=`**40**（旧公式错误地得 10）。
  未知费用**永不算 0、永不退款**。
- **ADR 决定 = 无需新 ADR（已给出可实现的映射证明）**：设计只扩展既有权威——同一
  `research_tasks.continuation_budget` 行（行内按 trigger 键控的有界 recovery 子记录，**非**独立
  store）、既有 closed contract/carrier + closed step-safety registry（非持久化权威）、既有
  prompt/guard/settlement receipt 表面按 attempt key 复用（非新 store）、既有 session-global call
  evidence 与 admission 路径（非新信任主体/跨 Plane 接口）、既有 Gateway→Backend
  `/internal/task-continuation/...` seam 与既有 adapter dispatch 路径；ADR-0084 gate 分类不变。若
  后续切片引入独立 recovery store、新 public/internal 跨 Plane 权威接口、DB schema/migration（如
  per-event_key 唯一索引）、新信任主体、**允许 recovery run 铸造新 domain key**，或 gate 分类
  变更，**必须先提出 Proposed ADR（不得 Accepted）**。
- **门禁与边界不变**：**完整 business-recovery gate 仍为 `IN_PROGRESS / BLOCKED_INTERNAL`**
  （本切片是设计，不是实现）；**不生成也不声称** D15 superseding assessment；B1/B2
  `BLOCKED_EXTERNAL`、历史 D15-G `NO_GO`、`R3_RESUME = NO` 全部不改写；未实现原生 child resume；
  未知副作用暂停。
- **本修订（P1-A..P1-R）**：撤回“新 reservation / 固定单 event key 的 3 次 / unique+advisory
  lock / registry-only 步骤查找 / `token_limit−charged_tokens` / 以 `reservation_id` 直接 rearm /
  单 settlement slot / 按 root 从 1 连续 / 双重扣减 / `may_produce_new_key` 可授权新 key / 单一
  executor_epoch 同时匹配 containment 与 live / 跨 HTTP 页持锁 / 只读豁免 token floor / carrier
  未携带 snapshot 身份”等表述；改为原行 rearm + 身份分离 + **interrupted/target 双 epoch** + 每
  attempt receipt + trigger-key 去重 + **snapshot-anchored** session-global closure（carrier 显式
  携带 snapshot 身份 + 规范化 digest + 原子比较）+ 自洽 tri-state 不双扣公式（**新 recovery
  model run 必须满足 model-call floor**）+ recovery admission envelope；均有 committed 代码行号
  支撑（见 `design.v1.json.real_code_facts`）。
- 构建身份：初始设计切片推进 `post-u8.190 → post-u8.191`；P1-A..P1-E 推进
  `post-u8.191 → post-u8.192`；P1-F..P1-K 推进 `post-u8.192 → post-u8.193`；P1-L..P1-N 推进
  `post-u8.193 → post-u8.194`；P1-O..P1-Q 推进 `post-u8.194 → post-u8.195`；本 P1-R 修订
  （`tests/` 变更）再推进 `post-u8.195 → post-u8.196`（`scripts/`、`tests/`、
  `services/runtime-adapter/Dockerfile.post-u8-candidate` 属 build inputs，仅重建身份；历史
  `.190`/`.191`/`.192`/`.193`/`.194`/`.195` manifest 与全部证据保留，不改
  selector/`compose.yml`/`deployment.json`/制品）。

## 0.9 authoritative step-safety + business recovery implementation（2026-09-21，权威维护条目）

本批执行“完整 business-recovery gate”的唯一后续实现切片：把
`docs/evidence/v090-step-safety-design/`（#351）的最小设计实现为**真实垂直切片**。独立
worktree/分支 `codex/v090-business-recovery-impl`，基于动态 `origin/main`（`021afb5`）。这是维护/
资格，**不推进 Product Phase**，不切换生产 selector，**不升级 DSH 依赖**，不 deploy，不创建/移动
tag/release，不恢复 Phase 100，不触碰 `codex/phase-100c`/PR #338，不做 Community 检查或复制，
不 fork/patch DSH，**不生成 D15 superseding assessment**，**不启动 0.10**。

- **身份分离**：budget 权威身份仍是原 `reservation_id`；每次恢复提交身份是 Backend 原子签发/
  持久化的 `recovery_attempt_key`（作为 prompt idempotency key，避免 Adapter 因同 key 旧 receipt
  返回旧 run）。carrier `task-continuation-reservation.v1.recovery_attempt` 为**封闭**九字段
  `{attempt_key, ordinal, trigger_key, interrupted_run_id, interrupted_generation,
  containment_attempt, interrupted_executor_epoch, snapshot_tail_sequence, snapshot_digest}`，**仅
  Backend 铸造**；客户端/模型不得铸造。
- **Backend 权威分配（行内，无新 store/migration）**：恢复**折入既有 continuation seam**——沿用
  既有 `/internal/task-continuation/{task_id}/dispatch` 与 `/receipt` 路由，**不新增任何跨 Plane 端点**。
  `claim_continuation_dispatch` 在既有 `research_tasks.continuation_budget` 行上的**同一 task-row
  `SELECT ... FOR UPDATE`** 内按 `trigger_key` 去重复用、否则分配下一 ordinal（cap 3），并把行 rearm
  为 `reserved`；accepted target 由既有 `record_continuation_receipt`（带 `attempt_key`）写回行内
  attempt 聚合，并以 target epoch/generation/run fence 拒绝 stale 写入。预算公式为设计中的**不自双扣**
  tri-state（`other_settled + other_unresolved + R.token_limit ≤ P.token_limit`；`R_available =
  R.token_limit − cum_exact`；未知费用→`paused`；任何新 recovery model run 必须有已知
  `R_available ≥ model_call_floor`）。
- **服务端权威（P1-A 修复）**：请求**不再携带** `read_only`/`occurred_calls`/`replayed_calls`/
  `evidence_conflict`/`model_call_floor`；这些全部由 Backend 从**自有权威证据**派生——occurred/replayed
  来自 `agent_domain_call_evidence` 与 `agent_domain_call_claims`（session-global 连续性、未决 claim、
  hash 冲突）、registry 来自 `domain_call_admission.ACTIONS`、floor 为服务端策略常量。请求只携带
  Adapter 签发的 fenced loss + snapshot（BYQ-owned execution evidence），且 `interrupted_run_id` 必须
  等于 Backend 自己已接受的 run（原始或既有 recovery attempt）。伪造/越权字段被闭合 payload 拒绝。
- **Adapter 校验/原子检查/安装**：`services/runtime-adapter/app/business_recovery.py` 从真实
  append-only lifecycle journal 计算固定 `{tail, digest, idle}`（canonical digest 绑定
  `session_id`+`trace_id`+tail+**有序** closed call rows）；`submit_prompt` 在 `record.lock` 内、
  **创建新 root/target generation 之前**校验 carrier、匹配 durable containment，并重算/原子比较当前
  snapshot 且要求 `idle=true`，随后安装 target generation 并在既有 prompt 响应内返回 accepted receipt
  `{target_executor_epoch, target_generation, run_id}`；旧 epoch/generation 迟到结果被 fence。
- **Gateway 折入既有 consumer**：`_consume_admitted_task_continuation` 在既有 peek/claim/dispatch/
  receipt seam 上检测 Adapter fenced containment（`containment_summary` 的只读 `recovery_anchor`），
  由 Backend 铸造封闭 carrier 后经既有 Adapter prompt 路由原子准入，并把 accepted target 经既有
  receipt 路由写回；`services/gateway/app/recovery_carrier.py` 只透传封闭九字段，额外/未知字段失败关闭。
- **guard 费用绑定**：Adapter 对丢失 run 从**持久化 guard journal** 恢复精确 `charged_tokens`
  （`_recover_guard_charge`），Gateway 经既有 receipt 路由把该精确费用绑定到原 attempt；不可读则保持
  unknown→`paused`，绝不当作 0 或退款。
- **recovery-mode admission envelope（封闭 registry）**：`packages/contracts/business_recovery.py` 的
  `STEP_SAFETY` 由 `domain_call_admission.ACTIONS` 派生，只允许只读或精确复用原
  `(action, task_id, idempotency_key, request_sha256, input_sha256)`；`may_produce_new_key` 为保守
  分类且**永远 ineligible**（允许新 key 须另立 Proposed ADR，本 PR 不开启/不暗示）。
- **runtime 不变式（P1-D）**：恢复模式不再只是起始判断。Backend 在行内 attempt 持久化
  `envelope_mode` 与 `allowed_calls`（**不**扩封闭 carrier）；`DomainCallEvidenceMixin.claim_domain_call`
  在**每次** claim 时经 `_recovery_claim_gate` 判定该 root 是否为 Backend 绑定的 recovery target
  run——是则**只**允许精确复用原五元组（不同 action/key/hash/task、`may_produce_new_key` 一律
  `recovery_envelope_violation`）；recovery attempt 处于 pending（已分配未绑定）时**任何**副作用 claim
  一律拒绝（关闭 admission→writeback 窗口）；非 recovery root 不受影响。Adapter 将
  `recovery_envelope_violation` 视为**停止**（`_domain_stop_result`），运行中无法铸造新 domain key。
- **session-global 作用域（P1-E）**：`_recovery_policy_facts` 改为对**完整 session/trace 闭包**判
  连续性（`sequence` 为 session 级主序列，合法非首 root 从 N>1 开始不再误报 gap），replay envelope
  再按**当前 task + 精确 lost root** 过滤，其他 root/task 的调用不进入本 reservation 的 replay 权威。
- **真实证据（非字符串测试）**：Postgres-backed 并发测试证明**同一 trigger+同一 snapshot 恰一次**、
  retry 复用原 attempt/ordinal、snapshot 变化**不得**改写或消耗另一 ordinal、ordinal cap、未知
  费用/证据冲突/floor fail closed、无二次扣减（`services/backend/tests/test_business_recovery.py`）；
  同文件含**真实 claim-path** 负例（recovery root 新 key / 新 key action / 不同 task 一律
  `recovery_envelope_violation`）、非首 root 序列合法、以及 foreign-task 调用不构成 replay 权威；
  Adapter 真实 journal 测试含 fault injection（digest 篡改、tail append、idle 翻转、containment
  不匹配、stale target epoch/generation、迟到 generation fence、recovery violation stop）（`services/
  runtime-adapter/tests/test_business_recovery.py`）；fail-able observer（25 项 defect-targeting 负例
  全部被拒）与真实 adapter journal 证据 `docs/evidence/v090-business-recovery/`，由
  `tests/test_v090_business_recovery.py` 守门。
- **P2 证据噪声收口**：`docs/evidence/research-handoff-h4/INTERFACE-REVIEW.json` 的改动**仅为
  digest 刷新且可复现**：本 PR 修改了 `services/backend/app/main.py`（267 行 source 行）、
  `services/gateway/app/main.py`、`services/runtime-adapter/app/main.py`、
  `services/runtime-adapter/app/runtime.py`、`services/backend/app/research_continuation.py`、
  `services/backend/app/domain_call_admission.py`，fail-closed auditor
  （`scripts/ci/check-reliability-review.py`）要求每个 source/dependency digest 与当前树一致；
  刷新后 `complete=true`（missing/stale/fake=0），未刷新则非零退出。生成命令
  `python3 scripts/ci/check-reliability-review.py` 定位 stale 行后仅重写其 digest；机器校验
  `python3 scripts/v090/business_recovery/check_ledger_diff.py --base origin/main` 证明
  **digest-only**：`entry_count 569=569`、`entry_identity_multiset_unchanged=true`、
  `manual_surface_identity_unchanged=true`、`non_digest_content_identical=true`、exit 0。无结构/字段/
  行增删，无 `auth_api.py`/`server.ts` 等无关文件 churn（已撤销）。`docs/evidence/v090-session-containment/
  observations.v2.json` 仅更新因果相关 digest（runtime.py + gateway main.py 的 provenance 与 endpoint
  场景 digest），保留原时间戳/run id，不再整文件重生成。
- **边界与门禁不变**：`recovery_attempts` 是既有 authority 行的**行内 JSONB 子记录**，非独立
  store、无 DB migration、无新跨 Plane 权威接口、无新信任主体、**不铸造新 domain key**。**完整
  business-recovery gate 仍为 `IN_PROGRESS / BLOCKED_INTERNAL`**（本切片交付实现与真实证据，最终
  验收与 D15 superseding assessment 仍未完成）。**保留的 0.9 收口顺序**：本 gate → 真实 recovery
  验收 → 正式把仓库默认 dependency/selector 升级到 coherent DSH `0.1.5-rc.1`（含 rollback/业务
  验证）→ D15 superseding assessment → 0.9 收口。B1/B2 仍 `BLOCKED_EXTERNAL`，历史 D15-G 仍
  `NO_GO`，`R3_RESUME = NO`，0.9 未关闭；**本 PR 不生成 superseding assessment（尚未生成）**，
  也不把既有候选资格写成正式升级完成。
- 构建身份推进 `post-u8.196 → post-u8.197`（`scripts/`、`tests/`、
  `services/runtime-adapter/Dockerfile.post-u8-candidate` 属 build inputs，仅重建身份；历史 `.196`
  manifest 与全部证据保留，不改 selector/`compose.yml`/`deployment.json`/制品）。

## 0.9 REAL business-recovery acceptance of merged #352（2026-09-21，权威维护条目）

本批执行 0.9 收口顺序中“本 gate → 真实 recovery 验收”的唯一任务：用**真实隔离服务组合**
（独立 compose 项目 `byq-v090-recovery`、独立网络/卷、全新 PostgreSQL、仅 loopback 端口）验收
已并入 `main` 的 #352 business-recovery 垂直切片。独立 worktree/分支
`codex/v090-business-recovery-acceptance`，基于动态 `origin/main`（`d906205`）。这是维护/资格，
**不推进 Product Phase**，不切换生产 selector，不 deploy，不创建/移动 tag/release，不恢复
Phase 100，不触碰 `codex/phase-100c`/PR #338，不做 Community 检查或复制，**不生成 D15
superseding assessment**，**不启动 0.10**。

- **真实边界**：committed Backend/Gateway（真实后台 `TaskContinuationDelivery` consumer）/
  Runtime Adapter（真实 DSH 0.1.2rc1 + append-only lifecycle journal + containment ledger）/MCP/
  PostgreSQL 均为真实组件；唯一受控项是**无密钥 scripted 模型 provider**，它不能影响任何权威
  决策。真实 `SIGKILL`/重启 Adapter OS 进程（容器 PID 变化）。
- **结果 = PASS**（9/9 场景，`docs/evidence/v090-business-recovery-acceptance/`）：真实 before-state
  →真实执行中终止 Adapter→containment 把**精确**未完成 run 记为 `interrupted`（`executor-loss`）
  →真实 Gateway consumer 触发→Backend 从自有证据重derive并铸造封闭 carrier→Adapter 原子准入并
  安装新 target generation→accepted target 写回；read-only recovery **未改变**任何权威业务行计数，
  journal 仅一次 lost + 一次 recovery generation；retry 精确复用同一 accepted run 且不新增 ordinal/
  generation。真实 fail-closed 负例：forged loss、existing-trigger snapshot 变化、unknown cost
  (`paused`)、below model-call floor、ordinal cap、stale target epoch、recovery-mode new key、
  cross-task。
- **发现并最小修复一个真实 #352 缺陷**：真实执行者丢失后 Gateway 永远到不了 recovery seam，因为
  Adapter `reconcile_prompt` 把丢失 run 的原始 prompt 报成 `accepted`（prompt receipt 只证明 run
  *启动*过），Gateway 在 `_resume_lost_reservation` 之前短路。修复
  `services/runtime-adapter/app/runtime.py::_reconcile_lost_receipt`：当 fenced containment 证明该
  精确 run 已丢失时返回 `outcome_unknown`，Gateway 因此进入既有 recovery 路径；正常完成无
  containment 记录，行为不变。回归测试
  `services/runtime-adapter/tests/test_business_recovery.py::test_lost_original_prompt_is_never_reconciled_as_accepted`。
- **可失败 observer**：`scripts/v090/business_recovery_acceptance/observer.py` 不信任 `result` 标签，
  从 RAW 字段重新推导；`--selfcheck` 20 项 defect-targeting 控制全部被拒；提交 verdict
  `format_valid=true`、`all_pass=true`、exit 0；cleanup 后 containers/networks/volumes 均为 0 且
  生产栈未被触碰。由 `tests/test_v090_business_recovery_acceptance.py` 守门。
- **边界不变**：B1/B2 仍 `BLOCKED_EXTERNAL`，历史 D15-G 仍 `NO_GO`（不改写），`R3_RESUME = NO`，
  生产 selector 仍 `dsh-0.1.2rc1`，0.9 未关闭；未生成 superseding assessment。构建身份推进
  `post-u8.197 → post-u8.198`（`scripts/`、`tests/`、
  `services/runtime-adapter/Dockerfile.post-u8-candidate` 属 build inputs，仅重建身份；历史 `.197`
  manifest 与全部证据保留，不改 selector/`compose.yml`/`deployment.json`/制品）。

## 0.9 正式升级仓库默认 dependency/selector 到 coherent DSH 0.1.5-rc.1（2026-09-22，权威维护条目）

本批执行 0.9 保留收口顺序中的“正式把仓库默认 dependency/selector 升级到 coherent DSH
`0.1.5-rc.1`（含 rollback/业务验证）”唯一步骤。独立 worktree/分支
`codex/v090-dsh-015rc1-default-upgrade`，基于动态 `origin/main`
（`4671c3e948b77c75a87c84a514888974f683a54b`，含 #353）。这是维护/资格，**不推进 Product Phase**，
**不部署生产**，不创建/移动 tag/release，不恢复 Phase 100，不做 Community 检查或复制，**不生成
D15 superseding assessment**，**不启动 0.10**；**不重实现 DSH**、不加跨进程 continuable provider、
不加第二 agent harness。

- **复用既有候选资格资产**：`config/dsh/candidates/dsh-0.1.5rc1/`（声明 + Python lock）、
  `services/runtime-adapter/Dockerfile.dsh-0.1.5rc1-candidate` 与
  `requirements.dsh-0.1.5rc1-candidate.lock`、compat shim
  `services/runtime-adapter/app/compat/dsh_015.py`、D15 证据（target-decision/recon/ledger/
  D15-1 probe/runtime v5）及 B2/B3/B4 候选切片。
- **默认 selector/dependency/profile/image 变更**：`config/dsh/deployment.json`
  `default_release → dsh-0.1.5rc1`、`candidate_releases → [dsh-0.1.2rc1]`（rollback）；新增
  `config/dsh/releases/dsh-0.1.5rc1.json` 与 `.python.lock`（upstream tag/commit/archive 取自 D15-0）；
  `candidate.json` 置 `promoted`、`production_default = dsh-0.1.5rc1`；默认 selector identity
  `config/dsh/generated/deployment.identity.json`（0.1.5）与回滚候选 identity
  `config/dsh/generated/dsh-0.1.2rc1.identity.json`；`Dockerfile.post-u8-candidate` 选择器/嵌入
  build manifest/安装断言；`requirements.candidate.lock`、`pyproject.toml` 固定 `0.1.5rc1`；
  `compose.yml` 默认 `BYQ_DSH_COMPATIBILITY_RELEASE:-dsh-0.1.5rc1` 与 session root；`compat/__init__.py`
  默认 0.1.5 边界（0.1.2 保留可选）；`build_revision` 当前 release `dsh-0.1.5rc1`、新 build id
  `dsh-0.1.5rc1-post-u8.200`（`dsh-0.1.2rc1-post-u8.199` 作为冻结回滚身份保留）；
  `runtime.py` F6 continuation gate 接受同一 coherent 0.1.5 对（避免默认升级静默禁用已资格业务能力）。
  现有 0.1.2 profile 版本无关、D15-1 已证明可加载于 0.1.5，故不新增 profile。
- **可验证 rollback**：0.1.2 的 release descriptor / Python lock / `dsh-0.1.2rc1-post-u8.199` build
  manifest 与 base commit Git blob 逐字节一致；归档 0.1.2 identity 与既部署镜像 digest 记录在案；
  `verify.py` 对回滚制品漂移 fail closed。
- **fail-closed 证据**：`scripts/v090/dsh_default_upgrade/verify.py`（+13 项 defect-targeting 负例，
  `--selfcheck` 全部被拒）；证据 `docs/evidence/v090-dsh-015rc1-default-upgrade/`，由
  `tests/test_v090_dsh_default_upgrade.py` 守门。
- **定向真实验证（keyless，非生产部署）**：升级后的 `Dockerfile.post-u8-candidate` 镜像构建成功
  （`sha256:a4892dd85c7f…`），`/readyz` 报 `release_identity=matched`/`release_id=dsh-0.1.5rc1`；
  镜像内运行时/领域 wire 套件 244 passed/40 skipped；F6 continuation budget 10 passed；D15 start
  probe `ready`/`idle`、事件序列连续、真实 `mcp__byq` tool call 且 message tool 仍被阻断。
- **历史证据仅 digest 刷新**：绑定 `runtime.py` 的两份 v090 证据
  （`docs/evidence/v090-session-containment/observations.v2.json`、
  `docs/evidence/v090-business-recovery/observations.v1.json`）与 H4 interface ledger 的
  `runtime.py` 依赖 digest 因该门禁变更有因果关联，仅刷新 digest，不改结论。
- **边界不变**：B1 `subagent-child-crash` 与 B2 `subagent-byq-adapter-restart` 仍
  `BLOCKED_EXTERNAL`；历史 D15-G 仍 `NO_GO`（不改写）；**不生成** D15 superseding assessment；
  `R3_RESUME = NO`；**未部署生产**、未创建 tag/release；Phase 100 未恢复；**0.10 未启动**。
- 构建身份推进 `post-u8.199 → post-u8.200`（`scripts/`、`tests/`、`services/runtime-adapter` 属
  build inputs；历史 `.199` manifest 与全部证据保留）。

## 0.9 具名 D15 superseding assessment（2026-09-22，权威维护条目）

本批执行 0.9 保留收口顺序中的“D15 superseding assessment”唯一步骤：在 ADR-0084 门禁重分类
与实际采用范围之上，建立**独立、具名、机器可读、可失败**的 superseding assessment。独立
worktree/分支 `codex/v090-d15-superseding-assessment`，基于动态 `origin/main`
（`8a4e4fe41771a25c472fa24195aedccf3f53a6a8`，含 #354）。这是维护/资格，**不推进 Product
Phase**，**不执行最终 0.9 closeout**，不 deploy，不创建/移动 tag/release，不恢复 Phase 100，
不启动 0.10，不触碰 `codex/phase-100c`/PR #338，不做 Community 检查或复制，不 fork/patch DSH，
不实现原生独立 child resume 或第二通用 harness。

- **具名评估与 observer**：`scripts/d15/superseding_assessment/contract.v1.json`（封闭 11 项
  required component + 有界 R3 范围 + `forbidden_assessment_fields` + fail-closed 清单）、
  `observer.py`（独立从**原始证据**派生、区分 `format_valid`/`honest`/`established`、
  `--selfcheck` 21 项负例全部被拒、19 项 defect-targeting）、`build_provenance.py`
  （create-only sha256 + 引入 commit 溯源）。
- **证据**：`docs/evidence/d15/d15-superseding/`（`assessment-input.v1.json`、`provenance.v1.json`、
  `verdict.v1.json`、`negative-controls.v1.json`、`README.md`），由
  `tests/test_v090_d15_superseding_assessment.py` 断言。
- **派生结论（证据驱动，非预设）**：历史 `historical_d15_g = NO_GO_PRESERVED`（引用不改写，
  四个 atomic blocker 不变）；ADR-0084 取代门禁 `replacement_gate_business_recovery = PASS`
  （真实隔离 business-recovery acceptance 9/9 + containment/classification 全 PASS +
  清理为零且生产未被触碰）；`coherent_dsh_default_upgrade = PASS`（coherent 0.1.5-rc.1 配对、
  默认 selector readiness `matched`、0.1.2rc1 回滚基线保留、未声称生产部署）；
  `b1_subagent_child_crash = BLOCKED_EXTERNAL` 与 `b2_subagent_byq_adapter_restart =
  BLOCKED_EXTERNAL`（rc.2/alpha.2 无进程外 continuable provider、committed composition 无 child
  rebind 表面）；`b3_terminal_adapter_restart`/`b4_terminal_dsh_runtime_restart =
  PASS_CANDIDATE`（仅候选/资格层，历史 D15-5/D15-G 快照不改写）；
  `native_independent_child_resume = NOT_IMPLEMENTED`。
- **实际采用范围的候选兼容/晋升（ADR-0084 §3/§5）**：
  `candidate_compatibility_actual_scope = PASS`（由 replacement gate + coherent upgrade +
  B3/B4 候选 PASS 派生，**B1/B2 按 ADR-0084 不 gate 该范围**）；
  `candidate_promotion_actual_scope = REPO_DEFAULT_PROMOTED`（仅**仓库默认**；生产部署/release/tag
  仍是独立决定，未执行也未声称）。
- **R3 范围（不预设、fail closed）**：`r3_permitted_scope` 仅
  `[safe_failure, observation, cleanup, new_generation_recovery]`（ADR-0084 §3 有界 thin
  supervisor 范围）；`r3_resume = NO`（原生独立 child 恢复未实现且历史 D15-G 仍 `NO_GO`，完整
  解冻需另行决定）。观察器拒绝把范围放宽/丢弃、把 `r3_resume` 声明为 `YES`、把
  `BLOCKED_EXTERNAL` 报成 PASS/IMPLEMENTED，或依赖缺失/哈希不符的证据。
- **构建身份同步**：`scripts/`/`tests/`/`services/runtime-adapter` 属 build inputs，构建身份推进
  `post-u8.200 → post-u8.201`（`config/dsh/builds/dsh-0.1.5rc1-post-u8.201.json`；
  `scripts/dsh/build_revision.py`、`Dockerfile.post-u8-candidate`、
  `scripts/v090/dsh_default_upgrade/verify.py` 同步；`.200` 与全部历史 manifest/证据保留）。
  因 `build_revision.py`、`Dockerfile.post-u8-candidate`、promoted release descriptor
  `config/dsh/releases/dsh-0.1.5rc1.json` 与生成的
  `config/dsh/generated/deployment.identity.json` 随重建身份变化，
  `docs/evidence/v090-dsh-015rc1-default-upgrade/default-upgrade.v1.json` 中对应条目**仅刷新
  digest**（因果相关的 rebuild-identity refresh），`verification.v1.json` 的 `promoted_build`/
  `promoted_descriptor_hash` 同步为 `.201`/新 descriptor；`.200` manifest 与历史 `changes`
  保持不变，未改任何结论。
- **边界不变**：B1/B2 仍 `BLOCKED_EXTERNAL`，历史 D15-4/D15-5/D15-G verdict 与文件不改写；
  `R3_RESUME = NO`；**0.9 未关闭**；**本 PR 不执行最终 0.9 closeout**、不 deploy、不 tag/release、
  不恢复 Phase 100、不启动 0.10。下一可执行步骤是**独立的** 0.9 收口，仍受维护者门禁与单独授权。

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
- 2026-09-20 **0.9 closeout governance & gap ledger audit** 本批为审计/治理：只做事实审计、
  plan/STATUS 修订、机器可读 acceptance matrix 与审计测试；不实现 Proposed ADR-0082/0083、
  不切换生产 selector、不 deploy、不创建/移动 tag/release。Phase 100 的 P100-C..E 冻结；
  `codex/phase-100c`（Draft PR #338）只有未审查实现提交，not delivered/未审查。S3/历史成分准备属
  0.10.0，不属于 0.9 closeout gate，不以 S3 开头或阻塞 0.9 顺序。详见顶部权威条目与
  [`docs/evidence/v090-closeout/`](../evidence/v090-closeout/README.md)。
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
